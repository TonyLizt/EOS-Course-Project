"""W1 Worker IPC 测试；假求解器只作为测试桩，不产生正式调度结果。"""

import json
import hashlib
import multiprocessing as mp
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from algorithms.objectives import ObjectiveWeights
from eos_system.algorithm_registry import CompletionParams, LegacySearchAdapter, SolveContext
from eos_system.contracts import RunConfig
from eos_system import worker_reference as worker
from schedulers.constraint_model import Schedule


RUN_ID = "00000000-0000-4000-8000-000000000101"
ATTEMPT = 1


def envelope(kind, seq=1, **changes):
    message = {
        "protocol_version": 1, "run_id": RUN_ID, "attempt": ATTEMPT,
        "seq": seq, "kind": kind, "sent_at": datetime.now(timezone.utc).isoformat(),
        "payload": {},
    }
    message.update(changes)
    return message


class WorkerIpcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scene = Path(self.temp.name) / "fixture.json"
        self.scene.write_text("{}", encoding="utf-8")
        self.config = RunConfig(
            run_id=RUN_ID, scenario_id="fixture", scenario_sha256="0" * 64,
            scenario_path=str(self.scene), algorithm_id="completion_first",
            algorithm_version="baseline-1", created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _start_command(self):
        return {"kind": "start", "run_id": RUN_ID, "attempt": ATTEMPT,
                "config": self.config.model_dump()}

    @contextmanager
    def harness(self, solve=None):
        event_recv, event_send = mp.Pipe(duplex=False)
        control_recv, control_send = mp.Pipe(duplex=False)
        context = SolveContext(1, 10.0, ObjectiveWeights(), CompletionParams())
        if solve is None:
            solve = lambda _solver, _problem, _constraints, _context: ({"assignments": []}, 0.01)
        with patch.object(worker.os, "setsid"), patch.object(worker, "sha256_file", return_value="0" * 64), \
                patch.object(worker, "prepare", return_value=(object(), object(), object(), context)), \
                patch.object(worker, "run_prepared", side_effect=solve):
            thread = threading.Thread(target=worker.worker_main,
                                      args=(RUN_ID, ATTEMPT, event_send, control_recv), daemon=True)
            thread.start()
            try:
                yield event_recv, control_send, thread
            finally:
                control_send.close()
                thread.join(timeout=3)
                event_recv.close()
                self.assertFalse(thread.is_alive(), "Worker 测试线程未退出")

    def read_event(self, event_recv):
        self.assertTrue(event_recv.poll(3), "未在 3 秒内收到 Worker 事件")
        return worker.receive_message(event_recv)

    def read_until_terminal(self, event_recv):
        messages = []
        while True:
            message = self.read_event(event_recv)
            messages.append(message)
            if message["kind"] in {"candidate_result", "failed"}:
                return messages
            if message["kind"] == "cancel_ack" and not event_recv.poll(0.2):
                return messages

    def read_until_kind(self, event_recv, expected):
        messages = []
        for _ in range(6):
            message = self.read_event(event_recv)
            messages.append(message)
            if message["kind"] == expected:
                return messages
        self.fail(f"未收到 {expected} 事件")

    def test_legacy_start_normal_exit_and_event_sequence(self):
        with self.harness() as (events, control, thread):
            self.assertEqual(self.read_event(events)["kind"], "started")
            worker.send_message(control, self._start_command())
            messages = self.read_until_terminal(events)
            self.assertEqual(messages[-1]["kind"], "candidate_result")
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            seq = [item["seq"] for item in messages]
            self.assertEqual(seq, sorted(set(seq)))
            self.assertEqual([item["kind"] for item in messages],
                             ["heartbeat", "heartbeat", "heartbeat", "candidate_result"])

    def test_full_start_envelope_is_accepted(self):
        with self.harness() as (events, control, _):
            self.read_event(events)
            worker.send_message(control, envelope("start", payload={"config": self.config.model_dump()}))
            self.assertEqual(self.read_until_terminal(events)[-1]["kind"], "candidate_result")

    def test_wrong_version_and_identity_are_rejected(self):
        cases = [
            envelope("start", protocol_version=2, payload={"config": self.config.model_dump()}),
            {**self._start_command(), "run_id": "another-run"},
            {**self._start_command(), "attempt": 2},
        ]
        for command in cases:
            with self.subTest(command=command):
                with self.harness() as (events, control, thread):
                    self.read_event(events)
                    control.send_bytes(json.dumps(command).encode())
                    self.assertEqual(self.read_until_terminal(events)[-1]["kind"], "failed")
                    thread.join(timeout=1)
                    self.assertFalse(thread.is_alive())

    def test_real_spawn_rejects_bad_start_and_exits(self):
        context = mp.get_context("spawn")
        event_recv, event_send = context.Pipe(duplex=False)
        control_recv, control_send = context.Pipe(duplex=False)
        process = context.Process(target=worker.worker_main,
                                  args=(RUN_ID, ATTEMPT, event_send, control_recv))
        try:
            process.start()
            event_send.close()
            control_recv.close()
            self.assertEqual(self.read_event(event_recv)["kind"], "started")
            control_send.send_bytes(json.dumps(envelope("start", protocol_version=2)).encode())
            self.assertEqual(self.read_event(event_recv)["kind"], "failed")
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            event_recv.close()
            control_send.close()

    def test_real_spawn_runs_empty_test_scenario(self):
        # 仅验证进程和 IPC 正常路径；空场景不是算法实验数据。
        scene = {"scenario_id": "fixture", "metadata": {
            "creation_time": "2026-01-01T00:00:00", "duration": 60,
        }, "satellites": [], "ground_stations": [], "missions": []}
        raw = json.dumps(scene).encode()
        self.scene.write_bytes(raw)
        config = self.config.model_copy(update={"scenario_sha256": hashlib.sha256(raw).hexdigest()})
        context = mp.get_context("spawn")
        event_recv, event_send = context.Pipe(duplex=False)
        control_recv, control_send = context.Pipe(duplex=False)
        process = context.Process(target=worker.worker_main,
                                  args=(RUN_ID, ATTEMPT, event_send, control_recv))
        try:
            process.start()
            event_send.close()
            control_recv.close()
            self.assertEqual(self.read_event(event_recv)["kind"], "started")
            worker.send_message(control_send, {"kind": "start", "run_id": RUN_ID,
                                               "attempt": ATTEMPT, "config": config.model_dump()})
            messages = self.read_until_terminal(event_recv)
            self.assertEqual(messages[-1]["kind"], "candidate_result", messages[-1])
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            event_recv.close()
            control_send.close()

    def test_malformed_json_and_required_fields_are_rejected(self):
        for data in (b"{", json.dumps(envelope("cancel", payload=[])).encode(),
                     json.dumps(envelope("cancel", seq=True)).encode()):
            with self.subTest(data=data):
                event_recv, event_send = mp.Pipe(duplex=False)
                try:
                    event_send.send_bytes(data)
                    with self.assertRaises(ValueError):
                        worker.receive_message(event_recv)
                finally:
                    event_recv.close()
                    event_send.close()

    def test_cancel_is_visible_during_solve_and_candidate_is_suppressed(self):
        entered = threading.Event()
        observed = threading.Event()

        def solve(_solver, _problem, _constraints, context):
            entered.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if context.is_cancelled():
                    observed.set()
                    return {"assignments": []}, 0.1
            raise AssertionError("测试桩未观察到取消")

        with self.harness(solve) as (events, control, thread):
            self.read_event(events)
            worker.send_message(control, self._start_command())
            self.assertTrue(entered.wait(2))
            worker.send_message(control, envelope("cancel"))
            messages = self.read_until_kind(events, "cancel_ack")
            self.assertEqual(messages[-1]["kind"], "cancel_ack")
            self.assertTrue(observed.wait(2))
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            while events.poll(0.1):
                try:
                    messages.append(worker.receive_message(events))
                except EOFError:
                    break
            self.assertNotIn("candidate_result", [item["kind"] for item in messages])

    def test_repeated_cancel_has_only_one_ack(self):
        entered = threading.Event()
        release = threading.Event()

        def solve(_solver, _problem, _constraints, context):
            entered.set()
            self.assertTrue(release.wait(2))
            self.assertTrue(context.is_cancelled())
            return {"assignments": []}, 0.1

        with self.harness(solve) as (events, control, thread):
            self.read_event(events)
            worker.send_message(control, self._start_command())
            self.assertTrue(entered.wait(2))
            worker.send_message(control, envelope("cancel", seq=1))
            worker.send_message(control, envelope("cancel", seq=1))
            messages = self.read_until_kind(events, "cancel_ack")
            release.set()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            while events.poll(0.1):
                try:
                    messages.append(worker.receive_message(events))
                except EOFError:
                    break
            self.assertEqual([item["kind"] for item in messages].count("cancel_ack"), 1)
            self.assertNotIn("candidate_result", [item["kind"] for item in messages])

    def test_solver_cancel_exception_does_not_become_failure(self):
        entered = threading.Event()

        def solve(_solver, _problem, _constraints, context):
            entered.set()
            while not context.is_cancelled():
                time.sleep(0.01)
            raise RuntimeError("test cancellation")

        with self.harness(solve) as (events, control, thread):
            self.read_event(events)
            worker.send_message(control, self._start_command())
            self.assertTrue(entered.wait(2))
            worker.send_message(control, envelope("cancel"))
            messages = self.read_until_kind(events, "cancel_ack")
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            while events.poll(0.1):
                try:
                    messages.append(worker.receive_message(events))
                except EOFError:
                    break
            self.assertNotIn("candidate_result", [item["kind"] for item in messages])
            self.assertNotIn("failed", [item["kind"] for item in messages])

    def test_wrong_cancel_identity_reports_failure(self):
        entered = threading.Event()

        def solve(_solver, _problem, _constraints, context):
            entered.set()
            while not context.is_cancelled():
                time.sleep(0.01)
            return {"assignments": []}, 0.1

        with self.harness(solve) as (events, control, _):
            self.read_event(events)
            worker.send_message(control, self._start_command())
            self.assertTrue(entered.wait(2))
            worker.send_message(control, envelope("cancel", run_id="wrong"))
            self.assertEqual(self.read_until_terminal(events)[-1]["kind"], "failed")

    def test_wrong_cancel_version_is_rejected(self):
        entered = threading.Event()

        def solve(_solver, _problem, _constraints, context):
            entered.set()
            while not context.is_cancelled():
                time.sleep(0.01)
            return {"assignments": []}, 0.1

        with self.harness(solve) as (events, control, _):
            self.read_event(events)
            worker.send_message(control, self._start_command())
            self.assertTrue(entered.wait(2))
            control.send_bytes(json.dumps(envelope("cancel", protocol_version=2)).encode())
            self.assertEqual(self.read_until_terminal(events)[-1]["kind"], "failed")

    def test_control_eof_after_start_reports_failure_and_exits(self):
        entered = threading.Event()

        def solve(_solver, _problem, _constraints, context):
            entered.set()
            while not context.is_cancelled():
                time.sleep(0.01)
            return {"assignments": []}, 0.1

        with self.harness(solve) as (events, control, thread):
            self.read_event(events)
            worker.send_message(control, self._start_command())
            self.assertTrue(entered.wait(2))
            control.close()
            self.assertEqual(self.read_until_terminal(events)[-1]["kind"], "failed")
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())

    def test_solver_exception_reports_failure(self):
        def solve(*_):
            raise RuntimeError("test solver failed")

        with self.harness(solve) as (events, control, _):
            self.read_event(events)
            worker.send_message(control, self._start_command())
            self.assertEqual(self.read_until_terminal(events)[-1]["payload"]["code"], "RuntimeError")

    def test_legacy_adapter_still_uses_engine_contract(self):
        initial = Schedule()

        class Constraints:
            def build_initial_schedule(self):
                return initial

        class OldAlgorithm:
            def search(self, problem, constraint_model, initial_schedule):
                self_test.assertIs(problem, marker)
                self_test.assertIsInstance(constraint_model, Constraints)
                self_test.assertIs(initial_schedule, initial)
                return initial_schedule

        self_test = self
        marker = object()
        context = SolveContext(1, 10.0, ObjectiveWeights(), CompletionParams())
        self.assertIs(LegacySearchAdapter(OldAlgorithm()).solve(marker, Constraints(), context), initial)


if __name__ == "__main__":
    unittest.main()
