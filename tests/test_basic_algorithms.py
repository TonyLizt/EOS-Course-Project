"""Mechanism fixtures are synthetic unit evidence, never physical certificates."""
from dataclasses import replace
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from algorithms.basic import BASIC_ALGORITHMS, BasicCancelled, BasicParams, BasicScheduler
from algorithms.factory import create_algorithm
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from eos_system.algorithm_registry import get_algorithm, make_context
from eos_system.contracts import ExperimentAlgorithm, ExperimentRequest, RunRequest
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.scenario_loader import (CommWindow, SchedulingGroundStation, SchedulingProblem,
    SchedulingSatellite, SchedulingTask, SensorSpec, TaskWindow)


class BasicAlgorithmTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1)
        self.problem = SchedulingProblem('basic-unit', self.start, self.start+timedelta(seconds=600),
            {'S': SchedulingSatellite('S', sensors={'cam': SensorSpec('cam')}, stabilization_time_s=0)}, {}, {}, [])
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=0)

    def task(self, tid, duration=10, priority=1, windows=((10, 100),), satellite='S'):
        task = SchedulingTask(tid, priority, duration)
        for begin, end in windows:
            task.windows.append(TaskWindow(1+sum(len(t.windows) for t in self.problem.tasks.values())+len(task.windows),
                satellite, tid, 'cam', 1, self.start+timedelta(seconds=begin), self.start+timedelta(seconds=end),
                agile_data={k: [0.] * 601 for k in ('roll_angles','pitch_angles','yaw_angles')},
                non_agile_data={'roll_angle':0., 'pitch_angle':0., 'yaw_angle':0.},
                planning_evidence={'trusted':True, 'version':'visibility_exit_refined_v3', 'step_s':1.,
                                   'evidence_sha256':'BASIC_SYNTHETIC_UNIT_ONLY'}))
        self.problem.tasks[tid] = task
        return task

    def solve(self, policy, **params):
        spec = get_algorithm(policy)
        context = make_context(42, 5, {}, spec, params)
        plan = spec.build(context).solve(self.problem, self.cm, context)
        checked = Schedule()
        for a in plan.assignments:
            self.assertTrue(self.cm.is_feasible_assignment(a, checked))
            checked.assignments.append(a)
        self.assertEqual(len(set(plan.assigned_task_ids)), len(plan.assignments))
        return plan

    def test_policies_choose_their_own_ready_task_not_the_highest_common_profit(self):
        self.task('first', duration=20, priority=2, windows=((10,90),))
        self.task('short', duration=5, priority=3, windows=((10,80),))
        self.task('valuable', duration=10, priority=100, windows=((10,100),))
        self.task('urgent', duration=20, priority=1, windows=((10,40),))
        expected = {'fcfs':'first', 'sjf':'short', 'priority':'valuable', 'edf':'urgent', 'llf':'urgent', 'hrrn':'first'}
        for policy, first in expected.items():
            with self.subTest(policy=policy):
                plan = self.solve(policy)
                self.assertEqual(plan.assignments[0].task_id, first)
                self.assertEqual(plan.metadata['basic_scheduler']['policy'], policy)

    def test_hrrn_recomputes_waiting_ratio_and_sjf_never_runs_future_tasks_early(self):
        self.task('busy', duration=40, windows=((0,40),))
        self.task('long', duration=20, windows=((10,130),))
        self.task('short', duration=5, windows=((20,130),))
        for policy in ('hrrn','sjf'):
            plan = self.solve(policy)
            self.assertEqual([a.task_id for a in plan.assignments[:2]], ['busy','short'])
            # The shared agile model requires 11.66 s of switching, on a 1 s grid.
            self.assertEqual(plan.assignments[1].sat_start_time, self.start+timedelta(seconds=52))

    def test_fcfs_uses_release_and_input_order_for_equal_arrivals(self):
        self.task('Z', windows=((20,100),))
        self.task('B', windows=((10,100),))
        self.task('A', windows=((10,100),))
        self.assertEqual([a.task_id for a in self.solve('fcfs').assignments], ['B','A','Z'])

    def test_llf_subtracts_service_duration_from_deadline(self):
        self.task('short', duration=5, windows=((10,40),))
        self.task('long', duration=30, windows=((10,50),))
        self.assertEqual(self.solve('edf').assignments[0].task_id, 'short')
        self.assertEqual(self.solve('llf').assignments[0].task_id, 'long')

    def test_no_windows_empty_scene_and_infeasible_jobs(self):
        for policy in BASIC_ALGORITHMS:
            self.assertEqual(self.solve(policy).assignments, [])
        self.task('none', windows=())
        self.task('too_long', duration=200)
        self.task('valid')
        for policy in BASIC_ALGORITHMS:
            self.assertEqual(self.solve(policy).assigned_task_ids, ['valid'])

    def test_fixed_payload_parallel_satellites_and_source_identity(self):
        self.problem.satellites['S'].maneuverability_type = 'non_agile'
        self.problem.satellites['T'] = replace(self.problem.satellites['S'], id='T')
        self.task('A', windows=((0,100),))
        self.task('B', windows=((0,100),), satellite='T')
        for policy in BASIC_ALGORITHMS:
            plan = self.solve(policy)
            self.assertEqual(len(plan.assignments), 2)
            self.assertEqual({a.sat_start_time for a in plan.assignments}, {self.start+timedelta(seconds=45)})
            self.assertEqual({a.sat_window_id for a in plan.assignments}, {1,2})

    def test_center_placement_and_capacity_are_still_shared_constraints(self):
        self.task('A', windows=((10,100),))
        self.task('B', windows=((10,100),))
        self.problem.satellites['S'].max_power_W = 1
        self.problem.satellites['S'].sensors['cam'].power_consumption_W = 1
        self.cm = ConstraintModel(self.problem,placement_mode='center')
        for policy in BASIC_ALGORITHMS:
            plan = self.solve(policy)
            self.assertEqual(len(plan.assignments),1)
            self.assertEqual(plan.assignments[0].sat_start_time,self.start+timedelta(seconds=50))

    def test_downlink_is_required_and_shared_station_never_overlaps(self):
        self.problem.ground_stations['G'] = SchedulingGroundStation('G')
        self.problem.satellites['T'] = replace(self.problem.satellites['S'], id='T')
        self.problem.comm_windows = [CommWindow(i, sid, 'G', self.start+timedelta(seconds=30),
            self.start+timedelta(seconds=100)) for i,sid in enumerate(('S','T'),1)]
        self.cm = ConstraintModel(self.problem, downlink_duration_ratio=2, non_agile_transition_s=0)
        self.task('A', windows=((10,20),))
        self.task('B', windows=((10,20),), satellite='T')
        for policy in BASIC_ALGORITHMS:
            plan = self.solve(policy)
            self.assertEqual(len(plan.assignments),2)
            a,b = sorted(plan.assignments,key=lambda a:a.gs_start_time)
            self.assertLessEqual(a.gs_end_time,b.gs_start_time)
            self.assertEqual((a.gs_end_time-a.gs_start_time).total_seconds(),20)
        self.problem.comm_windows.clear()
        self.assertEqual(self.solve('fcfs').assignments,[])

    def test_legacy_latest_placement_keeps_grid_and_fixed_payload_rules(self):
        task = self.task('A', windows=((10,101),))
        task.windows[0].time_step = 3
        task.windows[0].planning_evidence['step_s'] = 3
        self.cm = ConstraintModel(self.problem, placement_mode='latest')
        for policy in BASIC_ALGORITHMS:
            plan = create_algorithm(policy).search(self.problem,self.cm,Schedule())
            self.assertEqual(len(plan.assignments),1)
            self.assertEqual(plan.assignments[0].sat_start_time,self.start+timedelta(seconds=91))
            self.assertTrue(self.cm.is_feasible_assignment(plan.assignments[0],Schedule()))
        self.problem.satellites['S'].maneuverability_type = 'non_agile'
        for policy in BASIC_ALGORITHMS:
            self.assertEqual(self.solve(policy).assignments[0].sat_start_time,
                             self.start+timedelta(seconds=52))

    def test_large_grids_are_bounded_and_cancel_is_not_success(self):
        task = self.task('dense')
        task.windows[0].time_step = .000001
        # Position selection must not allocate the 80-million-point source grid.
        positions = BasicScheduler('fcfs')._positions(self.problem, task, task.windows[0], self.cm,
                                                     Schedule(), self.start, 8)
        self.assertLessEqual(len(positions),8)
        spec = get_algorithm('fcfs')
        context = make_context(42, 5, {}, spec, {})
        with self.assertRaises(BasicCancelled):
            spec.build(context).solve(self.problem,self.cm,replace(context,is_cancelled=lambda:True))
        with patch('algorithms.basic.time.monotonic', side_effect=[0.,10.,10.]):
            plan = spec.build(context).solve(self.problem,self.cm,context)
        self.assertTrue(plan.metadata['basic_scheduler']['budget_exit'])

    def test_aliases_parameters_legacy_factory_and_reproducibility(self):
        self.task('A'); self.task('B')
        for alias in ('fcfo','FCFO','fifo','FCFS'):
            self.assertEqual(RunRequest(scenario_id='s',algorithm_id=alias).algorithm_id,'fcfs')
            self.assertEqual(ExperimentAlgorithm(algorithm_id=alias).algorithm_id,'fcfs')
            plan = create_algorithm(alias).search(self.problem,self.cm,Schedule())
            self.assertEqual(plan.assignments,self.solve('fcfs').assignments)
        for policy in BASIC_ALGORITHMS:
            self.assertEqual(self.solve(policy).assignments,self.solve(policy).assignments)
            for invalid in ({'max_candidates_per_task':0},{'max_positions_per_window':True},{'unknown':1}):
                with self.assertRaises(ValueError): get_algorithm(policy).parse_params(invalid)

    def test_all_common_goals_keep_policy_and_balance_can_break_placement_ties(self):
        self.problem.satellites['T'] = replace(self.problem.satellites['S'], id='T')
        self.task('A', windows=((10,20),))
        b = self.task('B', windows=((40,50),))
        b.windows.append(replace(b.windows[0], window_id=3, satellite_id='T'))
        goals = [dict(w_profit=1.), dict(w_profit=0.,w_completion=1.), dict(w_profit=0.,w_timeliness=1.),
                 dict(w_profit=0.,w_balance=1.), dict(w_profit=.5,w_completion=.3,w_timeliness=.1,w_balance=.1)]
        for policy in BASIC_ALGORITHMS:
            outcomes = []
            for weights in goals:
                spec = get_algorithm(policy); ctx = make_context(42,5,weights,spec,{})
                plan = spec.build(ctx).solve(self.problem,self.cm,ctx)
                self.assertEqual([a.task_id for a in plan.assignments],['A','B'])
                self.assertNotIn('objective_adapter',plan.metadata)
                outcomes.append(plan.assignments[-1].satellite_id)
            self.assertEqual(outcomes[0],'S')
            self.assertEqual(outcomes[3],'T')


class BasicAPITests(unittest.TestCase):
    def test_new_and_existing_algorithms_share_experiment_without_false_adapter_identity(self):
        from eos_system.api import create_app
        from eos_system.config import Settings
        from algorithms.objective_adapters.protocol import verify_adapter
        from eos_system.contracts import RunConfig
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory); scenes=root/'scenarios'; scenes.mkdir()
            (scenes/'scene.json').write_text(json.dumps({'metadata':{'scenario_id':'scene','start_time':'2026-01-01T00:00:00','duration':60},
                'satellites':[],'missions':[],'ground_stations':[],'observation_windows':[],'communication_windows':[]}))
            app = create_app(Settings(runtime_dir=root,scenario_dir=scenes))
            cleanup.callback(app.state.replay.close)
            route = lambda path,method: next(r.endpoint for r in app.routes if r.path==path and method in r.methods)
            catalog = route('/api/algorithms','GET')()['items']
            self.assertTrue(set(BASIC_ALGORITHMS).issubset({a['algorithm_id'] for a in catalog}))
            ids = BASIC_ALGORITHMS + ('profit_first','timeliness_first','balance_first','sa','ga','aco','dartis')
            request = ExperimentRequest(runs=[RunRequest(scenario_id='scene',algorithm_id=aid,
                execution_mode='planning_preview') for aid in ids])
            result = route('/api/experiments','POST')(request,None)
            self.assertEqual(len(result['runs']),len(ids))
            for run in result['runs']:
                config = app.state.database.get_run(run['run_id'])['config']
                self.assertEqual(bool(config['objective_adapter']),config['algorithm_id'] not in BASIC_ALGORITHMS)
                verify_adapter(RunConfig(**config))
            from eos_system.contracts import ControlExperimentRequest
            peer = route('/api/experiments/{experiment_id}/temporary-control','POST')(
                result['experiment_id'],ControlExperimentRequest(schedule_model='adaptive_repair'),None)
            self.assertEqual(len(peer['runs']),len(ids))


if __name__ == '__main__':
    unittest.main()
