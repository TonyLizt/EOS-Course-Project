"""Synthetic algorithm checks; evidence below is UNIT_TEST_ONLY, not certification."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

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
    def test_engineering_window_admission_matches_public_exposure_policy(self):
        # 只验证候选准入，不伪造物理传播成功；最终核验仍由公共模型负责。
        from schedulers.preview_exposure import candidate_exposure
        from utils.continuous_exposure import ExposureStatus
        task = self.task("legacy", [("S1", 0)], width=20, evidence=False)
        window = task.windows[0]
        adapter = BoundedCandidateAdapter(self.cm, CAABSParams())
        for mode in ('physical_validation', 'planning_preview'):
            with self.subTest(mode=mode):
                self.problem.execution_mode = mode
                self.assertEqual(adapter._windows(task), [window])
                decision = candidate_exposure(self.problem, window, window.start_time,
                    window.start_time + timedelta(seconds=task.required_duration), task.required_duration)
                self.assertIs(decision.status, ExposureStatus.PLANNING_FEASIBLE)
        self.problem.execution_mode = 'formal'
        self.assertEqual(adapter._windows(task), [])
        self.problem.execution_mode = 'physical_validation'
        task.required_duration = 20
        self.assertEqual(adapter._windows(task), [])

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

    def test_agile_earliest_center_latest(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        task = self.task("T1", [("S1", 0)], width=30)
        candidates = BoundedCandidateAdapter(self.cm, CAABSParams()).build(task)
        self.assertEqual([(a.sat_start_time-self.start).total_seconds() for a in candidates], [0, 10, 20])
        self.assertEqual([len(a.sat_angles["roll_angles"]) for a in candidates], [10, 10, 10])

    def test_late_candidate_recovers_third_public_feasible_task(self):
        # Synthetic-only fixture: each task has one 120-second source window.
        # Earliest/center alone offer 0s and 55s; the native public latest
        # constructor offers 110s. Source IDs and attitude slices are retained.
        self.problem.satellites["S1"].maneuverability_type = "agile"
        tasks = [self.task(tid, [("S1", 0)], duration=10, width=120)
                 for tid in ("T1", "T2", "T3")]
        params = CAABSParams(beam_width=32, branch_limit=16,
                             max_candidates_per_task=16, max_windows_per_task=32)
        adapter = BoundedCandidateAdapter(self.cm, params)
        for task in tasks:
            candidates = adapter.build(task)
            self.assertEqual([(a.sat_start_time - self.start).total_seconds()
                              for a in candidates], [0, 55, 110])
            for candidate in candidates:
                self.assertTrue(self.cm.is_feasible_assignment(candidate, Schedule()))
                self.assertEqual(candidate.sat_window_id, task.windows[0].window_id)
                self.assertEqual(len(candidate.sat_angles["roll_angles"]), 10)
        result = ConflictBeamScheduler().solve(
            self.problem, self.cm, SolveContext(42, 60, ObjectiveWeights(), params))
        self.assertEqual(len(result.assignments), 3)
        self.assertEqual(result.metadata["caabs"]["stop_reason"], "completed")
        self.assert_shared_feasible(result)

    def test_late_candidates_remain_bounded(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        task = self.task("T1", [("S1", 0)], duration=10, width=120)
        params = CAABSParams(max_candidates_per_task=2)
        adapter = BoundedCandidateAdapter(self.cm, params)
        starts = [(a.sat_start_time - self.start).total_seconds()
                  for a in adapter.build(task)]
        self.assertEqual(starts, [0, 55])

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
        self.assertEqual(stats["candidate_builder_calls"], 9)

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

    def test_key_preserves_sequence_types_order_and_stability(self):
        candidate = self.candidate(self.task("T1", [("S1", 0)]))
        def key(payload):
            return canonical_assignment_key(replace(candidate, sat_angles=payload))
        for payload in ([], (), [1.0, 2.0], (1.0, 2.0)):
            with self.subTest(payload=payload):
                self.assertEqual(key(payload), key(deepcopy(payload)))
        self.assertNotEqual(key([]), key(()))
        self.assertNotEqual(key([1.0, 2.0]), key((1.0, 2.0)))
        self.assertNotEqual(key([1.0, 2.0]), key([2.0, 1.0]))
        self.assertNotEqual(key((1.0, 2.0)), key((2.0, 1.0)))

    def test_key_preserves_nested_container_types(self):
        candidate = self.candidate(self.task("T1", [("S1", 0)]))
        for left, right in (
            ({"attitude": [1.0, 2.0]}, {"attitude": (1.0, 2.0)}),
            ([{"samples": [1.0]}], [{"samples": (1.0,)}]),
            (([1.0],), ((1.0,),)),
        ):
            with self.subTest(left=left, right=right):
                a = replace(candidate, sat_angles=left)
                b = replace(candidate, sat_angles=right)
                self.assertNotEqual(canonical_assignment_key(a), canonical_assignment_key(b))
                self.assertEqual(canonical_assignment_key(a), canonical_assignment_key(deepcopy(a)))
        first = replace(candidate, sat_angles={"a": [1.0], "b": (2.0,)})
        reordered = replace(candidate, sat_angles={"b": (2.0,), "a": [1.0]})
        self.assertEqual(canonical_assignment_key(first), canonical_assignment_key(reordered))

    def test_key_preserves_scalar_and_float_encoding(self):
        candidate = self.candidate(self.task("T1", [("S1", 0)]))
        values = (None, False, True, 0, 1, "0", "1", 0.0, -0.0, 1.0, 1.0000000000000002)
        keys = [canonical_assignment_key(replace(candidate, sat_angles=value)) for value in values]
        self.assertEqual(len(keys), len(set(keys)))
        encoded = dict(canonical_assignment_key(replace(candidate, sat_angles=0.1)))
        self.assertEqual(encoded["sat_angles"], ("float", float(0.1).hex()))
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_assignment_key(replace(candidate, sat_angles={"samples": (value,)}))


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

    def test_C4_saturated_frontiers_are_unique_sorted_and_deterministic(self):
        for i in range(3):
            self.task(f"T{i}", [("S1", i * 100), ("S2", i * 100 + 20),
                               ("S1", i * 100 + 40)])
        for width in (1, 4, 8, 16):
            with self.subTest(width=width):
                runs = []
                for _ in range(2):
                    recorder = RecordingScheduler(clock=lambda: 0.0)
                    result = self.solve(scheduler=recorder, beam_width=width)
                    expected = [min(width, 4 ** depth) for depth in (1, 2, 3)]
                    self.assertEqual([len(level) for level in recorder.levels], expected)
                    for depth, level in enumerate(recorder.levels, 1):
                        self.assertEqual({state.task_index for state in level}, {depth})
                        keys = [state.search_key for state in level]
                        self.assertEqual(len(keys), len(set(keys)))
                        ranks = [state.rank_key for state in level]
                        self.assertEqual(ranks, sorted(ranks))
                    stats = result.metadata["caabs"]["stats"]
                    self.assertEqual(stats["max_beam_size"], width)
                    self.assertGreater(stats["pruned_states"], 0)
                    self.assertEqual(len(result.assignments), 3)
                    self.assert_shared_feasible(result)
                    runs.append([[state.search_key for state in level] for level in recorder.levels])
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


class BoundaryTests(Fixture):
    context = SearchTests.context
    solve = SearchTests.solve
    multipath = SearchTests.multipath

    def downlinks(self, *, start=10, end=30):
        self.problem.ground_stations["G1"] = SchedulingGroundStation("G1")
        self.problem.comm_windows = [CommWindow(
            i, sid, "G1", self.start + timedelta(seconds=start), self.start + timedelta(seconds=end))
            for i, sid in enumerate(("S1", "S2"), 1)]
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=0)

    def test_downlink_equality_rejected_and_strictly_later_accepted(self):
        task = self.task("T1", [("S1", 0)])
        self.downlinks()
        candidates = BoundedCandidateAdapter(self.cm, CAABSParams()).build(task)
        self.assertEqual(len(candidates), 1)  # earliest equality rejected; center accepted
        candidate = candidates[0]
        self.assertGreater(candidate.gs_start_time, candidate.sat_end_time)
        equal = replace(candidate, gs_start_time=candidate.sat_end_time,
                        gs_end_time=candidate.sat_end_time + timedelta(seconds=10))
        self.assertFalse(self.cm.is_feasible_assignment(equal, Schedule()))
        later = replace(equal, gs_start_time=equal.gs_start_time + timedelta(microseconds=1),
                        gs_end_time=equal.gs_end_time + timedelta(microseconds=1))
        self.assertTrue(self.cm.is_feasible_assignment(later, Schedule()))
        result = self.solve()
        self.assertEqual(len(result.assignments), 1)
        self.assert_shared_feasible(result)
        from schedulers.schedule_output import schedule_to_dict
        row = schedule_to_dict(result, self.problem)["assignments"][0]
        self.assertEqual(row["ground_station_id"], "G1")
        self.assertIsInstance(row["gs_start_time"], str)

    def test_exact_fit_downlink_has_no_strictly_later_solution(self):
        self.task("T1", [("S1", 0)])
        self.downlinks(end=20)
        self.assertEqual(self.solve().assignments, [])

    def test_ground_station_conflict_is_left_to_public_model(self):
        self.task("T1", [("S1", 0)])
        self.task("T2", [("S2", 0)])
        self.downlinks(start=20, end=30)
        result = self.solve()
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stats"]["prefilter_rejections"], 0)
        self.assert_shared_feasible(result)

    def test_non_agile_slew_not_pruned_statically(self):
        self.task("T1", [("S1", 0)])
        self.task("T2", [("S1", 15)])
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=10)
        result = self.solve()
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stats"]["prefilter_rejections"], 0)
        self.assert_shared_feasible(result)

    def test_agile_slew_uses_real_shared_angle_model(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        self.task("T1", [("S1", 0)])
        self.task("T2", [("S1", 20)])  # gap10 < shared zero-angle minimum11.66
        result = self.solve()
        self.assertEqual(len(result.assignments), 1)
        self.assert_shared_feasible(result)

    def test_M1_container_types_with_real_slew_constraints(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        previous = self.candidate(self.task("T0", [("S1", 0)]))
        candidate = self.candidate(self.task("T1", [("S1", 30)]))
        previous.sat_angles = [{"roll": 0.0, "pitch": 0.0, "yaw": 0.0}]
        listed = replace(candidate, sat_angles=[{"roll": 90.0, "pitch": 0.0, "yaw": 0.0}])
        tupled = replace(listed, sat_angles=tuple(deepcopy(listed.sat_angles)))
        parent = Schedule([previous])
        before = deepcopy(parent)
        self.assertTrue(self.cm.is_feasible_assignment(previous, Schedule()))
        self.assertTrue(self.cm.is_feasible_assignment(listed, Schedule()))
        self.assertTrue(self.cm.is_feasible_assignment(tupled, Schedule()))
        # The real parser handles outer lists but falls back for outer tuples.
        # Do not change that public rule here: the key must retain the distinction.
        self.assertFalse(self.cm.is_feasible_assignment(listed, parent))
        self.assertTrue(self.cm.is_feasible_assignment(tupled, parent))
        self.assertEqual(parent, before)
        self.assertNotEqual(canonical_assignment_key(listed), canonical_assignment_key(tupled))
        self.assertNotEqual(canonical_state_key(Schedule([previous, listed])),
                            canonical_state_key(Schedule([previous, tupled])))

    def test_M1_dedup_keeps_container_semantics(self):
        self.problem.satellites["S1"].maneuverability_type = "agile"
        candidate = self.candidate(self.task("T1", [("S1", 0)]))
        listed = replace(candidate, sat_angles=[{"roll": 90.0, "pitch": 0.0, "yaw": 0.0}])
        tupled = replace(listed, sat_angles=tuple(deepcopy(listed.sat_angles)))
        for value in (listed, tupled):
            self.assertTrue(self.cm.is_feasible_assignment(value, Schedule()))
        # Only candidate preparation is injected; insertion uses the real model.
        with patch.object(BoundedCandidateAdapter, "build",
                          return_value=[listed, tupled, deepcopy(listed)]):
            recorder = RecordingScheduler(clock=lambda: 0.0)
            result = self.solve(scheduler=recorder, beam_width=4)
        level, = recorder.levels
        self.assertEqual(len(level), 3)  # skip plus both distinct assignments
        assigned = [state for state in level if state.completed == 1]
        self.assertEqual({type(state.schedule.assignments[0].sat_angles) for state in assigned},
                         {list, tuple})
        self.assertEqual(len({state.search_key for state in level}), 3)
        self.assertEqual(result.metadata["caabs"]["stats"]["duplicate_states"], 1)
        for state in level:
            self.assert_shared_feasible(state.schedule)

    def test_branch_limit_bounds_real_alternatives(self):
        self.multipath()
        self.assertEqual(len(self.solve(beam_width=8, branch_limit=1).assignments), 1)
        self.assertEqual(len(self.solve(beam_width=8, branch_limit=2).assignments), 2)

    def test_normalized_utc_and_microsecond_keys(self):
        a = self.candidate(self.task("T1", [("S1", 0)]))
        local = timezone(timedelta(hours=8))
        aware = replace(a, sat_start_time=a.sat_start_time.replace(tzinfo=timezone.utc).astimezone(local),
                        sat_end_time=a.sat_end_time.replace(tzinfo=timezone.utc).astimezone(local))
        self.assertEqual(canonical_assignment_key(a), canonical_assignment_key(aware))
        self.assertNotEqual(canonical_assignment_key(a), canonical_assignment_key(
            replace(a, sat_start_time=a.sat_start_time + timedelta(microseconds=1))))

    def test_deduplication_removes_actual_duplicate_children(self):
        task = self.task("T1", [("S1", 0)])
        candidate = self.candidate(task)
        with patch.object(BoundedCandidateAdapter, "build", return_value=[candidate, deepcopy(candidate)]):
            scheduler = RecordingScheduler()
            result = self.solve(scheduler=scheduler)
        self.assertGreater(result.metadata["caabs"]["stats"]["duplicate_states"], 0)
        keys = [state.search_key for state in scheduler.levels[0]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assert_shared_feasible(result)

    def test_index_handles_nested_intervals_without_pair_graph(self):
        a = self.candidate(self.task("T1", [("S1", 0)]))
        # Invalid schedules are never searched; this fixture checks index lookup
        # correctness independently when a later short interval hides a long one.
        long = replace(a, sat_end_time=self.start + timedelta(seconds=100))
        short = replace(a, task_id="T2", sat_start_time=self.start + timedelta(seconds=10),
                        sat_end_time=self.start + timedelta(seconds=20))
        query = replace(a, task_id="T3", sat_start_time=self.start + timedelta(seconds=50),
                        sat_end_time=self.start + timedelta(seconds=60))
        index = SafeConflictIndex.from_schedule(Schedule([long, short]))
        self.assertTrue(index.rejects(query))
        self.assertEqual(len(index.observations["S1"][0]), 2)

    def test_inputs_and_original_placement_configuration_unchanged(self):
        self.multipath()
        before = deepcopy(self.problem)
        self.cm.placement_mode = "center"
        result = self.solve()
        self.assertEqual(self.problem, before)
        self.assertEqual(self.cm.placement_mode, "center")
        self.assert_shared_feasible(result)

    def test_completion_count_precedes_public_profit(self):
        self.task("T1", [("S1", 0)], duration=40, width=40, priority=100)
        self.task("T2", [("S1", 0)], priority=1)
        self.task("T3", [("S1", 20)], priority=1)
        result = self.solve(beam_width=8)
        self.assertEqual(set(result.assigned_task_ids), {"T2", "T3"})
        self.assert_shared_feasible(result)

    def test_frozen_objective_weights_decide_equal_completion(self):
        self.task("T1", [("S1", 100), ("S2", 0)])
        profit = self.solve()
        weights = ObjectiveWeights(w_profit=0, w_timeliness=1)
        context = replace(self.context(), objective_weights=weights)
        early = self.solve(context=context)
        self.assertEqual(profit.assignments[0].satellite_id, "S1")
        self.assertEqual(early.assignments[0].satellite_id, "S2")
        self.assertEqual(context.objective_weights, weights)
        self.assert_shared_feasible(early)


class StopTests(Fixture):
    context = SearchTests.context
    solve = SearchTests.solve
    multipath = SearchTests.multipath

    def test_budget_reserve_stops_before_requested_budget(self):
        self.multipath()
        clock = ManualClock()
        scheduler = RecordingScheduler(clock=clock, on_level=lambda _: setattr(clock, "now", .951))
        result = self.solve(scheduler=scheduler, context=replace(self.context(), time_budget_s=1))
        self.assertEqual(result.metadata["caabs"]["stop_reason"], "budget")
        self.assertAlmostEqual(result.metadata["caabs"]["return_reserve_s"], .05)
        self.assertEqual(len(result.assignments), 1)
        self.assertLess(clock.now, 1)

    def test_stop_in_later_preparation_preserves_incumbent(self):
        self.multipath()
        clock = ManualClock()
        original = BoundedCandidateAdapter.build
        def prepare(adapter, task):
            if task.id == "T2":
                clock.now = 60
            return original(adapter, task)
        with patch.object(BoundedCandidateAdapter, "build", prepare):
            result = self.solve(scheduler=ConflictBeamScheduler(clock=clock))
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stop_phase"], "candidate_preparation")
        self.assertEqual(result.metadata["caabs"]["stop_reason"], "budget")
        self.assert_shared_feasible(result)

    def test_stop_during_scoring_preserves_unpruned_incumbent(self):
        from algorithms.objectives import ObjectiveModel
        self.multipath()
        clock = ManualClock()
        original = ObjectiveModel.score
        scores = [0]
        def score(model, schedule):
            result = original(model, schedule)
            scores[0] += 1
            if scores[0] == 3:  # root, first child remembered, second child stops
                clock.now = 60
            return result
        with patch.object(ObjectiveModel, "score", score):
            result = self.solve(scheduler=ConflictBeamScheduler(clock=clock))
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stats"]["levels_completed"], 0)
        self.assertEqual(result.metadata["caabs"]["stop_phase"], "scoring")
        self.assert_shared_feasible(result)

    def test_stop_during_canonicalization_keeps_prior_snapshot(self):
        import algorithms.conflict_beam as module
        self.multipath()
        clock = ManualClock()
        original = module.canonical_state_key
        calls = [0]
        def key(schedule, checkpoint=lambda: None):
            result = original(schedule, checkpoint)
            calls[0] += 1
            if calls[0] == 3:
                clock.now = 60
            return result
        with patch.object(module, "canonical_state_key", key):
            result = self.solve(scheduler=ConflictBeamScheduler(clock=clock))
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stop_phase"], "canonicalization")
        self.assert_shared_feasible(result)

    def test_stop_during_deduplication_keeps_incumbent(self):
        self.multipath()
        clock = ManualClock()
        original = BeamState.search_key.fget
        def key(state):
            clock.now = 60
            return original(state)
        with patch.object(BeamState, "search_key", property(key)):
            result = self.solve(scheduler=ConflictBeamScheduler(clock=clock))
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stop_phase"], "deduplication")
        self.assert_shared_feasible(result)

    def test_stop_after_pruning_sort_keeps_incumbent(self):
        import builtins
        import algorithms.conflict_beam as module
        self.multipath()
        clock = ManualClock()
        def ordered(items, **kwargs):
            items = list(items)
            result = builtins.sorted(items, **kwargs)
            if items and isinstance(items[0], BeamState):
                clock.now = 60
            return result
        with patch.object(module, "sorted", ordered, create=True):
            result = self.solve(scheduler=ConflictBeamScheduler(clock=clock))
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.metadata["caabs"]["stop_phase"], "pruning")
        self.assert_shared_feasible(result)

    def test_cancellation_inside_preparation_is_polled(self):
        self.task("T1", [("S1", i * 30) for i in range(20)])
        import algorithms.conflict_beam as module
        cancelled = [False]
        original = module.candidate_exposure
        def checked(*args):
            result = original(*args)
            cancelled[0] = True
            return result
        with patch.object(module, "candidate_exposure", checked):
            result = self.solve(context=replace(self.context(), is_cancelled=lambda: cancelled[0]))
        self.assertEqual(result.metadata["caabs"]["stop_reason"], "cancelled")
        self.assertEqual(result.metadata["caabs"]["stop_phase"], "candidate_preparation")
        self.assertEqual(result.assignments, [])

    def test_invalid_budget_rejected_without_lifecycle_state(self):
        for budget in (0, -1, float("nan"), float("inf")):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.solve(context=replace(self.context(), time_budget_s=budget))


if __name__ == "__main__":
    unittest.main()
