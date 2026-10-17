import json
from pathlib import Path
import unittest

from eos_system.config import list_scenarios_in, sha256_file
from eos_system.provenance import capture_provenance
from schedulers.scenario_loader import load_scheduling_problem_from_json
from scripts.recompute_scenario_windows_parallel import covered_mission_ids
from utils.continuous_exposure import ExposureStatus, planning_window


SCENARIO_ROOT = Path(__file__).parents[1] / "experiments/scenarios"
MEDIUM_ROOT = SCENARIO_ROOT / "medium"


class EpochFixedScenarioSchedulingTests(unittest.TestCase):
    def test_epoch_fixed_candidates_do_not_bypass_current_release_gate(self):
        paths = sorted(SCENARIO_ROOT.glob("*/*_epoch_fixed_v1.json"))
        self.assertEqual(len(paths), 6)
        listed = list_scenarios_in(SCENARIO_ROOT, "bundled")
        listed_ids = {row["scenario_id"] for row in listed}
        for path in paths:
            with self.subTest(path=path.name):
                candidate_id = path.relative_to(SCENARIO_ROOT).with_suffix("").as_posix()
                legacy_id = candidate_id.removesuffix("_epoch_fixed_v1")
                self.assertNotIn(candidate_id, listed_ids)
                self.assertIn(legacy_id, listed_ids)
                # This is the historical sampled-release record.  It remains
                # readable for audit, but cannot supply trusted window lineage.
                evidence = capture_provenance(path, sha256_file(path))
                self.assertEqual(evidence["scenario_physics_version"], "epoch_fixed_v1")
                self.assertEqual(evidence["physical_validation_status"], "PASS")
                problem = load_scheduling_problem_from_json(path)
                first_window = next(window for task in problem.tasks.values() for window in task.windows)
                self.assertIsNone(first_window.planning_evidence)
                self.assertEqual(planning_window(first_window).status, ExposureStatus.INCONCLUSIVE)

    def test_medium_coverage_diagnostics_identify_short_or_empty_windows(self):
        for path in sorted(MEDIUM_ROOT.glob("*_epoch_fixed_v1.json")):
            with self.subTest(path=path.name):
                payload = json.loads(path.read_bytes())
                covered = covered_mission_ids(payload)
                missing = {row["id"] for row in payload["missions"]} - covered
                self.assertEqual(len(covered), 98)
                self.assertEqual(len(missing), 2)


if __name__ == "__main__":
    unittest.main()
