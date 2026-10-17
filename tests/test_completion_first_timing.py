from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from algorithms.heuristics import HeuristicCompletionFirstScheduler, HeuristicConfig
from schedulers.constraint_model import Assignment, Schedule


def assignment(start_second: int) -> Assignment:
    start = datetime(2026, 1, 1) + timedelta(seconds=start_second)
    return Assignment(
        task_id="M1",
        satellite_id="S1",
        sat_start_time=start,
        sat_end_time=start + timedelta(seconds=10),
        sat_window_id=start_second,
        sensor_id="camera",
    )


class FakeConstraints:
    placement_mode = "earliest"
    downlink_duration_ratio = 1.0

    def __init__(self, rejected_starts=()):
        self.rejected_starts = set(rejected_starts)

    def is_feasible_assignment(self, candidate, schedule):
        return candidate.sat_start_time.second not in self.rejected_starts


class CompletionFirstTimingTests(TestCase):
    def run_scheduler(self, candidates, constraints):
        problem = SimpleNamespace(tasks={"M1": SimpleNamespace(priority=1.0)})
        scheduler = HeuristicCompletionFirstScheduler(HeuristicConfig(seed=42, randomized=True))
        with patch("algorithms.heuristics.enumerate_task_candidates", return_value=candidates):
            return scheduler.search(problem, constraints, Schedule())

    def test_randomized_search_still_chooses_earliest_feasible_exposure(self):
        schedule = self.run_scheduler([assignment(40), assignment(10), assignment(25)], FakeConstraints())
        self.assertEqual(schedule.assignments[0].sat_start_time.second, 10)

    def test_transition_infeasible_early_exposure_moves_to_next_feasible_time(self):
        schedule = self.run_scheduler(
            [assignment(40), assignment(10), assignment(25)],
            FakeConstraints(rejected_starts={10}),
        )
        self.assertEqual(schedule.assignments[0].sat_start_time.second, 25)
