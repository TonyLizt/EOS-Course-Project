"""Registry + real spawn Worker + Controller + SQLite + replay/gantt contracts.

Positive formal lifecycle is SYNTHETIC UNIT TEST ONLY, not physical certification.
The real unchanged epoch-fixed scene is separately exercised as planning_preview.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from algorithms.auction_bundle import RABASParams, ResourceAwareBundleAuctionScheduler, VERSION
from eos_system.algorithm_registry import get_algorithm, make_context
from eos_system.api import create_app
from eos_system.config import Settings, sha256_file
from eos_system.replay_service import REPLAY_CONFIG_ID
from certification_fixtures import unit_certify
from rabas_integration_fixture import write_scene, cache_orbits
from test_replay_backend import _DirectClient


ROOT=Path(__file__).resolve().parents[1]


def wait_for(predicate,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise AssertionError('isolated RABAS integration timeout')


class RABASIntegrationTests(unittest.TestCase):
    def test_registry_metadata_and_strict_http_validation(self):
        spec=get_algorithm('rabas')
        self.assertEqual(spec.version,VERSION)
        context=make_context(42,5,{},spec,{'max_bundle_size':3})
        self.assertIsInstance(context.params,RABASParams)
        self.assertIsInstance(spec.build(context),ResourceAwareBundleAuctionScheduler)
        info=spec.public_info()
        self.assertFalse(info['uses_initial_schedule'])
        self.assertEqual(info['availability'],'ready')
        self.assertEqual(info['parameters']['properties']['max_bundle_size']['default'],2)
        with tempfile.TemporaryDirectory(prefix='rabas-api-') as directory:
            app=create_app(Settings(Path(directory),Path(directory)/'scenes'))
            with _DirectClient(app) as client:
                for params in ({'max_bundle_size':True},{'opportunity_cost_weight':-1},{'reauction_mode':'partial'}):
                    response=client.post('/api/runs',json={'scenario_id':'not-needed',
                        'algorithm_id':'rabas','algorithm_params':params})
                    self.assertEqual(response.status_code,422)

    def test_fresh_import_has_no_registry_cycle_or_factory_requirement(self):
        result=subprocess.run([sys.executable,'-c',
            "import sys;import algorithms.auction_bundle;assert 'eos_system.algorithm_registry' not in sys.modules;"
            "from eos_system.algorithm_registry import get_algorithm;assert get_algorithm('rabas').version=='1.0.0'"],
            cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_real_worker_controller_storage_gantt_replay_SYNTHETIC_CERTIFICATE_ONLY(self):
        with tempfile.TemporaryDirectory(prefix='rabas-e2e-') as directory:
            root=Path(directory);scenes=root/'scenes';scenes.mkdir()
            scene=scenes/'synthetic.json';write_scene(scene)
            digest=sha256_file(scene)
            settings=Settings(root/'runtime',scenes,replay_build_timeout_s=30)
            cache_orbits(settings,digest)
            app=create_app(settings)
            with patch('eos_system.verification.certify_schedule',side_effect=unit_certify):
                app.state.controller.start()
                try:
                    with _DirectClient(app) as client:
                        request={'scenario_id':'synthetic','algorithm_id':'rabas','time_budget_s':5,
                                 'algorithm_params':{'max_bundle_size':2,'opportunity_cost_weight':.5}}
                        response=client.post('/api/experiments',json={'runs':[request]})
                        self.assertEqual(response.status_code,202,response.text)
                        record=response.json();rid=record['runs'][0]['run_id']
                        def done():
                            row=app.state.database.get_run(rid)
                            return row if row['status'] in {'SUCCEEDED','FAILED','TIMED_OUT'} else None
                        row=wait_for(done)
                        self.assertEqual(row['status'],'SUCCEEDED',row.get('error'))
                        self.assertEqual(row['metrics']['completed_tasks'],3)
                        self.assertEqual(row['config']['algorithm_params'],request['algorithm_params'])
                        self.assertEqual(row['config']['algorithm_version'],VERSION)
                        self.assertNotEqual(row['attempts'][0]['worker_pid'],os.getpid())
                        self.assertEqual(row['continuous_certification']['predicate'],'UNIT_TEST_ONLY')
                        self.assertEqual(client.get('/api/experiments').json()['total'],1)
                        schedule=client.get(f'/api/runs/{rid}/visualization/schedule')
                        self.assertEqual(schedule.status_code,200)
                        self.assertEqual(len(schedule.json()['assignments']),3)
                        gantt=client.get(f'/visualization/gantt/{rid}')
                        self.assertEqual(gantt.status_code,307)
                        self.assertIn(rid,gantt.headers['location'])
                        view=client.get(f'/visualization/cesium/{rid}')
                        self.assertEqual(view.status_code,307)
                        self.assertIn(rid,view.headers['location'])
                        response=client.post(f'/api/runs/{rid}/replay',json={'replay_config_id':REPLAY_CONFIG_ID})
                        self.assertIn(response.status_code,(200,202),response.text)
                        def replay_done():
                            status=client.get(f'/api/runs/{rid}/replay').json()
                            return status if status['replay_status'] in {'READY','FAILED'} else None
                        status=wait_for(replay_done)
                        self.assertEqual(status['replay_status'],'READY',status)
                        self.assertEqual(sha256_file(scene),digest)
                finally:
                    app.state.temporary_controls.close()
                    app.state.replay.close()
                    app.state.controller.stop()

    def test_unchanged_real_scene_preview_and_formal_gate(self):
        scene=ROOT/'experiments/scenarios/small/Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1.json'
        if not scene.exists() or scene.stat().st_size<1024:
            self.skipTest('small scene LFS payload not available; do not fake physical input')
        with tempfile.TemporaryDirectory(prefix='rabas-real-') as directory:
            settings=Settings(Path(directory)/'runtime',scene.parent)
            app=create_app(settings)
            digest=sha256_file(scene)
            app.state.controller.start()
            try:
                with _DirectClient(app) as client:
                    for mode in ('planning_preview','formal'):
                        response=client.post('/api/runs',json={'scenario_id':scene.stem,
                            'algorithm_id':'rabas','execution_mode':mode,'time_budget_s':5})
                        self.assertEqual(response.status_code,202,response.text)
                        rid=response.json()['run_id']
                        def done():
                            row=app.state.database.get_run(rid)
                            return row if row['status'] in {'SUCCEEDED','FAILED','TIMED_OUT'} else None
                        row=wait_for(done)
                        if mode=='planning_preview':
                            self.assertEqual(row['status'],'SUCCEEDED',row.get('error'))
                            self.assertEqual(row['metrics']['completed_tasks'],20)
                            self.assertEqual(row['continuous_certification']['status'],'NOT_CERTIFIED')
                        else:
                            self.assertEqual(row['status'],'FAILED')
                            self.assertIn('UNTRUSTED_PHYSICAL_SETTINGS',row['error']['message'])
                            self.assertIsNone(row['plan'])
                            self.assertIsNone(row['metrics'])
                    self.assertEqual(sha256_file(scene),digest)
            finally:
                app.state.temporary_controls.close();app.state.replay.close();app.state.controller.stop()


if __name__=='__main__':unittest.main()
