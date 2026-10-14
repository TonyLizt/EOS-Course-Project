import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from replay.contracts import ReplayConfig
from replay.manifest import write_manifest
from replay.read_only import ReplayInputError, load_replay_inputs, require_isolated_output


def fixture(root: Path):
    scenario = root / "scenario.json"
    plan = root / "plan.json"
    scenario.write_text(json.dumps({
        "scenario_id": "demo", "metadata": {"creation_time": "2026-01-01T00:00:00+00:00", "duration": 60},
        "satellites": [{"id": "S1", "observation_capability": {"sensors": [{"sensor_id": "C1"}]}}],
        "missions": [{"id": "M1", "target_location": {"latitude": 0, "longitude": 0, "altitude_km": 0}}],
        "observation_windows": [],
    }), encoding="utf-8")
    plan.write_text(json.dumps({
        "scenario_id": "demo", "start_time": "2026-01-01T00:00:00+00:00", "end_time": "2026-01-01T00:01:00+00:00",
        "assignments": [{"task_id": "M1", "satellite_id": "S1", "sensor_id": "C1",
                         "sat_start_time": "2026-01-01T00:00:10+00:00", "sat_end_time": "2026-01-01T00:00:20+00:00"}],
    }), encoding="utf-8")
    return scenario, plan


class ReplayContractTests(unittest.TestCase):
    def test_load_is_byte_preserving_and_links_original_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            scenario, plan = fixture(Path(temp))
            before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (scenario, plan)}
            inputs = load_replay_inputs(scenario, plan)
            self.assertEqual(inputs.scenario["scenario_id"], "demo")
            self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (scenario, plan)})

    def test_output_must_not_overlap_any_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenario, plan = fixture(root)
            with self.assertRaises(ReplayInputError):
                require_isolated_output(root / "derived", [root])

    def test_manifest_has_source_hashes_and_no_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            scenario, plan = fixture(source)
            config = root / "config.json"
            profile = ReplayConfig.from_path(Path("replay_configs/display-profile-v2.json"))
            config.write_text(json.dumps(profile.as_dict()), encoding="utf-8")
            target = write_manifest(scenario, plan, config, root / "runtime" / "replays" / "demo", [])
            manifest = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(manifest["scenario_sha256"], hashlib.sha256(scenario.read_bytes()).hexdigest())
            self.assertEqual(manifest["attitude_version"], "geometry-pointing-fixed-payload-v1")
            self.assertEqual(manifest["geometry_version"], "wgs84-ray-ellipsoid-v1")
            self.assertEqual(manifest["resources"][0]["asset_id"], "landsat8-nasa-display")
            self.assertNotIn(str(root), target.read_text(encoding="utf-8"))

    def test_missing_timezone_is_diagnostic_not_repaired(self):
        with tempfile.TemporaryDirectory() as temp:
            scenario, plan = fixture(Path(temp))
            data = json.loads(plan.read_text())
            data["start_time"] = "2026-01-01T00:00:00"
            plan.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ReplayInputError, "timezone"):
                load_replay_inputs(scenario, plan)


if __name__ == "__main__":
    unittest.main()
