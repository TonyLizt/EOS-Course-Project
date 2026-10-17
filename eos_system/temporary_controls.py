"""Volatile comparison jobs. No database connection, export or replay registration.

Implements only the Controller execution sink, using the same worker/verification
path. The ordinary Controller queue owns dispatch: no extra worker concurrency.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid

from .experiments import aggregate_status, digest, common_config
from .storage import TERMINAL, now
from .planning_preview import PreviewReceipt, validate_preview
from utils.continuous_exposure import CertificationReceipt, validate_certification, check_deadline


class TemporaryControls:
    LEASE_S = 90
    MAX_AGE_S = 7200

    def __init__(self, certification_context, max_queued=20, clock=time.monotonic):
        self.expected_certification_context = certification_context
        self.max_queued = max_queued
        self.clock = clock
        self.lock = threading.RLock()
        self.sessions = {}
        self.runs = {}

    def _cancel(self, session):
        session['deleted'] = True
        for rid in session['ids']:
            run = self.runs[rid]
            run['cancel_requested_at'] = run['cancel_requested_at'] or now()
            run['metrics'] = None
            run['has_plan'] = False
            if run['status'] == 'QUEUED':
                run['status'] = 'CANCELLED'

    def _sweep(self):
        clock = self.clock()
        for sid, session in list(self.sessions.items()):
            if clock > session['lease'] or clock > session['born'] + self.MAX_AGE_S:
                self._cancel(session)
            if session['deleted'] and all(self.runs[rid]['status'] in TERMINAL for rid in session['ids']):
                for rid in session['ids']:
                    del self.runs[rid]
                del self.sessions[sid]

    def create(self, source_id, configs, key=None):
        if not configs or len(configs) > 9 or len({c.algorithm_id for c in configs}) != len(configs):
            raise ValueError('临时对照算法集合无效')
        shared = common_config(configs[0].model_dump())
        if any(common_config(c.model_dump()) != shared for c in configs):
            raise ValueError('临时对照条件不一致')
        signature = digest({'source': source_id, 'configs': [
            {k:v for k,v in c.model_dump().items() if k not in {'run_id','created_at'}} for c in configs]})
        with self.lock:
            self._sweep()
            for sid, session in self.sessions.items():
                if key and session['key'] == key and not session['deleted']:
                    if signature != session['signature']:
                        raise ValueError('相同临时请求标识对应不同配置')
                    return self.detail(sid)
            if len(self.sessions) >= 2 or sum(r['status'] not in TERMINAL for r in self.runs.values()) + len(configs) > self.max_queued:
                raise OverflowError('临时计算队列已满，请删除旧对照或稍后重试')
            sid = 'temporary-' + str(uuid.uuid4())
            clock = self.clock()
            self.sessions[sid] = {'source':source_id, 'ids':[c.run_id for c in configs],
                'born':clock, 'lease':clock+self.LEASE_S, 'deleted':False, 'key':key, 'signature':signature}
            for config in configs:
                self.runs[config.run_id] = {'run_id':config.run_id, 'config':config.model_dump(),
                    'status':'QUEUED', 'current_attempt':0, 'cancel_requested_at':None,
                    'last_seq':0, 'metrics':None, 'has_plan':False, 'error':None,
                    'temporary':True, 'result_kind':config.execution_mode}
            return self.detail(sid)

    def detail(self, sid):
        with self.lock:
            self._sweep()
            session = self.sessions.get(sid)
            if not session or session['deleted']:
                raise KeyError('临时对照不存在或已过期，请重新创建')
            session['lease'] = self.clock() + self.LEASE_S
            rows = copy.deepcopy([self.runs[rid] for rid in session['ids']])
            for row in rows:
                row['config'].pop('scenario_path', None)
                row['config'].pop('output_root', None)
            return {'experiment_id':sid, 'temporary':True, 'source_experiment_id':session['source'],
                'config':common_config(rows[0]['config']), 'runs':rows,
                'status':aggregate_status([r['status'] for r in rows]), 'lease_seconds':self.LEASE_S}

    def delete(self, sid):
        with self.lock:
            session = self.sessions.get(sid)
            if session:
                self._cancel(session)
            self._sweep()

    def close(self):
        with self.lock:
            for session in self.sessions.values():
                self._cancel(session)
            self._sweep()

    def next_queued(self):
        with self.lock:
            self._sweep()
            return next(({'run_id':r['run_id']} for r in self.runs.values() if r['status']=='QUEUED'), None)

    def start_attempt(self, rid):
        with self.lock:
            self._sweep()
            row = self.runs.get(rid)
            if not row or row['status'] != 'QUEUED':
                return None
            row.update(status='RUNNING', current_attempt=1)
            return 1, copy.deepcopy(row['config'])

    def get_status(self, rid):
        with self.lock:
            self._sweep()
            row = self.runs.get(rid)
            return {k:row[k] for k in ('status','current_attempt','cancel_requested_at')} if row else None

    def record_worker_event(self, message):
        with self.lock:
            row = self.runs.get(message['run_id'])
            if not row or row['current_attempt'] != message['attempt'] or row['status'] in TERMINAL or message['seq'] <= row['last_seq']:
                return False
            row['last_seq'] = message['seq']
            return True

    def record_system_event(self, *args, **kwargs):
        pass  # Diagnostics are not persisted for temporary comparisons.

    record_attempt_exit = record_system_event

    def set_verifying(self, rid, attempt):
        with self.lock:
            state = self.get_status(rid)
            if not state or state['current_attempt'] != attempt or state['status'] != 'RUNNING' or state['cancel_requested_at']:
                return False
            self.runs[rid]['status'] = 'VERIFYING'
            return True

    def finish_failure(self, rid, attempt, status, code, message):
        with self.lock:
            row = self.runs.get(rid)
            if row and row['status'] not in TERMINAL and row['current_attempt'] == attempt:
                if row['cancel_requested_at']:
                    status, code = 'CANCELLED', 'CANCELLED'
                row.update(status=status, error={'code':code,'message':str(message)[:300]}, metrics=None, has_plan=False)
            self._sweep()

    def _finish(self, rid, attempt, plan, metrics, receipt, deadline, preview):
        with self.lock:
            state = self.get_status(rid)
            if not state or state['current_attempt'] != attempt or state['status'] != 'VERIFYING' or state['cancel_requested_at']:
                return False
            row = self.runs[rid]
            check_deadline(deadline)
            if preview:
                if not isinstance(receipt, PreviewReceipt):
                    raise ValueError('Controller preview receipt required')
                evidence = validate_preview(receipt.evidence(), row['config'], plan)
            else:
                if not isinstance(receipt, CertificationReceipt):
                    raise ValueError('Controller certification receipt required')
                evidence = validate_certification(receipt.evidence(), run_id=rid,
                    scenario_sha=row['config']['scenario_sha256'], plan=plan, context=self.expected_certification_context())
                check_deadline(evidence['deadline_monotonic'])
            check_deadline(deadline)
            row['metrics'] = {k:metrics[v] for k,v in {'completed_tasks':'completed_tasks','total_tasks':'total_tasks',
                'TP':'task_profit','TCR':'task_completion_rate','BD':'balance_degree','TM':'timeliness_metric',
                'RT':'runtime_efficiency','RV':'robustness_variance'}.items()}
            row.update(status='SUCCEEDED', has_plan=True)
            row['continuous_certification'] = {'status':'INCONCLUSIVE' if preview else 'CONTINUOUS_PASS'}
            # Only metrics/validation retained: never a replayable temporary plan.
            return True

    def finish_preview(self, rid, attempt, plan, metrics, verify_s, *, receipt, deadline):
        return self._finish(rid, attempt, plan, metrics, receipt, deadline, True)

    def finish_success(self, rid, attempt, plan, metrics, verify_s, *, certification, deadline):
        return self._finish(rid, attempt, plan, metrics, certification, deadline, False)
