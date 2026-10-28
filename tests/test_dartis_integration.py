"""DARTIS registry and real loopback HTTP/spawn/SQLite integration tests.

Positive formal certification uses a test-only receipt. Real EOS-Bench-derived
input is exercised separately with unchanged production provenance gates.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from algorithms.deadline_insertion import DARTISParams, DARTISScheduler, VERSION
from eos_system.algorithm_registry import get_algorithm, list_algorithms, make_context
from eos_system.config import sha256_file
from eos_system.worker_process import read_proc
from input.scenario_splitter import split_scenario_file

ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE = Path("/mnt/f/EOS-Bench/output_s1/Sats1_M100_T7d_dist0.json")


def write_synthetic_scene(path):
    start = datetime(2026, 1, 1)
    scene = {
        "scenario_id": "dartis-synthetic-unit-only",
        "metadata": {"creation_time": start.isoformat(), "duration": 180},
        "satellites": [
            {"id": sid, "maneuverability_capability": {"maneuverability_type": "non_agile"},
             "satellite_specs": {"max_data_storage_GB": 20, "max_power_W": 20},
             "observation_capability": {"sensors": [
                 {"sensor_id": "cam", "data_rate_Mbps": 81.92,
                  "power_consumption_W": 1, "field_of_view_deg": 45}]}}
            for sid in ("S1", "S2")],
        "ground_stations": [], "missions": [], "observation_windows": []}
    from utils.continuous_exposure import window_generation_record
    scene["metadata"]["extra"] = {
        "window_generation": window_generation_record(1, 5, 60),
        "fixture_note": "SYNTHETIC_UNIT_TEST_ONLY_NOT_PHYSICAL_CERTIFICATION"}
    for i in range(3):
        tid = f"M{i+1}"
        scene["missions"].append({
            "id": tid, "priority": 3-i,
            "observation_requirement": {"duration_s": 10},
            "target_location": {"latitude": 1, "longitude": i+1, "altitude_km": 0}})
        for sid in ("S1", "S2"):
            begin = start + timedelta(seconds=10+40*i)
            scene["observation_windows"].append({
                "satellite_id": sid, "mission_id": tid, "sensor_id": "cam",
                "time_windows": [{"start_time": begin.isoformat(),
                    "end_time": (begin+timedelta(seconds=10)).isoformat(),
                    "orbit_number": 1, "time_step": 1,
                    "non_agile_data": {"roll_angle": 0, "pitch_angle": 0,
                                       "yaw_angle": 0}}]})
    path.write_text(json.dumps(scene), encoding="utf-8")


class _TestDARTIS(DARTISScheduler):
    def __init__(self, mode, marker):
        self._fake_now = [0.0]
        super().__init__(clock=(lambda: self._fake_now[0]) if mode == "budget"
                         else time.monotonic)
        self.mode, self.marker = mode, Path(marker)

    def _observe_round(self, version, opportunities):
        if self.mode == "budget" and version == 1:
            self._fake_now[0] = 10.0
            return
        if version != 0:
            return
        proc = read_proc(os.getpid())
        self.marker.write_text(json.dumps({
            "pid": os.getpid(), "starttime": proc.starttime,
            "boot_id": proc.boot_id}), encoding="ascii")
        if self.mode == "fault":
            raise RuntimeError("DARTIS_TEST_ONLY_FAULT")
        if self.mode == "slow":
            # The real Worker control thread receives cancel during this delay.
            time.sleep(0.6)


def _test_worker_entry(mode, marker, run_id, attempt, event_pipe, control_pipe):
    """Importable spawn target: only the child replaces the solver constructor."""
    from eos_system import worker_reference
    from eos_system import algorithm_registry
    spec = algorithm_registry.get_algorithm("dartis")
    algorithm_registry._SPECS["dartis"] = replace(
        spec, build=lambda context: _TestDARTIS(mode, marker))
    worker_reference.worker_main(run_id, attempt, event_pipe, control_pipe)


def make_test_app():
    """Uvicorn factory available only from tests/PYTHONPATH."""
    from eos_system import controller as controller_module
    from eos_system import verification
    from eos_system.api import create_app
    from eos_system.config import Settings
    mode = os.environ["EOS_DARTIS_TEST_MODE"]
    if os.environ.get("EOS_DARTIS_TEST_CERT") == "unit":
        from certification_fixtures import unit_certify
        verification.certify_schedule = unit_certify
    if mode in {"slow", "fault", "budget"}:
        controller_module.worker_main = partial(
            _test_worker_entry, mode, os.environ["EOS_DARTIS_MARKER"])
    return create_app(Settings(
        Path(os.environ["EOS_RUNTIME_DIR"]),
        Path(os.environ["EOS_SCENARIO_DIR"]),
        startup_timeout_s=10, transfer_timeout_s=5, stop_grace_s=1))


class DARTISRegistryTests(unittest.TestCase):
    def test_registry_metadata_context_and_strict_params(self):
        from eos_system.algorithm_registry import get_native_algorithm
        spec = get_native_algorithm("dartis")
        self.assertEqual(spec.version, VERSION)
        self.assertIs(spec.params_model, DARTISParams)
        self.assertIsInstance(spec.build(make_context(42, 5, {}, spec, {})),
                              DARTISScheduler)
        self.assertEqual(spec.public_info()["availability"], "ready")
        self.assertFalse(spec.public_info()["uses_initial_schedule"])
        self.assertIn("dartis", [row["algorithm_id"] for row in list_algorithms()])
        for params in ({"priority_mode": "bad"}, {"max_windows_per_task": True},
                       {"max_positions_per_window": 0}, {"unknown": 1}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                spec.parse_params(params)

    def test_fresh_import_is_acyclic(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import algorithms.deadline_insertion;"
             "assert 'eos_system.algorithm_registry' not in sys.modules;"
             "from eos_system.algorithm_registry import get_algorithm;"
             "from algorithms.deadline_insertion import VERSION;"
             "assert get_algorithm('dartis').version == VERSION + '+objective-v1'"],
            cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


class DARTISHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dartis-http-")
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.scenes = self.runtime / "scenarios"
        self.scenes.mkdir(parents=True)
        self.scene = self.scenes / "synthetic.json"
        write_synthetic_scene(self.scene)
        self.server = None
        self.marker = self.runtime / "worker-marker.json"
        self.cleanup_fallback = False

    def tearDown(self):
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=3)
            self.server.stderr.close()
        if self.marker.exists():
            identity = json.loads(self.marker.read_text(encoding="ascii"))
            current = read_proc(identity["pid"], identity["boot_id"])
            if current and current.starttime == identity["starttime"] and current.live:
                fd = os.pidfd_open(identity["pid"], 0)
                try:
                    again = read_proc(identity["pid"], identity["boot_id"])
                    if again and again.starttime == identity["starttime"] and again.live:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                        self.cleanup_fallback = True
                finally:
                    os.close(fd)
        self.temp.cleanup()
        self.assertFalse(self.cleanup_fallback, "test left a live Worker")

    def start_server(self, *, mode="normal", cert="unit"):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update({
            "EOS_RUNTIME_DIR": str(self.runtime),
            "EOS_SCENARIO_DIR": str(self.scenes),
            "EOS_DARTIS_TEST_MODE": mode,
            "EOS_DARTIS_TEST_CERT": cert,
            "EOS_DARTIS_MARKER": str(self.marker),
            "PYTHONPATH": str(ROOT / "tests") + os.pathsep + str(ROOT),
        })
        self.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn",
             "test_dartis_integration:make_test_app", "--factory",
             "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        until = time.monotonic() + 15
        while time.monotonic() < until:
            if self.server.poll() is not None:
                self.fail("server exited: " + self.server.stderr.read()[-1000:])
            try:
                if self.request("GET", "/api/health")[0] == 200:
                    return
            except OSError:
                time.sleep(.05)
        self.fail("loopback server did not start")

    def request(self, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        req = Request(self.base + path, data=body,
                      headers={"Content-Type": "application/json"} if body else {},
                      method=method)
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def submit(self, **overrides):
        payload = {"scenario_id": self.scene.stem, "algorithm_id": "dartis",
                   "time_budget_s": 5}
        payload.update(overrides)
        code, response = self.request("POST", "/api/runs", payload)
        self.assertEqual(code, 202, response)
        return response["run_id"]

    def wait_run(self, rid, *, timeout=25):
        until = time.monotonic() + timeout
        last = None
        while time.monotonic() < until:
            _, last = self.request("GET", f"/api/runs/{rid}")
            if last["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"}:
                return last
            time.sleep(.05)
        self.fail(f"run did not finish: {last}")

    def assert_reaped(self, row):
        self.assertEqual(len(row["attempts"]), 1)
        attempt = row["attempts"][0]
        self.assertIsNotNone(attempt["worker_pid"])
        self.assertFalse(Path(f"/proc/{attempt['worker_pid']}").exists())
        reaps = [e for e in row["events"] if e["event_type"] == "WORKER_REAP"]
        self.assertEqual(len(reaps), 1)
        self.assertTrue(reaps[0]["payload"]["identity_confirmed"])
        self.assertFalse(reaps[0]["payload"]["alive"])
        self.assertEqual(reaps[0]["payload"]["live_members"], 0)

    def test_real_http_worker_formal_transaction_synthetic_certificate_only(self):
        self.start_server()
        code, listing = self.request("GET", "/api/algorithms")
        self.assertEqual(code, 200)
        self.assertIn("dartis", [x["algorithm_id"] for x in listing["items"]])
        code, _ = self.request("POST", "/api/runs", {
            "scenario_id": self.scene.stem, "algorithm_id": "dartis",
            "algorithm_params": {"priority_mode": "bad"}})
        self.assertEqual(code, 422)
        before = sha256_file(self.scene)
        rid = self.submit(algorithm_params={"priority_mode": "llf"})
        row = self.wait_run(rid)
        self.assertEqual(row["status"], "SUCCEEDED", row.get("error"))
        self.assertEqual(row["metrics"]["completed_tasks"], 3)
        self.assertEqual(len(row["plan"]["assignments"]), 3)
        self.assertEqual(row["continuous_certification"]["predicate"], "UNIT_TEST_ONLY")
        self.assertEqual(row["config"]["algorithm_version"], VERSION + "+objective-v1")
        self.assertEqual(row["attempts"][0]["exit_code"], 0)
        self.assertNotEqual(row["attempts"][0]["worker_pid"], self.server.pid)
        self.assert_reaped(row)
        with sqlite3.connect(self.runtime / "results.sqlite3") as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM plans WHERE run_id=?", (rid,)).fetchone()[0], 1)
        self.assertEqual(sha256_file(self.scene), before)

    def test_real_http_budget_return_commits_partial_plan_test_clock_only(self):
        self.start_server(mode="budget")
        rid = self.submit()
        row = self.wait_run(rid)
        self.assertEqual(row["status"], "SUCCEEDED", row.get("error"))
        self.assertEqual(row["metrics"]["completed_tasks"], 1)
        self.assertEqual(len(row["plan"]["assignments"]), 1)
        self.assertEqual(row["continuous_certification"]["predicate"], "UNIT_TEST_ONLY")
        self.assert_reaped(row)

    def test_real_http_running_cancel_dartis(self):
        self.start_server(mode="slow")
        rid = self.submit()
        until = time.monotonic() + 10
        while time.monotonic() < until and not self.marker.exists():
            time.sleep(.02)
        self.assertTrue(self.marker.exists(), "DARTIS did not enter solve")
        code, response = self.request("POST", f"/api/runs/{rid}/cancel")
        self.assertEqual(code, 202, response)
        row = self.wait_run(rid)
        self.assertEqual(row["status"], "CANCELLED", row.get("error"))
        self.assertIsNone(row["plan"])
        self.assertIn("cancel_ack", [e["event_type"] for e in row["events"]])
        self.assertNotIn("candidate_result", [e["event_type"] for e in row["events"]])
        self.assert_reaped(row)

    def test_real_http_solver_exception_is_failed(self):
        self.start_server(mode="fault")
        rid = self.submit()
        row = self.wait_run(rid)
        self.assertEqual(row["status"], "FAILED", row.get("error"))
        self.assertEqual(row["error"]["code"], "RuntimeError")
        self.assertIn("DARTIS_TEST_ONLY_FAULT", row["error"]["message"])
        self.assertIsNone(row["plan"])
        self.assert_reaped(row)

    def test_real_eos_bench_derived_scene_without_certification_bypass(self):
        if not REAL_SOURCE.is_file():
            self.skipTest("read-only EOS-Bench source unavailable")
        before = sha256_file(REAL_SOURCE)
        derived = split_scenario_file(
            REAL_SOURCE, num_missions=30, start_offset="0h", duration="24h",
            search_root=REAL_SOURCE.parent, out_dir=self.scenes,
            out_name="dartis-derived", seed=20260927)
        self.scene = Path(derived)
        self.start_server(cert="none")
        rid = self.submit(execution_mode="planning_preview")
        row = self.wait_run(rid)
        # The legacy windows can fail a real Orekit visibility check. If
        # Orekit is unavailable, preview must also reject the candidate.
        events = [event["event_type"] for event in row["events"]]
        self.assertIn("candidate_result", events)
        self.assertEqual(row["status"], "FAILED", row.get("error"))
        self.assertEqual(row["error"]["code"], "PREVIEW_REJECTED")
        message = row["error"]["message"]
        self.assertIn("ExposureStatus.REJECTED: PREVIEW_PHYSICS_CHECK_FAILED:", message)
        if '"reason": "NONVISIBLE_EXPOSURE_START"' in message:
            self.assertIn('"task_id": "M025"', message)
            self.assertIn('"satellite_id": "ALOS-2_39766"', message)
            self.assertIn('"sampled_boundaries_status": "FAIL"', message)
        else:
            self.assertIn('"reason": "PHYSICS_UNAVAILABLE"', message)
            self.assertIn('"sampled_boundaries_status": "UNAVAILABLE"', message)
        self.assertIsNone(row["plan"])
        self.assertIsNone(row["metrics"])
        self.assertEqual(row["attempts"][0]["outcome"], "FAILED")
        self.assertEqual(row["attempts"][0]["exit_code"], 0)
        self.assertNotIn("PREVIEW_VALIDATED", events)
        self.assertNotIn("CONTINUOUS_CERTIFIED", events)
        self.assertNotIn("SUCCEEDED", events)
        with sqlite3.connect(self.runtime / "results.sqlite3") as db:
            self.assertEqual(db.execute(
                "SELECT status,error_code FROM runs WHERE run_id=?", (rid,)
            ).fetchone(), ("FAILED", "PREVIEW_REJECTED"))
            self.assertEqual(db.execute(
                "SELECT outcome,error_code FROM run_attempts WHERE run_id=?", (rid,)
            ).fetchone(), ("FAILED", "PREVIEW_REJECTED"))
            for table in ("plans", "assignments", "metrics"):
                with self.subTest(table=table):
                    self.assertEqual(db.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (rid,)
                    ).fetchone()[0], 0)
        self.assert_reaped(row)
        self.assertEqual(sha256_file(REAL_SOURCE), before)


if __name__ == "__main__":
    unittest.main()
