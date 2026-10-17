"""Temporary controls never enqueue, certify, export or persist into SQLite."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from eos_system.api import create_app
from eos_system.config import Settings
from eos_system.contracts import RunRequest, RunConfig, ExperimentRequest, ControlExperimentRequest


class TemporaryControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        scenes = root / 'scenes'
        scenes.mkdir()
        self.scene = scenes / 'empty.json'
        self.scene.write_text(json.dumps({'scenario_id':'empty', 'metadata':{
            'creation_time':'2026-01-01T00:00:00Z','duration':60},
            'missions':[],'satellites':[],'observation_windows':[]}))
        self.app = create_app(Settings(runtime_dir=root/'runtime',scenario_dir=scenes))
        self.addCleanup(self.app.state.replay.close)
        self.addCleanup(self.app.state.temporary_controls.close)
        self.db = self.app.state.database
        self.memory = self.app.state.temporary_controls
        self.source = self.route('/api/experiments','POST')(ExperimentRequest(runs=[
            RunRequest(scenario_id='empty',algorithm_id=aid,execution_mode='planning_preview',time_budget_s=1)
            for aid in ('profit_first','timeliness_first')]),None)

    def route(self, path, method):
        return next(r.endpoint for r in self.app.routes if r.path==path and method in r.methods)

    def counts(self):
        with self.db.connect() as conn:
            return {table:conn.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in
                ('experiments','experiment_runs','runs','run_attempts','run_events','plans','assignments','metrics')}

    def create(self, key='temporary-test'):
        return self.route('/api/experiments/{experiment_id}/temporary-control','POST')(
            self.source['experiment_id'],ControlExperimentRequest(schedule_model='adaptive_repair'),key)

    def test_api_is_memory_only_idempotent_and_no_replay_identity(self):
        before = self.counts()
        with patch.object(self.db,'write',side_effect=AssertionError('temporary API wrote SQLite')):
            result = self.create()
            again = self.create()
            self.assertEqual(result['experiment_id'],again['experiment_id'])
            self.assertEqual(len(result['runs']),2)
            self.assertTrue(result['temporary'])
            for row in result['runs']:
                self.assertIsNone(self.db.get_run(row['run_id']))
                self.assertIsNone(self.app.state.experiments.for_run(row['run_id']))
                self.assertNotIn('scenario_path',row['config'])
            self.memory.delete(result['experiment_id'])
            with self.assertRaises(KeyError):self.memory.detail(result['experiment_id'])
        self.assertEqual(self.counts(),before)

    def test_real_worker_verification_uses_volatile_sink_and_no_exports(self):
        result = self.create()
        before = self.counts()
        with patch.object(self.db,'write',side_effect=AssertionError('temporary Worker wrote SQLite')), \
             patch('eos_system.controller.persist_directory_exports') as export:
            for row in result['runs']:
                rid = row['run_id']
                attempt,config = self.memory.start_attempt(rid)
                self.app.state.controller._execute(RunConfig.model_validate(config),attempt,self.memory)
            export.assert_not_called()
        detail = self.memory.detail(result['experiment_id'])
        self.assertEqual(detail['status'],'SUCCEEDED',detail)
        self.assertTrue(all(r['has_plan'] and r['metrics']['TCR']==0 for r in detail['runs']))
        self.assertTrue(all('plan' not in r for r in detail['runs']))
        self.assertEqual(self.counts(),before)

    def test_running_cancel_expiry_and_late_result_are_safe(self):
        now = [0.0]
        self.memory.clock = lambda:now[0]
        result = self.create()
        rid = result['runs'][0]['run_id']
        self.memory.start_attempt(rid)
        self.memory.set_verifying(rid,1)
        self.memory.delete(result['experiment_id'])
        self.assertTrue(self.memory.get_status(rid)['cancel_requested_at'])
        self.assertFalse(self.memory.finish_preview(rid,1,{}, {},0,receipt=object(),deadline=time.monotonic()+10))
        self.memory.finish_failure(rid,1,'FAILED','LATE','late verifier')
        self.assertEqual(self.memory.sessions,{})
        self.assertEqual(self.memory.runs,{})
        result = self.create('expire')
        now[0] += self.memory.LEASE_S + 1
        with self.assertRaises(KeyError):self.memory.detail(result['experiment_id'])
        self.assertEqual(self.memory.runs,{})

    def test_bad_model_changed_source_capacity_and_forged_receipt_rejected(self):
        endpoint = self.route('/api/experiments/{experiment_id}/temporary-control','POST')
        with self.assertRaises(HTTPException):endpoint(self.source['experiment_id'],ControlExperimentRequest(schedule_model='completion_first'),None)
        self.memory.max_queued=1
        with self.assertRaises(HTTPException) as busy:self.create()
        self.assertEqual(busy.exception.status_code,429)
        self.memory.max_queued=20
        result=self.create()
        rid=result['runs'][0]['run_id'];self.memory.start_attempt(rid);self.memory.set_verifying(rid,1)
        with self.assertRaises(ValueError):self.memory.finish_preview(rid,1,{}, {},0,receipt=object(),deadline=time.monotonic()+10)
        self.assertIsNone(self.memory.runs[rid]['metrics'])
        self.scene.write_text(self.scene.read_text().replace('60','120'))
        with self.assertRaises(HTTPException) as changed:self.create('changed')
        self.assertEqual(changed.exception.status_code,409)


if __name__=='__main__':unittest.main()
