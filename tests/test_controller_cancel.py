"""W2-A Controller 取消测试；求解器仅是临时场景上的 spawn 测试桩。"""

import asyncio
import hashlib
import json
import multiprocessing as mp
import os
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from unittest.mock import patch

from algorithms.objectives import ObjectiveWeights
from eos_system import controller as controller_module
from eos_system import worker_reference as worker
from eos_system.algorithm_registry import CompletionParams, SolveContext
from eos_system.api import create_app
from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.storage import Database
from schedulers.constraint_model import Schedule
from schedulers.scenario_loader import load_scheduling_problem_from_json


class _SpawnSolver:
    def __init__(self, mode, entered, observed, release):
        self.mode, self.entered, self.observed, self.release = mode, entered, observed, release

    def solve(self, problem, constraints, context):
        self.entered.set()
        if self.mode in {"normal", "stale_event"}:
            return Schedule()
        if self.mode == "uncooperative":
            time.sleep(5)
            return Schedule()
        if self.mode == "held_candidate":
            if not self.release.wait(7):
                raise RuntimeError("测试候选释放超时")
            return Schedule()
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            if context.is_cancelled():
                self.observed.set()
                return Schedule()
            time.sleep(0.01)
        raise RuntimeError("测试求解器未观察到取消")


def _spawn_test_worker(mode, entered, observed, release, startup_gate,
                       run_id, attempt, event_pipe, control_pipe):
    """顶层可导入的真实 spawn 入口；替身只在子进程中安装。"""
    if mode == "early_exit":
        os._exit(17)
    if mode == "exit_no_ack":
        worker.send_message(event_pipe, {
            "protocol_version": 1, "run_id": run_id, "attempt": attempt,
            "seq": 1, "kind": "started",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"worker_pid": os.getpid()},
        })
        worker.receive_message(control_pipe)
        entered.set()
        release.wait(7)
        control_pipe.close()
        event_pipe.close()
        return
    if mode == "duplicate_ack":
        def report(seq, kind, payload):
            worker.send_message(event_pipe, {
                "protocol_version": 1, "run_id": run_id, "attempt": attempt,
                "seq": seq, "kind": kind,
                "sent_at": datetime.now(timezone.utc).isoformat(), "payload": payload,
            })

        report(1, "started", {"worker_pid": os.getpid()})
        worker.receive_message(control_pipe)  # 旧 start
        entered.set()
        command = worker.receive_message(control_pipe)
        if (command["protocol_version"] == 1 and command["run_id"] == run_id
                and command["attempt"] == attempt and command["seq"] == 1
                and command["kind"] == "cancel" and command["payload"] == {}):
            observed.set()
        report(2, "cancel_ack", {"accepted": True})
        report(2, "cancel_ack", {"accepted": True})
        control_pipe.close()
        event_pipe.close()
        return
    if mode == "closed_event":
        event_pipe.close()
        control_pipe.close()
        return
    if not startup_gate.wait(7):
        os._exit(18)
    if mode == "stale_event":
        worker.send_message(event_pipe, {
            "protocol_version": 1, "run_id": run_id, "attempt": attempt + 1,
            "seq": 1, "kind": "cancel_ack",
            "sent_at": datetime.now(timezone.utc).isoformat(), "payload": {"accepted": True},
        })

    def prepare_test_solver(config):
        problem = load_scheduling_problem_from_json(config.scenario_path)
        context = SolveContext(config.seed, config.time_budget_s, ObjectiveWeights(), CompletionParams())
        return _SpawnSolver(mode, entered, observed, release), problem, None, context

    with patch.object(worker, "prepare", side_effect=prepare_test_solver):
        worker.worker_main(run_id, attempt, event_pipe, control_pipe)


class ControllerCancelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        scenario_dir = root / "scenarios"
        scenario_dir.mkdir()
        self.env_patch = patch.dict(os.environ, {
            "EOS_RUNTIME_DIR": str(root), "EOS_SCENARIO_DIR": str(scenario_dir),
        })
        self.env_patch.start()
        self.settings = Settings(runtime_dir=root, scenario_dir=scenario_dir,
                                 startup_timeout_s=5, transfer_timeout_s=5, stop_grace_s=0.5)
        self.scene = scenario_dir / "fixture.json"
        raw = json.dumps({"scenario_id": "fixture", "metadata": {
            "creation_time": "2026-01-01T00:00:00", "duration": 60,
        }, "satellites": [], "ground_stations": [], "missions": []}).encode()
        self.scene.write_bytes(raw)
        self.digest = hashlib.sha256(raw).hexdigest()
        self.database = Database(self.settings.database_path)
        self.ctx = mp.get_context("spawn")
        self.entered, self.observed = self.ctx.Event(), self.ctx.Event()
        self.release, self.startup_gate = self.ctx.Event(), self.ctx.Event()
        self.release.set()
        self.startup_gate.set()
        self.run_id = str(uuid.uuid4())
        self.controller = None
        self.patch = None

    def tearDown(self):
        if self.controller is not None:
            self.controller.stop()
        if self.patch is not None:
            self.patch.stop()
        self.env_patch.stop()
        # 兜底只针对本测试 run_id 命名的直接 spawn 子进程。
        lingering = [child for child in mp.active_children()
                     if child.name == f"eos-worker-{self.run_id[:8]}"]
        for child in lingering:
            child.terminate()
            child.join(timeout=1)
            if child.is_alive():
                child.kill()
                child.join(timeout=1)
        self.assertFalse(lingering, "Controller 留下了仍活着的测试 Worker")

    def configure_worker(self, mode):
        target = partial(_spawn_test_worker, mode, self.entered, self.observed,
                         self.release, self.startup_gate)
        self.patch = patch.object(controller_module, "worker_main", target)
        self.patch.start()

    def enqueue(self):
        config = RunConfig(
            run_id=self.run_id, scenario_id="fixture", scenario_sha256=self.digest,
            scenario_path=str(self.scene), algorithm_id="completion_first",
            algorithm_version="baseline-1", time_budget_s=8,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.database.enqueue(config, max_queued=8)

    def start_controller(self):
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()

    def wait_status(self, expected, timeout=9):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.database.get_status(self.run_id)
            if status and status["status"] == expected:
                return status
            time.sleep(0.02)
        self.fail(f"等待 {expected} 超时；当前为 {self.database.get_status(self.run_id)}")

    def worker_events(self):
        return [item for item in self.database.get_run(self.run_id)["events"]
                if item["source"] == "worker"]

    def test_real_spawn_controller_sends_cancel_and_records_ack(self):
        self.configure_worker("cooperative")
        self.enqueue()
        self.start_controller()
        self.assertTrue(self.entered.wait(5))
        self.assertEqual(self.database.request_cancel(self.run_id)[1], True)
        self.wait_status("CANCELLED")
        self.assertTrue(self.observed.is_set())
        record = self.database.get_run(self.run_id)
        kinds = [event["event_type"] for event in self.worker_events()]
        self.assertEqual(kinds.count("cancel_ack"), 1)
        self.assertNotIn("candidate_result", kinds)
        self.assertIsNone(record["plan"])
        self.assertEqual(record["attempts"][0]["outcome"], "CANCELLED")

    def test_cancel_immediately_after_attempt_starts(self):
        self.startup_gate.clear()
        self.configure_worker("cooperative")
        self.enqueue()
        self.start_controller()
        self.wait_status("RUNNING")
        self.database.request_cancel(self.run_id)
        self.startup_gate.set()
        self.wait_status("CANCELLED")
        self.assertEqual([e["event_type"] for e in self.worker_events()].count("cancel_ack"), 1)
        self.assertIsNone(self.database.get_run(self.run_id)["plan"])

    def test_repeated_cancel_produces_one_ack_and_one_terminal_event(self):
        self.configure_worker("cooperative")
        self.enqueue()
        self.start_controller()
        self.assertTrue(self.entered.wait(5))
        self.database.request_cancel(self.run_id)
        self.database.request_cancel(self.run_id)
        self.wait_status("CANCELLED")
        self.assertEqual([e["event_type"] for e in self.worker_events()].count("cancel_ack"), 1)
        events = self.database.get_run(self.run_id)["events"]
        self.assertEqual([e["event_type"] for e in events].count("CANCELLED"), 1)
        self.assertEqual(self.database.request_cancel(self.run_id), ("CANCELLED", False))

    def test_ack_does_not_finish_run_before_worker_exits(self):
        self.configure_worker("uncooperative")
        self.enqueue()
        self.start_controller()
        self.assertTrue(self.entered.wait(5))
        self.database.request_cancel(self.run_id)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(e["event_type"] == "cancel_ack" for e in self.worker_events()):
                break
            time.sleep(0.02)
        else:
            self.fail("未收到 cancel_ack")
        self.assertEqual(self.database.get_status(self.run_id)["status"], "RUNNING")
        self.wait_status("CANCELLED")
        self.assertIsNone(self.database.get_run(self.run_id)["plan"])

    def test_worker_exit_without_ack_still_finishes_cancel(self):
        self.release.clear()
        self.configure_worker("exit_no_ack")
        self.enqueue()
        self.start_controller()
        self.assertTrue(self.entered.wait(5))
        self.database.request_cancel(self.run_id)
        self.release.set()
        self.wait_status("CANCELLED")
        self.assertNotIn("cancel_ack", [e["event_type"] for e in self.worker_events()])

    def test_complete_cancel_envelope_and_duplicate_ack(self):
        self.configure_worker("duplicate_ack")
        self.enqueue()
        self.start_controller()
        self.assertTrue(self.entered.wait(5))
        self.database.request_cancel(self.run_id)
        self.wait_status("CANCELLED")
        self.assertTrue(self.observed.is_set(), "Controller 未发送 W1 要求的 cancel 信封")
        self.assertEqual([e["event_type"] for e in self.worker_events()].count("cancel_ack"), 1)

    def test_closed_event_pipe_does_not_wait_forever(self):
        self.configure_worker("closed_event")
        self.enqueue()
        started = time.monotonic()
        self.start_controller()
        self.wait_status("FAILED")
        self.assertLess(time.monotonic() - started, 6)

    def test_early_worker_exit_does_not_wait_forever(self):
        self.configure_worker("early_exit")
        self.enqueue()
        started = time.monotonic()
        self.start_controller()
        self.wait_status("FAILED")
        self.assertLess(time.monotonic() - started, 6)

    def test_candidate_and_cancel_race_cannot_commit_success(self):
        self.release.clear()
        self.configure_worker("held_candidate")
        self.enqueue()
        self.start_controller()
        self.assertTrue(self.entered.wait(5))
        self.database.request_cancel(self.run_id)
        self.release.set()
        self.wait_status("CANCELLED")
        self.assertIsNone(self.database.get_run(self.run_id)["plan"])

    def test_cancel_during_real_spawn_candidate_verification_blocks_commit(self):
        self.configure_worker("normal")
        self.enqueue()
        entered_verify, release_verify = threading.Event(), threading.Event()
        actual_verify = controller_module.verify_candidate

        def delayed_verify(config, candidate, runtime):
            entered_verify.set()
            if not release_verify.wait(6):
                raise RuntimeError("测试核验释放超时")
            return actual_verify(config, candidate, runtime)

        try:
            with patch.object(controller_module, "verify_candidate", side_effect=delayed_verify):
                self.start_controller()
                self.assertTrue(entered_verify.wait(5))
                self.assertEqual(self.database.get_status(self.run_id)["status"], "VERIFYING")
                self.database.request_cancel(self.run_id)
                release_verify.set()
                self.wait_status("CANCELLED")
        finally:
            release_verify.set()
        self.assertIsNone(self.database.get_run(self.run_id)["plan"])

    def test_normal_success_path_still_commits_verified_plan(self):
        self.configure_worker("normal")
        self.enqueue()
        self.start_controller()
        self.wait_status("SUCCEEDED")
        record = self.database.get_run(self.run_id)
        self.assertIsNotNone(record["plan"])
        self.assertEqual([e["event_type"] for e in self.worker_events()].count("candidate_result"), 1)
        self.assertEqual(self.database.request_cancel(self.run_id), ("SUCCEEDED", False))

    def test_unmodified_reference_worker_success_path(self):
        """实际注册表和旧 start 经 Controller 完成空场景闭环。"""
        self.enqueue()
        self.start_controller()
        self.wait_status("SUCCEEDED")
        record = self.database.get_run(self.run_id)
        self.assertIsNotNone(record["plan"])
        self.assertEqual(record["attempts"][0]["outcome"], "SUCCEEDED")

    def test_stale_attempt_ack_is_ignored(self):
        self.configure_worker("stale_event")
        self.enqueue()
        self.start_controller()
        self.wait_status("SUCCEEDED")
        events = self.worker_events()
        self.assertFalse(any(e["attempt_no"] == 2 for e in events))
        self.assertEqual(self.database.get_run(self.run_id)["attempt"], 1)

    def test_http_cancel_uses_existing_route_and_temporary_database(self):
        self.configure_worker("cooperative")
        app = create_app(self.settings)

        async def request(method, path, body=None):
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

            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                     "method": method, "scheme": "http", "path": path,
                     "raw_path": path.encode(), "query_string": b"",
                     "headers": [(b"content-type", b"application/json")],
                     "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 8765)}
            await app(scope, receive, send)
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            data = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
            return status, json.loads(data)

        async def scenario():
            async with app.router.lifespan_context(app):
                status, submitted = await request("POST", "/api/runs", {
                    "scenario_id": "fixture", "algorithm_id": "completion_first",
                    "time_budget_s": 8,
                })
                self.assertEqual(status, 202)
                self.run_id = submitted["run_id"]
                self.assertTrue(await asyncio.to_thread(self.entered.wait, 5))
                status, cancelled = await request("POST", f"/api/runs/{self.run_id}/cancel")
                self.assertEqual(status, 202)
                self.assertTrue(cancelled["cancel_requested"])
                await asyncio.to_thread(self.wait_status, "CANCELLED")

        asyncio.run(scenario())
        self.assertEqual([e["event_type"] for e in self.worker_events()].count("cancel_ack"), 1)
        self.assertIsNone(self.database.get_run(self.run_id)["plan"])


if __name__ == "__main__":
    unittest.main()
