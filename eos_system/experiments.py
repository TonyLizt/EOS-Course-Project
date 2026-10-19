"""Persistent experiment membership; child Runs keep the existing Worker contract."""
from __future__ import annotations

import hashlib
import json
import uuid

from .contracts import RunConfig
from .storage import TERMINAL, compact_json, now


def common_config(config: dict) -> dict:
    return {k: v for k, v in config.items()
            if k not in {'run_id', 'created_at', 'algorithm_id', 'algorithm_version', 'algorithm_params', 'model_provenance'}}



def algorithm_identity(config):
    """模型是算法侧身份，不能进入所有算法共享配置，也不能从对照身份中丢失。"""
    identity = {'params': config.get('algorithm_params', {})}
    if config.get('model_provenance'): identity['model_provenance'] = config['model_provenance']
    return identity


def digest(value) -> str:
    return hashlib.sha256(compact_json(value).encode()).hexdigest()


def aggregate_status(statuses):
    if not statuses:return 'EMPTY'
    if any(s not in TERMINAL for s in statuses):return 'QUEUED' if all(s=='QUEUED' for s in statuses) else 'RUNNING'
    if all(s=='SUCCEEDED' for s in statuses):return 'SUCCEEDED'
    if 'SUCCEEDED' in statuses:return 'PARTIAL'
    if all(s=='CANCELLED' for s in statuses):return 'CANCELLED'
    return 'FAILED'


class Experiments:
    def __init__(self, database):
        self.db = database
        self.adopt_legacy()

    def adopt_legacy(self):
        # No reliable historical batch ID exists. Never guess from timestamps.
        with self.db.write() as conn:
            rows = conn.execute('SELECT r.* FROM runs r LEFT JOIN experiment_runs e USING(run_id) WHERE e.run_id IS NULL').fetchall()
            for row in rows:
                eid = 'legacy-' + row['run_id']
                conn.execute('INSERT OR IGNORE INTO experiments(experiment_id,common_json,created_at,legacy) VALUES (?,?,?,1)',
                             (eid, compact_json(common_config(json.loads(row['config_json']))), row['created_at']))
                conn.execute('INSERT INTO experiment_runs(experiment_id,run_id,algorithm_id) VALUES (?,?,?)',
                             (eid, row['run_id'], row['algorithm_id']))

    def _enqueue(self, conn, config):
        raw = compact_json(config.model_dump())
        conn.execute('INSERT INTO runs(run_id,source_id,scenario_id,scenario_sha256,algorithm_id,algorithm_version,output_profile_id,config_json,config_sha256,status,created_at,updated_at,queued_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (config.run_id, config.source_id, config.scenario_id, config.scenario_sha256,
                      config.algorithm_id, config.algorithm_version, config.output_profile_id,
                      raw, hashlib.sha256(raw.encode()).hexdigest(), 'QUEUED', config.created_at, config.created_at, config.created_at))
        self.db._event(conn, config.run_id, None, 'controller', None, 'QUEUED', None)

    def create(self, configs: list[RunConfig], max_queued: int, key: str | None = None, control_of: str | None = None) -> str:
        if not configs or len({c.algorithm_id for c in configs}) != len(configs):
            raise ValueError('实验至少一个算法，且算法不能重复')
        shared = common_config(configs[0].model_dump())
        if any(common_config(c.model_dump()) != shared for c in configs):
            raise ValueError('同一实验的场景、模型、种子、约束和预算必须一致')
        request_sha = digest({'runs':[{'common': shared, 'algorithm': c.algorithm_id, 'params': c.algorithm_params, **({'model_provenance': c.model_provenance} if c.model_provenance else {})}
                              for c in sorted(configs, key=lambda c: c.algorithm_id)], 'control_of':control_of})
        eid = str(uuid.uuid4())
        with self.db.write() as conn:
            if key:
                old = conn.execute('SELECT * FROM experiments WHERE idempotency_key=?', (key,)).fetchone()
                if old:
                    if old['request_sha256'] != request_sha:
                        raise ValueError('相同请求标识对应不同实验')
                    return old['experiment_id']
            if control_of:
                original=conn.execute('SELECT common_json,legacy FROM experiments WHERE experiment_id=?',(control_of,)).fetchone()
                if not original:raise KeyError('原实验不存在')
                expected=json.loads(original['common_json']);previous=expected.get('schedule_model')
                expected['schedule_model']=shared['schedule_model']
                members={r['algorithm_id']:algorithm_identity(json.loads(r['config_json'])) for r in conn.execute(
                    'SELECT r.algorithm_id,r.config_json FROM experiment_runs e JOIN runs r USING(run_id) WHERE e.experiment_id=? AND e.removed_at IS NULL',(control_of,))}
                if original['legacy'] or previous==shared['schedule_model'] or expected!=shared or members!={c.algorithm_id:algorithm_identity(c.model_dump()) for c in configs}:
                    raise ValueError('原实验条件或算法已变化，不能创建单变量对照；请刷新后重试')
            queued = conn.execute("SELECT count(*) FROM runs WHERE status='QUEUED'").fetchone()[0]
            if queued + len(configs) > max_queued:
                raise OverflowError('队列空间不足；本次实验未创建，请稍后重试')
            conn.execute('INSERT INTO experiments(experiment_id,common_json,created_at,idempotency_key,request_sha256) VALUES (?,?,?,?,?)',
                         (eid, compact_json(shared), now(), key, request_sha))
            for config in configs:
                self._enqueue(conn, config)
                conn.execute('INSERT INTO experiment_runs(experiment_id,run_id,algorithm_id) VALUES (?,?,?)',
                             (eid, config.run_id, config.algorithm_id))
            if control_of:
                self.db._event(conn,configs[0].run_id,None,'api',None,'EXPERIMENT_CONTROL_CREATED',
                    {'source_experiment_id':control_of,'changed_field':'schedule_model',
                     'from':previous,'to':shared['schedule_model']})
        return eid

    def common(self, eid):
        with self.db.connect() as conn:
            row = conn.execute('SELECT common_json FROM experiments WHERE experiment_id=?', (eid,)).fetchone()
        if row is None:
            raise KeyError('实验不存在')
        return json.loads(row['common_json'])

    def add(self, eid, config: RunConfig, max_queued):
        from .experiment_compatibility import presentation_only_source_change
        incoming, previous = common_config(config.model_dump()), self.common(eid)
        changed = {key for key in incoming.keys() | previous.keys()
                   if incoming.get(key) != previous.get(key)}
        metadata_only = changed == {'algorithm_code_sha'} and presentation_only_source_change(
            previous.get('algorithm_code_sha'), incoming.get('algorithm_code_sha'))
        if changed and not metadata_only:
            raise ValueError('实验条件已变化（' + ', '.join(sorted(changed))
                             + '），不能混入此实验；请使用相同版本或建立新实验')
        with self.db.write() as conn:
            if conn.execute('SELECT 1 FROM experiment_runs WHERE experiment_id=? AND algorithm_id=? AND removed_at IS NULL',
                            (eid, config.algorithm_id)).fetchone():
                raise ValueError('算法已在此实验中，请勿重复添加')
            if conn.execute("SELECT count(*) FROM runs WHERE status='QUEUED'").fetchone()[0] >= max_queued:
                raise OverflowError('队列已满，请稍后重试')
            self._enqueue(conn, config)
            conn.execute('INSERT INTO experiment_runs(experiment_id,run_id,algorithm_id) VALUES (?,?,?)',
                         (eid, config.run_id, config.algorithm_id))
            if metadata_only:
                self.db._event(conn, config.run_id, None, 'api', None,
                               'EXPERIMENT_PRESENTATION_ONLY_COMPATIBILITY', {
                                   'experiment_id': eid,
                                   'experiment_source_sha': previous['algorithm_code_sha'],
                                   'run_source_sha': incoming['algorithm_code_sha'],
                                   'reason': 'parameter presentation metadata only; no solver or constraint change',
                               })

    def remove(self, eid, algorithm_id):
        with self.db.write() as conn:
            row = conn.execute('SELECT run_id FROM experiment_runs WHERE experiment_id=? AND algorithm_id=? AND removed_at IS NULL',
                               (eid, algorithm_id)).fetchone()
            if row is None:
                raise KeyError('此实验中没有该算法')
            conn.execute('UPDATE experiment_runs SET removed_at=? WHERE run_id=?', (now(), row['run_id']))
            self.db.request_cancel_in(conn, row['run_id'])
        return row['run_id']

    def for_run(self, rid):
        with self.db.connect() as conn:
            row = conn.execute('SELECT experiment_id FROM experiment_runs WHERE run_id=? AND removed_at IS NULL', (rid,)).fetchone()
        return row['experiment_id'] if row else None

    def detail(self, eid):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM experiments WHERE experiment_id=?', (eid,)).fetchone()
            links = conn.execute('SELECT run_id FROM experiment_runs WHERE experiment_id=? AND removed_at IS NULL ORDER BY rowid', (eid,)).fetchall()
            control = conn.execute("SELECT payload_json FROM run_events e JOIN experiment_runs m USING(run_id) WHERE m.experiment_id=? AND e.event_type='EXPERIMENT_CONTROL_CREATED' ORDER BY event_id LIMIT 1",(eid,)).fetchone()
        if row is None:
            raise KeyError('实验不存在')
        runs = [self.db.get_run(link['run_id']) for link in links]
        runs = [r for r in runs if r is not None]
        common = json.loads(row['common_json'])
        statuses = [r['status'] for r in runs]
        status=aggregate_status(statuses)
        return {'experiment_id': eid, 'created_at': row['created_at'], 'legacy': bool(row['legacy']),
                'config': common, 'runs': runs, 'status': status,
                'control':json.loads(control['payload_json']) if control else None}

    def listing(self, limit=30, offset=0):
        with self.db.connect() as conn:
            total = conn.execute('SELECT count(*) FROM experiments').fetchone()[0]
            ids = conn.execute('SELECT experiment_id FROM experiments ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        rows = []
        for item in ids:
            with self.db.connect() as conn:
                parent = dict(conn.execute('SELECT * FROM experiments WHERE experiment_id=?', (item['experiment_id'],)).fetchone())
                children = [dict(r) for r in conn.execute('SELECT r.algorithm_id,r.status,r.run_id FROM experiment_runs e JOIN runs r USING(run_id) WHERE e.experiment_id=? AND e.removed_at IS NULL ORDER BY e.rowid', (item['experiment_id'],))]
            states = [c['status'] for c in children]
            state=aggregate_status(states)
            rows.append({'experiment_id':parent['experiment_id'],'created_at':parent['created_at'],
                         'legacy':bool(parent['legacy']),'config':json.loads(parent['common_json']),
                         'algorithms':children,'status':state})
        return {'items': rows, 'total': total, 'limit': limit, 'offset': offset}

    def _comparison_identity(self, eid):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM experiments WHERE experiment_id=?', (eid,)).fetchone()
            if row is None:
                raise KeyError('实验不存在')
            selections = {r['algorithm_id']: algorithm_identity(json.loads(r['config_json'])) for r in conn.execute(
                'SELECT r.algorithm_id,r.config_json FROM experiment_runs e JOIN runs r USING(run_id) WHERE e.experiment_id=? AND e.removed_at IS NULL', (eid,))}
        return dict(row), selections

    def assert_comparable(self, eid, other_id):
        first, sa = self._comparison_identity(eid)
        other, sb = self._comparison_identity(other_id)
        a, b = json.loads(first['common_json']), json.loads(other['common_json'])
        ma, mb = a.pop('schedule_model', None), b.pop('schedule_model', None)
        if (eid == other_id or not ma or not mb or ma == mb or a != b
                or sa != sb or not sa or first['legacy'] or other['legacy']):
            raise ValueError('仅允许同一场景与全部实验条件、算法及参数相同，只有初始模型不同的两组实验比较')

    def compare(self, eid, other_id):
        self.assert_comparable(eid, other_id)
        pair = [self.detail(eid), self.detail(other_id)]
        selections = lambda e: {r['config']['algorithm_id']: algorithm_identity(r['config']) for r in e['runs']}
        if selections(pair[0]) != selections(pair[1]):
            raise ValueError('比较期间算法成员发生变化，请刷新后重新选择')
        versions={r['metrics'].get('metric_schema_version') for e in pair for r in e['runs'] if r.get('metrics')}
        if len(versions)>1:raise ValueError('评价指标版本不一致，不能比较')
        return pair
