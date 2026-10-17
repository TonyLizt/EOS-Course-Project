from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.release_epoch_fixed_scenario import validate_release
from scripts.recompute_scenario_windows import sidecar_path


ROOT = Path(__file__).parents[1]
LEGACY = ROOT / "experiments/scenarios/small/Scenario_S1_Sats10_M20_T1.0d_dist1.json"
CANDIDATE = ROOT / "experiments/scenarios/small/Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1.json"


class EpochReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="epoch-release-test-")
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.legacy = root / LEGACY.name
        self.candidate = root / CANDIDATE.name
        shutil.copyfile(LEGACY, self.legacy)
        shutil.copyfile(CANDIDATE, self.candidate)

    def test_sampled_candidate_cannot_be_formally_released(self):
        with self.assertRaisesRegex(ValueError, "trusted window-generation evidence"):
            validate_release(self.legacy, self.candidate, seeds=(42,), minimum_tcr=0.92)
        self.assertFalse(sidecar_path(self.candidate).exists())

    def test_static_lineage_change_is_rejected_without_sidecar(self):
        payload = json.loads(self.candidate.read_bytes())
        payload["missions"][0]["priority"] += 1
        self.candidate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "static lineage changed"):
            validate_release(self.legacy, self.candidate, seeds=(42,), minimum_tcr=0.92)
        self.assertFalse(sidecar_path(self.candidate).exists())


if __name__ == "__main__":
    unittest.main()
