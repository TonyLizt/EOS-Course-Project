import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from eos_system.api import create_app
from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.storage import Database, compact_json, now
from replay.document import build_replay_document
from eos_system.replay_service import ReplayError


class ReplayDeliveryTests(unittest.TestCase):
    def test_successful_run_replay_is_repeatable_read_only_and_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenario_dir = root / "scenarios"
            scenario_dir.mkdir()
            scenario = scenario_dir / "fixture.json"
            scenario.write_text(json.dumps({
                "scenario_id": "fixture",
                "metadata": {"creation_time": "2026-01-01T00:00:00+00:00", "duration": 60},
                "satellites": [{
                    "id": "ALOS-2_39766",
                    "observation_capability": {"sensors": [{"sensor_id": "ALOS-2_39766_sensor"}]},
                    "maneuverability_capability": {"maneuverability_type": "agile"},
                }],
                "missions": [{
                    "id": "M1",
                    "target_location": {"latitude": 0, "longitude": 0, "altitude_km": 0},
                }],
                "observation_windows": [],
            }), encoding="utf-8")
            scenario_before = hashlib.sha256(scenario.read_bytes()).hexdigest()
            settings = Settings(runtime_dir=root / "runtime", scenario_dir=scenario_dir)
            app = create_app(settings)
            database = Database(settings.database_path)
            run_id = "00000000-0000-4000-8000-000000000006"
            config = RunConfig(
                run_id=run_id,
                scenario_id="fixture",
                scenario_sha256=scenario_before,
                scenario_path=str(scenario),
                algorithm_id="completion_first",
                algorithm_version="baseline-1",
                created_at=now(),
            )
            database.enqueue(config, max_queued=8)
            attempt, _ = database.start_attempt(run_id)
            self.assertTrue(database.set_verifying(run_id, attempt))
            plan = {
                "scenario_id": "fixture",
                # The production scheduler emits naive ISO strings whose
                # established meaning is UTC after scenario-loader normalisation.
                "start_time": "2026-01-01T00:00:00",
                "end_time": "2026-01-01T00:01:00",
                "assignments": [{
                    "task_id": "M1",
                    "satellite_id": "ALOS-2_39766",
                    "sensor_id": "ALOS-2_39766_sensor",
                    "sat_start_time": "2026-01-01T00:00:10",
                    "sat_end_time": "2026-01-01T00:00:20",
                }],
                "unassigned_tasks": [],
            }
            metrics = {
                "completed_tasks": 1, "total_tasks": 1, "task_profit": 1.0,
                "task_completion_rate": 1.0, "balance_degree": 1.0,
                "timeliness_metric": 1.0, "runtime_efficiency": 0.01,
                "robustness_variance": None, "mip_gap": None,
            }
            self.assertTrue(database.finish_success(run_id, attempt, plan, metrics, 0.001))
            formal_before = compact_json(database.get_run(run_id))

            replay_endpoint = next(
                route.endpoint for route in app.routes
                if getattr(route, "path", None) == "/api/runs/{run_id}/visualization/replay"
            )
            # GET 兼容层只读 READY，不在未申请状态隐式生成侧车。
            with self.assertRaises(ReplayError) as caught:
                replay_endpoint(run_id)
            self.assertEqual(caught.exception.status,409)
            profile=Path(__file__).resolve().parents[1]/"replay_configs/display-profile-v2.json"
            first=build_replay_document(database.get_run(run_id),profile)
            second=build_replay_document(database.get_run(run_id),profile)
            self.assertEqual(compact_json(first), compact_json(second))
            replay = first
            manifest = replay["manifest"]
            self.assertEqual(manifest["geometry_version"], "wgs84-ray-ellipsoid-v1")
            self.assertEqual(manifest["resources"][0]["asset_id"], "landsat8-nasa-display")
            self.assertEqual(manifest["start_time"], "2026-01-01T00:00:00+00:00")
            self.assertEqual(replay["assignments"][0]["sat_start_time"], "2026-01-01T00:00:10+00:00")
            self.assertEqual(len(manifest["asset_manifest_sha256"]), 64)
            self.assertEqual(len(manifest["model_resources_sha256"]), 64)
            self.assertEqual(hashlib.sha256(scenario.read_bytes()).hexdigest(), scenario_before)
            self.assertEqual(compact_json(database.get_run(run_id)), formal_before)

            for static_path in (
                "/visualization/fixed-payload-state.js",
                "/visualization/fixed-payload-geometry.js",
                "/visualization/fixed-payload-view.js",
                "/visualization/trackpad-zoom.js",
                "/visualization/satellite-follow.js",
                "/visualization/replay-build-policy.js",
                "/visualization/assets/satellites/landsat8.glb",
            ):
                endpoint = next(
                    route.endpoint for route in app.routes
                    if getattr(route, "path", None) == static_path
                )
                response = endpoint()
                self.assertTrue(Path(response.path).is_file(), static_path)
            app.state.replay.close()


if __name__ == "__main__":
    unittest.main()
