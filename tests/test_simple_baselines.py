"""简单基线机制测试：不把合成夹具作为物理核验证据。"""
from dataclasses import replace
import json
import random
import unittest

import test_basic_algorithms as fixtures
from algorithms.objectives import ObjectiveWeights
from algorithms.simple_baselines import SIMPLE_BASELINES, SimpleBaselineScheduler, SimpleBaselineCancelled
from eos_system.algorithm_registry import get_algorithm, get_native_algorithm, make_context
from schedulers.constraint_model import Schedule


class SimpleBaselineTests(unittest.TestCase):
    setUp = fixtures.BasicAlgorithmTests.setUp
    task = fixtures.BasicAlgorithmTests.task

    def run_policy(self, policy, seed=42, weights=None):
        spec=get_algorithm(policy)
        ctx=make_context(seed,5,weights or {},spec,{})
        plan=spec.build(ctx).solve(self.problem,self.cm,ctx)
        replay=Schedule()
        for assignment in sorted(plan.assignments,key=lambda a:(a.sat_start_time,a.task_id)):
            self.assertTrue(self.cm.is_feasible_assignment(assignment,replay))
            replay.assignments.append(assignment)
        self.assertEqual(len(plan.assignments),len(set(plan.assigned_task_ids)))
        json.dumps(plan.metadata,allow_nan=False)
        return plan,ctx

    def test_seed_reproducibility_and_no_global_rng_changes(self):
        for i in range(12):self.task(str(i),windows=((0,400),))
        before=random.getstate()
        first,_=self.run_policy('random_feasible')
        second,_=self.run_policy('random_feasible')
        other,_=self.run_policy('random_feasible',seed=43)
        self.assertEqual(first.assignments,second.assignments)
        self.assertNotEqual(first.metadata['simple_baseline']['task_order'],other.metadata['simple_baseline']['task_order'])
        self.assertEqual(before,random.getstate())

    def test_round_robin_cycles_satellites_and_keeps_task_identity(self):
        self.problem.satellites['T']=replace(self.problem.satellites['S'],id='T')
        for name in ('A','B'):
            task=self.task(name,windows=((10,20),))
            task.windows.append(replace(task.windows[0],window_id=10+len(self.problem.tasks),satellite_id='T'))
        plan,_=self.run_policy('satellite_round_robin')
        self.assertEqual([(a.task_id,a.satellite_id) for a in plan.assignments],[('A','S'),('B','T')])

    def test_same_physical_resource_constraints_apply(self):
        self.problem.satellites['S'].max_power_W=1
        self.problem.satellites['S'].sensors['cam'].power_consumption_W=1
        self.task('A');self.task('B')
        for policy in SIMPLE_BASELINES:
            plan,_=self.run_policy(policy)
            self.assertEqual(len(plan.assignments),1)

    def test_no_hidden_objective_optimization_or_r1_adapter(self):
        self.task('low',priority=1);self.task('high',priority=100)
        for policy in SIMPLE_BASELINES:
            a,_=self.run_policy(policy,weights=dict(w_profit=1))
            b,_=self.run_policy(policy,weights=dict(w_profit=0,w_completion=1))
            self.assertEqual(a.assignments,b.assignments)
            self.assertIs(get_algorithm(policy),get_native_algorithm(policy))
            self.assertFalse(get_algorithm(policy).public_info()['uses_initial_schedule'])
            self.assertFalse(get_algorithm(policy).version.endswith('+objective-v1'))

    def test_empty_missing_windows_and_invalid_candidates(self):
        self.task('no',windows=())
        self.task('too_long',duration=500)
        for policy in SIMPLE_BASELINES:
            plan,_=self.run_policy(policy)
            self.assertEqual(plan.assignments,[])

    def test_cancellation_and_budget_are_not_ignored(self):
        self.task('A')
        for policy in SIMPLE_BASELINES:
            _,ctx=self.run_policy(policy)
            with self.assertRaises(SimpleBaselineCancelled):
                get_algorithm(policy).build(ctx).solve(self.problem,self.cm,replace(ctx,is_cancelled=lambda:True))
            tick=[0.]
            def clock():
                tick[0]+=.01
                return tick[0]
            plan=SimpleBaselineScheduler(policy,clock=clock).solve(self.problem,self.cm,replace(ctx,time_budget_s=.01))
            self.assertEqual(plan.metadata['simple_baseline']['stop_reason'],'budget')

    def test_parameter_contract_rejects_unrecognized_or_invalid_fields(self):
        for policy in SIMPLE_BASELINES:
            for params in ({'max_candidates_per_task':0},{'max_positions_per_window':True},{'unknown':1}):
                with self.assertRaises(ValueError):get_algorithm(policy).parse_params(params)


if __name__=='__main__':unittest.main()
