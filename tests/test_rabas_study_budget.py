"""The experiment must not silently accept an over-budget baseline result."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import time
from algorithms.auction_bundle import RABASParams
from schedulers.constraint_model import Schedule
from scripts.benchmark_rabas_cross_scale import job_run

class StudyBudgetTests(TestCase):
    def run_solver(self, solver):
        spec=SimpleNamespace(parse_params=lambda raw:RABASParams(),build=lambda ctx:solver)
        job=dict(algorithm='rabas',family='uniform',n=2,scenario_seed=101,seed=41,
                 budget=.02,baseline='89dff80f881ed4c2a49b43906071ba07012be46c',params={})
        with patch('scripts.benchmark_rabas_cross_scale.get_algorithm',return_value=spec):
            return job_run(job)

    def test_broad_exception_helper_cannot_swallow_deadline(self):
        class Solver:
            def solve(self,*args):
                end=time.perf_counter()+.08
                while time.perf_counter()<end:
                    try:time.sleep(.005)
                    except Exception:pass
                return Schedule()
        row=self.run_solver(Solver())
        self.assertEqual(row['status'],'TIMED_OUT')
        self.assertIsNone(row['completed'])

    def test_even_base_exception_swallow_cannot_claim_equal_budget_success(self):
        class Solver:
            def solve(self,*args):
                end=time.perf_counter()+.05
                while time.perf_counter()<end:
                    try:time.sleep(.005)
                    except BaseException:pass  # Deliberately hostile test double only.
                return Schedule()
        row=self.run_solver(Solver())
        self.assertEqual(row['status'],'OVER_BUDGET')
        self.assertIsNone(row['completed'])
        self.assertNotIn('metrics',row)
