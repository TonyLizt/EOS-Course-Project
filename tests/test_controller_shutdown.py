"""W2-C Controller 停机与 flock 生命周期隔离测试。"""

import hashlib
import json
import multiprocessing as mp
import os
import signal
import subprocess
import sys
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
from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.storage import Database
from eos_system import worker_reference as worker
from eos_system.worker_reference import receive_message, send_message
from eos_system.worker_process import read_proc


def _shutdown_worker(run_id, attempt, event_pipe, control_pipe):
    os.setsid()
    seq = 0

    def event(kind, payload):
        nonlocal seq
        seq += 1
        send_message(event_pipe, {
            "protocol_version": 1, "run_id": run_id, "attempt": attempt, "seq": seq,
            "kind": kind, "sent_at": datetime.now(timezone.utc).isoformat(), "payload": payload,
        })

    event("started", {"worker_pid": os.getpid(), "pgid": os.getpgrp()})
    receive_message(control_pipe)
    event("heartbeat", {"phase": "SEARCHING"})
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if control_pipe.poll(0.02):
            command = receive_message(control_pipe)
            if command["kind"] == "cancel":
                event("cancel_ack", {"accepted": True})
                return


def _worker_with_descendant(pid_path, early_exit, run_id, attempt, event_pipe, control_pipe):
    os.setsid()
    now = lambda: datetime.now(timezone.utc).isoformat()

    def event(seq, kind, payload):
        send_message(event_pipe, {"protocol_version": 1, "run_id": run_id,
                                  "attempt": attempt, "seq": seq, "kind": kind,
                                  "sent_at": now(), "payload": payload})

    event(1, "started", {"worker_pid": os.getpid(), "pgid": os.getpgrp()})
    receive_message(control_pipe)
    child = subprocess.Popen([
        sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(6)",
    ], close_fds=True)
    time.sleep(0.15)
    Path(pid_path).write_text(str(child.pid))
    event(2, "heartbeat", {"phase": "SEARCHING"})
    if early_exit:
        time.sleep(0.3)
        os._exit(23)
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if control_pipe.poll(0.02):
            command = receive_message(control_pipe)
            if command["kind"] == "cancel":
                event(3, "cancel_ack", {"accepted": True})
                return


def _worker_crash_after_unseen_child(pid_path, gate_path, run_id, attempt,
                                     event_pipe, control_pipe):
    os.setsid()
    send_message(event_pipe, {"protocol_version": 1, "run_id": run_id,
                              "attempt": attempt, "seq": 1, "kind": "started",
                              "sent_at": datetime.now(timezone.utc).isoformat(),
                              "payload": {"worker_pid": os.getpid(), "pgid": os.getpgrp()}})
    receive_message(control_pipe)
    send_message(event_pipe, {"protocol_version": 1, "run_id": run_id,
                              "attempt": attempt, "seq": 2, "kind": "heartbeat",
                              "sent_at": datetime.now(timezone.utc).isoformat(),
                              "payload": {"phase": "SEARCHING"}})
    deadline = time.monotonic() + 3
    while not Path(gate_path).exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    child = subprocess.Popen([
        sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(6)",
    ], close_fds=True, preexec_fn=lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN))
    Path(pid_path).write_text(str(child.pid))
    os._exit(23)


def _unconfirmed_candidate_worker(start_received, run_id, attempt, event_pipe, control_pipe):
    """故障桩：不 setsid、不等待 start，却上报合法候选后正常退出。"""
    now = lambda: datetime.now(timezone.utc).isoformat()
    send_message(event_pipe, {"protocol_version": 1, "run_id": run_id,
                              "attempt": attempt, "seq": 1, "kind": "started",
                              "sent_at": now(),
                              "payload": {"worker_pid": os.getpid(), "pgid": os.getpid()}})
    time.sleep(0.2)
    if control_pipe.poll(0):
        start_received.set()
    for seq, kind, payload in (
        (2, "heartbeat", {"phase": "SEARCHING"}),
        (3, "candidate_result", {"plan": {"scenario_id": "fixture"},
                                 "algorithm_runtime_s": 0.01}),
    ):
        send_message(event_pipe, {"protocol_version": 1, "run_id": run_id,
                                  "attempt": attempt, "seq": seq, "kind": kind,
                                  "sent_at": now(), "payload": payload})


def _pre_setsid_pause_worker(run_id, attempt, event_pipe, control_pipe):
    time.sleep(6)  # Controller 必须只用 Process 句柄回收，不能信任继承的进程组。


def _delayed_started_reference(ready, release, start_received, algorithm_entered,
                               run_id, attempt, event_pipe, control_pipe):
    """在真实 worker_main 的 setsid 后拦住 started；桩只在子进程内生效。"""
    original_send = worker.send_message
    original_receive = worker.receive_message

    def delayed_send(connection, message):
        if message["kind"] == "started":
            ready.set()
            release.wait(5)
        return original_send(connection, message)

    def observed_receive(connection):
        message = original_receive(connection)
        if message["kind"] == "start":
            start_received.set()
        return message

    def unexpected_prepare(config):
        algorithm_entered.set()
        raise AssertionError("取消或停机之后不应执行算法准备")

    with (patch.object(worker, "send_message", side_effect=delayed_send),
          patch.object(worker, "receive_message", side_effect=observed_receive),
          patch.object(worker, "prepare", side_effect=unexpected_prepare)):
        worker.worker_main(run_id, attempt, event_pipe, control_pipe)


class ControllerShutdownTests(unittest.TestCase):
    def setUp(self):
        from certification_fixtures import unit_certify
        certification_patch = patch("eos_system.verification.certify_schedule", side_effect=unit_certify)
        certification_patch.start()
        self.addCleanup(certification_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        scenarios = root / "scenarios"
        scenarios.mkdir()
        raw = json.dumps({"scenario_id": "fixture", "metadata": {
            "creation_time": "2026-01-01T00:00:00", "duration": 60,
        }, "satellites": [], "ground_stations": [], "missions": []}).encode()
        self.scene = scenarios / "fixture.json"
        self.scene.write_bytes(raw)
        self.digest = hashlib.sha256(raw).hexdigest()
        self.settings = Settings(root, scenarios, startup_timeout_s=2,
                                 transfer_timeout_s=0.3, stop_grace_s=0.2)
        self.database = Database(self.settings.database_path)
        self.run_id = str(uuid.uuid4())
        self.controller = None
        self.patch_worker = None

    def tearDown(self):
        if self.controller is not None and self.controller._lock_file is not None:
            self.controller.stop()
        if self.patch_worker is not None:
            self.patch_worker.stop()
        self.assertFalse([child for child in mp.active_children()
                          if child.name == f"eos-worker-{self.run_id[:8]}"])

    def enqueue(self):
        config = RunConfig(
            run_id=self.run_id, scenario_id="fixture", scenario_sha256=self.digest,
            scenario_path=str(self.scene), algorithm_id="completion_first",
            algorithm_version="baseline-1", time_budget_s=3,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.database.enqueue(config, max_queued=8)

    def wait_for(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("等待条件超时")

    def test_stop_active_worker_marks_internal_interruption_and_releases_lock(self):
        self.enqueue()
        self.patch_worker = patch.object(controller_module, "worker_main", _shutdown_worker)
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        self.wait_for(lambda: any(event["event_type"] == "heartbeat" and
                                  event["payload"].get("phase") == "SEARCHING"
                                  for event in self.database.get_run(self.run_id)["events"]))
        self.controller.stop()
        record = self.database.get_run(self.run_id)
        self.assertEqual((record["status"], record["error"]["code"]),
                         ("FAILED", "CONTROLLER_STOP"))
        self.assertFalse(self.controller._thread.is_alive())
        self.assertIsNone(self.controller._lock_file)
        self.assertTrue(any(event["event_type"] == "cancel_ack" for event in record["events"]))
        other = controller_module.Controller(self.settings, self.database)
        other.start()
        other.stop()

    def test_stop_and_start_attempt_are_serialized(self):
        self.enqueue()
        entered, release = threading.Event(), threading.Event()
        original = self.database.start_attempt

        def blocked_start(run_id):
            entered.set()
            release.wait(3)
            return original(run_id)

        self.patch_worker = patch.object(controller_module, "worker_main", _shutdown_worker)
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        with patch.object(self.database, "start_attempt", side_effect=blocked_start):
            self.controller.start()
            self.assertTrue(entered.wait(3))
            errors = []
            stopper = threading.Thread(target=lambda: self._stop_capture(errors))
            stopper.start()
            time.sleep(0.1)
            self.assertTrue(stopper.is_alive())
            release.set()
            stopper.join(timeout=8)
            self.assertFalse(stopper.is_alive())
            self.assertEqual(errors, [])
        self.assertFalse(self.controller._thread.is_alive())
        self.assertEqual(self.database.get_run(self.run_id)["status"], "FAILED")

    def _stop_capture(self, errors):
        try:
            self.controller.stop()
        except BaseException as exc:
            errors.append(exc)

    def watch_child(self, pid_path):
        self.wait_for(pid_path.exists)
        pid = int(pid_path.read_text())
        identity = read_proc(pid)
        self.assertIsNotNone(identity)
        fd = os.pidfd_open(pid, 0)

        def cleanup():
            current = read_proc(pid, identity.boot_id)
            if current and current.starttime == identity.starttime and current.live:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            os.close(fd)

        self.addCleanup(cleanup)
        return pid, identity

    def assert_child_stopped(self, pid, identity):
        current = read_proc(pid, identity.boot_id)
        self.assertTrue(current is None or not current.live or
                        current.starttime != identity.starttime)

    def test_stop_cleans_verified_descendant(self):
        self.enqueue()
        pid_path = self.settings.runtime_dir / "descendant.pid"
        self.patch_worker = patch.object(controller_module, "worker_main",
                                         partial(_worker_with_descendant, str(pid_path), False))
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        pid, identity = self.watch_child(pid_path)
        self.wait_for(lambda: any(event["event_type"] == "heartbeat" and
                                  event["payload"].get("phase") == "SEARCHING"
                                  for event in self.database.get_run(self.run_id)["events"]))
        self.controller.stop()
        self.assert_child_stopped(pid, identity)
        record = self.database.get_run(self.run_id)
        self.assertEqual(record["error"]["code"], "CONTROLLER_STOP")
        reap = next(event for event in record["events"] if event["event_type"] == "WORKER_REAP")
        self.assertEqual(reap["payload"]["live_members"], 0)
        self.assertTrue(reap["payload"]["identity_confirmed"])

    def test_crashed_leader_leaves_no_verified_live_descendant(self):
        self.enqueue()
        pid_path = self.settings.runtime_dir / "descendant.pid"
        self.patch_worker = patch.object(controller_module, "worker_main",
                                         partial(_worker_with_descendant, str(pid_path), True))
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        pid, identity = self.watch_child(pid_path)
        self.wait_for(lambda: self.database.get_run(self.run_id)["status"] == "FAILED")
        self.controller.stop()
        self.assert_child_stopped(pid, identity)
        reap = next(event for event in self.database.get_run(self.run_id)["events"]
                    if event["event_type"] == "WORKER_REAP")
        self.assertEqual(reap["payload"]["live_members"], 0)
        self.assertIn("SIGKILL", " ".join(reap["payload"]["member_signals"]))

    def test_controller_recovers_child_after_immediate_leader_crash(self):
        self.enqueue()
        pid_path = self.settings.runtime_dir / "unseen-descendant.pid"
        gate_path = self.settings.runtime_dir / "release-worker"
        self.patch_worker = patch.object(
            controller_module, "worker_main",
            partial(_worker_crash_after_unseen_child, str(pid_path), str(gate_path)))
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        self.wait_for(lambda: any(event["event_type"] == "heartbeat" and
                                  event["payload"].get("phase") == "SEARCHING"
                                  for event in self.database.get_run(self.run_id)["events"]))
        gate_path.touch()
        pid, identity = self.watch_child(pid_path)
        self.wait_for(lambda: self.database.get_run(self.run_id)["status"] == "FAILED")
        self.controller.stop()
        self.assert_child_stopped(pid, identity)
        record = self.database.get_run(self.run_id)
        self.assertEqual(record["error"]["code"], "IPC_DISCONNECTED")
        reap = next(event for event in record["events"] if event["event_type"] == "WORKER_REAP")
        self.assertEqual(reap["payload"]["live_members"], 0)
        self.assertFalse(reap["payload"]["scan_limited"])
        self.assertTrue(reap["payload"]["member_signals"])

    def test_fast_reference_worker_confirms_session_before_success(self):
        self.enqueue()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        self.wait_for(lambda: self.database.get_run(self.run_id)["status"] in
                      {"SUCCEEDED", "FAILED"})
        self.controller.stop()
        record = self.database.get_run(self.run_id)
        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertIsNotNone(record["plan"])
        reap = next(event for event in record["events"] if event["event_type"] == "WORKER_REAP")
        self.assertTrue(reap["payload"]["identity_confirmed"])
        self.assertFalse(reap["payload"]["scan_limited"])

    def test_unconfirmed_session_cannot_commit_legal_candidate(self):
        self.enqueue()
        start_received = mp.get_context("spawn").Event()
        self.patch_worker = patch.object(controller_module, "worker_main",
                                         partial(_unconfirmed_candidate_worker, start_received))
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        self.wait_for(lambda: self.database.get_run(self.run_id)["status"] == "FAILED")
        self.controller.stop()
        record = self.database.get_run(self.run_id)
        self.assertEqual(record["error"]["code"], "WORKER_IDENTITY_UNCONFIRMED")
        self.assertFalse(start_received.is_set(), "未确认 Session 已收到 start")
        self.assertIsNone(record["plan"])
        self.assertTrue(any(event["event_type"] == "candidate_result" for event in record["events"]))
        self.assertTrue(any(event["event_type"] == "WORKER_IDENTITY" for event in record["events"]))
        reap = next(event for event in record["events"] if event["event_type"] == "WORKER_REAP")
        self.assertEqual(reap["payload"]["exit_code"], 0)
        self.assertFalse(reap["payload"]["identity_confirmed"])

    def test_cancel_before_setsid_uses_direct_reap_without_group_signal(self):
        self.enqueue()
        self.patch_worker = patch.object(controller_module, "worker_main", _pre_setsid_pause_worker)
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        self.wait_for(lambda: self.database.get_status(self.run_id)["status"] == "RUNNING")
        self.database.request_cancel(self.run_id)
        self.wait_for(lambda: self.database.get_run(self.run_id)["status"] == "CANCELLED")
        self.controller.stop()
        record = self.database.get_run(self.run_id)
        self.assertIsNone(record["plan"])
        reap = next(event for event in record["events"] if event["event_type"] == "WORKER_REAP")
        self.assertFalse(reap["payload"]["identity_confirmed"])
        self.assertEqual(reap["payload"]["group_signals"], [])
        self.assertTrue(any(event["event_type"] == "WORKER_IDENTITY" for event in record["events"]))

    def test_cancel_before_delayed_started_never_sends_start(self):
        self.enqueue()
        context = mp.get_context("spawn")
        ready, release = context.Event(), context.Event()
        start_received, algorithm_entered = context.Event(), context.Event()
        self.addCleanup(release.set)
        self.patch_worker = patch.object(
            controller_module, "worker_main",
            partial(_delayed_started_reference, ready, release, start_received, algorithm_entered))
        self.patch_worker.start()
        original_status = self.database.get_status
        cancel_observed = threading.Event()

        def observed_status(run_id):
            status = original_status(run_id)
            if (threading.current_thread().name == "eos-controller" and status
                    and status["cancel_requested_at"]):
                cancel_observed.set()
            return status

        with patch.object(self.database, "get_status", side_effect=observed_status):
            self.controller = controller_module.Controller(self.settings, self.database)
            self.controller.start()
            self.assertTrue(ready.wait(3), "Worker 未到达 setsid 后的 started 发送点")
            self.database.request_cancel(self.run_id)
            self.assertTrue(cancel_observed.wait(2), "Controller 未读取已持久化的取消")
            release.set()
            self.wait_for(lambda: self.database.get_run(self.run_id)["status"] == "CANCELLED", 5)
        self.controller.stop()
        self.assertFalse(start_received.is_set())
        self.assertFalse(algorithm_entered.is_set())
        record = self.database.get_run(self.run_id)
        self.assertIsNone(record["plan"])
        reap = next(event for event in record["events"] if event["event_type"] == "WORKER_REAP")
        self.assertFalse(reap["payload"]["alive"])
        self.assertTrue(reap["payload"]["identity_confirmed"])

    def test_stop_before_delayed_started_never_sends_start(self):
        self.enqueue()
        context = mp.get_context("spawn")
        ready, release = context.Event(), context.Event()
        start_received, algorithm_entered = context.Event(), context.Event()
        self.addCleanup(release.set)
        self.patch_worker = patch.object(
            controller_module, "worker_main",
            partial(_delayed_started_reference, ready, release, start_received, algorithm_entered))
        self.patch_worker.start()
        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller.start()
        self.assertTrue(ready.wait(3), "Worker 未到达 setsid 后的 started 发送点")
        errors = []
        stopper = threading.Thread(target=lambda: self._stop_capture(errors))
        stopper.start()
        self.assertTrue(self.controller._stop.wait(2))
        release.set()
        stopper.join(timeout=6)
        self.assertFalse(stopper.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(start_received.is_set())
        self.assertFalse(algorithm_entered.is_set())
        record = self.database.get_run(self.run_id)
        self.assertEqual((record["status"], record["error"]["code"]),
                         ("FAILED", "CONTROLLER_STOP"))
        reap = next(event for event in record["events"] if event["event_type"] == "WORKER_REAP")
        self.assertFalse(reap["payload"]["alive"])
        self.assertIsNone(self.controller._lock_file)

    def test_blocked_verification_keeps_flock_until_thread_finishes(self):
        self.enqueue()
        entered, release = threading.Event(), threading.Event()
        original = controller_module.verify_candidate

        def blocked_verify(*args):
            entered.set()
            release.wait(4)
            return original(*args)

        self.controller = controller_module.Controller(self.settings, self.database)
        self.controller._shutdown_timeout_s = 0.2
        with patch.object(controller_module, "verify_candidate", side_effect=blocked_verify):
            self.controller.start()
            self.assertTrue(entered.wait(4))
            with self.assertRaisesRegex(RuntimeError, "实例锁仍保留"):
                self.controller.stop()
            self.assertIsNotNone(self.controller._lock_file)
            self.assertTrue(self.controller._thread.is_alive())
            other = controller_module.Controller(self.settings, self.database)
            with self.assertRaises(RuntimeError):
                other.start()
            release.set()
            self.controller.stop()
        self.assertFalse(self.controller._thread.is_alive())
        self.assertEqual(self.database.get_run(self.run_id)["error"]["code"],
                         "CONTROLLER_STOP")

    def test_startup_exception_releases_flock(self):
        self.controller = controller_module.Controller(self.settings, self.database)
        with patch.object(self.database, "recover_interrupted", side_effect=OSError("test")):
            with self.assertRaises(OSError):
                self.controller.start()
        self.assertIsNone(self.controller._lock_file)
        other = controller_module.Controller(self.settings, self.database)
        other.start()
        other.stop()

    def test_thread_start_exception_releases_flock(self):
        self.controller = controller_module.Controller(self.settings, self.database)
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                self.controller.start()
        self.assertIsNone(self.controller._lock_file)
        self.assertIsNone(self.controller._thread)
        other = controller_module.Controller(self.settings, self.database)
        other.start()
        other.stop()


if __name__ == "__main__":
    unittest.main()
