import json
from pathlib import Path
import unittest

from algorithms.factory import create_algorithm
from eos_system.config import list_scenarios_in, sha256_file
from eos_system.provenance import capture_provenance
from schedulers.constraint_model import ConstraintModel
from schedulers.engine import SchedulingEngine
from schedulers.scenario_loader import load_scheduling_problem_from_json
from scripts.recompute_scenario_windows_parallel import covered_mission_ids


SCENARIO_ROOT = Path(__file__).parents[1] / "experiments/scenarios"
SMALL_ROOT = SCENARIO_ROOT / "small"
MEDIUM_ROOT = SCENARIO_ROOT / "medium"


class EpochFixedScenarioSchedulingTests(unittest.TestCase):
    def test_released_scenarios_are_catalogued_and_accepted_by_run_gate(self):
        paths = sorted(SCENARIO_ROOT.glob("*/*_epoch_fixed_v1.json"))
        self.assertEqual(len(paths), 6)
        listed = list_scenarios_in(SCENARIO_ROOT, "bundled")
        self.assertEqual(
            [row["scenario_id"] for row in listed],
            [path.relative_to(SCENARIO_ROOT).with_suffix("").as_posix() for path in paths],
        )
        for path in paths:
            with self.subTest(path=path.name):
                evidence = capture_provenance(path, sha256_file(path))
                self.assertEqual(evidence["scenario_physics_version"], "epoch_fixed_v1")
                self.assertEqual(evidence["physical_validation_status"], "PASS")

    def test_all_published_small_scenarios_restore_tcr_without_occlusion_bypass(self):
        paths = sorted(SMALL_ROOT.glob("*_epoch_fixed_v1.json"))
        self.assertEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.name):
                problem = load_scheduling_problem_from_json(path)
                constraints = ConstraintModel(problem)
                for seed in (1, 42, 99):
                    schedule = SchedulingEngine(
                        problem, constraints,
                        create_algorithm("completion_first", cfg_overrides={"seed": seed}),
                    ).run()
                    self.assertGreaterEqual(
                        len(schedule.assignments) / len(problem.tasks), 0.92,
                        f"{path.name} seed={seed}",
                    )

    def test_published_medium_scenarios_remain_above_release_tcr(self):
        paths = sorted(MEDIUM_ROOT.glob("*_epoch_fixed_v1.json"))
        self.assertEqual(len(paths), 2)
        for path in paths:
            with self.subTest(path=path.name):
                problem = load_scheduling_problem_from_json(path)
                schedule = SchedulingEngine(
                    problem,
                    ConstraintModel(problem),
                    create_algorithm("completion_first", cfg_overrides={"seed": 42}),
                ).run()
                self.assertGreaterEqual(
                    len(schedule.assignments) / len(problem.tasks), 0.92,
                    path.name,
                )

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
