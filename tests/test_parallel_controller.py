"""真实独立进程并发、单独取消与降并发；不注入物理认证成功。"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from eos_system import controller as module
from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.storage import Database
from eos_system.worker_reference import send_message, receive_message


def waiting_worker(rid, attempt, event_pipe, control_pipe):
    os.setsid(); seq = 0
    def event(kind, payload):
        nonlocal seq
        seq += 1
        send_message(event_pipe, {'protocol_version':1,'run_id':rid,'attempt':attempt,'seq':seq,
            'kind':kind,'sent_at':datetime.now(timezone.utc).isoformat(),'payload':payload})
    event('started', {'worker_pid':os.getpid(),'pgid':os.getpgrp()})
    receive_message(control_pipe); event('heartbeat', {'phase':'SEARCHING'})
    deadline = time.monotonic()+60
    while time.monotonic()<deadline:
        if control_pipe.poll(.05) and receive_message(control_pipe)['kind']=='cancel':
            event('cancel_ack', {'accepted':True}); return


def wait_for(predicate, timeout=35):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        value = predicate()
        if value: return value
        time.sleep(.03)
    raise AssertionError('等待并行状态超时')


class ParallelControllerTests(unittest.TestCase):
    def test_real_parallel_workers_isolated_cancel_and_reduced_limit(self):
        with tempfile.TemporaryDirectory(prefix='eos-parallel-test-') as folder:
            root=Path(folder); scene=root/'scene.json'
            raw=json.dumps({'scenario_id':'tiny','metadata':{'creation_time':'2026-01-01T00:00:00','duration':60},
                            'satellites':[],'missions':[],'ground_stations':[]}).encode();scene.write_bytes(raw)
            settings=Settings(root,root,max_workers=2,startup_timeout_s=30,stop_grace_s=.2)
            db=Database(settings.database_path); ids=[str(uuid.uuid4()) for _ in range(3)]
            for rid in ids:
                db.enqueue(RunConfig(run_id=rid,scenario_id='tiny',scenario_path=str(scene),
                    scenario_sha256=hashlib.sha256(raw).hexdigest(),algorithm_id='completion_first',
                    algorithm_version='test',created_at=datetime.now(timezone.utc).isoformat(),time_budget_s=60),8)
            owner=module.Controller(settings,db)
            with patch.object(module,'worker_main',waiting_worker):
                owner.start()
                try:
                    def searching(rid):
                        row=db.get_run(rid)
                        return row if any(e['event_type']=='heartbeat' and e['payload'].get('phase')=='SEARCHING' for e in row['events']) else None
                    one=wait_for(lambda:searching(ids[0]));two=wait_for(lambda:searching(ids[1]))
                    self.assertNotEqual(one['attempts'][0]['worker_pid'],two['attempts'][0]['worker_pid'])
                    self.assertEqual(db.get_run(ids[2])['status'],'QUEUED')
                    self.assertTrue(owner.worker_journal.path.exists())
                    self.assertTrue((root/'worker-slots/1/worker-lease.json').exists())
                    owner.set_max_workers(1)
                    db.request_cancel(ids[0]);wait_for(lambda:db.get_run(ids[0])['status']=='CANCELLED')
                    self.assertEqual(db.get_run(ids[1])['status'],'RUNNING')
                    self.assertEqual(db.get_run(ids[2])['status'],'QUEUED')
                    db.request_cancel(ids[1]);wait_for(lambda:db.get_run(ids[1])['status']=='CANCELLED')
                    wait_for(lambda:searching(ids[2]))
                finally:
                    owner.stop()
            self.assertEqual(db.get_run(ids[2])['error']['code'],'CONTROLLER_STOP')
            self.assertTrue(all(len(db.get_run(rid)['attempts'])==1 for rid in ids))
            self.assertFalse(owner.worker_journal.path.exists())
            self.assertFalse((root/'worker-slots/1/worker-lease.json').exists())
            self.assertIsNone(owner._lock_file)


if __name__=='__main__': unittest.main()
