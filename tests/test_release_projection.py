"""发布场景的96位种子不应使列表/回放投影溢出。"""
import json
import tempfile
import unittest
from pathlib import Path
from replay.scene import load_display_scene, file_sha256


class ReleaseProjectionTests(unittest.TestCase):
    def test_large_seed_preserved_and_coordinates_json_serializable(self):
        seed = 29502154955141302882957219537
        data = {'metadata': {'duration': 1800.5, 'extra': {'generator_seed': seed}},
                'missions': [{'target_location': {'latitude': 31.25}}],
                'observation_windows': [{'discarded_seed': seed}], 'scenario_id': 'test'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scene.json'
            path.write_text(json.dumps(data))
            before = file_sha256(path)
            actual = load_display_scene(path)
            self.assertEqual(actual['metadata'], data['metadata'])
            self.assertIsInstance(actual['metadata']['extra']['generator_seed'], int)
            self.assertIsInstance(actual['metadata']['duration'], float)
            self.assertEqual(json.loads(json.dumps(actual))['missions'], data['missions'])
            self.assertNotIn('observation_windows', actual)
            self.assertEqual(before, file_sha256(path))
