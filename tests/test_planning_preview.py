"""Preview may complete, but cannot acquire a formal certificate or formal export."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest

from eos_system.contracts import RunRequest, RunConfig
from eos_system.storage import Database, now, compact_json
from eos_system.planning_preview import audit_preview, PreviewRecord, PreviewReceipt, require_preview_record
from eos_system.exporting import render_json
from schedulers.preview_exposure import candidate_exposure
from utils.continuous_exposure import ExposureStatus, ContinuousCertificationError


class PreviewIsolationTests(unittest.TestCase):
    def test_api_default_remains_formal_and_preview_window_is_conservative(self):
        self.assertEqual(RunRequest(scenario_id='x', algorithm_id='completion_first').execution_mode, 'formal')
        start = datetime(2026,1,1)
        window = SimpleNamespace(start_time=start, end_time=start+timedelta(seconds=11), time_step=1,
                                 planning_evidence=None)
        formal = SimpleNamespace(execution_mode='formal')
        preview = SimpleNamespace(execution_mode='planning_preview')
        self.assertIs(candidate_exposure(formal,window,start,start+timedelta(seconds=10),10).status, ExposureStatus.INCONCLUSIVE)
        self.assertIs(candidate_exposure(preview,window,start,start+timedelta(seconds=10),10).status, ExposureStatus.PLANNING_FEASIBLE)
        self.assertIs(candidate_exposure(preview,window,start,start+timedelta(seconds=11),11).status, ExposureStatus.REJECTED)

    def test_preview_storage_readback_exports_and_tamper_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root/'scene.json'; scene.write_text('{"scenario_id":"x","metadata":{},"missions":[],"satellites":[]}')
            config = RunConfig(run_id='preview-test',scenario_id='x',scenario_path=str(scene),
                scenario_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(), algorithm_id='completion_first',
                algorithm_version='baseline-1', execution_mode='planning_preview',created_at=now())
            db = Database(root/'results.sqlite3'); db.enqueue(config,8)
            attempt,_ = db.start_attempt(config.run_id); db.set_verifying(config.run_id,attempt)
            plan = dict(scenario_id='x',assignments=[],unassigned_tasks=[])
            metrics = dict(completed_tasks=0,total_tasks=0,task_profit=0,task_completion_rate=0,
                balance_degree=0,timeliness_metric=0,runtime_efficiency=.1,robustness_variance=None,mip_gap=None)
            receipt = audit_preview(config,plan,deadline=time.monotonic()+30)
            with self.assertRaises(ValueError):
                db.finish_preview(config.run_id,attempt,plan,metrics,.01,
                    receipt=PreviewReceipt(receipt.evidence_json,None),deadline=time.monotonic()+30)
            with self.assertRaises(ContinuousCertificationError):
                db.finish_success(config.run_id,attempt,plan,metrics,.01,certification=receipt)
            self.assertTrue(db.finish_preview(config.run_id,attempt,plan,metrics,.01,receipt=receipt,deadline=time.monotonic()+30))
            record = db.get_run(config.run_id)
            self.assertIsInstance(record,PreviewRecord); require_preview_record(record)
            self.assertEqual(record['continuous_certification']['status'],'NOT_CERTIFIED')
            self.assertTrue(db.get_replay_source(config.run_id)['plan_json'])
            with self.assertRaises(ValueError): render_json(record)
            with self.assertRaises(ValueError): require_preview_record(dict(record))
            self.assertFalse(any(e['event_type']=='CONTINUOUS_CERTIFIED' for e in record['events']))
            changed = {**plan,'unassigned_tasks':['forged']}; raw = compact_json(changed)
            with db.write() as conn:
                conn.execute('UPDATE plans SET plan_json=?,plan_sha256=? WHERE run_id=?',
                             (raw,hashlib.sha256(raw.encode()).hexdigest(),config.run_id))
            self.assertIsNone(db.get_run(config.run_id)['plan'])


if __name__ == '__main__': unittest.main()
