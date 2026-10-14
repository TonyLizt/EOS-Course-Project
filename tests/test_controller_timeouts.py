"""W2-B 隔离故障测试；所有异常行为由真实 spawn 子进程产生。"""

import hashlib
import json
import multiprocessing as mp
import os
import signal
import struct
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from unittest.mock import patch

from eos_system import controller as controller_module
from eos_system import worker_reference as worker
from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.storage import Database


def _fault_worker(mode, observed, run_id, attempt, event_pipe, control_pipe):
    """真实子进程中的有界故障桩，不作为正式算法结果。"""
    os.setsid()

    def event(seq, kind, payload):
        worker.send_message(event_pipe, {
            "protocol_version": 1, "run_id": run_id, "attempt": attempt,
            "seq": seq, "kind": kind,
            "sent_at": datetime.now(timezone.utc).isoformat(), "payload": payload,
        })

    event(1, "started", {"worker_pid": os.getpid()})
    if mode == "blocked_start":
        time.sleep(6)  # 已确认独立 Session，但故意不读取 start Pipe。
        return
    worker.receive_message(control_pipe)
    if mode == "crash":
        os._exit(23)
    if mode == "loading_hang":
        event(2, "heartbeat", {"phase": "LOADING"})
        time.sleep(6)
        return
    if mode == "partial_frame":
        os.write(event_pipe.fileno(), struct.pack("!i", 100) + b'{"protocol_version":1')
        time.sleep(6)
        return
    if mode == "partial_close":
        os.write(event_pipe.fileno(), struct.pack("!i", 100) + b'{"protocol_version":1')
        return
    if mode == "oversize_frame":
        os.write(event_pipe.fileno(), struct.pack("!i", worker.MAX_MESSAGE_BYTES + 1))
        time.sleep(6)
        return
    if mode == "malformed_json":
        event_pipe.send_bytes(b"{")
        return
    if mode == "zero_length_frame":
        event_pipe.send_bytes(b"")
        time.sleep(6)
        return
    if mode in {"invalid_version", "invalid_fields"}:
        message = {"protocol_version": 2 if mode == "invalid_version" else 1,
                   "run_id": run_id, "attempt": attempt, "seq": 2,
                   "kind": "heartbeat", "sent_at": datetime.now(timezone.utc).isoformat(),
                   "payload": {"phase": "SEARCHING"}}
        if mode == "invalid_fields":
            message.pop("seq")
        event_pipe.send_bytes(json.dumps(message).encode())
        return
    if mode == "failed_event":
        event(2, "failed", {"code": "TEST_FAILURE", "message": "测试故障"})
        return
    if mode in {"candidate_hang", "crash_after_candidate"}:
        event(2, "heartbeat", {"phase": "SEARCHING"})
        event(3, "candidate_result", {"plan": {"scenario_id": "fixture"},
                                       "algorithm_runtime_s": 0.01})
        if mode == "crash_after_candidate":
            os._exit(24)
        time.sleep(6)
        return
    if mode == "repeat_candidate":
        event(2, "heartbeat", {"phase": "SEARCHING"})
        deadline = time.monotonic() + 6
        seq = 3
        while time.monotonic() < deadline:
            event(seq, "candidate_result", {"plan": {"scenario_id": "fixture", "candidate_no": seq},
                                             "algorithm_runtime_s": 0.01})
            seq += 1
            time.sleep(0.04)
        return
    if mode == "same_seq_candidate":
        event(2, "heartbeat", {"phase": "SEARCHING"})
        payload = {"plan": {"scenario_id": "fixture"}, "algorithm_runtime_s": 0.01}
        event(3, "candidate_result", payload)
        event(3, "candidate_result", payload)
        time.sleep(6)
        return
    if mode in {"search_hang", "repeat_searching"}:
        event(2, "heartbeat", {"phase": "SEARCHING"})
        deadline = time.monotonic() + 6
        seq = 3
        while time.monotonic() < deadline:
            if control_pipe.poll(0.02):
                command = worker.receive_message(control_pipe)
                if command["kind"] == "cancel":
                    observed.set()
            if mode == "repeat_searching":
                event(seq, "heartbeat", {"phase": "SEARCHING"})
                seq += 1
                time.sleep(0.06)
        return
    if mode == "ignore_term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        event(2, "heartbeat", {"phase": "SEARCHING"})
        time.sleep(6)
        return
    raise AssertionError(f"未知测试模式：{mode}")


class ControllerTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        scenarios = root / "scenarios"
        scenarios.mkdir()
        self.env = patch.dict(os.environ, {"EOS_RUNTIME_DIR": str(root),
                                        "EOS_SCENARIO_DIR": str(scenarios)})
        self.env.start()
        self.settings = Settings(runtime_dir=root, scenario_dir=scenarios,
                                 startup_timeout_s=2, transfer_timeout_s=0.3,
                                 stop_grace_s=0.2)
        scene = scenarios / "fixture.json"
        raw = json.dumps({"scenario_id": "fixture", "metadata": {
            "creation_time": "2026-01-01T00:00:00", "duration": 60,
        }, "satellites": [], "ground_stations": [], "missions": []}).encode()
        scene.write_bytes(raw)
        self.scene, self.digest = scene, hashlib.sha256(raw).hexdigest()
        self.database = Database(self.settings.database_path)
        self.run_id = str(uuid.uuid4())
        self.observed = mp.get_context("spawn").Event()
        self.controller = None
        self.worker_patch = None

    def tearDown(self):
        if self.controller is not None:
            self.controller.stop()
        if self.worker_patch is not None:
            self.worker_patch.stop()
        self.env.stop()
        lingering = [child for child in mp.active_children()
                     if child.name == f"eos-worker-{self.run_id[:8]}"]
        for child in lingering:
            child.terminate()
            child.join(timeout=1)
            if child.is_alive():
                child.kill()
                child.join(timeout=1)
        self.assertFalse(lingering, "测试结束时直接 Worker 仍存活")

    def run_mode(self, mode, *, budget=0.2, padding=0):
        if mode is not None:
            self.worker_patch = patch.object(controller_module, "worker_main",
                                             partial(_fault_worker, mode, self.observed))
            self.worker_patch.start()
        config = RunConfig(
            run_id=self.run_id, scenario_id="fixture", scenario_sha256=self.digest,
            scenario_path=str(self.scene), algorithm_id="completion_first",
            algorithm_version="baseline-1", time_budget_s=budget,
            algorithm_params={"padding": "x" * padding} if padding else {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.database.enqueue(config, max_queued=8)
        self.controller = controller_module.Controller(self.settings, self.database)
        started = time.monotonic()
        self.controller.start()
        return started

    def wait_terminal(self, timeout=7):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.database.get_run(self.run_id)
            if record["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}:
                return record
            time.sleep(0.02)
        self.fail(f"运行未在期限内结束：{self.database.get_status(self.run_id)}")

    def assert_reaped(self, record, expected_action=None):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            events = [e for e in self.database.get_run(self.run_id)["events"]
                      if e["event_type"] == "WORKER_REAP"]
            if events:
                break
            time.sleep(0.02)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["payload"]["alive"])
        self.assertEqual(record["attempts"][0]["exit_code"], events[0]["payload"]["exit_code"])
        if expected_action is not None:
            self.assertEqual(events[0]["payload"]["action"], expected_action)

    def test_real_reference_worker_success_records_zero_exit(self):
        self.run_mode(None, budget=3)
        record = self.wait_terminal()
        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertEqual(record["attempts"][0]["exit_code"], 0)
        self.assert_reaped(record, "exited")

    def test_search_wall_timeout_reaps_uncooperative_worker(self):
        started = self.run_mode("search_hang")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "TIMED_OUT")
        self.assertEqual(record["error"]["code"], "ALGORITHM_TIMEOUT")
        self.assertTrue(self.observed.is_set(), "超时后未尝试协作 cancel")
        self.assertLess(time.monotonic() - started, 5)
        self.assert_reaped(record, "terminate")

    def test_repeated_searching_does_not_extend_wall_deadline(self):
        started = self.run_mode("repeat_searching")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "TIMED_OUT")
        self.assertLess(time.monotonic() - started, 5)
        self.assert_reaped(record, "terminate")

    def test_startup_prepare_timeout_is_failed_not_algorithm_timeout(self):
        started = self.run_mode("loading_hang")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "WORKER_STARTUP_TIMEOUT")
        self.assertLess(time.monotonic() - started, 4)
        self.assert_reaped(record, "terminate")

    def test_real_blocked_control_send_has_deadline(self):
        self.settings = Settings(runtime_dir=self.settings.runtime_dir,
                                 scenario_dir=self.settings.scenario_dir,
                                 startup_timeout_s=0.8, transfer_timeout_s=0.3,
                                 stop_grace_s=0.2)
        started = self.run_mode("blocked_start", padding=1_000_000)
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "IPC_SEND_TIMEOUT")
        self.assertLess(time.monotonic() - started, 3)
        self.assert_reaped(record, "terminate")

    def test_user_cancel_stays_bounded_while_start_send_is_blocked(self):
        start_queued = threading.Event()
        original_enqueue = controller_module.ControlWriter.enqueue

        def observe_enqueue(writer, message, deadline):
            original_enqueue(writer, message, deadline)
            if message["kind"] == "start":
                start_queued.set()

        with patch.object(controller_module.ControlWriter, "enqueue", observe_enqueue):
            started = self.run_mode("blocked_start", padding=1_000_000)
            self.assertTrue(start_queued.wait(2), "测试未进入 start 已排队的阻塞写路径")
            self.database.request_cancel(self.run_id)
            record = self.wait_terminal()
        self.assertEqual(record["status"], "CANCELLED")
        self.assertLess(time.monotonic() - started, 5)
        self.assert_reaped(record, "terminate")
        errors = [event for event in record["events"] if event["event_type"] == "IPC_ERROR"]
        self.assertTrue(any(event["payload"]["code"] == "IPC_SEND_TIMEOUT" for event in errors))

    def test_partial_event_frame_has_transfer_deadline(self):
        started = self.run_mode("partial_frame")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "IPC_TRANSFER_TIMEOUT")
        self.assertLess(time.monotonic() - started, 3)
        self.assert_reaped(record, "terminate")

    def test_partial_event_frame_closed_early_is_interrupted(self):
        self.run_mode("partial_close")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "IPC_TRANSFER_INTERRUPTED")
        self.assert_reaped(record, "exited")

    def test_pipe_descriptors_close_after_worker_failure(self):
        baseline = len(os.listdir("/proc/self/fd"))
        self.run_mode("partial_close")
        record = self.wait_terminal()
        self.assert_reaped(record, "exited")
        self.controller.stop()
        self.controller = None
        self.worker_patch.stop()
        self.worker_patch = None
        self.assertLessEqual(len(os.listdir("/proc/self/fd")), baseline)

    def test_ignored_sigterm_falls_back_to_kill(self):
        started = self.run_mode("ignore_term")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "TIMED_OUT")
        self.assertEqual(record["attempts"][0]["exit_code"], -signal.SIGKILL)
        self.assertLess(time.monotonic() - started, 5)
        self.assert_reaped(record, "kill")

    def test_oversized_frame_rejected_before_body(self):
        self.run_mode("oversize_frame")
        record = self.wait_terminal()
        self.assertEqual(record["error"]["code"], "IPC_MESSAGE_TOO_LARGE")
        self.assert_reaped(record, "terminate")

    def test_zero_length_send_bytes_is_protocol_error(self):
        self.run_mode("zero_length_frame")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "IPC_PROTOCOL_ERROR")
        errors = [event for event in record["events"] if event["event_type"] == "IPC_ERROR"]
        self.assertTrue(any(event["payload"]["code"] == "IPC_PROTOCOL_ERROR" for event in errors))
        self.assert_reaped(record, "terminate")

    def test_malformed_json_and_invalid_fields_are_protocol_errors(self):
        for mode in ("malformed_json", "invalid_version", "invalid_fields"):
            with self.subTest(mode=mode):
                if self.controller is not None:
                    self.controller.stop()
                if self.worker_patch is not None:
                    self.worker_patch.stop()
                self.controller = None
                self.worker_patch = None
                self.run_id = str(uuid.uuid4())
                self.run_mode(mode)
                record = self.wait_terminal()
                self.assertEqual(record["status"], "FAILED")
                self.assertEqual(record["error"]["code"], "IPC_PROTOCOL_ERROR")
                self.assert_reaped(record)

    def test_crash_cannot_be_mistaken_for_success(self):
        self.run_mode("crash")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["attempts"][0]["exit_code"], 23)
        self.assertIsNone(record["plan"])
        self.assert_reaped(record, "exited")

    def test_failed_event_wins_over_zero_exit_code(self):
        self.run_mode("failed_event")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "TEST_FAILURE")
        self.assertEqual(record["attempts"][0]["exit_code"], 0)

    def test_candidate_followed_by_crash_cannot_commit(self):
        self.run_mode("crash_after_candidate")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["attempts"][0]["exit_code"], 24)
        self.assertIsNone(record["plan"])

    def test_candidate_exit_timeout_reaps_worker(self):
        started = self.run_mode("candidate_hang")
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "WORKER_EXIT_TIMEOUT")
        self.assertLess(time.monotonic() - started, 3)
        self.assert_reaped(record, "terminate")

    def test_new_sequence_candidate_cannot_extend_exit_deadline(self):
        started = self.run_mode("repeat_candidate", budget=3)
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "IPC_PROTOCOL_ERROR")
        self.assertIsNone(record["plan"])
        self.assertLess(time.monotonic() - started, 3)
        candidates = [event for event in record["events"] if event["event_type"] == "candidate_result"]
        self.assertGreaterEqual(len(candidates), 2)
        self.assert_reaped(record, "terminate")

    def test_same_sequence_candidate_remains_deduplicated(self):
        self.run_mode("same_seq_candidate", budget=3)
        record = self.wait_terminal()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error"]["code"], "WORKER_EXIT_TIMEOUT")
        candidates = [event for event in record["events"] if event["event_type"] == "candidate_result"]
        self.assertEqual(len(candidates), 1)
        self.assert_reaped(record, "terminate")

    def test_persisted_user_cancel_precedes_search_timeout(self):
        self.run_mode("search_hang", budget=0.4)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(e["event_type"] == "heartbeat" and e["payload"].get("phase") == "SEARCHING"
                   for e in self.database.get_run(self.run_id)["events"]):
                break
            time.sleep(0.02)
        else:
            self.fail("未进入 SEARCHING")
        self.database.request_cancel(self.run_id)
        record = self.wait_terminal()
        self.assertEqual(record["status"], "CANCELLED")
        self.assert_reaped(record, "terminate")

    def test_timeout_reason_does_not_change_after_late_cancel(self):
        self.run_mode("search_hang")
        self.assertTrue(self.observed.wait(4), "Worker 未收到超时后的 cancel")
        self.database.request_cancel(self.run_id)
        record = self.wait_terminal()
        self.assertEqual(record["status"], "TIMED_OUT")
        self.assert_reaped(record, "terminate")


if __name__ == "__main__":
    unittest.main()
