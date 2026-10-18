"""公共场景配额/可复现来源及工程结果与严格连续认证的边界。"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from scripts.build_shared_dataset import allocation, missions, static_satellites
from eos_system.contracts import RunConfig
from eos_system.storage import Database, now
from eos_system.planning_preview import audit_preview, PhysicalValidatedRecord
from eos_system.exporting import render_json, render_csv, require_certified_record


class AllocationTests(unittest.TestCase):
    def test_100_sources_and_stratified_60_20_20(self):
        rows=allocation()
        self.assertEqual(len(rows),100)
        self.assertEqual(len({r['lineage_group_id'] for r in rows}),100)
        self.assertEqual(Counter(r['split'] for r in rows),{'train_development':60,'validation':20,'final_test':20})
        for scale in {r['scale'] for r in rows}:
            group=[r for r in rows if r['scale']==scale]
            self.assertEqual(len(group),25)
            self.assertEqual(Counter(r['distribution_type'] for r in group),{0:13,1:12})
            self.assertEqual(Counter(r['split'] for r in group),{'train_development':15,'validation':5,'final_test':5})

    def test_all_task_collections_unique_reproducible_and_controlled(self):
        serialized=[]
        for config in allocation():
            tasks=missions(config)
            self.assertEqual(tasks,missions(config))
            self.assertEqual(len(tasks),config['task_count'])
            self.assertTrue(all(5<=t['observation_requirement']['duration_s']<=15 for t in tasks))
            serialized.append(json.dumps(tasks,sort_keys=True))
        self.assertEqual(len(set(serialized)),100)

    def test_static_inputs_match_real_raw_orbits(self):
        for size in (10,20):
            sats,record=static_satellites(size)
            self.assertEqual(len(sats),size)
            self.assertEqual(len(record['raw_satellite_sha256']),64)

    def test_cli_private_seeds_are_not_derived_from_public_seed_formula(self):
        from unittest.mock import patch
        from scripts import build_shared_dataset as builder
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'dataset'
            # 仅检查配额与私有seed冻结；limit1+only-final-test不执行任何场景计算。
            with patch.object(builder.visibility,'ensure_orekit'), patch.object(
                    builder.secrets,'randbelow',side_effect=range(400000000,400000020)), patch.object(
                    builder.secrets,'token_hex',side_effect=[f'UNIT_TEST_SOURCE_{i}' for i in range(20)]):
                builder.main(['--output',str(root),'--only-final-test','--limit','1'])
            rows=json.loads((root/'dataset_spec.json').read_text())['allocation']
            expected=allocation()
            for actual,public in zip(rows,expected):
                if actual['split']=='final_test':
                    self.assertNotEqual(actual['task_seed'],public['task_seed'])
                    self.assertEqual(actual['position_seed'],actual['task_seed']*10+1)
                else:self.assertEqual(actual,public)
            self.assertFalse(list(root.rglob('EOS-G*.json')))


class FreshProvenanceTests(unittest.TestCase):
    def test_fresh_sources_allow_no_parent_but_do_not_claim_continuous_pass(self):
        from eos_system.provenance import capture_provenance
        from utils.continuous_exposure import window_generation_record
        with tempfile.TemporaryDirectory() as directory:
            scene=Path(directory)/'EOS-Gunit.json';scene.write_text('{}')
            sha=hashlib.sha256(scene.read_bytes()).hexdigest()
            folder=scene.parent/'provenance';folder.mkdir()
            sidecar=folder/(scene.name+'.provenance.json')
            record=dict(artifact_kind='fresh_generated_shared_v1',scenario_sha256=sha,
                completion_status='complete',calculator_kind='orekit',window_boundary_version='visibility_exit_refined_v3',
                window_generation=window_generation_record(10,5,60),provenance_status='verified_generation',
                publication_status='development',formal_release_eligible=False,parent_scenario_sha256=None,
                lineage_group_id='UNIT_TEST_SOURCE',physical_validation={'status':'SAMPLED_PASS','continuous_status':'INCONCLUSIVE'})
            sidecar.write_text(json.dumps(record))
            captured=capture_provenance(scene,sha)
            self.assertIsNone(captured['parent_scenario_sha256'])
            self.assertEqual(captured['physical_validation_status'],'SAMPLED_PASS')
            self.assertEqual(captured['continuous_certification_status'],'INCONCLUSIVE')
            for change in ({'scenario_sha256':'0'*64},{'formal_release_eligible':True},
                           {'physical_validation':{'status':'PASS','continuous_status':'PASS'}}):
                sidecar.write_text(json.dumps({**record,**change}))
                with self.assertRaises(ValueError):capture_provenance(scene,sha)

    def test_only_line_endings_are_normalized(self):
        from utils.continuous_exposure import window_physics_sources,WINDOW_PHYSICS_FILES
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in WINDOW_PHYSICS_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'actual_code=1\r\n')
            crlf=window_physics_sources(root)
            for name in WINDOW_PHYSICS_FILES:(root/name).write_bytes(b'actual_code=1\n')
            self.assertEqual(crlf,window_physics_sources(root))
            (root/WINDOW_PHYSICS_FILES[0]).write_bytes(b'actual_code=2\n')
            self.assertNotEqual(crlf,window_physics_sources(root))

    def test_fresh_physics_binding_rejects_changed_geometry_but_ignores_controller_identity(self):
        from utils.continuous_exposure import window_generation_record,planning_evidence
        with tempfile.TemporaryDirectory() as directory:
            scene=Path(directory)/'unit.json';scene.write_text('{}')
            sha=hashlib.sha256(scene.read_bytes()).hexdigest()
            folder=scene.parent/'provenance';folder.mkdir();side=folder/(scene.name+'.provenance.json')
            window=window_generation_record(10,5,60)
            window['source_files_sha256']={'controller_history':'an earlier actual deployment'}
            record=dict(artifact_kind='fresh_generated_shared_v1',scenario_sha256=sha,
                completion_status='complete',calculator_kind='orekit',
                window_boundary_version='visibility_exit_refined_v3',window_generation=window)
            side.write_text(json.dumps(record))
            self.assertTrue(planning_evidence({},scene,sha)['trusted'])
            window['physics_sources_sha256_lf']['utils/visibility.py']='0'*64
            side.write_text(json.dumps(record))
            self.assertIsNone(planning_evidence({},scene,sha))


class EngineeringRecordTests(unittest.TestCase):
    def test_engineering_export_is_labeled_and_cannot_be_continuously_certified(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scene=root/'unit.json'
            scene.write_text('{"scenario_id":"unit","metadata":{},"missions":[],"satellites":[]}')
            config=RunConfig(run_id='engineering-unit',scenario_id='unit',scenario_path=str(scene),
                scenario_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),algorithm_id='completion_first',
                algorithm_version='baseline-1',execution_mode='physical_validation',created_at=now())
            db=Database(root/'results.sqlite3');db.enqueue(config,8)
            attempt,_=db.start_attempt(config.run_id);db.set_verifying(config.run_id,attempt)
            plan=dict(scenario_id='unit',assignments=[],unassigned_tasks=[])
            metrics=dict(completed_tasks=0,total_tasks=0,task_profit=0,task_completion_rate=0,
                balance_degree=0,timeliness_metric=0,runtime_efficiency=.01,robustness_variance=None,mip_gap=None)
            receipt=audit_preview(config,plan,deadline=time.monotonic()+10)
            self.assertEqual(receipt.evidence()['status'],'SAMPLED_PHYSICAL_PASS')
            self.assertTrue(db.finish_preview(config.run_id,attempt,plan,metrics,.01,
                receipt=receipt,deadline=time.monotonic()+10))
            record=db.get_run(config.run_id)
            self.assertIsInstance(record,PhysicalValidatedRecord)
            self.assertEqual(record['continuous_certification']['status'],'NOT_CERTIFIED')
            exported=json.loads(render_json(record))
            self.assertEqual(exported['result_kind'],'physical_validation')
            self.assertIn('not a continuous',exported['physical_validation']['validation_scope'])
            self.assertIn(b'SAMPLED_PHYSICAL_PASS',render_csv(record))
            with self.assertRaises(ValueError):require_certified_record(record)
            # 普通dict即使自报状态也不能作为Storage签发记录导出。
            with self.assertRaises(ValueError):render_json(dict(record))
            db.record_export(config.run_id,'json',render_json(record))


if __name__=='__main__':unittest.main()
