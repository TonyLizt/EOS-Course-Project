"""R1: requested goals belong to the experiment; model training goals do not replace them."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from eos_system.algorithm_registry import get_algorithm

TP = dict(w_profit=1., w_completion=0., w_timeliness=0., w_balance=0.)
TCR = dict(w_profit=0., w_completion=1., w_timeliness=0., w_balance=0.)
MIXED = dict(w_profit=.5, w_completion=.3, w_timeliness=.1, w_balance=.1)


class ObjectiveCompatibilityTests(unittest.TestCase):
    def test_registered_learned_solvers_accept_all_requested_goals(self):
        # Constructor contract only. No synthetic model or physical success is registered.
        for aid in ('ppo', 'lavis'):
            spec = get_algorithm(aid)
            for weights in (TP, TCR, MIXED):
                with self.subTest(algorithm=aid, weights=weights):
                    context = SolveContext(42, 2., ObjectiveWeights(**weights),
                        spec.parse_params({'model_id':'unit-model'}),
                        model_provenance={'model_id':'unit-model', 'model_sha256':'a'*64,
                                          'execution_mode':'physical_validation'})
                    with patch('algorithms.ppo.model.FrozenPolicy'), \
                         patch('algorithms.lavis.model.FrozenPredictor'), \
                         patch('algorithms.lavis.solver.FrozenPredictor'):
                        solver = spec.build(context)
                    self.assertTrue(callable(solver.solve))
                    self.assertEqual(vars(context.objective_weights), weights)

    def test_training_protocols_remain_strict_and_unchanged(self):
        from algorithms.ppo.protocol import validate_weights as ppo_training
        from algorithms.lavis.protocol import validate_weights as lavis_training
        with self.assertRaises(ValueError): ppo_training(ObjectiveWeights(**TCR))
        with self.assertRaises(ValueError): lavis_training(ObjectiveWeights(**TP))


class WeightAndDomainTests(unittest.TestCase):
    def test_arbitrary_weights_are_validated_and_requested_copy_is_unchanged(self):
        from eos_system.contracts import RunRequest
        from algorithms.objective_adapters.protocol import validate_model_request, validate_weights
        from copy import deepcopy
        goals = (TP, TCR, MIXED, dict(TP, w_profit=0., w_timeliness=2.),
                 dict(TP, w_profit=0., w_balance=3.), dict(TP, w_profit=37.))
        for aid in ('ppo', 'lavis'):
            for weights in goals:
                request = RunRequest(scenario_id='unit', algorithm_id=aid,
                    execution_mode='physical_validation', objective_weights=weights)
                before = deepcopy(request.model_dump())
                validate_model_request(aid, request, {'execution_mode':'physical_validation'})
                self.assertEqual(request.model_dump(), before)
                self.assertEqual(validate_weights(request.objective_weights), weights)
        for invalid in (dict(TP, w_profit=-1), dict(TP, w_profit=float('nan')),
                        dict(TP, w_profit=float('inf')), dict(TP, w_profit=0),
                        dict(TP, w_profit=1e308, w_completion=1e308)):
            with self.assertRaises(ValueError): validate_weights(invalid)

    def test_non_objective_model_domain_is_still_rejected(self):
        from eos_system.contracts import RunRequest
        from algorithms.objective_adapters.protocol import validate_model_request
        for aid in ('ppo','lavis'):
            for change in ({'placement_mode':'center'}, {'execution_mode':'formal'},
                           {'constraints':{'agility_profile':'Low-Agility'}}):
                raw = dict(scenario_id='unit', algorithm_id=aid, execution_mode='physical_validation', objective_weights=MIXED)
                raw.update(change)
                with self.assertRaisesRegex(ValueError, 'DOMAIN_MISMATCH'):
                    validate_model_request(aid, RunRequest(**raw), {'execution_mode':'physical_validation'})

    def test_original_model_inference_source_identity_is_preserved(self):
        from algorithms.ppo.model import inference_code_sha as ppo
        from algorithms.lavis.model import inference_code_sha as lavis
        self.assertEqual(ppo(), '4403af55a633025532107635feab6d5831b63e11d946621cfa091fb9acf58640')
        self.assertEqual(lavis(), '4fb3f8dedaa152daf512647f7963ad6cb8a36d6a30493278771ce198b7b8984e')


class ObjectiveSearchTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timedelta
        from schedulers.scenario_loader import SchedulingProblem, SchedulingTask, SchedulingSatellite, SensorSpec, TaskWindow
        from schedulers.constraint_model import ConstraintModel
        self.start = datetime(2026,1,1)
        sat = SchedulingSatellite('S1', maneuverability_type='non_agile', sensors={'cam':SensorSpec('cam',0.,0.)})
        self.problem = SchedulingProblem('R1_SYNTHETIC_MECHANISM_ONLY', self.start,
            self.start+timedelta(seconds=120), {'S1':sat}, {}, {}, [])
        for ordinal, (tid, priority, start, duration) in enumerate((('A',9,10,30),('B',4,10,10),('C',4,30,10)),1):
            window = TaskWindow(ordinal,'S1',tid,'cam',1,self.start+timedelta(seconds=start),
                self.start+timedelta(seconds=start+duration),
                non_agile_data={'roll_angle':0.,'pitch_angle':0.,'yaw_angle':0.},
                planning_evidence={'trusted':True,'version':'visibility_exit_refined_v3','step_s':1.,
                                   'evidence_sha256':'R1_UNIT_MECHANISM_NOT_PHYSICAL_ACCEPTANCE'})
            self.problem.tasks[tid] = SchedulingTask(tid,priority,duration,[window])
        self.problem.execution_mode = 'formal'
        self.cm = ConstraintModel(self.problem)

    def context(self, aid, weights):
        spec=get_algorithm(aid)
        return SolveContext(42,3.,ObjectiveWeights(**weights),spec.parse_params({'model_id':'unit'}),
            model_provenance={'model_id':'unit','model_sha256':'a'*64,'execution_mode':'formal'})

    def solver(self, aid, adapt=True, preferred=1):
        from algorithms.objective_adapters.search import PPOObjectiveSolver, LavisObjectiveSolver
        import numpy as np
        if aid=='ppo':
            solver=object.__new__(PPOObjectiveSolver)
            def scores(obs):
                result=np.where(obs['action_mask']>0, -1., -np.inf)
                result[0]=-2.
                if preferred < len(result) and obs['action_mask'][preferred]:result[preferred]=0.
                return result
            solver.action_scores=scores
        else:
            solver=object.__new__(LavisObjectiveSolver)
            class Predictor:
                def predict(self, rows):return [float(i==preferred-1) for i in range(len(rows))]
            solver.predictor=Predictor()
        solver.version='unit+objective-v1';solver.adapt=adapt
        return solver

    def assert_valid(self, plan):
        from schedulers.constraint_model import Schedule
        replay=Schedule()
        for a in sorted(plan.assignments,key=lambda a:a.sat_start_time):
            self.assertTrue(self.cm.is_feasible_assignment(a,replay))
            replay.assignments.append(a)

    def test_requested_weights_change_feasible_decisions_for_both_learned_adapters(self):
        for aid in ('ppo','lavis'):
            answers={}
            for name,weights in [('TP',TP),('TCR',TCR),('MIXED',MIXED)]:
                plan=self.solver(aid).solve(self.problem,self.cm,self.context(aid,weights))
                self.assert_valid(plan)
                answers[name]=set(plan.assigned_task_ids)
                metadata=plan.metadata['objective_adapter']
                self.assertGreater(metadata['model_calls'],0)
                self.assertGreater(metadata['objective_evaluations'],0)
                self.assertEqual(metadata['identity']['requested_objective'],weights)
                self.assertEqual(metadata['identity']['effective_objective'],weights)
            self.assertEqual(answers['TP'],{'A'},aid)
            self.assertEqual(answers['TCR'],{'B','C'},aid)
            self.assertEqual(answers['MIXED'],{'B','C'},aid)

    def test_independent_ablation_exposes_real_objective_search_effect(self):
        from algorithms.objectives import ObjectiveModel
        objective=ObjectiveModel(self.problem,ObjectiveWeights(**TCR))
        for aid in ('ppo','lavis'):
            native=self.solver(aid,False).solve(self.problem,self.cm,self.context(aid,TCR))
            adapted=self.solver(aid,True).solve(self.problem,self.cm,self.context(aid,TCR))
            self.assertGreater(objective.score(adapted),objective.score(native),aid)
            self.assertEqual(native.metadata['objective_adapter']['mode'],'ablation_model_only')

    def test_model_still_decides_equal_objective_allocations(self):
        from dataclasses import replace as dc_replace
        task=self.problem.tasks['A'];self.problem.tasks={'A':task}
        self.problem.satellites['S2']=dc_replace(self.problem.satellites['S1'],id='S2')
        task.windows.append(dc_replace(task.windows[0],window_id=4,satellite_id='S2'))
        for aid in ('ppo','lavis'):
            first=self.solver(aid,preferred=1).solve(self.problem,self.cm,self.context(aid,TP))
            second=self.solver(aid,preferred=2).solve(self.problem,self.cm,self.context(aid,TP))
            self.assertNotEqual(first.assignments[0].satellite_id,second.assignments[0].satellite_id,aid)

    def test_native_proposal_refinement_is_requested_objective_sensitive(self):
        from algorithms.candidate_pool import enumerate_task_candidates
        from algorithms.objective_adapters.search import refine,Control
        from schedulers.constraint_model import Schedule
        initial=Schedule([enumerate_task_candidates(self.problem,self.problem.tasks['A'],seed=42)[0]])
        answers=[]
        for weights in (TP,TCR):
            ctx=self.context('ppo',weights)
            result=refine(self.problem,self.cm,ctx,initial,Control(ctx))
            self.assert_valid(result);answers.append(set(result.assigned_task_ids))
        self.assertEqual(answers,[{'A'},{'B','C'}])

    def test_cancellation_does_not_return_success(self):
        for aid in ('ppo','lavis'):
            ctx=replace(self.context(aid,MIXED),is_cancelled=lambda:True)
            with self.assertRaises(RuntimeError):self.solver(aid).solve(self.problem,self.cm,ctx)


class ObjectiveIdentityTests(unittest.TestCase):
    def config(self, aid='ppo', weights=MIXED):
        from eos_system.contracts import RunConfig
        from algorithms.objective_adapters.protocol import freeze_adapter
        spec=get_algorithm(aid)
        model={'model_id':'unit-'+aid,'model_sha256':'a'*64} if aid in ('ppo','lavis') else {}
        return RunConfig(run_id='unit-'+aid,created_at='2026-01-01',scenario_id='unit',
            scenario_path='/read-only/unit.json',scenario_sha256='b'*64,
            algorithm_code_sha='c'*64,algorithm_id=aid,algorithm_version=spec.version,
            objective_weights=weights,model_provenance=model,
            objective_adapter=freeze_adapter(aid,spec.version,weights,model))

    def test_snapshot_binds_weights_version_code_model_and_effective_goal(self):
        from algorithms.objective_adapters.protocol import verify_adapter
        from copy import deepcopy
        for aid in ('ppo','lavis','caabs'):
            config=self.config(aid);verify_adapter(config)
            for field in ('effective_objective','requested_objective','training_objective',
                          'adapter_code_sha256_lf','solver_version','model_sha256'):
                changed=deepcopy(config.objective_adapter);changed[field]='tampered'
                with self.subTest(algorithm=aid,field=field),self.assertRaises(ValueError):
                    verify_adapter(config.model_copy(update={'objective_adapter':changed}))
            for update in ({'objective_adapter':{}},{'algorithm_version':'old'},
                           {'objective_weights':self.config(aid,TP).objective_weights},
                           {'model_provenance':{'model_sha256':'d'*64}}):
                with self.assertRaises(ValueError):verify_adapter(config.model_copy(update=update))

    def test_algorithm_metadata_is_separate_but_shared_objective_is_mandatory(self):
        from eos_system.experiments import common_config,algorithm_identity,Experiments
        from eos_system.storage import Database
        import tempfile
        from pathlib import Path
        a,b=self.config('ppo'),self.config('lavis')
        self.assertEqual(common_config(a.model_dump()),common_config(b.model_dump()))
        self.assertNotEqual(algorithm_identity(a.model_dump()),algorithm_identity(b.model_dump()))
        self.assertIn('objective_weights',common_config(a.model_dump()))
        with tempfile.TemporaryDirectory() as folder:
            store=Experiments(Database(Path(folder)/'unit.sqlite3'))
            eid=store.create([a,b],8,'same');self.assertEqual(len(store.detail(eid)['runs']),2)
            # Repeating identical request remains idempotent; no learned model identity is lost.
            self.assertEqual(store.create([a,b],8,'same'),eid)
            with self.assertRaises(ValueError):store.create([a,self.config('lavis',TP)],8)
            changed=b.model_copy(update={'objective_adapter':b.objective_adapter|{'mechanism':'other'}})
            with self.assertRaises(ValueError):store.create([a,changed],8,'same')

    def test_server_only_identity_and_invalid_weight_sum_rejected_by_http_contract(self):
        from eos_system.contracts import RunRequest
        for extra in ({'objective_adapter':{}}, {'model_provenance':{}},
                      {'objective_weights':dict(TP,w_profit=1e308,w_completion=1e308)}):
            with self.assertRaises(ValueError):RunRequest(scenario_id='unit',algorithm_id='ppo',**extra)


class AllNativeObjectivesTests(unittest.TestCase):
    setUp = ObjectiveSearchTests.setUp
    def test_each_native_algorithm_actually_evaluates_all_requested_goals(self):
        from eos_system.algorithm_registry import COMPARISON_ALGORITHMS,make_context
        tuning={'sa':{'max_iterations':2,'neighbor_attempts':2},
                'ga':{'population_size':4,'generations':1},'aco':{'ants':2,'iterations':1}}
        for aid in COMPARISON_ALGORITHMS:
            if aid in ('ppo','lavis'):continue
            for goal in (TP,TCR,MIXED):
                with self.subTest(algorithm=aid,weights=goal):
                    spec=get_algorithm(aid);ctx=make_context(42,2.,goal,spec,tuning.get(aid,{}))
                    plan=spec.build(ctx).solve(self.problem,self.cm,ctx)
                    info=plan.metadata['objective_adapter']
                    self.assertGreater(info['objective_evaluations'],0)
                    self.assertEqual(info['identity']['effective_objective'],goal)
                    self.assertTrue(plan.assignments)


class ObjectiveBudgetTests(unittest.TestCase):
    def test_search_reserves_return_time_without_expanding_solver_budget(self):
        from algorithms.objective_adapters.search import Control,BudgetExpired
        from types import SimpleNamespace
        context=SimpleNamespace(time_budget_s=5.,is_cancelled=lambda:False)
        with patch('algorithms.objective_adapters.search.time.monotonic',return_value=100.):
            control=Control(context)
        self.assertEqual(control.deadline,104.5)
        with patch('algorithms.objective_adapters.search.time.monotonic',return_value=104.5):
            with self.assertRaises(BudgetExpired):control.checkpoint()


class ObjectivePresentationTests(unittest.TestCase):
    def test_presented_model_schema_discloses_actual_versioned_adaptation(self):
        from eos_system.algorithm_presentation import algorithm_info
        for aid in ('ppo','lavis'):
            info=algorithm_info(get_algorithm(aid))
            text=info['parameters']['properties']['model_id']['description']
            self.assertIn('R1',text);self.assertIn('TP',text);self.assertIn('TCR',text)
            self.assertNotIn('仅支持完成率',text)
        modes=algorithm_info(get_algorithm('lavis'))['parameters']['properties']
        self.assertIn('束宽4',modes['search_mode']['description'])
        self.assertIn('min(8,max_branches)',modes['max_branches']['description'])
