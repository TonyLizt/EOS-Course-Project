"""Console metadata remains evidence-based; listing never promotes a legacy scene."""
import json
from pathlib import Path
import tempfile
import unittest

from eos_system.algorithm_registry import list_algorithms
from eos_system.scenario_catalog import ScenarioCatalog


class ConsoleMetadataTests(unittest.TestCase):
    def test_custom_scene_summary_and_changed_content_identity(self):
        catalog = ScenarioCatalog(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root/'sample.json'
            document = dict(satellites=[{'id': 'S1'}], missions=[{'id': 'M1'}],
                            metadata={'duration': 86400})
            scene.write_text(json.dumps(document))
            row = catalog.list_scenarios(root, 'custom')[0]
            self.assertEqual((row['satellite_count'], row['mission_count'], row['duration_s']), (1, 1, 86400))
            self.assertEqual(row['availability'], 'ready')
            self.assertEqual(row['scenario_physics_version'], 'legacy_unknown')
            self.assertNotEqual(row['physical_validation_status'], 'PASS')
            document['missions'].append({'id': 'M2'})
            scene.write_text(json.dumps(document))
            changed = catalog.list_scenarios(root, 'custom')[0]
            self.assertNotEqual(row['sha256'], changed['sha256'])
            self.assertEqual(changed['mission_count'], 2)

    def test_algorithm_strategy_and_schema_come_from_actual_registry(self):
        algorithms = list_algorithms()
        self.assertTrue(algorithms)
        for algorithm in algorithms:
            self.assertTrue(algorithm['strategy'])
            self.assertTrue(algorithm['objectives'])
            self.assertTrue(algorithm['limitations'])
            self.assertEqual(algorithm['availability'], 'ready')
            self.assertEqual(algorithm['parameters']['type'], 'object')


if __name__ == '__main__':
    unittest.main()
