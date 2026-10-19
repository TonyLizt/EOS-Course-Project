"""Nine comparison algorithms and two seed models are separate public concepts."""
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eos_system.algorithm_registry import (
    COMPARISON_ALGORITHMS, get_algorithm, list_algorithms,
    list_schedule_models, make_context,
)
from eos_system.contracts import RunRequest
from eos_system.config import Settings
from eos_system.api import create_app
from fastapi import HTTPException
from schedulers.constraint_model import Schedule
from test_adaptive_repair import AdaptiveRepairTests


class NineAlgorithmTests(unittest.TestCase):
    def test_catalog_and_models_are_disjoint_and_dependencies_explicit(self):
        rows = list_algorithms()
        self.assertEqual(len(rows), 12)  # 原九种 + CAABS + RABAS + 真实冻结模型LAVIS。
        self.assertEqual({r['algorithm_id'] for r in rows}, set(COMPARISON_ALGORITHMS))
        self.assertEqual({r['model_id'] for r in list_schedule_models()},
                         {'completion_first', 'adaptive_repair'})
        self.assertNotIn('completion_first', COMPARISON_ALGORITHMS)
        self.assertEqual(get_algorithm('completion_first').version, 'baseline-1')
        self.assertEqual(next(r for r in rows if r['algorithm_id'] == 'ppo')['availability'], 'unavailable')
        with self.assertRaises(ValueError):
            get_algorithm('sa').parse_params({'model_path': '/untrusted'})
        with self.assertRaises(ValueError):
            RunRequest(scenario_id='x', algorithm_id='sa', schedule_model='unknown')

    def test_selected_model_is_passed_to_real_search_adapter(self):
        spec = get_algorithm('sa')
        context = make_context(42, 5, {}, spec, {}, schedule_model='adaptive_repair')
        initial = Schedule()
        model = SimpleNamespace(search=lambda *args: initial)
        algorithm = SimpleNamespace(search=lambda p, cm, seed: seed)
        with patch('eos_system.algorithm_registry.create_algorithm', side_effect=[algorithm, model]) as factory:
            solver = spec.build(context)
            result = solver.solve(object(), SimpleNamespace(build_initial_schedule=lambda: Schedule()), context)
        self.assertIs(result, initial)
        self.assertEqual(factory.call_args_list[1].args[0], 'adaptive_repair')

    def test_submission_rejects_model_as_algorithm_and_unavailable_ppo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(Settings(runtime_dir=root, scenario_dir=root/'scenarios'))
            submit = next(route.endpoint for route in app.routes if route.path == '/api/runs' and 'POST' in route.methods)
            for aid in ('completion_first', 'adaptive_repair', 'ppo'):
                with self.subTest(algorithm=aid), self.assertRaises(HTTPException) as raised:
                    submit(RunRequest(scenario_id='not-needed', algorithm_id=aid), None)
                self.assertEqual(raised.exception.status_code, 422)

    def test_seven_available_searches_on_small_trusted_unit_fixture(self):
        # Synthetic planning evidence is UNIT TEST ONLY, not a physical certificate.
        tiny = AdaptiveRepairTests(); tiny.setUp()
        tiny.add_task('A', [0, 50]); tiny.add_task('B', [30])
        tuning = {'sa': {'max_iterations': 2, 'neighbor_attempts': 2},
                  'ga': {'population_size': 4, 'generations': 1},
                  'aco': {'ants': 2, 'iterations': 1}}
        for aid in COMPARISON_ALGORITHMS:
            if aid in ('mip', 'ppo', 'lavis'):
                continue
            with self.subTest(algorithm=aid):
                spec = get_algorithm(aid)
                context = make_context(42, 5, {}, spec, tuning.get(aid, {}))
                result = spec.build(context).solve(tiny.problem, tiny.cm, context)
                self.assertGreater(len(result.assignments), 0)
                checked = Schedule()
                for assignment in result.assignments:
                    self.assertTrue(tiny.cm.is_feasible_assignment(assignment, checked))
                    checked.assignments.append(assignment)


if __name__ == '__main__':
    unittest.main()
