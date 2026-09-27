"""Regression checks for attitude parsing and transition configuration."""

import unittest
from datetime import datetime, timedelta

from schedulers.constraint_model import Assignment, ConstraintModel
from schedulers.scenario_loader import SchedulingProblem, SchedulingSatellite
from schedulers.transition_utils import (
    compute_transition_time_agile,
    delta_g_between,
    extract_attitude_from_angles,
)


class TransitionModelTests(unittest.TestCase):
    def setUp(self):
        start = datetime(2026, 1, 1)
        self.problem = SchedulingProblem(
            scenario_id="test",
            start_time=start,
            end_time=start + timedelta(hours=1),
            satellites={"S1": SchedulingSatellite(id="S1", maneuverability_type="agile")},
            ground_stations={},
            tasks={},
            comm_windows=[],
        )
        self.previous = Assignment(
            task_id="A", satellite_id="S1", sat_start_time=start,
            sat_end_time=start + timedelta(seconds=10), sat_window_id=1,
            sat_angles={
                "roll_angles": [1.0, 3.0],
                "pitch_angles": [4.0, 8.0],
                "yaw_angles": [0.0, 2.0],
            },
        )
        self.next = Assignment(
            task_id="B", satellite_id="S1", sat_start_time=start + timedelta(seconds=40),
            sat_end_time=start + timedelta(seconds=50), sat_window_id=2,
            sat_angles={
                "roll_angles": [5.0, 6.0],
                "pitch_angles": [13.0, 14.0],
                "yaw_angles": [6.0, 7.0],
            },
        )

    def test_plural_angle_fields_use_last_then_first_sample(self):
        self.assertEqual(
            extract_attitude_from_angles(self.previous.sat_angles, want_first=False),
            {"roll": 3.0, "pitch": 8.0, "yaw": 2.0},
        )
        self.assertEqual(delta_g_between(self.previous.sat_angles, self.next.sat_angles), 11.0)

    def test_profile_is_stored_and_changes_transition_time(self):
        high = ConstraintModel(self.problem, agility_profile="High-Agility")
        low = ConstraintModel(self.problem, agility_profile="Low-Agility")
        self.assertAlmostEqual(
            high._transition_time_s("S1", self.previous, self.next),
            compute_transition_time_agile(11.0, "High-Agility"),
        )
        self.assertGreater(
            low._transition_time_s("S1", self.previous, self.next),
            high._transition_time_s("S1", self.previous, self.next),
        )

    def test_non_agile_transition_setting_is_stored(self):
        self.problem.satellites["S1"].maneuverability_type = "non_agile"
        model = ConstraintModel(self.problem, non_agile_transition_s=27.0)
        self.assertEqual(model._transition_time_s("S1", self.previous, self.next), 27.0)

    def test_existing_angle_shape_remains_supported(self):
        self.assertEqual(
            extract_attitude_from_angles(
                {"roll": [1.0, 2.0], "pitch": [3.0, 4.0], "yaw": [5.0, 6.0]},
                want_first=True,
            ),
            {"roll": 1.0, "pitch": 3.0, "yaw": 5.0},
        )


if __name__ == "__main__":
    unittest.main()
