import unittest

from replay.timeline import build_task_phases, phase_at
from schedulers.transition_utils import compute_transition_time_agile


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.scenario = {"satellites": [{
            "id": "S1", "maneuverability_capability": {"maneuverability_type": "agile"}
        }]}
        self.plan = {"assignments": [
            {"task_id": "M1", "satellite_id": "S1", "sensor_id": "C1",
             "sat_start_time": "2026-01-01T00:00:10+00:00", "sat_end_time": "2026-01-01T00:00:20+00:00",
             "sat_angles": {"roll_angles": [0], "pitch_angles": [0], "yaw_angles": [0]}},
            {"task_id": "M2", "satellite_id": "S1", "sensor_id": "C1",
             "sat_start_time": "2026-01-01T00:02:00+00:00", "sat_end_time": "2026-01-01T00:02:10+00:00",
             "sat_angles": {"roll_angles": [10], "pitch_angles": [20], "yaw_angles": [30]}},
        ]}

    def test_plural_angles_use_current_legacy_model_and_endpoints_stay_exact(self):
        segments, diagnostics = build_task_phases(self.scenario, self.plan, agility_profile="Standard-Agility", non_agile_transition_s=10)
        self.assertEqual(diagnostics[0]["delta_g_deg"], 60.0)
        self.assertEqual(diagnostics[0]["legacy_transition_time_s"], compute_transition_time_agile(60, "Standard-Agility"))
        observing = [item for item in segments if item["phase"] == "OBSERVING"]
        self.assertEqual(observing[1]["start_time"], "2026-01-01T00:02:00+00:00")
        self.assertEqual(observing[1]["end_time"], "2026-01-01T00:02:10+00:00")
        self.assertFalse(diagnostics[0]["used_fallback"])

    def test_phase_is_half_open_and_order_independent(self):
        segments, _ = build_task_phases(self.scenario, self.plan, agility_profile="Standard-Agility", non_agile_transition_s=10)
        first = phase_at(segments, "S1", "2026-01-01T00:00:10+00:00")
        after = phase_at(segments, "S1", "2026-01-01T00:00:20+00:00")
        again = phase_at(segments, "S1", "2026-01-01T00:00:10+00:00")
        self.assertEqual(first["phase"], "OBSERVING")
        self.assertIsNone(after)
        self.assertEqual(first, again)

    def test_insufficient_gap_is_diagnostic_and_never_moves_observation(self):
        self.plan["assignments"][1]["sat_start_time"] = "2026-01-01T00:00:25+00:00"
        self.plan["assignments"][1]["sat_end_time"] = "2026-01-01T00:00:35+00:00"
        segments, diagnostics = build_task_phases(self.scenario, self.plan, agility_profile="Standard-Agility", non_agile_transition_s=10)
        self.assertTrue(diagnostics[0]["display_degraded"])
        self.assertEqual(diagnostics[0]["reason_code"], "TRANSITION_GAP_INSUFFICIENT")
        second = [item for item in segments if item["phase"] == "OBSERVING"][1]
        self.assertEqual(second["start_time"], "2026-01-01T00:00:25+00:00")


if __name__ == "__main__":
    unittest.main()
