"""LAVIS专项机制：模型控制、共享约束、标签语义、数据隔离与制品冻结。"""
from datetime import datetime,timedelta
from collections import defaultdict
from dataclasses import replace
import io,json,math,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from algorithms.lavis.protocol import *
from algorithms.lavis.candidates import build_pool,feasible,key
from algorithms.lavis.features import extract
from algorithms.lavis.labels import label_state
from algorithms.lavis.solver import LavisScheduler
from algorithms.lavis.training import splits,weighted_arrays
from algorithms.lavis.model import *
from schedulers.constraint_model import ConstraintModel,Schedule
from schedulers.scenario_loader import SchedulingProblem,SchedulingTask,SchedulingSatellite,SensorSpec,TaskWindow

class DiscreteFixture(ConstraintModel):
    # 合成例仅验证构造与离散机制，不伪造物理证据。真实Orekit链路另做集成验收。
    def is_feasible_assignment(self,a,p):return self.check_discrete_assignment(a,p)

def tiny():
    start=datetime(2025,11,18);end=start+timedelta(seconds=30)
    sensors={'C':SensorSpec('C',0.,0.)}
    satellites={sid:SchedulingSatellite(sid,sensors=sensors,stabilization_time_s=0.) for sid in ('S1','S2')}
    tasks={tid:SchedulingTask(tid,1.,2.) for tid in ('T1','T2')}
    for ordinal,(tid,sid) in enumerate([('T1','S1'),('T1','S2'),('T2','S1')],1):
        tasks[tid].windows.append(TaskWindow(ordinal,sid,tid,'C',1,start,start+timedelta(seconds=3),
            agile_data={'roll':[0.,0.,0.],'pitch':[0.,0.,0.]}))
    p=SchedulingProblem('tiny',start,end,satellites,{},tasks,[])
    return p,DiscreteFixture(p)

class Bias:
    def __init__(self,index):self.index=index;self.calls=0
    def predict(self,rows):
        scores=[0.]*len(rows)
        if self.calls==0:scores[self.index]=1.
        self.calls+=1;return scores

class MechanismTests(unittest.TestCase):
    def setUp(self):
        self.problem,self.cm=tiny();self.pool,_=build_pool(self.problem,self.cm,Control())
        self.ctx=SolveContext(42,5,ObjectiveWeights(0,1,0,0),LavisParams())

    def test_multisatellite_candidates_and_model_scores_change_decision(self):
        self.assertEqual(len(self.pool),3)
        a=LavisScheduler(Bias(0)).solve(self.problem,self.cm,self.ctx)
        b=LavisScheduler(Bias(1)).solve(self.problem,self.cm,self.ctx)
        self.assertNotEqual(key(a.assignments[0]),key(b.assignments[0]))
        self.assertEqual(len(a.assignments),1);self.assertEqual(len(b.assignments),2)
        self.assertEqual(len(set(b.assigned_task_ids)),len(b.assignments))

    def test_main_quaternion_boundaries_are_preserved_and_fractional_endpoint_rejected(self):
        from schedulers.assignment_building import configured_observation
        from schedulers.source_windows import observation_source_matches
        task=self.problem.tasks['T1'];window=task.windows[0]
        window.agile_data['boundary_quaternions_xyzw']=[[0.,0.,0.,1.] for _ in range(4)]
        a=configured_observation(self.problem,task,window,'earliest')
        self.assertEqual(len(a.sat_angles['boundary_quaternions_xyzw']),3)
        self.assertTrue(observation_source_matches(self.problem,task,window,vars(a),a.sat_start_time,a.sat_end_time))
        task.required_duration=1.5
        bad=configured_observation(self.problem,task,window,'earliest')
        self.assertFalse(observation_source_matches(self.problem,task,window,vars(bad),bad.sat_start_time,bad.sat_end_time))

    def test_expanded_positions_are_source_aligned_and_original_defaults_unchanged(self):
        import copy
        before = copy.deepcopy(self.problem.tasks)
        original,_ = build_pool(self.problem,self.cm,Control())
        expanded,stats = build_pool(self.problem,self.cm,Control(),strategy='expanded')
        self.assertEqual(len(original),3)
        self.assertGreater(len(expanded),len(original))
        self.assertTrue(set(map(key,original)).issubset(set(map(key,expanded))))
        self.assertEqual(self.problem.tasks,before)
        self.assertEqual(stats['candidate_strategy'],'expanded')
        for item in expanded:
            self.assertEqual((item.sat_start_time-self.problem.start_time).total_seconds()%1,0)
            self.assertTrue(self.cm.is_feasible_assignment(item,Schedule()))

    def test_multistart_preserves_incumbent_and_uses_model_alternative(self):
        single=LavisScheduler(Bias(0)).solve(self.problem,self.cm,self.ctx)
        context=replace(self.ctx,params=LavisParams(search_mode='multistart',max_branches=4))
        branched=LavisScheduler(Bias(0)).solve(self.problem,self.cm,context)
        self.assertEqual(len(single.assignments),1)
        self.assertEqual(len(branched.assignments),2)
        self.assertTrue(branched.metadata['lavis']['weights_reused'])
        self.assertEqual(len(set(branched.assigned_task_ids)),2)
        replay=Schedule()
        for item in branched.assignments:
            self.assertTrue(self.cm.is_feasible_assignment(item,replay))
            replay.assignments.append(item)

    def test_all_24_features_and_overlap_pressure(self):
        rows=extract(self.problem,Schedule(),self.pool,self.pool,Control())
        self.assertTrue(all(len(r)==24 and all(math.isfinite(x) for x in r) for r in rows))
        self.assertEqual(rows[0][15],1.);self.assertEqual(rows[1][15],0.)
        self.assertEqual(rows[0][16],1.)

    def test_labels_are_paired_continuations_not_teacher_action_flags(self):
        args=(self.problem,self.cm,self.pool,Schedule(),self.pool,{'lineage_group_id':'tiny'},42,'state:0')
        first=list(label_state(*args));second=list(label_state(*args))
        self.assertEqual(first,second)
        self.assertEqual([r['y'] for r in first],[.5,1.,1.])
        self.assertEqual([len(r['fixed_assignments']) for r in first],[0,0,0])

    def test_dynamic_mask_matches_full_shared_check_and_invalidates_conflict(self):
        plan=Schedule([self.pool[0]])
        self.assertEqual(feasible(self.pool,plan,self.cm,Control()),[])
        plan=Schedule([self.pool[1]])
        optimized=feasible(self.pool,plan,self.cm,Control())
        full=[a for a in self.pool if self.cm.is_feasible_assignment(a,plan)]
        self.assertEqual([key(a) for a in optimized],[key(a) for a in full])

    def test_long_window_has_one_configured_position_and_cancellation_is_not_success(self):
        w=self.problem.tasks['T1'].windows[0];w.end_time=w.start_time+timedelta(days=1000)
        pool,stats=build_pool(self.problem,self.cm,Control())
        self.assertEqual(len(pool),3)
        with self.assertRaises(LavisCancelled):
            LavisScheduler(Bias(0)).solve(self.problem,self.cm,replace(self.ctx,is_cancelled=lambda:True))
        with self.assertRaises(BudgetExpired):build_pool(self.problem,self.cm,Control(deadline=0))

    def test_close_scores_are_not_clipped_and_nonfinite_is_rejected(self):
        class Close:
            def predict(self,rows):return [1.000001]+[1.000002]*(len(rows)-1)
        result=LavisScheduler(Close()).solve(self.problem,self.cm,self.ctx)
        self.assertEqual(key(result.assignments[0]),key(self.pool[1]))
        class Bad:
            def predict(self,rows):return [float('nan')]*len(rows)
        with self.assertRaisesRegex(ValueError,'NONFINITE'):LavisScheduler(Bad()).solve(self.problem,self.cm,self.ctx)
        with self.assertRaisesRegex(ValueError,'COMPLETION_ONLY'):
            LavisScheduler(Bias(0)).solve(self.problem,self.cm,replace(self.ctx,objective_weights=ObjectiveWeights()))

    def test_splits_are_60_20_and_group_disjoint(self):
        rows=splits();self.assertEqual(len(rows['train_development']),60);self.assertEqual(len(rows['validation']),20)
        self.assertFalse({r['lineage_group_id'] for r in rows['train_development']} & {r['lineage_group_id'] for r in rows['validation']})

class ModelIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.patch=patch.dict('os.environ',{'EOS_RUNTIME_DIR':self.temp.name});self.patch.start();self.addCleanup(self.patch.stop)

    def artifact(self):
        try:
            import joblib,numpy as np
            from sklearn.ensemble import HistGradientBoostingRegressor
            from threadpoolctl import threadpool_limits
        except ImportError:self.skipTest('需要requirements-ml.txt；算法本体导入不依赖sklearn')
        from algorithms.lavis.protocol import FEATURE_NAMES,DOMAIN,POOL_CONFIG,FEATURE_VERSION,CANDIDATE_VERSION,LABEL_VERSION
        with threadpool_limits(limits=1):
            X=np.arange(24*40).reshape(40,24);model=HistGradientBoostingRegressor(max_iter=3,min_samples_leaf=2).fit(X,np.arange(40)/40)
        blob=io.BytesIO();joblib.dump(model,blob);raw=blob.getvalue()
        directory=model_root()/'tiny';directory.mkdir(parents=True)
        manifest=dict(model_id='tiny',model_version='0.1.0',format='team-joblib-v1',model_sha256=digest(raw),
            feature_version=FEATURE_VERSION,features=list(FEATURE_NAMES),candidate_version=CANDIDATE_VERSION,
            label_version=LABEL_VERSION,pool_config=POOL_CONFIG,domain=DOMAIN,dependencies=dependencies(),
            inference_code_sha256_lf=inference_code_sha())
        (directory/'model.joblib').write_bytes(raw);(directory/'manifest.json').write_text(json.dumps(manifest))
        return directory

    def test_opportunity_model_loads_only_with_explicit_training_contract(self):
        directory = self.artifact()
        path = directory/'manifest.json'
        manifest = json.loads(path.read_text())
        manifest.update(label_version='lavis-opportunity-cost-v1',
                        training_protocol='lavis-opportunity-cost-v1',
                        training_candidate_strategy='expanded')
        path.write_text(json.dumps(manifest))
        snapshot = freeze('tiny')
        self.assertEqual(snapshot['label_version'], 'lavis-opportunity-cost-v1')
        self.assertTrue(math.isfinite(FrozenPredictor(snapshot).predict([[0.]*24])[0]))
        # 不允许只有新标签名、却缺少对应训练合同的制品混入模型列表。
        del manifest['training_protocol']
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'INCOMPATIBLE_MODEL'):
            freeze('tiny')

    def test_real_training_loading_and_replacement_sha_fail_closed(self):
        directory=self.artifact();snapshot=freeze('tiny');predictor=FrozenPredictor(snapshot)
        prediction=predictor.predict([[0.]*24,[1000.]*24]);self.assertNotEqual(prediction[0],prediction[1])
        (directory/'model.joblib').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SHA_MISMATCH'):verify_snapshot(snapshot)

    def test_reviewed_legacy_weights_freeze_runtime_adapter_without_rewriting_artifact(self):
        from utils.course_compatibility import LEGACY_INFERENCE_SHA
        directory = self.artifact()
        path = directory/'manifest.json'
        manifest = json.loads(path.read_text())
        manifest.update(inference_code_sha256_lf=LEGACY_INFERENCE_SHA,
                        scenario_physics_version='fresh_epoch_parsed_v1')
        path.write_text(json.dumps(manifest))
        original = path.read_bytes()
        snapshot = freeze('tiny')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(snapshot['inference_code_sha256_lf'], LEGACY_INFERENCE_SHA)
        self.assertEqual(snapshot['runtime_compatibility']['runtime_inference_code_sha256_lf'], inference_code_sha())
        FrozenPredictor(snapshot)
        # 适配器更新后也要拒绝已提交的旧快照，不仅检查训练时的指纹。
        with patch('algorithms.lavis.model.inference_code_sha', return_value='changed-runtime'):
            with self.assertRaisesRegex(ValueError, 'CHANGED_AFTER'): verify_snapshot(snapshot)
        manifest['inference_code_sha256_lf'] = 'unknown-history'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'INCOMPATIBLE'): freeze('tiny')

    def test_shared_attitude_module_change_invalidates_frozen_model(self):
        self.artifact();freeze('tiny')
        original=Path.read_bytes
        def changed(path):
            raw=original(path)
            return raw+b'\n# UNIT_TEST_ONLY changed attitude contract\n' if path.as_posix().endswith('/utils/attitude_frames.py') else raw
        # 只替换本进程读取结果，不修改仓库或实际物理源码。
        with patch.object(Path,'read_bytes',changed):
            with self.assertRaisesRegex(ValueError,'INCOMPATIBLE'):freeze('tiny')

    def test_manifest_replacement_schema_and_paths_are_rejected(self):
        directory=self.artifact();snapshot=freeze('tiny')
        manifest=json.loads((directory/'manifest.json').read_text());manifest['model_version']='replaced'
        (directory/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'CHANGED_AFTER'):verify_snapshot(snapshot)
        manifest['feature_version']='wrong';(directory/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'INCOMPATIBLE'):freeze('tiny')
        with self.assertRaises(ValueError):freeze('../tiny')
        self.assertEqual(list_models(),[])

    def test_same_model_id_changed_snapshot_has_distinct_idempotency_identity(self):
        from eos_system.experiments import algorithm_identity,common_config
        first={'algorithm_params':{'model_id':'tiny'},'model_provenance':{'model_sha256':'a'}}
        second=first|{'model_provenance':{'model_sha256':'b'}}
        self.assertNotEqual(algorithm_identity(first),algorithm_identity(second))
        self.assertEqual(common_config(first),common_config(second))

if __name__=='__main__':unittest.main()
