"""独立高冲突家族、受保护索引只读、配对采样和旧分布保护。"""
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch
from collections import Counter
from scripts.build_conflict_dataset import family_plan,satellites,protected_groups
from algorithms.lavis.training import splits,validation_rank
from algorithms.lavis.labels import collect,label_state,conflict_options
from algorithms.lavis.protocol import Control
from algorithms.lavis.candidates import build_pool
from schedulers.constraint_model import Schedule
from test_lavis import tiny
from schedulers.scenario_loader import SchedulingTask

class FamilyTests(unittest.TestCase):
    def test_48_fresh_families_are_preassigned_32_16_and_stratified(self):
        plan=family_plan();self.assertEqual(plan,family_plan())
        self.assertEqual(Counter(r['split'] for r in plan),{'train_development':32,'validation':16})
        self.assertEqual(len({r['lineage_group_id'] for r in plan}),48)
        self.assertEqual(len({r['seed'] for r in plan}),48)
        self.assertTrue(all(r['seed']>=2**63 for r in plan))
        for profile in {r['profile']['name'] for r in plan}:
            self.assertEqual(Counter(r['split'] for r in plan if r['profile']['name']==profile),{'train_development':8,'validation':4})

    def test_orbits_are_new_synthetic_values_and_reproducible_proposals(self):
        a,b=family_plan()[:2];s=satellites(a)
        self.assertEqual(s,satellites(a));self.assertNotEqual(s,satellites(a,{0:1}))
        self.assertNotEqual(s[0]['orbital_params'],satellites(b)[0]['orbital_params'])
        self.assertTrue(all(x['id'].startswith('HC') for x in s))
        self.assertTrue(all(x['orbital_params']['epoch'].startswith('2025-12') for x in s))
        self.assertTrue(all(x['maneuverability_capability']['max_yaw_angle_deg']==45 for x in s))

    def test_protected_index_reads_no_scene_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'splits').mkdir()
            for name in ('train_development','validation'):
                (root/'splits'/(name+'.json')).write_text(json.dumps([dict(artifact_id=name,lineage_group_id=name,scenario_sha256=name)]))
            freeze=root/'final_test'/'test_freeze.json';freeze.parent.mkdir()
            freeze.write_text(json.dumps({'records':[dict(artifact_id=str(i),lineage_group_id='private-'+str(i),scenario_sha256=str(i)) for i in range(20)]}))
            # 若实现误扫私有场景，将遇到无法当JSON读取的哨兵；这里只允许索引字段。
            (freeze.parent/'DO_NOT_READ.json').write_bytes(b'not scene data')
            groups,proof=protected_groups(root,freeze)
            self.assertEqual(len(groups),22);self.assertEqual(proof['protected_test_source_count'],20)
            self.assertFalse(proof['protected_scene_content_read']);self.assertFalse(proof['protected_targets_or_labels_used'])

    def test_same_orbit_family_cannot_cross_extra_train_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'splits').mkdir()
            (root/'dataset_spec.json').write_text(json.dumps({'dataset_id':'lavis-conflict-v1','families':[
                {'lineage_group_id':'new-a','split':'train_development'},{'lineage_group_id':'new-b','split':'validation'}]}))
            (root/'isolation_report.json').write_text(json.dumps({'all_family_siblings_same_split':True,'protected_groups_disjoint':True,'final_test_content_used':False}))
            for group,cohort in [('new-a','train_development'),('new-b','validation')]:
                (root/'splits'/(cohort+'.json')).write_text(json.dumps([{'artifact_id':group,'scenario_sha256':group,
                    'lineage_group_id':group,'orbital_family_sha256':'same-orbit','data_origin':'lavis-conflict-v1'}]))
            with self.assertRaisesRegex(ValueError,'FAMILY_LEAKAGE'):splits(root)

class SamplingTests(unittest.TestCase):
    def test_sibling_states_include_scene_sha_to_avoid_cross_variant_deduplication(self):
        p,cm=tiny();pool,_=build_pool(p,cm,Control());rows=[]
        for sha in ('a','b'):
            rows.append(list(label_state(p,cm,pool,Schedule(),pool,{'scenario_sha256':sha},42,'state',sampler='conflict-v2')))
        self.assertNotEqual(rows[0][0]['state_hash'],rows[1][0]['state_hash'])
        self.assertEqual([x['y'] for x in rows[0]],[x['y'] for x in rows[1]])

    def test_reachable_sampling_includes_middle_of_short_trace(self):
        p,cm=tiny()
        for i in range(40):p.tasks['ZERO'+str(i)]=SchedulingTask('ZERO'+str(i),1,2,[])
        pool,_=build_pool(p,cm,Control())
        rows=collect(p,cm,pool,{'scenario_sha256':'tiny','artifact_id':'tiny'},states=10,sampler='conflict-v2')
        self.assertTrue(any(r['n0']==1 for r in rows));self.assertTrue(all(r['n0']<2 for r in rows))

    def test_old_distribution_guard_beats_a_challenge_only_gain(self):
        def result(old,hard):return {'cohorts':{'eos-course-v1':{'completed':old},'lavis-conflict-v1':{'family_macro_TCR':hard}}}
        ref=result(715,.1)
        self.assertLess(validation_rank(result(715,.2),{},ref),validation_rank(result(714,.9),{},ref))
        self.assertLess(validation_rank(result(715,.3),{},ref),validation_rank(result(715,.2),{},ref))


    def test_all_regressing_trials_are_rejected_without_registering_weights(self):
        try:
            import sklearn.ensemble
        except ImportError:
            self.skipTest('需要requirements-ml.txt')
        from algorithms.lavis.training import train
        def result(old,hard):
            return {'completed':old+10,'macro_TCR':hard,'cohorts':{
                'eos-course-v1':{'completed':old},'lavis-conflict-v1':{'family_macro_TCR':hard}}}
        rows=[{'lineage_group_id':'train-only','state_hash':'s','candidate':[i],
               'features':[float(i)]*24,'y':float(i)} for i in (0,1)]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('algorithms.lavis.training.training_rows',return_value=(rows,[],{})), \
                 patch('algorithms.lavis.training.model_root',return_value=root/'models'), \
                 patch('algorithms.lavis.training.freeze',return_value={}), \
                 patch('algorithms.lavis.training.FrozenPredictor'), \
                 patch('algorithms.lavis.training.evaluate',side_effect=[result(715,.1)]+[result(714,.9)]*8), \
                 patch('sklearn.ensemble.HistGradientBoostingRegressor'), \
                 patch('builtins.print'):
                with self.assertRaisesRegex(ValueError,'ORIGINAL_VALIDATION_REGRESSION'):
                    train(root/'dataset',root,model_id='reject-me',extra_dataset=root/'extra')
            self.assertFalse((root/'models'/'reject-me').exists())
            report=json.loads((root/'rejected-validation-trials.json').read_text())
            self.assertEqual(len(report['trials']),8)
            self.assertFalse(report['final_test_used'])


class RelativeTargetTests(unittest.TestCase):
    def rows(self):
        return [dict(lineage_group_id='g',state_hash=state,candidate=[i],y=value,r=20)
                for state,values in [('a',[.4,.4,.5]),('flat',[.9,.9])] for i,value in enumerate(values)]

    def test_advantage_ignores_state_baseline_and_does_not_mutate_labels(self):
        from scripts.refine_lavis_ranking import relative_targets
        rows=self.rows();before=json.loads(json.dumps(rows))
        a=relative_targets(rows,'task_advantage')
        b=relative_targets([dict(r,y=r['y']+.2) for r in rows],'task_advantage')
        self.assertEqual(rows,before);self.assertEqual(len(a),3)
        self.assertAlmostEqual(sum(r['y'] for r in a),0.)
        for x,y in zip(a,b):self.assertAlmostEqual(x['y'],y['y'])
        self.assertAlmostEqual(a[2]['y']-a[0]['y'],2.)

    def test_ordinal_target_keeps_ties_without_using_absolute_values(self):
        from scripts.refine_lavis_ranking import relative_targets
        a=relative_targets(self.rows(),'ordinal_rank')
        self.assertEqual([r['y'] for r in a],[-.25,-.25,.5])
        with self.assertRaisesRegex(ValueError,'NO_INFORMATIVE'):
            relative_targets([r for r in self.rows() if r['state_hash']=='flat'],'ordinal_rank')

    def test_publication_requires_both_cohorts_and_strict_challenge_gain(self):
        from scripts.refine_lavis_ranking import passes_reference
        def result(old,hard,macro):return {'cohorts':{'eos-course-v1':{'completed':old},
            'lavis-conflict-v1':{'completed':hard,'family_macro_TCR':macro}}}
        ref=result(715,1410,.452)
        self.assertFalse(passes_reference(ref,ref))
        self.assertFalse(passes_reference(result(714,1500,.5),ref))
        self.assertFalse(passes_reference(result(715,1409,.5),ref))
        self.assertTrue(passes_reference(result(715,1411,.453),ref))

if __name__=='__main__':unittest.main()
