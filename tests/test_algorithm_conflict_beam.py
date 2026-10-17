"""Synthetic algorithm checks; evidence below is UNIT_TEST_ONLY, not certification."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from pydantic import ValidationError

from algorithms.conflict_beam import (
    BeamState, BoundedCandidateAdapter, CAABSParams, branch_schedule,
    canonical_assignment_key, canonical_state_key,
)
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


if __name__ == "__main__":
    unittest.main()
