"""RABAS mechanisms on synthetic public-model fixtures; NOT physical certificates."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from pydantic import ValidationError

from algorithms.auction_bundle import (RABASParams, RABASCancelled,
                                       ResourceAwareBundleAuctionScheduler)
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.evaluation_metrics import compute_evaluation_metrics
from schedulers.scenario_loader import (TaskWindow, CommWindow, SensorSpec, SchedulingTask,
    SchedulingSatellite, SchedulingGroundStation, SchedulingProblem)


class ObservedAuction(ResourceAwareBundleAuctionScheduler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bids, self.awards = [], []

    def _observe_bid(self, bid):
        self.bids.append(bid)

    def _observe_award(self, bid):
        self.awards.append(bid)


class RABASFixture(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1)
        self.problem = SchedulingProblem('RABAS_SYNTHETIC_UNIT_ONLY', self.start,
            self.start+timedelta(hours=1), {sid: SchedulingSatellite(sid,
                maneuverability_type='non_agile', sensors={'cam': SensorSpec('cam',819.2,1)})
                for sid in ('S1','S2')}, {}, {}, [])
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=0)
        self.window_id = 0

    def task(self, tid, placements, priority=1, width=10):
        windows = []
        for sid, offset in placements:
            self.window_id += 1
            windows.append(TaskWindow(self.window_id, sid, tid, 'cam', 1,
                self.start+timedelta(seconds=offset), self.start+timedelta(seconds=offset+width),
                agile_data={key: [0.] * (int(width)+1) for key in ('pitch_angles','roll_angles','yaw_angles')},
                non_agile_data={key:0. for key in ('pitch_angle','roll_angle','yaw_angle')},
                planning_evidence={'trusted':True,'version':'visibility_exit_refined_v3',
                                   'step_s':1.,'evidence_sha256':'RABAS_SYNTHETIC_UNIT_ONLY'}))
        self.problem.tasks[tid] = SchedulingTask(tid, priority, 10, windows)
        return self.problem.tasks[tid]

    def solve(self, **params):
        solver = ObservedAuction()
        context = SolveContext(42, 5, ObjectiveWeights(), RABASParams(**params))
        plan = solver.solve(self.problem, self.cm, context)
        self.feasible(plan)
        return solver, plan

    def feasible(self, plan):
        replay = Schedule()
        for a in sorted(plan.assignments, key=lambda a:a.sat_start_time):
            self.assertTrue(self.cm.is_feasible_assignment(a, replay))
            replay.assignments.append(a)
        self.assertEqual(len(plan.assignments), len(set(plan.assigned_task_ids)))


class AuctionMechanismTests(RABASFixture):
    def test_B1_opportunity_changes_actual_bid_and_allocation(self):
        self.task('T1',[('S1',0),('S2',0)],priority=10)
        self.task('T2',[('S1',0)],priority=1)
        args = dict(max_bundle_size=1, transition_cost_weight=0.,resource_cost_weight=0.)
        off, p0 = self.solve(opportunity_cost_weight=0., **args)
        on, p1 = self.solve(opportunity_cost_weight=.5, **args)
        self.assertEqual([(a.task_id,a.satellite_id) for a in p0.assignments],[('T1','S1')])
        self.assertEqual({(a.task_id,a.satellite_id) for a in p1.assignments},{('T1','S2'),('T2','S1')})
        target = lambda s:next(b for b in s.bids if b.plan_version==0 and b.satellite_id=='S1'
                             and [a.task_id for a in b.additions]==['T1'])
        self.assertGreater(target(on).opportunity_cost,0)
        self.assertLess(target(on).score,target(off).score)

    def test_B2_same_task_never_wins_twice(self):
        self.task('T1',[('S1',0),('S2',0)])
        solver, plan = self.solve()
        self.assertEqual(len(plan.assignments),1)
        self.assertEqual(len({b.satellite_id for b in solver.bids}),2)

    def test_B3_real_two_task_bid_is_globally_awarded_atomically(self):
        self.cm.non_agile_transition_s=10
        self.task('T1',[('S1',0)])
        self.task('T2',[('S1',30)])
        solver, plan = self.solve()
        pairs=[b for b in solver.bids if len(b.additions)==2]
        self.assertTrue(pairs)
        self.assertEqual(len(solver.awards),1)
        self.assertEqual(len(solver.awards[0].additions),2)
        self.assertEqual(len(plan.assignments),2)
        self.assertEqual(pairs[0].transition_seconds,10)
        self.assertGreater(pairs[0].resource_cost,0)
        self.feasible(pairs[0].candidate_plan)

    def test_middle_insertion_checks_successor_not_only_predecessor(self):
        self.cm.non_agile_transition_s=10
        self.task('late',[('S1',45)],priority=100)
        self.task('middle',[('S1',30)],priority=90)
        self.task('early',[('S1',0)],priority=1)
        solver, plan=self.solve()
        self.assertEqual(set(plan.assigned_task_ids),{'late','early'})
        self.assertFalse(any({'middle','late'} <= {a.task_id for a in b.additions} for b in solver.bids))

    def test_true_agile_transition_helper_used_for_bid_cost(self):
        self.problem.satellites['S1'].maneuverability_type='agile'
        self.task('T1',[('S1',0)],priority=2)
        task=self.task('T2',[('S1',100)])
        task.windows[0].agile_data['roll_angles']=[30.]*11
        solver,plan=self.solve()
        pair=next(b for b in solver.bids if len(b.additions)==2)
        ordered=sorted(pair.additions,key=lambda a:a.sat_start_time)
        self.assertAlmostEqual(pair.transition_seconds,self.cm._transition_time_s('S1',*ordered))
        self.assertGreater(pair.transition_cost,0)

    def test_cumulative_storage_prevents_three_task_bundle(self):
        self.problem.satellites['S1'].max_data_storage_GB=2.5
        for i in range(3): self.task(f'T{i}',[('S1',30*i)])
        solver,plan=self.solve(max_bundle_size=3)
        self.assertEqual(len(plan.assignments),2)
        self.assertEqual(plan.metadata['rabas']['stats']['max_bundle_built'],2)
        pair=next(b for b in solver.bids if len(b.additions)==2)
        self.assertAlmostEqual(pair.resources[0].storage_remaining_GB,.5)

    def test_power_capacity_is_not_energy_reinterpreted(self):
        self.problem.satellites['S1'].max_power_W=1.5
        self.task('T1',[('S1',0)]);self.task('T2',[('S1',30)])
        _,plan=self.solve()
        self.assertEqual(len(plan.assignments),1)

    def test_B4_shared_ground_station_invalidates_old_other_satellite_bid(self):
        self.problem.ground_stations['G']=SchedulingGroundStation('G')
        self.cm=ConstraintModel(self.problem,non_agile_transition_s=0)
        self.problem.comm_windows=[CommWindow(i,sid,'G',self.start+timedelta(seconds=30),
            self.start+timedelta(seconds=40)) for i,sid in enumerate(('S1','S2'),1)]
        self.task('T1',[('S1',0)],priority=2)
        self.task('T2',[('S2',0)])
        solver,plan=self.solve(max_bundle_size=1)
        self.assertEqual({b.satellite_id for b in solver.bids if b.plan_version==0},{'S1','S2'})
        self.assertEqual(len(plan.assignments),1)
        self.assertEqual(plan.assigned_task_ids,['T1'])
        self.assertEqual(plan.metadata['rabas']['stats']['reauctions'],1)
        self.assertEqual(plan.metadata['rabas']['stats']['stale_bids_rejected'],0)

    def test_B4_round_versions_rebuilt_after_award(self):
        for i in range(3): self.task(f'T{i}',[('S1',30*i)])
        solver,plan=self.solve(max_bundle_size=1)
        self.assertEqual([b.plan_version for b in solver.awards],[0,1,2])
        for bid in solver.bids:
            self.assertEqual(len(bid.candidate_plan.assignments),bid.plan_version+1)
        self.assertEqual(len(plan.assignments),3)

    def test_B5_bundle_ablation_records_mechanism_not_assumed_superiority(self):
        for i in range(3): self.task(f'T{i}',[('S1',30*i)])
        _,one=self.solve(max_bundle_size=1)
        _,two=self.solve(max_bundle_size=2)
        self.assertEqual(one.metadata['rabas']['stats']['max_bundle_built'],1)
        self.assertEqual(two.metadata['rabas']['stats']['max_bundle_built'],2)
        self.assertEqual(one.metadata['rabas']['stats']['awards'],3)
        self.assertEqual(two.metadata['rabas']['stats']['awards'],2)
        self.assertEqual(compute_evaluation_metrics(self.problem,one,0).task_profit,
                         compute_evaluation_metrics(self.problem,two,0).task_profit)

    def test_three_task_bundle_is_supported(self):
        for i in range(3): self.task(f'T{i}',[('S1',30*i)])
        solver,plan=self.solve(max_bundle_size=3)
        self.assertEqual(len(solver.awards[0].additions),3)
        self.assertEqual(len(plan.assignments),3)

    def test_resource_weight_affects_actual_score(self):
        self.task('T1',[('S1',0)])
        self.problem.satellites['S1'].max_data_storage_GB=2
        a,_=self.solve(resource_cost_weight=0.)
        b,_=self.solve(resource_cost_weight=1.)
        self.assertGreater(b.bids[0].resource_cost,0)
        self.assertLess(b.bids[0].score,a.bids[0].score)


class ContractTests(RABASFixture):
    def test_invalid_parameters_rejected(self):
        for raw in ({'max_bundle_size':0},{'max_bundle_size':4},{'max_bundle_size':True},
                    {'max_bundle_size':'2'},{'max_rounds':-1},{'max_windows_per_task':1.2},
                    {'max_positions_per_window':9},{'reauction_mode':'partial'},
                    {'opportunity_cost_weight':float('nan')},{'resource_cost_weight':float('inf')},
                    {'transition_cost_weight':True},{'unknown':1}):
            with self.subTest(raw=raw),self.assertRaises(ValidationError): RABASParams(**raw)

    def test_input_unchanged_and_deterministic(self):
        self.task('T1',[('S1',0),('S2',0)]);self.task('T2',[('S1',30)])
        before=deepcopy(self.problem)
        _,one=self.solve();_,two=self.solve()
        self.assertEqual(self.problem,before)
        self.assertEqual(one,two)

    def test_missing_planning_lineage_is_not_bypassed(self):
        self.task('T1',[('S1',0)]).windows[0].planning_evidence=None
        _,plan=self.solve()
        self.assertEqual(plan.assignments,[])

    def test_earth_blocked_window_rejected_by_shared_preview_geometry(self):
        from schedulers.observation_geometry import validate_observation_interval
        task=self.task('hidden',[('S1',0)])
        self.problem.execution_mode='planning_preview'
        self.problem.satellites['S1'].orbital_params={
            'semi_major_axis_km':7000.,'eccentricity':0.,'inclination_deg':0.,
            'argument_of_perigee_deg':0.,'right_ascension_of_ascending_node_deg':0.,
            'mean_anomaly_deg':0.,'epoch':'2026-01-01T00:00:00Z'}
        task.target_latitude_deg=0.
        for longitude in (0.,180.):
            task.target_longitude_deg=longitude
            result=validate_observation_interval(self.problem,'S1',task.id,self.start,
                                                  self.start+timedelta(seconds=10))
            if not result.feasible:break
        self.assertTrue(result.checked)
        self.assertFalse(result.feasible)
        _,plan=self.solve()
        self.assertEqual(plan.assignments,[])

    def test_cancelled_is_exception_not_successful_incumbent(self):
        self.task('T1',[('S1',0)])
        ctx=SolveContext(42,1,ObjectiveWeights(),RABASParams(),is_cancelled=lambda:True)
        with self.assertRaises(RABASCancelled):
            ObservedAuction().solve(self.problem,self.cm,ctx)

    def test_budget_returns_last_whole_award(self):
        for i in range(3): self.task(f'T{i}',[('S1',30*i)])
        clock=[0.]
        class StopAfterAward(ObservedAuction):
            def _observe_award(self,bid):
                super()._observe_award(bid);clock[0]=100
        solver=StopAfterAward(clock=lambda:clock[0])
        plan=solver.solve(self.problem,self.cm,SolveContext(42,1,ObjectiveWeights(),RABASParams()))
        self.assertEqual(len(plan.assignments),2)
        self.assertEqual(plan.metadata['rabas']['stop_reason'],'budget')
        self.feasible(plan)

    def test_cancel_after_award_still_does_not_return_success(self):
        self.task('T1',[('S1',0)]);self.task('T2',[('S1',30)])
        flag=[False]
        class CancelAfterAward(ObservedAuction):
            def _observe_award(self,bid):flag[0]=True
        ctx=SolveContext(42,1,ObjectiveWeights(),RABASParams(max_bundle_size=1),is_cancelled=lambda:flag[0])
        with self.assertRaises(RABASCancelled):CancelAfterAward().solve(self.problem,self.cm,ctx)

    def test_invalid_budget_rejected(self):
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                ObservedAuction().solve(self.problem,self.cm,SolveContext(1,value,ObjectiveWeights(),RABASParams()))

    def test_round_limit_and_check_limit_are_bounded(self):
        for i in range(10):self.task(f'T{i}',[('S1',30*i)])
        _,plan=self.solve(max_bundle_size=1,max_rounds=1)
        self.assertEqual(len(plan.assignments),1)
        self.assertEqual(plan.metadata['rabas']['stop_reason'],'round_limit')
        _,plan=self.solve(max_checks_per_round=16, opportunity_cost_weight=0., bid_candidates_per_satellite=32)
        self.assertEqual(plan.metadata['rabas']['stop_reason'],'round_check_limit')
        self.assertGreater(len(plan.assignments),0)
        self.assertLessEqual(plan.metadata['rabas']['stats']['public_constraint_checks'],16+len(plan.assignments))
        self.feasible(plan)

    def test_empty_problem(self):
        _,plan=self.solve()
        self.assertEqual(plan.assignments,[])


if __name__=='__main__':unittest.main()
