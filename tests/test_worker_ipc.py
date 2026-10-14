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
from schedulers.scenario_loader import load_scheduling_problem_from_json


RUN_ID = "00000000-0000-4000-8000-000000000101"
ATTEMPT = 1


class SpawnTestSolver:
    """仅在真实 spawn 子进程中运行的有限时长求解桩。"""

    def __init__(self, mode, entered, observed):
        self.mode = mode
        self.entered = entered
        self.observed = observed

    def solve(self, problem, constraints, context):
        self.entered.set()
        if self.mode == "raises":
            raise RuntimeError("spawn test solver failure")
        if self.mode == "uncooperative":
            time.sleep(5)  # 有界阻塞；故意不查询 is_cancelled。
            return Schedule()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if context.is_cancelled():
                self.observed.set()
                return Schedule()
            time.sleep(0.01)
        raise RuntimeError("测试求解桩未在 6 秒内观察到取消")


def spawn_worker_with_test_solver(run_id, attempt, event_pipe, control_pipe, mode, entered, observed):
    """可被 spawn 导入的入口；测试替身在子进程内安装并执行。"""
    def prepare_test_solver(config):
        problem = load_scheduling_problem_from_json(config.scenario_path)
        context = SolveContext(config.seed, config.time_budget_s, ObjectiveWeights(), CompletionParams())
        return SpawnTestSolver(mode, entered, observed), problem, None, context

    with patch.object(worker, "prepare", side_effect=prepare_test_solver):
        worker.worker_main(run_id, attempt, event_pipe, control_pipe)


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

    def make_empty_scene(self):
        # 只供进程/IPC 测试，不代表真实调度实验。
        scene = {"scenario_id": "fixture", "metadata": {
            "creation_time": "2026-01-01T00:00:00", "duration": 60,
        }, "satellites": [], "ground_stations": [], "missions": []}
        raw = json.dumps(scene).encode()
        self.scene.write_bytes(raw)
        return self.config.model_copy(update={"scenario_sha256": hashlib.sha256(raw).hexdigest()})

    @contextmanager
    def spawn_stub_harness(self, mode):
        config = self.make_empty_scene()
        context = mp.get_context("spawn")
        event_recv, event_send = context.Pipe(duplex=False)
        control_recv, control_send = context.Pipe(duplex=False)
        entered, observed = context.Event(), context.Event()
        process = context.Process(target=spawn_worker_with_test_solver,
                                  args=(RUN_ID, ATTEMPT, event_send, control_recv,
                                        mode, entered, observed))
        forced_cleanup = False
        try:
            process.start()
            event_send.close()
            control_recv.close()
            yield process, event_recv, control_send, entered, observed, config
        finally:
            control_send.close()
            event_recv.close()
            if process.pid is not None:
                process.join(timeout=0.5)
                if process.is_alive():
                    forced_cleanup = True
                    process.terminate()
                    process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
                self.assertFalse(process.is_alive(), "测试结束后遗留 Worker 子进程")
            self.assertFalse(forced_cleanup, "Worker 未自行退出，测试端执行了外部强制回收")

    def drain_after_exit(self, event_recv):
        messages = []
        for _ in range(8):
            self.assertTrue(event_recv.poll(1), "Worker 已退出但事件 Pipe 未关闭")
            try:
                messages.append(worker.receive_message(event_recv))
            except EOFError:
                return messages
        self.fail("Worker 退出后事件 Pipe 未出现 EOF")

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
        config = self.make_empty_scene()
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

    def test_real_spawn_cooperative_cancel_observed_without_candidate(self):
        with self.spawn_stub_harness("cooperative") as (process, events, control, entered, observed, config):
            started = self.read_event(events)
            self.assertEqual(started["kind"], "started")
            self.assertEqual(started["payload"]["worker_pid"], process.pid)
            worker.send_message(control, {"kind": "start", "run_id": RUN_ID,
                                          "attempt": ATTEMPT, "config": config.model_dump()})
            self.assertTrue(entered.wait(3), "spawn 子进程未进入 solve()")
            worker.send_message(control, envelope("cancel"))
            messages = self.read_until_kind(events, "cancel_ack")
            self.assertTrue(observed.wait(2), "spawn 子进程未通过 is_cancelled() 观察到取消")
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0, "Worker 未自行正常退出")
            messages.extend(self.drain_after_exit(events))
            self.assertNotIn("candidate_result", [item["kind"] for item in messages])
            self.assertEqual([item["kind"] for item in messages].count("cancel_ack"), 1)
            self.assertEqual([item["seq"] for item in [started] + messages],
                             list(range(1, len(messages) + 2)))
            self.assertFalse(process.is_alive())

    def test_real_spawn_uncooperative_cancel_has_bounded_worker_exit(self):
        with self.spawn_stub_harness("uncooperative") as (process, events, control, entered, observed, config):
            self.assertEqual(self.read_event(events)["kind"], "started")
            worker.send_message(control, {"kind": "start", "run_id": RUN_ID,
                                          "attempt": ATTEMPT, "config": config.model_dump()})
            self.assertTrue(entered.wait(3), "spawn 子进程未进入不合作 solve()")
            sent_at = time.monotonic()
            worker.send_message(control, envelope("cancel"))
            messages = self.read_until_kind(events, "cancel_ack")
            self.assertLess(time.monotonic() - sent_at, 1.5, "cancel_ack 未及时到达")
            process.join(timeout=worker.CANCEL_GRACE_S + 2)
            elapsed = time.monotonic() - sent_at
            self.assertEqual(process.exitcode, 0, "Worker 未在取消宽限后自行退出")
            self.assertLess(elapsed, 4.5, "Worker 主线程被不合作求解线程阻塞")
            self.assertFalse(observed.is_set(), "不合作测试桩不应读取 is_cancelled()")
            messages.extend(self.drain_after_exit(events))
            self.assertNotIn("candidate_result", [item["kind"] for item in messages])
            self.assertFalse(process.is_alive())

    def test_real_spawn_control_eof_exits_without_lingering_process(self):
        with self.spawn_stub_harness("cooperative") as (process, events, control, entered, _observed, config):
            self.assertEqual(self.read_event(events)["kind"], "started")
            worker.send_message(control, {"kind": "start", "run_id": RUN_ID,
                                          "attempt": ATTEMPT, "config": config.model_dump()})
            self.assertTrue(entered.wait(3))
            control.close()
            messages = self.read_until_terminal(events)
            self.assertEqual(messages[-1]["kind"], "failed")
            self.assertEqual(messages[-1]["payload"]["code"], "ConnectionError")
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(self.drain_after_exit(events), [])

    def test_real_spawn_solver_exception_exits_without_lingering_process(self):
        with self.spawn_stub_harness("raises") as (process, events, control, entered, _observed, config):
            self.assertEqual(self.read_event(events)["kind"], "started")
            worker.send_message(control, {"kind": "start", "run_id": RUN_ID,
                                          "attempt": ATTEMPT, "config": config.model_dump()})
            self.assertTrue(entered.wait(3))
            messages = self.read_until_terminal(events)
            self.assertEqual(messages[-1]["kind"], "failed")
            self.assertEqual(messages[-1]["payload"]["code"], "RuntimeError")
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(self.drain_after_exit(events), [])

    def test_real_spawn_closed_event_pipe_exits_without_lingering_process(self):
        with self.spawn_stub_harness("cooperative") as (process, events, control, entered, _observed, config):
            self.assertEqual(self.read_event(events)["kind"], "started")
            worker.send_message(control, {"kind": "start", "run_id": RUN_ID,
                                          "attempt": ATTEMPT, "config": config.model_dump()})
            self.assertTrue(entered.wait(3))
            events.close()
            worker.send_message(control, envelope("cancel"))
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0, "事件 Pipe 关闭后 Worker 未自行退出")
            self.assertFalse(process.is_alive())

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
