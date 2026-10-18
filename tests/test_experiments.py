"""Experiment parent/child persistence, isolation, migration and cancellation."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from eos_system.contracts import RunConfig, RunRequest, ExperimentRequest, ExperimentAlgorithm, ControlExperimentRequest
from eos_system.config import Settings
from eos_system.api import create_app
from fastapi import HTTPException
from eos_system.experiments import Experiments
from eos_system.storage import Database, now


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'runs.sqlite3'
        self.db=Database(self.path);self.store=Experiments(self.db)

    def config(self,aid='profit_first',**changes):
        return RunConfig(run_id=str(uuid.uuid4()),created_at=now(),algorithm_id=aid,
                         algorithm_version='console-1',scenario_id='scene',scenario_path='/readonly/scene.json',
                         scenario_sha256='a'*64,algorithm_code_sha='b'*64,**changes)

    def test_one_experiment_many_runs_atomic_queue_and_idempotency(self):
        configs=[self.config(),self.config('timeliness_first')]
        with self.assertRaises(OverflowError):self.store.create(configs,1)
        self.assertEqual(self.store.listing()['total'],0)
        self.assertEqual(self.db.list_runs()['total'],0)
        eid=self.store.create(configs,8,'request-1')
        retry=[self.config(),self.config('timeliness_first')]
        self.assertEqual(self.store.create(retry,8,'request-1'),eid)
        self.assertEqual(self.store.listing()['total'],1)
        self.assertEqual(len(self.store.detail(eid)['runs']),2)
        self.assertEqual(self.db.list_runs()['total'],2)
        with self.assertRaises(ValueError):self.store.create([self.config(seed=99)],8,'request-1')

    def test_reject_mixed_experiment_conditions_and_duplicate_algorithms(self):
        for configs in ([self.config(),self.config('sa',schedule_model='adaptive_repair')],
                        [self.config(),self.config()],
                        [self.config(),self.config('sa',seed=123)]):
            with self.assertRaises(ValueError):self.store.create(configs,8)
        self.assertEqual(self.store.listing()['total'],0)

    def test_remove_retains_run_cancels_and_readd_does_not_resurrect(self):
        config=self.config();eid=self.store.create([config],8)
        self.store.remove(eid,'profit_first')
        self.assertEqual(self.db.get_status(config.run_id)['status'],'CANCELLED')
        self.assertEqual(self.store.detail(eid)['runs'],[])
        self.assertIsNotNone(self.db.get_run(config.run_id))
        self.store.adopt_legacy()
        self.assertEqual(self.store.listing()['total'],1)
        replacement=self.config();self.store.add(eid,replacement,8)
        self.assertEqual([r['run_id'] for r in self.store.detail(eid)['runs']],[replacement.run_id])
        with self.assertRaises(ValueError):self.store.add(eid,self.config(),8)
        with self.assertRaises(ValueError):self.store.add(eid,self.config('sa',seed=99),8)

    def test_remove_running_requests_original_cancellation(self):
        config=self.config();eid=self.store.create([config],8)
        self.db.start_attempt(config.run_id)
        self.store.remove(eid,'profit_first')
        self.assertEqual(self.db.get_status(config.run_id)['status'],'RUNNING')
        self.assertTrue(self.db.get_status(config.run_id)['cancel_requested_at'])

    def test_control_creation_rechecks_source_membership_inside_transaction(self):
        eid=self.store.create([self.config(),self.config('sa')],8)
        self.store.remove(eid,'sa')
        before=self.db.list_runs()['total']
        with self.assertRaises(ValueError):
            self.store.create([self.config(schedule_model='adaptive_repair'),
                self.config('sa',schedule_model='adaptive_repair')],8,control_of=eid)
        self.assertEqual(self.db.list_runs()['total'],before)
        self.assertEqual(self.store.listing()['total'],1)

    def test_existing_upgrade_backup_is_never_overwritten(self):
        backup=self.path.with_name(self.path.name+'.pre-v4.bak');backup.write_bytes(b'preserved older backup')
        with self.db.connect() as conn:
            conn.executescript('DROP TABLE experiment_runs; DROP TABLE experiments; PRAGMA user_version=3;')
        Database(self.path)
        self.assertEqual(backup.read_bytes(),b'preserved older backup')
        self.assertEqual(len(list(self.path.parent.glob(self.path.name+'.pre-v4.*.bak'))),1)

    def test_compare_only_opposite_models_and_identical_experiment_inputs(self):
        first=self.store.create([self.config()],8)
        other=self.store.create([self.config(schedule_model='adaptive_repair')],8)
        self.assertEqual(len(self.store.compare(first,other)),2)
        for candidate in (first,self.store.create([self.config(seed=1,schedule_model='adaptive_repair')],8),
                          self.store.create([self.config('sa',schedule_model='adaptive_repair')],8)):
            with self.assertRaises(ValueError):self.store.compare(first,candidate)

    def test_v3_backup_migration_and_legacy_not_guessed_by_time(self):
        a,b=self.config(),self.config('sa')
        self.db.enqueue(a,8);self.db.enqueue(b,8)
        with self.db.connect() as conn:
            conn.executescript('DROP TABLE experiment_runs; DROP TABLE experiments; PRAGMA user_version=3;')
        migrated=Database(self.path);store=Experiments(migrated)
        self.assertTrue(self.path.with_name(self.path.name+'.pre-v4.bak').exists())
        self.assertEqual(store.listing()['total'],2)
        self.assertEqual(migrated.get_run(a.run_id)['config']['scenario_sha256'],a.scenario_sha256)
        self.assertTrue(all(r['legacy'] for r in store.listing()['items']))
        with migrated.connect() as conn:self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],4)

    def test_http_group_contract_and_changed_scene_addition_rejected(self):
        root=Path(self.temp.name);scenes=root/'scenes';scenes.mkdir()
        scene=scenes/'scene.json'
        document={'scenario_id':'scene','metadata':{'creation_time':'2026-01-01T00:00:00Z','duration':60},
                  'missions':[],'satellites':[],'observation_windows':[]}
        scene.write_text(json.dumps(document))
        app=create_app(Settings(runtime_dir=root/'api-runtime',scenario_dir=scenes))
        route=lambda path,method:next(r.endpoint for r in app.routes if r.path==path and method in r.methods)
        payload=ExperimentRequest(runs=[RunRequest(scenario_id='scene',algorithm_id=aid,execution_mode='planning_preview')
                                        for aid in ('profit_first','timeliness_first')])
        result=route('/api/experiments','POST')(payload,None)
        self.assertEqual(len(result['runs']),2)
        self.assertNotIn('scenario_path',result['config'])
        self.assertTrue(all('scenario_path' not in r['config'] for r in result['runs']))
        clone=route('/api/experiments/{experiment_id}/control','POST')
        peer=clone(result['experiment_id'],ControlExperimentRequest(schedule_model='adaptive_repair'),'control-1')
        retried=clone(result['experiment_id'],ControlExperimentRequest(schedule_model='adaptive_repair'),'control-1')
        self.assertEqual(peer['experiment_id'],retried['experiment_id'])
        self.assertEqual(peer['control']['source_experiment_id'],result['experiment_id'])
        self.assertEqual(peer['control']['changed_field'],'schedule_model')
        self.assertTrue(set(r['run_id'] for r in result['runs']).isdisjoint(r['run_id'] for r in peer['runs']))
        with self.assertRaises(HTTPException) as same:
            clone(result['experiment_id'],ControlExperimentRequest(schedule_model='completion_first'),None)
        self.assertEqual(same.exception.status_code,422)
        eligible=route('/api/experiments/{experiment_id}/peers','GET')(result['experiment_id'])
        self.assertEqual([r['experiment_id'] for r in eligible['items']],[peer['experiment_id']])
        compared=route('/api/experiments/{experiment_id}/compare/{other_id}','GET')(result['experiment_id'],peer['experiment_id'])
        self.assertEqual(len(compared['items']),2)
        document['metadata']['duration']=120;scene.write_text(json.dumps(document))
        with self.assertRaises(HTTPException) as raised:
            route('/api/experiments/{experiment_id}/algorithms','POST')(
                result['experiment_id'],ExperimentAlgorithm(algorithm_id='sa'))
        self.assertEqual(raised.exception.status_code,409)
        self.assertEqual(len(app.state.experiments.detail(result['experiment_id'])['runs']),2)

    def test_inline_metadata_regression_can_add_without_rewriting_history(self):
        from eos_system.experiment_compatibility import PRESENTATION_ONLY_SOURCE_PAIR
        first_sha, other_sha = sorted(PRESENTATION_ONLY_SOURCE_PAIR)
        original=self.config().model_copy(update={'algorithm_code_sha':first_sha})
        eid=self.store.create([original],8)
        child=self.config('sa').model_copy(update={'algorithm_code_sha':other_sha})
        self.store.add(eid,child,8)
        result=self.store.detail(eid)
        self.assertEqual(len(result['runs']),2)
        self.assertEqual(result['config']['algorithm_code_sha'],first_sha)
        self.assertEqual(self.db.get_run(child.run_id)['config']['algorithm_code_sha'],other_sha)
        with self.db.connect() as connection:
            row=connection.execute("SELECT payload_json FROM run_events WHERE run_id=? AND event_type='EXPERIMENT_PRESENTATION_ONLY_COMPATIBILITY'",(child.run_id,)).fetchone()
        self.assertEqual(json.loads(row[0])['experiment_source_sha'],first_sha)
        # The exception is exact and never permits actual source/scene changes.
        for changes in ({'algorithm_code_sha':'c'*64},
                        {'algorithm_code_sha':other_sha,'seed':99},
                        {'algorithm_code_sha':other_sha,'scenario_sha256':'d'*64}):
            invalid=self.config('ga').model_copy(update=changes)
            with self.assertRaises(ValueError):self.store.add(eid,invalid,8)
        self.assertEqual(len(self.store.detail(eid)['runs']),2)

    def test_http_add_to_pre_ui_and_inline_metadata_experiments(self):
        from unittest.mock import patch
        from eos_system.config import algorithm_source_sha256
        from eos_system.experiment_compatibility import PRESENTATION_ONLY_SOURCE_PAIR
        root=Path(self.temp.name);scenes=root/'add-scenes';scenes.mkdir()
        (scenes/'scene.json').write_text(json.dumps({
            'scenario_id':'scene','metadata':{'creation_time':'2026-01-01T00:00:00Z','duration':60},
            'missions':[],'satellites':[],'observation_windows':[]}))
        app=create_app(Settings(runtime_dir=root/'add-runtime',scenario_dir=scenes))
        self.addCleanup(app.state.replay.close)
        route=lambda path,method:next(r.endpoint for r in app.routes if r.path==path and method in r.methods)
        # 核验语义发生真实变化后，新源码不能套用历史“仅展示层变化”例外。
        # 当前身份可继续追加；历史pair仅在实际当前仍属于该pair时互认。
        from fastapi import HTTPException
        current=algorithm_source_sha256()
        sources=list(dict.fromkeys([current,*sorted(PRESENTATION_ONLY_SOURCE_PAIR)]))
        for source_sha in sources:
            with patch('eos_system.api.algorithm_source_sha256',return_value=source_sha):
                created=route('/api/experiments','POST')(ExperimentRequest(runs=[
                    RunRequest(scenario_id='scene',algorithm_id='profit_first',execution_mode='planning_preview')]),None)
            add=route('/api/experiments/{experiment_id}/algorithms','POST')
            if source_sha != current and current not in PRESENTATION_ONLY_SOURCE_PAIR:
                with self.assertRaises(HTTPException) as caught:
                    add(created['experiment_id'],ExperimentAlgorithm(algorithm_id='timeliness_first'))
                self.assertEqual(caught.exception.status_code,409)
                self.assertEqual(len(app.state.experiments.detail(created['experiment_id'])['runs']),1)
            else:
                added=add(created['experiment_id'],ExperimentAlgorithm(algorithm_id='timeliness_first'))
                self.assertEqual(added['experiment_id'],created['experiment_id'])
                self.assertEqual([r['config']['algorithm_id'] for r in added['runs']],['profit_first','timeliness_first'])
                self.assertEqual(added['runs'][-1]['config']['algorithm_code_sha'],current)
        self.assertEqual(app.state.experiments.listing()['total'],len(sources))
        catalog=route('/api/algorithms','GET')()['items']
        self.assertTrue(all(prop.get('description') for a in catalog for prop in a['parameters']['properties'].values()))

    def test_cesium_retains_original_page_and_run_context(self):
        # Explicit synthetic certification fixture: tests URL ownership, not physics.
        from test_integrated_replay import fixture
        with fixture() as f:
            route=lambda path:next(r.endpoint for r in f.app.routes if r.path==path)
            child=route('/visualization/cesium/{run_id}')(f.run_id)
            self.assertTrue(child.headers['location'].startswith('/visualization/cesium-page?'))
            self.assertIn('experiment_id=',child.headers['location'])
            self.assertIn(f.run_id,child.headers['location'])
            raw=route('/visualization/cesium-page')()
            self.assertTrue(str(raw.path).endswith('draw/cesium_viewer.html'))
            context=route('/api/runs/{run_id}/experiment')(f.run_id)
            self.assertEqual(context['runs'][0]['run_id'],f.run_id)


if __name__=='__main__':unittest.main()
