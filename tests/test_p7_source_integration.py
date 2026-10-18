"""Source-closure regression; mutations affect only an owned temporary copy."""
from pathlib import Path
import tempfile
import unittest
import json
import hashlib


class PhysicsClosureTests(unittest.TestCase):
    def test_relative_pointing_helper_change_invalidates_window_physics_identity(self):
        from utils.continuous_exposure import WINDOW_PHYSICS_FILES, window_physics_sources
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in set(WINDOW_PHYSICS_FILES) | {'utils/attitude_frames.py'}:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((repository / name).read_bytes())
            before = window_physics_sources(root)
            path = root / 'utils/attitude_frames.py'
            path.write_bytes(path.read_bytes() + b'\n# changed local physics dependency\n')
            self.assertNotEqual(before, window_physics_sources(root))


class DevelopmentRoutingTests(unittest.TestCase):
    def test_missing_development_sidecar_never_downgrades_to_legacy(self):
        from eos_system.provenance import capture_execution_provenance
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / 'unit.json'
            scene.write_text(json.dumps({'metadata': {'extra': {
                'development_generation_contract': 'gen02.development.v1'}}}))
            sha = hashlib.sha256(scene.read_bytes()).hexdigest()
            for mode in ('planning_preview', 'formal', 'physical_validation'):
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    capture_execution_provenance(scene, sha, mode)


if __name__ == '__main__':
    unittest.main()
