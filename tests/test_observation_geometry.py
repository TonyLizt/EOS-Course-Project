from datetime import datetime, timedelta
from pathlib import Path
import unittest

from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.observation_geometry import validate_observation_interval
from schedulers.scenario_loader import load_scheduling_problem_from_json


SCENE = Path(__file__).parents[1] / "experiments/scenarios/small/Scenario_S1_Sats10_M20_T1.0d_dist1.json"


class ObservationGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.problem = load_scheduling_problem_from_json(SCENE)

    def test_known_scd_m003_exposure_is_earth_occluded(self):
        result = validate_observation_interval(
            self.problem, "SCD_1_22490", "M003",
            datetime.fromisoformat("2025-11-18T19:05:00"),
            datetime.fromisoformat("2025-11-18T19:05:15"),
        )
        self.assertTrue(result.checked)
        self.assertFalse(result.feasible)
        self.assertLess(result.min_elevation_deg, -70.0)

    def test_known_gpm_m018_exposure_is_earth_occluded(self):
        result = validate_observation_interval(
            self.problem, "GPM-CORE_39574", "M018",
            datetime.fromisoformat("2025-11-18T23:41:13"),
            datetime.fromisoformat("2025-11-18T23:41:24"),
        )
        self.assertTrue(result.checked)
        self.assertFalse(result.feasible)
        self.assertLess(result.min_elevation_deg, -40.0)

    def test_unified_constraint_model_rejects_stale_window_assignment(self):
        task = self.problem.tasks["M003"]
        start = datetime.fromisoformat("2025-11-18T19:05:00")
        window = next(w for w in task.windows if w.satellite_id == "SCD_1_22490" and w.start_time <= start < w.end_time)
        assignment = Assignment(
            task_id=task.id,
            satellite_id=window.satellite_id,
            sat_start_time=start,
            sat_end_time=start + timedelta(seconds=task.required_duration),
            sat_window_id=window.window_id,
            sensor_id=window.sensor_id,
            orbit_number=window.orbit_number,
            sat_angles=window.agile_data,
        )
        self.assertFalse(ConstraintModel(self.problem).is_feasible_assignment(assignment, Schedule()))


if __name__ == "__main__":
    unittest.main()
