"""回放后端的真实 HTTP、SQLite 与独立构建子进程闭环。"""

from __future__ import annotations

from certification_fixtures import storage_receipt

import asyncio
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eos_system.api import create_app
from eos_system.config import Settings
from eos_system.visualization import orbit_cache_file
from eos_system.contracts import RunConfig
from eos_system.storage import Database, SCHEMA, now


class _Response:
    def __init__(self, status_code: int, body: bytes, headers: dict):
        self.status_code, self.content, self.headers = status_code, body, headers
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class _DirectClient:
    """直接调用 ASGI，避免测试额外依赖可选的 httpx2。"""

    def __init__(self, app):
        self.app = app

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.app.state.replay.close()

    def _request(self, method: str, path: str, body=None, headers=None):
        async def call():
            messages = []
            payload = json.dumps(body).encode() if body is not None else b""
            received = False

            async def receive():
                nonlocal received
                if not received:
                    received = True
                    return {"type": "http.request", "body": payload, "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message):
                messages.append(message)

            scope = {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": path,
                "raw_path": path.encode(), "query_string": b"",
                "headers": ([(b"content-type", b"application/json")] if body is not None else [])
                           + [(key.lower().encode(), value.encode())
                              for key, value in (headers or {}).items()],
                "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 80),
            }
            await self.app(scope, receive, send)
            status = next(item["status"] for item in messages
                          if item["type"] == "http.response.start")
            output_headers = {key.decode().lower(): value.decode()
                              for item in messages if item["type"] == "http.response.start"
                              for key, value in item["headers"]}
            content = b"".join(item.get("body", b"") for item in messages
                               if item["type"] == "http.response.body")
            return _Response(status, content, output_headers)

        return asyncio.run(call())

    def get(self, path, headers=None):
        return self._request("GET", path, headers=headers)

    def post(self, path, json=None):
        return self._request("POST", path, body=json)

    def delete(self, path):
        return self._request("DELETE", path)


class ReplayBackendTests(unittest.TestCase):
    def test_v2_database_adds_replay_table_without_rewriting_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.sqlite3"
            with sqlite3.connect(path) as db:
                db.executescript(SCHEMA + "\nPRAGMA user_version=2;")
                db.execute(
                    "INSERT INTO runs(run_id,scenario_id,scenario_sha256,algorithm_id,"
                    "algorithm_version,config_json,config_sha256,status,created_at,"
                    "updated_at,queued_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("old", "fixture", "a" * 64, "completion_first", "baseline-1",
                     "{}", "b" * 64, "FAILED", now(), now(), now()),
                )
            Database(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertEqual(db.execute("SELECT status FROM runs WHERE run_id='old'").fetchone()[0],
                                 "FAILED")
                self.assertIsNotNone(db.execute(
                    "SELECT name FROM sqlite_master WHERE name='replay_artifacts'").fetchone())
            self.assertTrue(path.with_name(path.name + ".pre-v3.bak").is_file())

    def test_http_build_reuse_resources_and_delete(self):
        """单任务正式结果用固定轨道样本验证独立构建与观测阶段。"""
        project = Path(__file__).resolve().parent.parent
        original = json.loads(
            (project / "docs" / "Scenario_S1_Sats20_M500_T0.5d_dist0.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenarios = root / "scenarios"
            scenarios.mkdir()
            start = datetime(2025, 11, 18, 12, 0, tzinfo=timezone.utc)
            scene = {
                "scenario_id": "replay_fixture", "scenario_type": "test",
                "metadata": {"creation_time": start.replace(tzinfo=None).isoformat(),
                             "duration": 600.0, "time_step": 1.0},
                "satellites": [original["satellites"][0]], "missions": [original["missions"][0]],
                "observation_windows": [],
            }
            scene_path = scenarios / "replay_fixture.json"
            scene_path.write_text(json.dumps(scene), encoding="utf-8")
            digest = hashlib.sha256(scene_path.read_bytes()).hexdigest()
            settings = Settings(runtime_dir=root / "runtime", scenario_dir=scenarios,
                                replay_build_timeout_s=90)
            # 使用三个确定轨道样本测试接口/发布；Orekit 缓存未命中路径另做手动验证。
            cache = orbit_cache_file(settings, digest)
            cache.parent.mkdir(parents=True)
            epoch = start.isoformat().replace("+00:00", "Z")
            cache.write_text(json.dumps([
                {"id": "document", "clock": {"interval": epoch + "/" +
                 (start + timedelta(seconds=600)).isoformat().replace("+00:00", "Z")}},
                {"id": original["satellites"][0]["id"],
                 "position": {"epoch": epoch, "cartographicDegrees": [
                     0, 0, 0, 600000, 300, 2, 1, 600100, 600, 4, 2, 600200]}}
            ]), encoding="utf-8")
            database = Database(settings.database_path)
            run_id = str(uuid.uuid4())
            config = RunConfig(run_id=run_id, scenario_id="replay_fixture",
                               scenario_sha256=digest, scenario_path=str(scene_path),
                               algorithm_id="completion_first", algorithm_version="baseline-1",
                               created_at=now())
            database.enqueue(config, max_queued=8)
            attempt, _ = database.start_attempt(run_id)
            self.assertTrue(database.set_verifying(run_id, attempt))
            plan = {"scenario_id": "replay_fixture",
                    "start_time": start.isoformat(),
                    "end_time": (start + timedelta(seconds=600)).isoformat(),
                    "assignments": [{"task_id": original["missions"][0]["id"], "satellite_id": original["satellites"][0]["id"], "sensor_id": original["satellites"][0]["observation_capability"]["sensors"][0]["sensor_id"], "sat_start_time": (start + timedelta(seconds=100)).isoformat(), "sat_end_time": (start + timedelta(seconds=111)).isoformat()}], "unassigned_tasks": []}
            metrics = {"completed_tasks": 1, "total_tasks": 1, "task_profit": 5.0,
                       "task_completion_rate": 1.0, "balance_degree": 0.0,
                       "timeliness_metric": 0.0, "runtime_efficiency": 0.01,
                       "robustness_variance": None, "mip_gap": None}
            self.assertTrue(database.finish_success(run_id, attempt, plan, metrics, 0.001, certification=storage_receipt(database,run_id,plan)))
            original_plan_sha = database.get_replay_source(run_id)["plan_sha256"]
            with _DirectClient(create_app(settings)) as client:
                schedule = client.get(f"/api/runs/{run_id}/visualization/schedule")
                self.assertEqual(schedule.status_code, 200)
                self.assertEqual(schedule.json()["plan_sha256"], original_plan_sha)
                self.assertEqual(len(schedule.json()["assignments"]), 1)
                before = client.get(f"/api/runs/{run_id}/replay")
                self.assertEqual(before.json()["replay_status"], "NOT_REQUESTED")
                with database.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_artifacts").fetchone()[0], 0)
                response = client.post(f"/api/runs/{run_id}/replay",
                                       json={"replay_config_id": "geometry-illustration-v2"})
                self.assertEqual(response.status_code, 202, response.text)
                replay_id = response.json()["replay_id"]
                self.assertEqual(client.post(f"/api/runs/{run_id}/replay",
                    json={"replay_config_id": "geometry-illustration-v2"}).json()["replay_id"],
                    replay_id)
                state = None
                for _ in range(450):
                    state = client.get(f"/api/runs/{run_id}/replays/{replay_id}").json()
                    if state["replay_status"] != "BUILDING":
                        break
                    time.sleep(0.2)
                self.assertEqual(state["replay_status"], "READY", state)
                manifest = state["manifest"]
                self.assertEqual(manifest["plan_sha256"], original_plan_sha)
                self.assertEqual(manifest["attitude_source"], "geometry_pointing_illustration")
                self.assertEqual(set(manifest["resources"]),
                                 {"orbit_display", "attitude_samples", "segments",
                                  "diagnostics", "replay_config"})
                resource = client.get(manifest["resources"]["attitude_samples"]["url"])
                self.assertEqual(resource.status_code, 200)
                self.assertGreater(len(resource.json()["samples"]), 0)
                phases = client.get(manifest["resources"]["segments"]["url"]).json()["segments"]
                self.assertTrue(any(row["phase"] == "OBSERVING" and row["task_id"] == "M001" for row in phases))
                self.assertEqual(client.get(
                    manifest["resources"]["attitude_samples"]["url"],
                    headers={"If-None-Match": resource.headers["etag"]}).status_code, 304)
                self.assertEqual(client.get(
                    f"/api/runs/{run_id}/replays/{replay_id}/resources/unknown").status_code, 404)
                reused = client.post(f"/api/runs/{run_id}/replay",
                                     json={"replay_config_id": "geometry-illustration-v2"})
                self.assertEqual(reused.status_code, 200)
                self.assertEqual(reused.json()["replay_id"], replay_id)
                self.assertEqual(database.get_replay_source(run_id)["plan_sha256"], original_plan_sha)
                deleted = client.delete(f"/api/runs/{run_id}")
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertFalse((settings.replay_dir / replay_id).exists())
                self.assertIsNone(database.get_run(run_id))


if __name__ == "__main__":
    unittest.main()
