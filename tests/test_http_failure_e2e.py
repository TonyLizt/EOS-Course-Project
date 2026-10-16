"""Real loopback HTTP failure paths with an isolated, test-only spawned Worker."""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from algorithms.objectives import ObjectiveWeights
from eos_system import controller as controller_module
from eos_system import worker_reference as worker
from eos_system.algorithm_registry import CompletionParams, SolveContext
from eos_system.api import create_app
from eos_system.config import Settings
from eos_system.worker_process import read_proc
from schedulers.constraint_model import Schedule
from schedulers.scenario_loader import load_scheduling_problem_from_json


class _TestSolver:
    """A bounded test stub; its output is not a scheduling experiment result."""

    def __init__(self, mode, marker):
        self.mode = mode
        self.marker = Path(marker)

    def solve(self, problem, constraints, context):
        self.marker.write_text(str(os.getpid()), encoding="ascii")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.mode == "cooperative" and context.is_cancelled():
                return Schedule()
            time.sleep(0.01)
        return Schedule()


def _test_worker_entry(mode, marker, run_id, attempt, event_pipe, control_pipe):
    """Importable spawn target; patching occurs inside the actual child only."""
    if mode == "crash":
        os.setsid()

        def report(seq, kind, payload):
            worker.send_message(event_pipe, {
                "protocol_version": 1, "run_id": run_id, "attempt": attempt,
                "seq": seq, "kind": kind,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            })

        report(1, "started", {"worker_pid": os.getpid(), "pgid": os.getpgrp()})
        worker.receive_message(control_pipe)
        report(2, "heartbeat", {"phase": "SEARCHING"})
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(8)"],
            close_fds=True,
        )
        identity = read_proc(child.pid)
        if identity is None:
            os._exit(22)
        Path(marker).write_text(json.dumps({
            "pid": child.pid, "starttime": identity.starttime, "boot_id": identity.boot_id,
        }), encoding="utf-8")
        time.sleep(0.2)
        os._exit(23)

    def test_prepare(config):
        problem = load_scheduling_problem_from_json(Path(config.scenario_path))
        context = SolveContext(config.seed, config.time_budget_s,
                               ObjectiveWeights(), CompletionParams())
        return _TestSolver(mode, marker), problem, None, context

    with patch.object(worker, "prepare", side_effect=test_prepare):
        worker.worker_main(run_id, attempt, event_pipe, control_pipe)


def make_test_app():
    """Uvicorn factory used only by this test module, never by production startup."""
    mode = os.environ["EOS_HTTP_TEST_MODE"]
    runtime = Path(os.environ["EOS_RUNTIME_DIR"])
    controller_module.worker_main = partial(
        _test_worker_entry, mode, str(runtime / "worker-marker.json"))
    settings = Settings(runtime_dir=runtime,
                        scenario_dir=Path(os.environ["EOS_SCENARIO_DIR"]),
                        startup_timeout_s=5, transfer_timeout_s=0.25,
                        stop_grace_s=0.3)
    return create_app(settings)


class HttpFailureE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eos-http-failure-")
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.scenarios = self.runtime / "scenarios"
        self.scenarios.mkdir(parents=True)
        raw = json.dumps({
            "scenario_id": "fixture",
            "metadata": {"creation_time": "2026-01-01T00:00:00", "duration": 60},
            "satellites": [], "ground_stations": [], "missions": [],
        }).encode()
        (self.scenarios / "fixture.json").write_bytes(raw)
        self.scene_sha256 = hashlib.sha256(raw).hexdigest()
        self.server = None
        self.mode = None
        self.child_fallback_used = False

    def tearDown(self):
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=3)
            self.server.stderr.close()
        marker = self.runtime / "worker-marker.json"
        if self.mode == "crash" and marker.exists():
            info = json.loads(marker.read_text(encoding="utf-8"))
            current = read_proc(info["pid"], info["boot_id"])
            if current and current.starttime == info["starttime"] and current.live:
                fd = os.pidfd_open(info["pid"], 0)
                try:
                    current = read_proc(info["pid"], info["boot_id"])
                    if current and current.starttime == info["starttime"] and current.live:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                        self.child_fallback_used = True
                finally:
                    os.close(fd)
        self.temp.cleanup()
        self.assertFalse(self.child_fallback_used,
                         "Controller left a live trusted test descendant")

    def start_server(self, mode):
        self.mode = mode
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update({
            "EOS_RUNTIME_DIR": str(self.runtime),
            "EOS_SCENARIO_DIR": str(self.scenarios),
            "EOS_HTTP_TEST_MODE": mode,
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": str(Path(__file__).resolve().parent) + os.pathsep
                          + str(Path(__file__).resolve().parent.parent),
        })
        self.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn",
             "test_http_failure_e2e:make_test_app", "--factory",
             "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                self.fail(f"test server exited: {self.server.stderr.read()[-1000:]}")
            try:
                status, _ = self.request("GET", "/api/health")
                if status == 200:
                    self.fd_baseline = len(os.listdir(f"/proc/{self.server.pid}/fd"))
                    return
            except OSError:
                time.sleep(0.05)
        self.fail("test server did not become healthy")

    def request(self, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        with urlopen(Request(self.base + path, data=body, headers=headers,
                             method=method), timeout=3) as response:
            return response.status, json.loads(response.read())

    def submit(self, budget=3):
        status, created = self.request("POST", "/api/runs", {
            "scenario_id": "fixture", "algorithm_id": "completion_first",
            "time_budget_s": budget,
        })
        self.assertEqual(status, 202)
        return created["run_id"]

    def wait_for(self, predicate, run_id, timeout=9):
        deadline = time.monotonic() + timeout
        detail = None
        while time.monotonic() < deadline:
            _, detail = self.request("GET", f"/api/runs/{run_id}")
            if predicate(detail):
                return detail
            time.sleep(0.03)
        self.fail(f"timed out waiting for HTTP run condition: {detail}")

    def assert_record(self, detail, status, error_code, exit_code=None):
        self.assertEqual(detail["status"], status, detail)
        self.assertEqual(detail["error"]["code"], error_code)
        self.assertIsNone(detail["plan"])
        self.assertIsNone(detail["metrics"])
        self.assertEqual(detail["attempt"], 1)
        attempt = detail["attempts"][0]
        self.assertEqual(attempt["attempt_no"], 1)
        self.assertEqual(attempt["outcome"], status)
        self.assertIsNotNone(attempt["worker_pid"])
        self.assertIsNotNone(attempt["exit_code"])
        if exit_code is not None:
            self.assertEqual(attempt["exit_code"], exit_code)
        reap = [event for event in detail["events"]
                if event["event_type"] == "WORKER_REAP"]
        self.assertEqual(len(reap), 1)
        self.assertFalse(reap[0]["payload"]["alive"])
        self.assertEqual(reap[0]["payload"]["live_members"], 0)
        self.assertTrue(reap[0]["payload"]["identity_confirmed"])
        self.assertFalse(reap[0]["payload"]["scan_limited"])
        self.assertFalse(Path(f"/proc/{attempt['worker_pid']}").exists())
        # After the attempt, Controller should have closed both Pipe endpoints.
        time.sleep(0.1)
        self.assertLessEqual(len(os.listdir(f"/proc/{self.server.pid}/fd")),
                             self.fd_baseline + 2)
        import sqlite3
        with sqlite3.connect(self.runtime / "results.sqlite3") as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM plans WHERE run_id=?", (detail["run_id"],)
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM run_attempts WHERE run_id=?", (detail["run_id"],)
            ).fetchone()[0], 1)

    def test_real_http_running_cancel_reaps_worker_without_plan(self):
        self.start_server("cooperative")
        run_id = self.submit()
        marker = self.runtime / "worker-marker.json"
        self.wait_for(lambda _: marker.exists(), run_id)
        status, response = self.request("POST", f"/api/runs/{run_id}/cancel")
        self.assertEqual(status, 202)
        self.assertTrue(response["cancel_requested"])
        detail = self.wait_for(
            lambda row: row["status"] in {"CANCELLED", "FAILED", "TIMED_OUT"}, run_id)
        self.assert_record(detail, "CANCELLED", "CANCELLED", 0)
        events = [event["event_type"] for event in detail["events"]]
        self.assertEqual(events.count("cancel_ack"), 1)
        self.assertNotIn("candidate_result", events)

    def test_real_http_search_timeout_reaps_slow_solver(self):
        self.start_server("slow")
        run_id = self.submit(budget=0.25)
        detail = self.wait_for(
            lambda row: row["status"] in {"CANCELLED", "FAILED", "TIMED_OUT"}, run_id)
        self.assert_record(detail, "TIMED_OUT", "ALGORITHM_TIMEOUT")
        events = [event["event_type"] for event in detail["events"]]
        self.assertIn("cancel_ack", events)
        self.assertNotIn("candidate_result", events)

    def test_real_http_crash_reaps_trusted_descendant(self):
        self.start_server("crash")
        run_id = self.submit()
        detail = self.wait_for(
            lambda row: row["status"] in {"CANCELLED", "FAILED", "TIMED_OUT"}, run_id)
        self.assert_record(detail, "FAILED", "IPC_DISCONNECTED", 23)
        events = [event["event_type"] for event in detail["events"]]
        self.assertIn("started", events)
        self.assertIn("WORKER_REAP", events)
        info = json.loads((self.runtime / "worker-marker.json").read_text(encoding="utf-8"))
        current = read_proc(info["pid"], info["boot_id"])
        self.assertTrue(current is None or not current.live
                        or current.starttime != info["starttime"])


if __name__ == "__main__":
    unittest.main()
