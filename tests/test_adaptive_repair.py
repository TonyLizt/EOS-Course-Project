"""Small deterministic checks for the completion-first repair scheduler."""

import time
import unittest
from datetime import datetime, timedelta

from algorithms.adaptive_repair import AdaptiveRepairConfig, AdaptiveRepairScheduler
from algorithms.factory import create_algorithm
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.scenario_loader import (
    SchedulingProblem, SchedulingSatellite, SchedulingTask, TaskWindow,
)


class AdaptiveRepairTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1)
        self.problem = SchedulingProblem(
            scenario_id="repair-test",
            start_time=self.start,
            end_time=self.start + timedelta(minutes=2),
            satellites={"S1": SchedulingSatellite(id="S1", maneuverability_type="non_agile")},
            ground_stations={}, tasks={}, comm_windows=[],
        )
        self.cm = ConstraintModel(self.problem, non_agile_transition_s=0.0)
        self.algorithm = AdaptiveRepairScheduler(AdaptiveRepairConfig(
            max_candidates_per_task=8, max_repair_checks=500,
            alns_iterations=5, time_budget_s=5.0,
        ))

    def add_task(self, tid, starts, priority=1):
        windows = [TaskWindow(
            window_id=100 * ord(tid) + i,
            satellite_id="S1", mission_id=tid, sensor_id="sensor", orbit_number=1,
            start_time=self.start + timedelta(seconds=second),
            end_time=self.start + timedelta(seconds=second + 10),
            non_agile_data={"roll_angle": 0.0, "pitch_angle": 0.0, "yaw_angle": 0.0},
        ) for i, second in enumerate(starts)]
        self.problem.tasks[tid] = SchedulingTask(
            id=tid, priority=priority, required_duration=10, windows=windows,
        )

    def test_candidates_cover_separate_windows(self):
        self.add_task("A", [0, 20, 40, 60])
        algorithm = AdaptiveRepairScheduler(AdaptiveRepairConfig(max_candidates_per_task=4))
        candidates = algorithm._diverse_candidates(
            self.problem, self.problem.tasks["A"], self.cm, 1,
        )
        self.assertEqual(len(candidates), 4)
        self.assertEqual(len({a.sat_window_id for a in candidates}), 4)

    def test_chain_reinserts_displaced_task(self):
        self.add_task("A", [0, 50])
        self.add_task("B", [30])
        self.add_task("C", [0])
        cand = {tid: self.algorithm._diverse_candidates(
            self.problem, task, self.cm, i,
        ) for i, (tid, task) in enumerate(self.problem.tasks.items())}
        initial = Schedule(assignments=[cand["A"][0], cand["B"][0]])
        result = self.algorithm._insert_chain(
            "C", initial, 2, frozenset(), cand, self.cm,
            {"checks": 0, "limit": 500}, time.monotonic() + 5,
        )
        self.assertIsNotNone(result)
        self.assertEqual(set(result.assigned_task_ids), {"A", "B", "C"})
        replay = Schedule()
        for assignment in result.assignments:
            self.assertTrue(self.cm.is_feasible_assignment(assignment, replay))
            replay.assignments.append(assignment)

    def test_factory_and_search_return_feasible_schedule(self):
        self.add_task("A", [0, 50])
        self.add_task("B", [30])
        self.add_task("C", [0])
        algorithm = create_algorithm("adaptive_repair", cfg_overrides={
            "max_candidates_per_task": 8, "time_budget_s": 5.0,
        })
        result = algorithm.search(self.problem, self.cm, Schedule())
        self.assertEqual(len(result.assignments), 3)
        replay = Schedule()
        for assignment in result.assignments:
            self.assertTrue(self.cm.is_feasible_assignment(assignment, replay))
            replay.assignments.append(assignment)


if __name__ == "__main__":
    unittest.main()
