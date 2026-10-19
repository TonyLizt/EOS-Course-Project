"""DARTIS synthetic unit fixtures: scheduling checks, not physical certificates."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from pydantic import ValidationError

from algorithms.deadline_insertion import DARTISCancelled, DARTISParams, DARTISScheduler
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from eos_system.algorithm_registry import get_algorithm
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.schedule_output import schedule_to_dict
from schedulers.scenario_loader import (
    CommWindow, SchedulingGroundStation, SchedulingProblem,
    SchedulingSatellite, SchedulingTask, SensorSpec, TaskWindow,
)


class ObservedDARTIS(DARTISScheduler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rounds = []

    def _observe_round(self, version, opportunities):
        self.rounds.append((version, tuple((o.task_id, o.satellite_id,
                                             o.window_id, o.laxity_s)
                                            for o in opportunities)))


class DARTISFixture(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1)
        self.problem = SchedulingProblem(
            "DARTIS_SYNTHETIC_UNIT_ONLY", self.start,
            self.start + timedelta(hours=1),
            {sid: SchedulingSatellite(sid, maneuverability_type="non_agile",
                 sensors={"cam": SensorSpec("cam", 819.2, 1.0)})
             for sid in ("S1", "S2")}, {}, {}, [])
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=0)
        self.next_window = 0

    def task(self, tid, placements, *, duration=10, priority=1):
        windows = []
        for sid, offset, width in placements:
            self.next_window += 1
            windows.append(TaskWindow(
                self.next_window, sid, tid, "cam", 1,
                self.start + timedelta(seconds=offset),
                self.start + timedelta(seconds=offset + width),
                time_step=1.0,
                agile_data={key: [0.0] * (int(width) + 1)
                            for key in ("roll_angles", "pitch_angles", "yaw_angles")},
                non_agile_data={key: 0.0
                                for key in ("roll_angle", "pitch_angle", "yaw_angle")},
                planning_evidence={"trusted": True,
                    "version": "visibility_exit_refined_v3", "step_s": 1.0,
                    "evidence_sha256": "DARTIS_SYNTHETIC_UNIT_ONLY"}))
        result = SchedulingTask(tid, priority, duration, windows)
        self.problem.tasks[tid] = result
        return result

    def solve(self, *, mode="llf", solver=None, budget=5, cancel=lambda: False, **params):
        solver = solver or ObservedDARTIS()
        context = SolveContext(42, budget, ObjectiveWeights(),
                               DARTISParams(priority_mode=mode, **params),
                               is_cancelled=cancel)
        plan = solver.solve(self.problem, self.cm, context)
        self.assert_shared_feasible(plan)
        return solver, plan

    def assert_shared_feasible(self, plan):
        replay = Schedule()
        for assignment in sorted(plan.assignments, key=lambda a: a.sat_start_time):
            self.assertTrue(self.cm.is_feasible_assignment(assignment, replay))
            replay.assignments.append(assignment)
        self.assertEqual(len(plan.assignments), len(set(plan.assigned_task_ids)))


class DARTISCoreTests(DARTISFixture):
    def test_A1_infeasible_narrow_window_preserves_wide_alternative(self):
        self.task("A", [("S1", 0, 10)])
        self.task("B", [("S1", 0, 10), ("S2", 20, 20)])
        solver, plan = self.solve()
        self.assertEqual({(a.task_id, a.satellite_id) for a in plan.assignments},
                         {("A", "S1"), ("B", "S2")})
        self.assertEqual([row[0] for row in solver.rounds], [0, 1])
        self.assertIn(("B", "S2"), {(r[0], r[1]) for r in solver.rounds[1][1]})

    def test_A2_middle_insertion_rejects_successor_slew(self):
        self.cm.non_agile_transition_s = 10
        self.task("early", [("S1", 0, 10)])
        self.task("late", [("S1", 45, 10)])
        middle = self.task("middle", [("S1", 20, 30)])
        solver, plan = self.solve()
        self.assertEqual(set(plan.assigned_task_ids), {"early", "late"})
        probe = self.cm.build_feasible_assignment_for_task(middle, Schedule())
        self.assertIsNotNone(probe)
        self.assertFalse(self.cm.is_feasible_assignment(probe, plan))
        self.assertGreaterEqual(plan.metadata["dartis"]["stats"]["recomputations"], 2)

    def test_A3_alternate_satellite_and_unique_task(self):
        self.task("A", [("S1", 0, 10)])
        self.task("B", [("S1", 0, 10), ("S2", 20, 10)])
        _, plan = self.solve()
        self.assertEqual([(a.task_id, a.satellite_id) for a in plan.assignments],
                         [("A", "S1"), ("B", "S2")])

    def test_A4_edf_llf_differ_and_full_recomputation_is_deterministic(self):
        self.task("A", [("S1", 0, 20)], duration=10)
        self.task("B", [("S1", 0, 18)], duration=2)
        llf_solver, llf = self.solve(mode="llf")
        edf_solver, edf = self.solve(mode="edf")
        self.assertEqual(llf.assignments[0].task_id, "A")
        self.assertEqual(edf.assignments[0].task_id, "B")
        self.assertEqual([v for v, _ in llf_solver.rounds], [0, 1])
        self.assertEqual(llf_solver.rounds[1][1], ())
        self.assertEqual([v for v, _ in edf_solver.rounds], [0, 1])
        self.assertEqual(llf.metadata["dartis"]["stats"]["recomputations"], 1)
        self.assertEqual(schedule_to_dict(llf, self.problem),
                         schedule_to_dict(self.solve(mode="llf")[1], self.problem))

    def test_dynamic_inspected_earliest_start_moves_after_insertion(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        self.task("A", [("S1", 0, 10)])
        self.task("B", [("S1", 0, 50)])
        solver, plan = self.solve()
        by_task = {a.task_id: a for a in plan.assignments}
        self.assertEqual((by_task["B"].sat_start_time-self.start).total_seconds(), 40)
        first = next(row for row in solver.rounds[0][1] if row[0] == "B")
        second = next(row for row in solver.rounds[1][1] if row[0] == "B")
        self.assertGreater(first[3], second[3])

    def test_missing_planning_evidence_is_rejected_by_public_model(self):
        task = self.task("A", [("S1", 0, 10)])
        task.windows[0].planning_evidence = None
        _, plan = self.solve()
        self.assertEqual(plan.assignments, [])

    def test_feasible_middle_insertion_not_tail_only(self):
        self.task("early", [("S1", 0, 10)])
        self.task("late", [("S1", 50, 10)])
        self.task("middle", [("S1", 20, 30)])
        solver, plan = self.solve()
        self.assertEqual([a.task_id for a in plan.assignments],
                         ["early", "middle", "late"])
        self.assertIn(("late", "middle"),
                      [(solver.rounds[1][1][0][0], solver.rounds[2][1][0][0])])

    def test_empty_and_no_window(self):
        self.assertEqual(self.solve()[1].assignments, [])
        self.task("none", [])
        _, plan = self.solve()
        self.assertEqual(plan.assignments, [])
        self.assertEqual(plan.metadata["dartis"]["stop_reason"],
                         "no_feasible_opportunity")

    def test_energy_and_storage_limits_use_public_model(self):
        self.problem.satellites["S1"].max_data_storage_GB = 1.5
        self.problem.satellites["S1"].max_power_W = 1.5
        self.task("A", [("S1", 0, 10)])
        self.task("B", [("S1", 30, 10)])
        _, plan = self.solve()
        self.assertEqual(len(plan.assignments), 1)

    def test_ground_station_downlink_source_and_conflict(self):
        self.problem.ground_stations["G"] = SchedulingGroundStation("G")
        self.problem.comm_windows = [
            CommWindow(1, "S1", "G", self.start+timedelta(seconds=30),
                       self.start+timedelta(seconds=40)),
            CommWindow(2, "S2", "G", self.start+timedelta(seconds=30),
                       self.start+timedelta(seconds=40))]
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=0)
        self.task("A", [("S1", 0, 10)])
        self.task("B", [("S2", 0, 10)])
        _, plan = self.solve()
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(plan.assignments[0].gs_window_id, 1)
        self.assertGreater(plan.assignments[0].gs_start_time,
                           plan.assignments[0].sat_end_time)

    def test_invalid_params_are_rejected(self):
        for params in ({"priority_mode": "other"},
                       {"max_windows_per_task": 0},
                       {"max_windows_per_task": True},
                       {"max_positions_per_window": 33},
                       {"recompute_mode": "affected"},
                       {"tie_break": "random"},
                       {"unknown": 1}):
            with self.subTest(params=params), self.assertRaises(ValidationError):
                DARTISParams(**params)

    def test_budget_returns_owned_feasible_plan(self):
        self.task("A", [("S1", 0, 10)])
        tick = [0]
        def clock():
            tick[0] += 1
            return tick[0] * 0.01
        _, plan = self.solve(solver=ObservedDARTIS(clock=clock), budget=0.005)
        self.assertEqual(plan.assignments, [])
        self.assertEqual(plan.metadata["dartis"]["stop_reason"], "budget")

    def test_budget_after_first_insertion_returns_last_legal_plan(self):
        self.task("A", [("S1", 0, 10)])
        self.task("B", [("S2", 20, 10)])
        now = [0.0]
        class ExpiringAfterFirst(ObservedDARTIS):
            def _observe_round(inner, version, opportunities):
                super()._observe_round(version, opportunities)
                if version == 1:
                    now[0] = 10.0
        _, plan = self.solve(solver=ExpiringAfterFirst(clock=lambda: now[0]), budget=5)
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(plan.metadata["dartis"]["stop_reason"], "budget")

    def test_cancel_after_first_insertion_suppresses_incumbent(self):
        self.task("A", [("S1", 0, 10)])
        self.task("B", [("S2", 20, 10)])
        cancelled = [False]
        class CancelAfterFirst(ObservedDARTIS):
            def _observe_round(inner, version, opportunities):
                super()._observe_round(version, opportunities)
                if version == 1:
                    cancelled[0] = True
        solver = CancelAfterFirst()
        context = SolveContext(42, 5, ObjectiveWeights(), DARTISParams(),
                               is_cancelled=lambda: cancelled[0])
        with self.assertRaises(DARTISCancelled):
            solver.solve(self.problem, self.cm, context)
        self.assertEqual([v for v, _ in solver.rounds], [0, 1])

    def test_cancellation_is_not_successful_return(self):
        self.task("A", [("S1", 0, 10)])
        context = SolveContext(42, 5, ObjectiveWeights(), DARTISParams(),
                               is_cancelled=lambda: True)
        with self.assertRaises(DARTISCancelled):
            DARTISScheduler().solve(self.problem, self.cm, context)

    def test_input_unchanged_and_standard_serialization(self):
        self.task("A", [("S1", 0, 10)])
        self.task("B", [])
        original = deepcopy(self.problem)
        _, plan = self.solve()
        self.assertEqual(self.problem, original)
        result = schedule_to_dict(plan, self.problem)
        self.assertEqual(result["scenario_id"], self.problem.scenario_id)
        self.assertEqual(result["unassigned_tasks"], ["B"])
        self.assertEqual(result["assignments"][0]["sat_window_id"], 1)

    def test_window_cap_preserves_other_satellite(self):
        self.task("A", [("S1", i*20, 10) for i in range(10)]
                  + [("S2", 200, 10)])
        _, plan = self.solve(max_windows_per_task=2)
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(plan.metadata["dartis"]["stats"]["windows_inspected"], 2)
        self.assertEqual(plan.metadata["dartis"]["stats"]["windows_truncated"], 9)

    def test_position_cap_reports_approximation(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        self.task("A", [("S1", 0, 30)])
        _, plan = self.solve(max_positions_per_window=2)
        self.assertLessEqual(plan.metadata["dartis"]["stats"]["positions_inspected"], 2)
        self.assertGreater(plan.metadata["dartis"]["stats"]["positions_truncated"], 0)
        self.assertTrue(plan.metadata["dartis"]["approximate_laxity"])

    def test_large_grid_is_not_materialized(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        self.task("A", [("S1", 0, 2000)])
        _, plan = self.solve()
        self.assertEqual(plan.assignments, [])
        self.assertEqual(plan.metadata["dartis"]["stats"]["grid_limited_windows"], 1)

    def test_existing_registry_algorithms_unmodified(self):
        self.assertEqual(get_algorithm("caabs").algorithm_id, "caabs")
        self.assertEqual(get_algorithm("rabas").algorithm_id, "rabas")


if __name__ == "__main__":
    unittest.main()
