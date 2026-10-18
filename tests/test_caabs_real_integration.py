"""Opt-in REAL physics/Spawn end-to-end regression; no IPC or verifier mocks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.environ.get("EOS_RUN_CAABS_REAL_E2E") == "1", "real Orekit/Spawn end-to-end opt-in")
class RealIntegrationTests(unittest.TestCase):
    def test_real_scene_runner_spawn_cancel_crash_and_controller_restart(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="caabs-real-e2e-") as temp:
            output = Path(temp) / "acceptance"
            result = subprocess.run([sys.executable, "-B", "scripts/validate_caabs_real_integration.py",
                "--output", str(output), "--orekit-data", os.environ["EOS_OREKIT_DATA"]],
                cwd=root, capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads((output / "acceptance.json").read_bytes())
            self.assertEqual(evidence["small"]["planning_windows"], 3)
            for algorithm in ("caabs", "completion_first"):
                self.assertGreater(evidence["runner"][algorithm]["metrics"]["completed_tasks"], 0)
            self.assertEqual(evidence["controller"]["cancel"]["status"], "CANCELLED")
            self.assertEqual(evidence["controller"]["crash"]["status"], "FAILED")
            self.assertEqual(evidence["controller"]["restart"]["status"], "SUCCEEDED")
