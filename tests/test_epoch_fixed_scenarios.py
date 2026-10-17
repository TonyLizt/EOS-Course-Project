from pathlib import Path
import unittest

from algorithms.factory import create_algorithm
from schedulers.constraint_model import ConstraintModel
from schedulers.engine import SchedulingEngine
from schedulers.scenario_loader import load_scheduling_problem_from_json


ROOT = Path(__file__).parents[1] / "experiments/scenarios/small"


class EpochFixedScenarioSchedulingTests(unittest.TestCase):
    def test_all_published_small_scenarios_restore_tcr_without_occlusion_bypass(self):
        paths = sorted(ROOT.glob("*_epoch_fixed_v1.json"))
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


if __name__ == "__main__":
    unittest.main()
