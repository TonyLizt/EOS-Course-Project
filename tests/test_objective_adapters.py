"""R1: requested goals belong to the experiment; model training goals do not replace them."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from eos_system.algorithm_registry import get_algorithm

TP = dict(w_profit=1., w_completion=0., w_timeliness=0., w_balance=0.)
TCR = dict(w_profit=0., w_completion=1., w_timeliness=0., w_balance=0.)
MIXED = dict(w_profit=.5, w_completion=.3, w_timeliness=.1, w_balance=.1)


class ObjectiveCompatibilityTests(unittest.TestCase):
    def test_registered_learned_solvers_accept_all_requested_goals(self):
        # Constructor contract only. No synthetic model or physical success is registered.
        for aid in ('ppo', 'lavis'):
            spec = get_algorithm(aid)
            for weights in (TP, TCR, MIXED):
                with self.subTest(algorithm=aid, weights=weights):
                    context = SolveContext(42, 2., ObjectiveWeights(**weights),
                        spec.parse_params({'model_id':'unit-model'}),
                        model_provenance={'model_id':'unit-model', 'model_sha256':'a'*64,
                                          'execution_mode':'physical_validation'})
                    with patch('algorithms.ppo.model.FrozenPolicy'), \
                         patch('algorithms.lavis.model.FrozenPredictor'), \
                         patch('algorithms.lavis.solver.FrozenPredictor'):
                        solver = spec.build(context)
                    self.assertTrue(callable(solver.solve))
                    self.assertEqual(vars(context.objective_weights), weights)

    def test_training_protocols_remain_strict_and_unchanged(self):
        from algorithms.ppo.protocol import validate_weights as ppo_training
        from algorithms.lavis.protocol import validate_weights as lavis_training
        with self.assertRaises(ValueError): ppo_training(ObjectiveWeights(**TCR))
        with self.assertRaises(ValueError): lavis_training(ObjectiveWeights(**TP))
