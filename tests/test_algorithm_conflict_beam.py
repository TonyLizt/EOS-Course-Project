"""Synthetic algorithm checks; evidence below is UNIT_TEST_ONLY, not certification."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from pydantic import ValidationError

from algorithms.conflict_beam import (
    BeamState, BoundedCandidateAdapter, CAABSParams, ConflictBeamScheduler,
    SafeConflictIndex, branch_schedule,
    canonical_assignment_key, canonical_state_key,
)
from algorithms.objectives import ObjectiveWeights
from eos_system.algorithm_registry import SolveContext
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import (
    CommWindow, SchedulingGroundStation, SchedulingProblem, SchedulingSatellite,
    SchedulingTask, SensorSpec, TaskWindow,
)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1)
        self.problem = SchedulingProblem(
            "caabs-unit-test", self.start, self.start + timedelta(hours=1),
            {sid: SchedulingSatellite(sid, maneuverability_type="non_agile",
                sensors={"cam": SensorSpec("cam", 819.2, 1.0)}) for sid in ("S1", "S2")},
            {}, {}, [],
        )
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=0)
        self.next_window = 0

    def task(self, tid, placements, *, duration=10, width=10, evidence=True, priority=1):
        windows = []
        for sid, second in placements:
            self.next_window += 1
            windows.append(TaskWindow(
                self.next_window, sid, tid, "cam", 1,
                self.start + timedelta(seconds=second),
                self.start + timedelta(seconds=second + width),
                time_step=1.0,
                agile_data={"roll_angles": [0.0] * int(width + 1),
                            "pitch_angles": [0.0] * int(width + 1),
                            "yaw_angles": [0.0] * int(width + 1)},
                non_agile_data={"roll_angle": 0.0, "pitch_angle": 0.0, "yaw_angle": 0.0},
                # Same in-memory fixture convention as test_adaptive_repair.
                # Never exported or installed as production provenance.
                planning_evidence={"trusted": True, "version": "visibility_exit_refined_v3",
                    "step_s": 1.0, "evidence_sha256": "CAABS_UNIT_TEST_ONLY"} if evidence else None,
            ))
        task = SchedulingTask(tid, priority, duration, windows)
        self.problem.tasks[tid] = task
        return task

    def candidate(self, task):
        return self.cm.build_feasible_assignment_for_task(task, Schedule())

    def assert_shared_feasible(self, schedule):
        replay = Schedule()
        for assignment in schedule.assignments:
            self.assertTrue(self.cm.is_feasible_assignment(assignment, replay))
            replay.assignments.append(assignment)
        self.assertEqual(len(schedule.assignments), len(set(schedule.assigned_task_ids)))


class FoundationTests(Fixture):
    def test_parameter_defaults_and_validation(self):
        params = CAABSParams()
        self.assertEqual((params.beam_width, params.branch_limit, params.max_candidates_per_task), (8, 8, 16))
        for raw in ({"beam_width": 0}, {"beam_width": 257}, {"branch_limit": 65},
                    {"max_candidates_per_task": 0}, {"max_candidates_per_task": 129},
                    {"max_windows_per_task": 0}, {"beam_width": True},
                    {"beam_width": 1.5}, {"conflict_prefilter": "yes"}, {"unknown": 1}):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                CAABSParams(**raw)

    def test_candidate_coverage_balances_satellites_and_horizon(self):
        task = self.task("T1", [("S1", i * 20) for i in range(20)] + [("S2", 0), ("S2", 1000)])
        stats = {}
        adapter = BoundedCandidateAdapter(self.cm, CAABSParams(max_candidates_per_task=4), stats=stats)
        candidates = adapter.build(task)
        self.assertEqual(len(candidates), 4)
        self.assertEqual({a.satellite_id for a in candidates}, {"S1", "S2"})
        offsets = {(a.satellite_id, (a.sat_start_time-self.start).total_seconds()) for a in candidates}
        self.assertIn(("S1", 380), offsets)
        self.assertIn(("S2", 1000), offsets)
        self.assertLessEqual(stats["candidate_builder_calls"], 8)
        self.assertEqual(candidates, adapter.build(task))

    def test_agile_only_earliest_and_center(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        task = self.task("T1", [("S1", 0)], width=30)
        candidates = BoundedCandidateAdapter(self.cm, CAABSParams()).build(task)
        self.assertEqual([(a.sat_start_time-self.start).total_seconds() for a in candidates], [0, 10])
        self.assertEqual([len(a.sat_angles["roll_angles"]) for a in candidates], [10, 10])

    def test_non_agile_center_and_missing_evidence(self):
        task = self.task("T1", [("S1", 0)], width=30)
        candidates = BoundedCandidateAdapter(self.cm, CAABSParams()).build(task)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].sat_start_time, self.start + timedelta(seconds=10))
        task.windows[0].planning_evidence = None
        self.assertEqual(BoundedCandidateAdapter(self.cm, CAABSParams()).build(task), [])

    def test_no_windows_and_zero_duration(self):
        task = self.task("T1", [])
        adapter = BoundedCandidateAdapter(self.cm, CAABSParams())
        self.assertEqual(adapter.build(task), [])
        self.assertEqual(adapter.build(replace(task, required_duration=0)), [])

    def test_constructor_call_bound_even_when_all_modes_fail(self):
        task = self.task("T1", [("S1", i * 30) for i in range(100)])
        self.problem.ground_stations["G1"] = SchedulingGroundStation("G1")
        cm = ConstraintModel(self.problem)
        stats = {}
        candidates = BoundedCandidateAdapter(cm, CAABSParams(max_candidates_per_task=3), stats=stats).build(task)
        self.assertEqual(candidates, [])
        self.assertEqual(stats["candidate_builder_calls"], 6)

    def test_schedule_branch_deep_isolation(self):
        a = self.candidate(self.task("T1", [("S1", 0)]))
        b = self.candidate(self.task("T2", [("S2", 30)]))
        parent = Schedule([a], {"nested": {"values": [1]}})
        first = branch_schedule(parent, b)
        second = branch_schedule(parent, b)
        first.assignments[0].sat_angles["roll_angle"] = 99
        first.assignments[1].sat_angles["roll_angle"] = 88
        first.metadata["nested"]["values"].append(2)
        first.assignments.pop()
        self.assertEqual(len(parent.assignments), 1)
        self.assertEqual(len(second.assignments), 2)
        self.assertEqual(parent.metadata["nested"]["values"], [1])
        self.assertEqual(second.assignments[0].sat_angles["roll_angle"], 0)
        self.assertEqual(b.sat_angles["roll_angle"], 0)

    def test_key_order_and_metadata_independence(self):
        a = self.candidate(self.task("T1", [("S1", 0)]))
        b = self.candidate(self.task("T2", [("S2", 30)]))
        self.assertEqual(canonical_state_key(Schedule([a, b])), canonical_state_key(Schedule([b, a], {"debug": 1})))
        one = BeamState(Schedule([a]), 1, 1, 0.5, canonical_state_key(Schedule([a])))
        self.assertNotEqual(one.search_key, replace(one, task_index=2).search_key)

    def test_key_distinguishes_all_assignment_fields(self):
        a = self.candidate(self.task("T1", [("S1", 0)]))
        alternatives = {
            "task_id": "T2", "satellite_id": "S2", "sat_window_id": 99,
            "sat_start_time": a.sat_start_time + timedelta(microseconds=1),
            "sat_end_time": a.sat_end_time + timedelta(microseconds=1),
            "sensor_id": "other", "orbit_number": 2, "data_volume_GB": 2.0,
            "power_cost_W": 2.0, "sat_angles": {"roll_angle": 3.0},
            "ground_station_id": "G1", "gs_window_id": 7,
            "gs_start_time": self.start + timedelta(seconds=20),
            "gs_end_time": self.start + timedelta(seconds=30),
        }
        for name, value in alternatives.items():
            with self.subTest(field=name):
                self.assertNotEqual(canonical_assignment_key(a), canonical_assignment_key(replace(a, **{name: value})))
        changed = deepcopy(a)
        changed.sat_angles = dict(reversed(list(a.sat_angles.items())))
        self.assertEqual(canonical_assignment_key(a), canonical_assignment_key(changed))

    def test_v2_boundary_uses_shared_planning_semantics(self):
        task = self.task("T1", [("S1", 0)])
        task.windows[0].planning_evidence["version"] = "visibility_grid_v2"
        self.assertEqual(BoundedCandidateAdapter(self.cm, CAABSParams()).build(task), [])


class ManualClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RecordingScheduler(ConflictBeamScheduler):
    def __init__(self, *, on_level=None, **kwargs):
        super().__init__(**kwargs)
        self.levels = []
        self.on_level = on_level

    def _observe_beam(self, states):
        # Own snapshots, never mutate the solver's branch objects.
        self.levels.append(tuple(deepcopy(state) for state in states))
        if self.on_level:
            self.on_level(len(self.levels))


class SearchTests(Fixture):
    def context(self, **params):
        return SolveContext(42, 60, ObjectiveWeights(), CAABSParams(**params))

    def solve(self, *, scheduler=None, context=None, constraints=None, **params):
        scheduler = scheduler or ConflictBeamScheduler()
        return scheduler.solve(self.problem, constraints or self.cm, context or self.context(**params))

    def multipath(self):
        self.task("T1", [("S1", 0), ("S2", 0)])
        self.task("T2", [("S1", 0)])

    def test_C1_real_alternative_path_survives_and_improves(self):
        self.multipath()
        narrow = self.solve(beam_width=1)
        recorder = RecordingScheduler()
        wide = self.solve(scheduler=recorder, beam_width=4)
        first = recorder.levels[0]
        placements = {tuple((a.task_id, a.satellite_id) for a in s.schedule.assignments) for s in first}
        self.assertIn((("T1", "S1"),), placements)
        self.assertIn((("T1", "S2"),), placements)
        self.assertEqual(len(narrow.assignments), 1)
        self.assertEqual(len(wide.assignments), 2)
        self.assertEqual({(a.task_id, a.satellite_id) for a in wide.assignments}, {("T1", "S2"), ("T2", "S1")})
        self.assert_shared_feasible(wide)

    def test_C2_true_cumulative_storage_and_power(self):
        for resource in ("storage", "power"):
            with self.subTest(resource=resource):
                self.setUp()
                sat = self.problem.satellites["S1"]
                if resource == "storage":
                    sat.max_data_storage_GB = 2.5
                else:
                    sat.max_power_W = 2.5
                tasks = [self.task(f"T{i}", [("S1", i * 30)]) for i in range(1, 4)]
                candidates = [self.candidate(task) for task in tasks]
                for candidate in candidates:
                    self.assertTrue(self.cm.is_feasible_assignment(candidate, Schedule()))
                self.assertTrue(self.cm.is_feasible_assignment(candidates[1], Schedule([candidates[0]])))
                self.assertFalse(self.cm.is_feasible_assignment(candidates[2], Schedule(candidates[:2])))
                self.assertFalse(SafeConflictIndex.from_schedule(Schedule(candidates[:2])).rejects(candidates[2]))
                result = self.solve()
                self.assertEqual(len(result.assignments), 2)
                self.assert_shared_feasible(result)

    def test_C3_task_unique_with_multiple_satellites(self):
        self.task("T1", [("S1", 0), ("S2", 0), ("S1", 60)])
        result = self.solve(beam_width=16)
        self.assertEqual(result.assigned_task_ids, ["T1"])
        self.assertEqual(len(result.assignments), 1)
        self.assert_shared_feasible(result)

    def test_C4_widths_and_stable_ranking(self):
        self.multipath()
        for width in (1, 4, 8, 16):
            with self.subTest(width=width):
                runs = []
                for _ in range(2):
                    recorder = RecordingScheduler()
                    result = self.solve(scheduler=recorder, beam_width=width)
                    self.assertEqual(len(result.assignments), 1 if width == 1 else 2)
                    for level in recorder.levels:
                        self.assertLessEqual(len(level), width)
                        self.assertEqual([s.rank_key for s in level], sorted(s.rank_key for s in level))
                    runs.append([[s.search_key for s in level] for level in recorder.levels])
                    self.assertLessEqual(result.metadata["caabs"]["stats"]["max_beam_size"], width)
                self.assertEqual(runs[0], runs[1])

    def test_C5_budget_returns_incumbent_with_manual_clock(self):
        self.multipath()
        clock = ManualClock()
        recorder = RecordingScheduler(clock=clock, on_level=lambda _: setattr(clock, "now", 60))
        result = self.solve(scheduler=recorder)
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stop_reason"], "budget")
        self.assertEqual(result.metadata["caabs"]["stats"]["levels_completed"], 1)
        self.assert_shared_feasible(result)

    def test_C5_cancel_uses_current_solve_context_and_keeps_incumbent(self):
        self.multipath()
        cancelled = [False]
        context = replace(self.context(), is_cancelled=lambda: cancelled[0])
        recorder = RecordingScheduler(on_level=lambda _: cancelled.__setitem__(0, True))
        result = self.solve(scheduler=recorder, context=context)
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stop_reason"], "cancelled")
        self.assert_shared_feasible(result)
        early = self.solve(context=replace(self.context(), is_cancelled=lambda: True))
        self.assertEqual(early.assignments, [])
        self.assertEqual(early.metadata["caabs"]["stats"]["candidate_builder_calls"], 0)

    def test_C6_prefilter_ablation_reduces_calls_without_changing_plan(self):
        self.task("T1", [("S1", 0)])
        self.task("T2", [("S1", 0)])
        enabled = self.solve(conflict_prefilter=True)
        disabled = self.solve(conflict_prefilter=False)
        self.assert_shared_feasible(enabled)
        self.assert_shared_feasible(disabled)
        self.assertEqual(canonical_state_key(enabled), canonical_state_key(disabled))
        yes = enabled.metadata["caabs"]["stats"]
        no = disabled.metadata["caabs"]["stats"]
        self.assertGreater(yes["prefilter_rejections"], 0)
        self.assertEqual(no["prefilter_rejections"], 0)
        self.assertLess(yes["public_constraint_calls"], no["public_constraint_calls"])

    def test_empty_no_candidates_and_missing_evidence(self):
        for kind in ("empty", "no_windows", "untrusted"):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == "no_windows":
                    self.task("T1", [])
                elif kind == "untrusted":
                    self.task("T1", [("S1", 0)], evidence=False)
                result = self.solve()
                self.assertEqual(result.assignments, [])
                self.assertEqual(result.metadata["caabs"]["feasibility"], "structural_fallback")

    def test_safe_index_only_proven_conflicts(self):
        a = self.candidate(self.task("T1", [("S1", 0)]))
        b = self.candidate(self.task("T2", [("S1", 10)]))
        index = SafeConflictIndex.from_schedule(Schedule([a]))
        self.assertTrue(index.rejects(replace(a, satellite_id="S2")))
        self.assertTrue(index.rejects(replace(b, sat_start_time=self.start + timedelta(seconds=9))))
        self.assertFalse(index.rejects(b))  # half-open touching boundary
        self.assertFalse(index.rejects(replace(b, satellite_id="S2", sat_start_time=self.start)))

    def test_every_insert_checks_untouched_parent(self):
        self.multipath()
        original = self.cm.is_feasible_assignment
        calls = []
        def check(candidate, parent):
            before = canonical_state_key(parent)
            self.assertNotIn(candidate.task_id, parent.assigned_task_ids)
            answer = original(candidate, parent)
            self.assertEqual(before, canonical_state_key(parent))
            calls.append((candidate.task_id, answer))
            return answer
        self.cm.is_feasible_assignment = check
        result = self.solve()
        self.assertEqual(len(result.assignments), 2)
        self.assertEqual(len(calls), result.metadata["caabs"]["stats"]["public_constraint_calls"])

    def test_incumbent_and_beam_siblings_own_mutable_data(self):
        self.multipath()
        class Capturing(ConflictBeamScheduler):
            def _observe_beam(inner, states):
                inner.last = states
        scheduler = Capturing()
        result = self.solve(scheduler=scheduler)
        result_before = deepcopy(result)
        for state in scheduler.last:
            state.schedule.metadata["nested"] = [99]
            if state.schedule.assignments:
                state.schedule.assignments[0].sat_angles["roll_angle"] = 99
        self.assertEqual(result, result_before)
        self.assertEqual(self.problem.tasks["T1"].windows[0].non_agile_data["roll_angle"], 0)

    def test_seeded_determinism_and_serialization(self):
        from schedulers.schedule_output import schedule_to_dict
        self.multipath()
        first = self.solve()
        second = self.solve()
        self.assertEqual(first, second)
        data = schedule_to_dict(first, self.problem)
        self.assertEqual(data["scenario_id"], self.problem.scenario_id)
        self.assertEqual(len(data["assignments"]), 2)
        self.assertEqual(data["unassigned_tasks"], [])
        self.assertIsInstance(data["assignments"][0]["sat_start_time"], str)
        self.assertNotIn("metadata", data)


if __name__ == "__main__":
    unittest.main()
