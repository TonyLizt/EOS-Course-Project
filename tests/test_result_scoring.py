"""固定公式与未知来源边界，不使用其他算法结果归一化。"""
import unittest
from eos_system.result_scoring import calculate_score, score_run


class ResultScoringTests(unittest.TestCase):
    def test_formula_directions_and_upper_bound(self):
        self.assertEqual(calculate_score({'TCR': .8, 'TP': 70, 'TM': .1}, 100)['value'], 79)
        self.assertEqual(calculate_score({'TCR': 1, 'TP': 100, 'TM': 0}, 100)['value'], 100)
        self.assertEqual(calculate_score({'TCR': 0, 'TP': 0, 'TM': 1}, 100)['value'], 0)
        self.assertEqual(calculate_score({'TCR': 1, 'TP': 0, 'TM': 0}, 0)['value'], 80)

    def test_nonfinite_invalid_or_missing_results_are_not_scores(self):
        for key in ('TCR', 'TP', 'TM'):
            metrics = {'TCR': .5, 'TP': 50, 'TM': .5}; metrics[key] = float('nan')
            with self.assertRaises(ValueError): calculate_score(metrics, 100)
        self.assertIsNone(score_run({'status': 'FAILED', 'metrics': {'TCR': 1}}))
        self.assertIsNone(score_run({'status': 'SUCCEEDED', 'plan': {}, 'metrics': {'TCR': 1}}))


if __name__ == '__main__': unittest.main()
