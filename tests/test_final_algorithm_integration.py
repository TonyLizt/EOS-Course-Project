"""最终算法兼容集成回归；合成算法夹具不作为物理认证证据。"""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

import test_algorithm_conflict_beam as beam_fixture
import test_algorithm_deadline_insertion as dartis_fixture
import test_algorithm_auction_bundle as rabas_fixture
from algorithms.conflict_beam import BoundedCandidateAdapter, CAABSParams
from algorithms.deadline_insertion import DARTISParams, _BudgetExpired, _assignment_key, _grid_steps, _select_windows
from algorithms.dartis_repair import bounded_repair
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from eos_system.algorithm_registry import get_algorithm
from schedulers.constraint_model import Schedule

class FinalAlgorithmContractTests(unittest.TestCase):
    def test_unported_score_protocol_options_are_not_exposed(self):
        for algorithm, field in [('caabs','score_future_guide'), ('rabas','score_bid_opportunity'), ('dartis','score_retime')]:
            with self.subTest(algorithm=algorithm):
                spec = get_algorithm(algorithm)
                with self.assertRaises(ValueError):
                    spec.parse_params({field: True})
                self.assertNotIn(field, spec.params_model.model_fields)


class FinalBeamTests(beam_fixture.Fixture):
    def test_source_grid_extension_is_bounded_and_preserves_original_angles(self):
        self.problem.satellites['S1'].maneuverability_type = 'agile'
        task = self.task('T', [('S1', 0)], width=60)
        before = deepcopy(task.windows[0].agile_data)
        params = CAABSParams(max_candidates_per_task=9)
        adapter = BoundedCandidateAdapter(self.cm, params)
        candidates = adapter.build(task)
        self.assertEqual(len(candidates), 9)
        self.assertEqual(len({a.sat_start_time for a in candidates}), 9)
        self.assertEqual(task.windows[0].agile_data, before)
        for candidate in candidates:
            self.assertTrue(self.cm.is_feasible_assignment(candidate, Schedule()))
            self.assertEqual(candidate.sat_window_id, task.windows[0].window_id)

    def test_exact_cap_at_last_anchor_does_not_append_extra_grid_point(self):
        self.problem.satellites['S1'].maneuverability_type = 'agile'
        task = self.task('T', [('S1', 0)], width=60)
        candidates = BoundedCandidateAdapter(self.cm, CAABSParams(max_candidates_per_task=3)).build(task)
        self.assertEqual(len(candidates), 3)

    def test_dynamic_candidates_remain_source_bound_and_require_public_check(self):
        self.problem.satellites['S1'].maneuverability_type = 'agile'
        task = self.task('T', [('S1', 0)], width=100)
        other = self.task('U', [('S1', 20)], width=10)
        occupied = self.candidate(other)
        params = CAABSParams(dynamic_repair_limit=4, grid_coverage=False)
        adapter = BoundedCandidateAdapter(self.cm, params)
        candidates = adapter.repair(task, Schedule([occupied]), adapter.build(task))
        self.assertLessEqual(len(candidates), 4)
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(candidate.sat_window_id, task.windows[0].window_id)
            self.assertGreaterEqual(candidate.sat_start_time, task.windows[0].start_time)
            self.assertLessEqual(candidate.sat_end_time, task.windows[0].end_time)


class FinalDARTISTests(dartis_fixture.DARTISFixture):
    def test_single_ejection_can_replace_blocking_task_with_two_and_keeps_input(self):
        long = self.task('long', [('S1', 0, 30)], duration=30)
        self.task('first', [('S1', 0, 10)])
        self.task('second', [('S1', 20, 10)])
        initial = Schedule([self.cm.build_feasible_assignment_for_task(long, Schedule())])
        before = deepcopy(initial)
        params = DARTISParams(local_repair_rounds=1)
        context = SolveContext(42, 5, ObjectiveWeights(0,1,0,0), params)
        result, stats = bounded_repair(self.problem, self.cm, context, initial, params,
            lambda: None, _BudgetExpired, _select_windows, _grid_steps, _assignment_key)
        self.assertEqual(set(result.assigned_task_ids), {'first','second'})
        self.assertGreater(stats['improvements'], 0)
        self.assertEqual(initial, before)
        replay = Schedule()
        for candidate in result.assignments:
            self.assertTrue(self.cm.is_feasible_assignment(candidate, replay))
            replay.assignments.append(candidate)


class FinalRABASTests(rabas_fixture.RABASFixture):
    def test_cross_star_repair_frees_capacity_without_changing_resource_rules(self):
        for satellite in self.problem.satellites.values():
            satellite.max_data_storage_GB = 1.
        self.task('T1', [('S1',0),('S2',0)], priority=10)
        self.task('T2', [('S1',30)], priority=1)
        options = dict(max_bundle_size=1, opportunity_cost_weight=0.,
                       transition_cost_weight=0., resource_cost_weight=0.)
        _, baseline = self.solve(**options)
        _, repaired = self.solve(cross_star_repair=True, **options)
        self.assertEqual(len(baseline.assignments), 1)
        self.assertEqual(len(repaired.assignments), 2)
        self.assertGreater(repaired.metadata['rabas']['cross_star_repair']['repairs'], 0)
        self.feasible(repaired)
        # IPC 只接受 JSON；排序内部的 datetime 不能泄露进 Worker 诊断。
        json.dumps(repaired.metadata, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
