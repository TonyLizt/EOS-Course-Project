"""实验队列和参考 Worker 的 Controller。

持久排队以 SQLite 为准；调度槽位并行求解、串行领取同一条记录，避免内存队列在重启后丢任务。
"""

from __future__ import annotations

import fcntl
import math
import multiprocessing as mp
import os
import threading
import queue
from utils.continuous_exposure import (CertificationReceipt, ContinuousCertificationError,
                                       ExposureStatus, validate_certification, certification_runtime, check_deadline)
import time
from datetime import datetime, timezone

from .config import Settings
from .controller_ipc import (EOF, ControlWriter, EventReader, IpcError,
                             IpcMessageTooLarge, IpcProtocolError,
                             IpcSendTimeout, IpcTransferInterrupted,
                             IpcTransferTimeout)
from .contracts import RunConfig
from .exporting import persist_directory_exports
from .storage import Database
from .worker_reference import CANCEL_GRACE_S, PROTOCOL_VERSION, worker_main
from .worker_process import WorkerGroup, reap_worker
from .planning_preview import PreviewReceipt, validate_preview
from .process_state import atomic_json, identity
from .worker_recovery import WorkerJournal


VERIFICATION_TIMEOUT_S = 30.0


def verify_candidate(config, candidate, runtime_s):
    # Preserve the patchable public hook; keep algorithm/physics imports out of
    # spawned fault-worker module initialization and the identity handshake.
    from .verification import verify_candidate as implementation
    return implementation(config, candidate, runtime_s)


class Controller:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.transient = None  # Optional volatile queue; never a SQLite store.
        self._stop = threading.Event()
        self._verification_slot = threading.BoundedSemaphore(1)
        self._verification_thread = None
        self._dispatch_lock = threading.Lock()
        # 终态写入及目录导出期间，API 删除须等待，避免刚成功就被删导致导出写入悬空。
        self.finalization_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._lock_file = None
        self._shutdown_timeout_s = max(10.0, CANCEL_GRACE_S + 3 * settings.stop_grace_s + 3)
        self.instance_id = f"{os.getpid()}-{int(time.time())}"
        self._progress_at = time.monotonic()
        self.worker_journal = WorkerJournal(settings.runtime_dir)
        if type(settings.max_workers) is not int or not 1 <= settings.max_workers <= 8:
            raise ValueError('并发 Worker 数须为 1 到 8')
        self._max_workers = settings.max_workers
        self._slot_local = threading.local()
        self._threads = []
        self._active_runs = {}
        # 槽位0保留旧路径以兼容历史恢复；其余槽位有独立租约，互不覆盖。
        self._journals = [self.worker_journal] + [
            WorkerJournal(settings.runtime_dir / 'worker-slots' / str(i)) for i in range(1, 8)]
        self._verification_slots = [self._verification_slot] + [threading.BoundedSemaphore(1) for _ in range(7)]
        self._verification_threads = {}
        self._verification_lock = threading.Lock()
        self._slot_progress = [time.monotonic()] * 8

    def _touch(self):
        self._progress_at = time.monotonic()
        self._slot_progress[getattr(self._slot_local, 'slot', 0)] = self._progress_at

    @property
    def max_workers(self):
        return self._max_workers

    def execution_status(self):
        with self._dispatch_lock:
            return {'max_workers': self._max_workers, 'active_runs': len(self._active_runs),
                    'slots': [{'slot': k + 1, 'run_id': v} for k, v in sorted(self._active_runs.items())],
                    'maximum': 8}

    def set_max_workers(self, value):
        if type(value) is not int or not 1 <= value <= 8:
            raise ValueError('并发 Worker 数须为 1 到 8')
        with self._dispatch_lock:
            atomic_json(self.settings.runtime_dir / 'execution-settings.json', {'max_workers': value})
            self._max_workers = value
        return self.execution_status()

    def heartbeat(self) -> dict:
        return {"process": identity(os.getpid()), "stopping": self._stop.is_set(),
                "dispatch_alive": bool(self._threads and all(t.is_alive() for t in self._threads)),
                "progress_age_s": max(0., time.monotonic() - min(
                    [self._slot_progress[i] for i in list(self._active_runs)] or [self._progress_at]))}

    def start(self) -> None:
        """单实例文件锁与数据库恢复由 Controller 在启动时完成。"""
        # spawn 子进程会继承环境变量；固定哈希种子可消除集合迭代的跨进程差异。
        os.environ.setdefault("PYTHONHASHSEED", "0")
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        if self._lock_file is not None:
            raise RuntimeError("Controller 已启动")
        if os.environ.get("EOS_PREINITIALIZE_OREKIT") == "1":
            from utils.visibility import ensure_orekit
            ensure_orekit(os.environ.get("EOS_OREKIT_DATA"))
        self._stop.clear()
        self._lock_file = self.settings.lock_path.open("a+")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Only the lock-owning Controller coordinates old Workers. No task replay.
            for journal in self._journals:
                journal.recover(self.settings.stop_grace_s)
            self.database.recover_interrupted()
            self._touch()
            # 固定上限8个轻量管理线程；只有开放槽位领取任务，真正计算仍在独立进程。
            self._threads = [threading.Thread(target=self._loop, args=(i,),
                name='eos-controller' if i == 0 else f'eos-controller-{i+1}', daemon=True) for i in range(8)]
            self._thread = self._threads[0]
            for thread in self._threads:
                thread.start()
        except BaseException as exc:
            self._stop.set()
            for thread in self._threads:
                if thread.is_alive():
                    thread.join(timeout=self._shutdown_timeout_s)
                if thread.is_alive():
                    raise RuntimeError("Controller 启动异常后线程仍存活；实例锁仍保留") from exc
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None
            self._thread = None
            if isinstance(exc, BlockingIOError):
                raise RuntimeError("已有 Controller 正在使用此运行目录") from exc
            raise

    def announce_stopping(self) -> None:
        """Durable operator shutdown intent; independent of HTTP availability."""
        self._stop.set()
        if token := os.environ.get('EOS_SUPERVISION_TOKEN'):
            atomic_json(self.settings.runtime_dir / 'controller-stopping.json',
                        {'token': token, 'process': identity(os.getpid())})

    def stop(self) -> None:
        self.announce_stopping()
        # 与 start_attempt 串行：一旦取得锁，后续不会再领取新 attempt。
        if not self._dispatch_lock.acquire(timeout=max(1.0, self.settings.stop_grace_s)):
            raise RuntimeError("Controller 停机未能等待任务领取结束；实例锁仍保留")
        self._dispatch_lock.release()
        deadline = time.monotonic() + self._shutdown_timeout_s
        for thread in self._threads:
            thread.join(timeout=max(0., deadline - time.monotonic()))
            if thread.is_alive():
                raise RuntimeError('Controller 执行线程尚未退出；实例锁仍保留')
        with self._verification_lock:
            verifiers = list(self._verification_threads.values())
        for thread in verifiers:
            thread.join(timeout=max(0., deadline - time.monotonic()))
            if thread.is_alive():
                raise RuntimeError('认证线程尚未退出；实例锁仍保留')
        if self._lock_file:
            # Do not certify a clean shutdown while a failed reap left a lease.
            for journal in self._journals:
                journal.recover(self.settings.stop_grace_s)
            if token := os.environ.get('EOS_SUPERVISION_TOKEN'):
                atomic_json(self.settings.runtime_dir / 'controller-stopped.json',
                            {'token': token, 'instance_id': self.instance_id,
                             'process': identity(os.getpid())})
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    def _loop(self, slot=0) -> None:
        self._slot_local.slot = slot
        while not self._stop.is_set():
            self._touch()
            started = None
            with self._dispatch_lock:
                if self._stop.is_set():
                    break
                # 降低并发时已运行的任务继续完成；关闭槽位不再领取新任务。
                # 优先最低空闲槽位，保持第一个任务沿用历史租约路径，恢复证据可预测。
                next_slot = next((i for i in range(self._max_workers) if i not in self._active_runs), None)
                if slot == next_slot and len(self._active_runs) < self._max_workers:
                    store = self.database
                    queued = store.next_queued()
                    if queued is None and self.transient is not None:
                        store = self.transient
                        queued = store.next_queued()
                    if queued is not None:
                        started = store.start_attempt(queued['run_id'])
                        if started is not None:
                            self._active_runs[slot] = queued['run_id']
                            limit_at_dispatch = self._max_workers
                            active_at_dispatch = len(self._active_runs)
            if started is None:
                self._stop.wait(.1)
                continue
            attempt, config_data = started
            try:
                store.record_system_event(queued['run_id'], attempt, 'EXECUTION_RESOURCES',
                    {'worker_limit': limit_at_dispatch, 'active_at_dispatch': active_at_dispatch, 'slot': slot + 1,
                     'warning': '并行运行存在资源竞争；严肃耗时比较请设为1'})
                if store is self.database:
                    self._execute(RunConfig.model_validate(config_data), attempt)
                else:
                    self._execute(RunConfig.model_validate(config_data), attempt, store)
            except BaseException as exc:
                store.finish_failure(queued['run_id'], attempt, 'FAILED', type(exc).__name__, str(exc))
            finally:
                with self._dispatch_lock:
                    self._active_runs.pop(slot, None)

    def _reap_worker(self, process: mp.Process, group: WorkerGroup,
                     initial_grace_s: float) -> dict:
        def progress():
            self._touch()
        return reap_worker(process, group, initial_grace_s, self.settings.stop_grace_s,
                           on_progress=progress)

    def _verify_with_deadline(self, config, candidate, runtime, store=None):
        # Background Controller only; never executed in an HTTP request thread.
        # A late verifier cannot persist anything: only this owner finalizes.
        deadline = time.monotonic() + VERIFICATION_TIMEOUT_S
        context = (store or self.database).expected_certification_context()
        check_deadline(deadline)
        slot = getattr(self._slot_local, 'slot', 0)
        verification_slot = self._verification_slots[slot]
        if not verification_slot.acquire(blocking=False):
            raise ContinuousCertificationError(ExposureStatus.ERROR, "PREVIOUS_VERIFIER_STILL_RUNNING")
        result = queue.Queue(maxsize=1)
        def verify():
            try:
                with certification_runtime(deadline, context):
                    result.put((True, verify_candidate(config, candidate, runtime)))
            except BaseException as exc:
                result.put((False, exc))
            finally:
                verification_slot.release()
        thread = threading.Thread(target=verify, name="eos-continuous-verifier", daemon=True)
        with self._verification_lock:
            self._verification_threads[slot] = thread
        if slot == 0:
            self._verification_thread = thread
        thread.start()
        while not self._stop.is_set():
            self._touch()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ContinuousCertificationError(ExposureStatus.ERROR, "CERTIFICATION_TIMEOUT")
            try:
                ok, value = result.get(timeout=min(.05, remaining))
            except queue.Empty:
                continue
            check_deadline(deadline)
            if not ok:
                raise value
            plan, metrics, receipt = value
            if config.execution_mode in ('planning_preview', 'physical_validation'):
                if not isinstance(receipt, PreviewReceipt):
                    raise ValueError('missing Controller preview receipt')
                validate_preview(receipt.evidence(), config.model_dump(), plan)
                return plan, metrics, receipt, deadline
            if not isinstance(receipt, CertificationReceipt):
                raise ContinuousCertificationError(ExposureStatus.ERROR, "MISSING_CONTROLLER_RECEIPT")
            validate_certification(receipt.evidence(), run_id=config.run_id,
                                   scenario_sha=config.scenario_sha256, plan=plan, context=context)
            check_deadline(deadline)
            return plan, metrics, receipt, deadline
        thread.join(timeout=max(0.0, deadline-time.monotonic()))
        raise ContinuousCertificationError(ExposureStatus.ERROR, "CONTROLLER_STOP_DURING_CERTIFICATION")

    def _execute(self, config: RunConfig, attempt: int, store=None) -> None:
        store = store or self.database
        journal = self._journals[getattr(self._slot_local, 'slot', 0)]
        context = mp.get_context("spawn")
        event_recv, event_send = context.Pipe(duplex=False)
        control_recv, control_send = context.Pipe(duplex=False)
        process = context.Process(
            target=worker_main,
            args=(config.run_id, attempt, event_send, control_recv),
            name=f"eos-worker-{config.run_id[:8]}",
        )
        startup_started_at = time.monotonic()
        startup_deadline = startup_started_at + self.settings.startup_timeout_s
        reaped = False
        group: WorkerGroup | None = None
        try:
            process.start()
            group = WorkerGroup(process.pid)
            event_send.close()
            control_recv.close()
            reader = EventReader(event_recv)
            writer = ControlWriter(control_send)
            started_seen = False
            start_queued = False
            cancel_queued = False
            searching_at: float | None = None
            candidate: dict | None = None
            reported_runtime: float | None = None
            candidate_exit_deadline: float | None = None
            failure: tuple[str, str, str] | None = None
            stop_reason: str | None = None
            stop_deadline: float | None = None
            cancel_ack_received = False
            ipc_diagnostic: tuple[str, str] | None = None
            event_eof = False
            # W1 最多等待 2 秒；Controller 额外留出一次 IPC/调度宽限。
            cancel_grace_s = CANCEL_GRACE_S + self.settings.stop_grace_s
            while True:
                self._touch()
                group.refresh()
                if start_queued:
                    journal.capture(group, config.run_id, attempt)
                state = store.get_status(config.run_id)
                if not state or state["current_attempt"] != attempt:
                    failure = ("FAILED", "WORKER_STATE", "运行记录或 attempt 已变化")
                    break
                if state["status"] in {"CANCELLED", "FAILED", "TIMED_OUT"}:
                    failure = ("FAILED", "WORKER_STATE", "实验已处于终态")
                    break
                clock = time.monotonic()
                # 同一轮先看已持久化的用户取消，再判定墙钟超时；已锁定的理由不回退。
                if state["cancel_requested_at"] and stop_reason is None:
                    stop_reason = "USER_CANCEL"
                    stop_deadline = clock + cancel_grace_s
                if self._stop.is_set() and stop_reason is None:
                    stop_reason = "CONTROLLER_STOP"
                    stop_deadline = clock + cancel_grace_s
                if stop_deadline is not None and clock >= stop_deadline:
                    if writer.pending:
                        ipc_diagnostic = ("IPC_SEND_TIMEOUT", "取消控制消息未在协作期限内写完")
                    break
                if stop_reason is None and searching_at is None and clock >= startup_deadline:
                    if writer.pending:
                        failure = ("FAILED", "IPC_SEND_TIMEOUT", "Worker start 控制消息未在启动期限内写完")
                    elif not start_queued and started_seen:
                        failure = ("FAILED", "WORKER_IDENTITY_UNCONFIRMED", "Worker 启动身份未在期限内核验")
                    else:
                        failure = ("FAILED", "WORKER_STARTUP_TIMEOUT", "Worker 启动或加载超时")
                    break
                if stop_reason is None and searching_at is not None and candidate is None:
                    if clock >= searching_at + config.time_budget_s + self.settings.transfer_timeout_s:
                        stop_reason = "ALGORITHM_TIMEOUT"
                        stop_deadline = clock + cancel_grace_s
                if stop_reason is None and candidate_exit_deadline is not None and clock >= candidate_exit_deadline:
                    failure = ("FAILED", "WORKER_EXIT_TIMEOUT", "Worker 返回候选后未按期退出")
                    break
                # Worker 在 started 后等待 start；仅凭事件中的 PID/PGID 不足以放行。
                # 重新读取本次 Process 的内核身份，并要求 pidfd 固定组长 PID。
                leader = group.leader_current()
                if (stop_reason is None and started_seen and not start_queued
                        and clock < startup_deadline
                        and group.confirmed and group.leader_fd is not None
                        and leader is not None and leader.live
                        and leader.pgrp == process.pid and leader.sid == process.pid):
                    journal.capture(group, config.run_id, attempt)
                    try:
                        writer.enqueue({"kind": "start", "run_id": config.run_id,
                                        "attempt": attempt, "config": config.model_dump()},
                                       startup_deadline)
                        start_queued = True
                    except (IpcError, ValueError) as exc:
                        ipc_diagnostic = ("IPC_SEND_ERROR", str(exc))
                        break
                if stop_reason is not None and start_queued and not cancel_queued:
                    # 旧 start 没有 seq；本 attempt 首条完整控制命令仍使用 seq=1。
                    try:
                        writer.enqueue({
                            "protocol_version": PROTOCOL_VERSION, "run_id": config.run_id,
                            "attempt": attempt, "seq": 1, "kind": "cancel",
                            "sent_at": datetime.now(timezone.utc).isoformat(), "payload": {},
                        }, stop_deadline)
                        cancel_queued = True
                    except (IpcError, ValueError) as exc:
                        ipc_diagnostic = ("IPC_SEND_ERROR", str(exc))
                        break
                try:
                    writer.check_deadline(clock)
                    writer.pump()
                    if not event_eof:
                        reader.check_deadline(clock, self.settings.transfer_timeout_s)
                        message = reader.read_one()
                    else:
                        message = EOF
                except (IpcError, ValueError) as exc:
                    if isinstance(exc, IpcMessageTooLarge):
                        code = "IPC_MESSAGE_TOO_LARGE"
                    elif isinstance(exc, IpcTransferTimeout):
                        code = "IPC_TRANSFER_TIMEOUT"
                    elif isinstance(exc, IpcTransferInterrupted):
                        code = "IPC_TRANSFER_INTERRUPTED"
                    elif isinstance(exc, IpcSendTimeout):
                        code = "IPC_SEND_TIMEOUT"
                    elif isinstance(exc, IpcProtocolError):
                        code = "IPC_PROTOCOL_ERROR"
                    else:
                        code = "IPC_DISCONNECTED"
                    ipc_diagnostic = (code, str(exc))
                    if stop_reason is None:
                        failure = ("FAILED", code, str(exc))
                    break

                if message is EOF:
                    event_eof = True
                    if candidate is None and stop_reason is None:
                        failure = ("FAILED", "IPC_DISCONNECTED", "Worker 事件 Pipe 已关闭")
                        break
                elif message is not None:
                    if message["run_id"] != config.run_id or message["attempt"] != attempt:
                        continue
                    kind, payload = message["kind"], message["payload"]
                    if kind not in {"started", "heartbeat", "candidate_result", "failed", "cancel_ack"}:
                        failure = ("FAILED", "IPC_PROTOCOL_ERROR", f"未知 Worker 事件：{kind}")
                        break
                    if kind == "started" and payload.get("worker_pid") != process.pid:
                        failure = ("FAILED", "WORKER_IDENTITY", "Worker 身份与所启动进程不一致")
                        break
                    if kind != "started" and ("worker_pid" in payload or "worker_start_token" in payload):
                        failure = ("FAILED", "IPC_PROTOCOL_ERROR", "非 started 事件携带 Worker 身份字段")
                        break
                    if kind == "heartbeat" and not isinstance(payload.get("phase"), str):
                        failure = ("FAILED", "IPC_PROTOCOL_ERROR", "heartbeat 阶段字段错误")
                        break
                    if kind == "cancel_ack" and type(payload.get("accepted")) is not bool:
                        failure = ("FAILED", "IPC_PROTOCOL_ERROR", "cancel_ack 接受字段错误")
                        break
                    if kind == "failed" and (not isinstance(payload.get("code"), str)
                                             or not isinstance(payload.get("message"), str)):
                        failure = ("FAILED", "IPC_PROTOCOL_ERROR", "failed 载荷字段错误")
                        break
                    runtime: float | None = None
                    if kind == "candidate_result":
                        if not isinstance(payload.get("plan"), dict):
                            failure = ("FAILED", "IPC_PROTOCOL_ERROR", "候选计划结构错误")
                            break
                        try:
                            runtime = float(payload["algorithm_runtime_s"])
                        except (KeyError, TypeError, ValueError) as exc:
                            failure = ("FAILED", "IPC_PROTOCOL_ERROR", f"候选 runtime 错误：{exc}")
                            break
                        if not math.isfinite(runtime):
                            failure = ("FAILED", "IPC_PROTOCOL_ERROR", "候选 runtime 非有限数")
                            break
                    if not store.record_worker_event(message):
                        continue
                    if kind == "started":
                        started_seen = True
                    elif kind == "heartbeat" and payload.get("phase") == "SEARCHING" and searching_at is None:
                        searching_at = time.monotonic()
                    elif kind == "cancel_ack" and stop_reason is not None and payload.get("accepted") is True:
                        cancel_ack_received = True
                    elif kind == "candidate_result" and stop_reason is None:
                        if candidate is not None:
                            failure = ("FAILED", "IPC_PROTOCOL_ERROR", "Worker 重复发送候选计划")
                            break
                        candidate = payload["plan"]
                        reported_runtime = runtime
                        candidate_exit_deadline = time.monotonic() + self.settings.stop_grace_s
                    elif kind == "failed" and stop_reason is None:
                        failure = ("FAILED", str(payload.get("code", "WORKER_ERROR")),
                                   str(payload.get("message", "Worker 报告失败")))
                        break

                if not process.is_alive():
                    # 子进程退出后再读尽已有完整帧；不丢弃已发送的候选或失败事件。
                    if event_eof:
                        break
                    if message is None and reader.frame_started_at is None:
                        break
                time.sleep(0.01)

            if ipc_diagnostic is not None:
                store.record_system_event(config.run_id, attempt, "IPC_ERROR",
                                                  {"code": ipc_diagnostic[0], "message": ipc_diagnostic[1][:300]})
            grace = 0.0 if stop_reason is not None or candidate_exit_deadline is not None else self.settings.stop_grace_s
            reap = self._reap_worker(process, group, grace)
            reaped = True
            store.record_attempt_exit(config.run_id, attempt, reap["exit_code"],
                                              {"action": reap["action"], "alive": reap["alive"],
                                               "live_members": reap["live_members"],
                                               "identity_confirmed": reap["identity_confirmed"],
                                               "identity_failed": reap["identity_failed"],
                                               "scan_limited": reap["scan_limited"],
                                               "group_signals": reap["group_signals"],
                                               "member_signals": reap["member_signals"],
                                               "signal_errors": reap["signal_errors"],
                                               "reason": stop_reason or (failure[1] if failure else "NORMAL")})
            if not reap["identity_confirmed"]:
                store.record_system_event(config.run_id, attempt, "WORKER_IDENTITY",
                                                  {"code": "WORKER_IDENTITY_UNCONFIRMED",
                                                   "message": "本次 Worker 独立 Session 未经内核身份核验",
                                                   "direct_worker_exited": not reap["alive"]})
            if reap["alive"] or reap["live_members"] or reap["scan_limited"]:
                self._stop.set()  # do not dispatch more work with unowned survivors
                store.finish_failure(config.run_id, attempt, "FAILED", "WORKER_CLEANUP_INCOMPLETE", "Worker 或已识别后代未能确认退出")
                return
            journal.clear()
            if stop_reason == "USER_CANCEL":
                message = "用户取消运行" if cancel_ack_received else "用户取消运行；未收到 Worker 确认"
                store.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED", message)
                return
            if stop_reason == "ALGORITHM_TIMEOUT":
                store.finish_failure(config.run_id, attempt, "TIMED_OUT", "ALGORITHM_TIMEOUT", "算法运行或结果传输超过墙钟期限")
                return
            if stop_reason == "CONTROLLER_STOP" or self._stop.is_set():
                store.finish_failure(config.run_id, attempt, "FAILED", "CONTROLLER_STOP", "Controller 主动停机中断运行")
                return
            if failure:
                store.finish_failure(config.run_id, attempt, *failure)
                return
            if not reap["identity_confirmed"] or not start_queued:
                store.finish_failure(config.run_id, attempt, "FAILED",
                                             "WORKER_IDENTITY_UNCONFIRMED",
                                             "Worker 独立 Session 或 start 放行未能确认")
                return
            if candidate is None or reported_runtime is None:
                store.finish_failure(config.run_id, attempt, "FAILED", "WORKER_EXIT", f"Worker 未返回候选计划，退出码 {process.exitcode}")
                return
            if process.exitcode != 0:
                store.finish_failure(config.run_id, attempt, "FAILED", "WORKER_EXIT", f"Worker 返回计划后异常退出，退出码 {process.exitcode}")
                return
            if reported_runtime < 0 or reported_runtime > config.time_budget_s:
                store.finish_failure(config.run_id, attempt, "TIMED_OUT", "SEARCH_BUDGET", "算法搜索超过预算")
                return
            # 候选到达和 join 期间可能收到取消；事务检查仍负责最终裁决。
            state = store.get_status(config.run_id)
            if state and state["current_attempt"] == attempt and state["cancel_requested_at"]:
                store.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED", "用户取消运行")
                return
            if not store.set_verifying(config.run_id, attempt):
                store.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED_DURING_VERIFY", "核验前已取消")
                return
            verify_started = time.perf_counter()
            try:
                if store is self.database:
                    plan, metrics, receipt, certification_deadline = self._verify_with_deadline(config, candidate, reported_runtime)
                else:
                    plan, metrics, receipt, certification_deadline = self._verify_with_deadline(config, candidate, reported_runtime, store)
            except ContinuousCertificationError as exc:
                prefix = ('PHYSICS_' if config.execution_mode == 'physical_validation' else
                          'PREVIEW_' if config.execution_mode == 'planning_preview' else 'CONTINUOUS_')
                code = "CONTROLLER_STOP" if self._stop.is_set() else prefix + exc.status.value
                store.finish_failure(config.run_id, attempt, "FAILED", code, str(exc))
                return
            with self.finalization_lock:
                if self._stop.is_set():
                    store.finish_failure(config.run_id, attempt, "FAILED", "CONTROLLER_STOP", "Controller 停机中断核验")
                    return
                try:
                    check_deadline(certification_deadline)
                    if config.execution_mode in ('planning_preview', 'physical_validation'):
                        succeeded = store.finish_preview(config.run_id, attempt, plan, metrics,
                            time.perf_counter()-verify_started, receipt=receipt, deadline=certification_deadline)
                    else:
                        succeeded = store.finish_success(config.run_id, attempt, plan, metrics,
                            time.perf_counter() - verify_started, certification=receipt, deadline=certification_deadline)
                except ContinuousCertificationError as exc:
                    store.finish_failure(config.run_id, attempt, "FAILED", "CONTINUOUS_" + exc.status.value, str(exc))
                    return
                if not succeeded:
                    # 核验期间可能收到取消请求；成功事务会拒绝提交，此处补上明确终态。
                    store.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED_DURING_VERIFY", "核验期间已取消")
                else:
                    try:
                        if config.execution_mode in ('formal', 'physical_validation') and store is self.database:
                            persist_directory_exports(self.database, config)
                    except (OSError, ValueError) as exc:
                        # 正式计划已在库中提交，外部目录故障只记诊断事件，不篡改成功状态。
                        store.record_system_event(config.run_id, attempt, "EXPORT_FAILED", {"message": str(exc)[:300]})
        finally:
            if process.pid is not None and not reaped and group is not None:
                cleanup = self._reap_worker(process, group, 0)
                if not cleanup['alive'] and not cleanup['live_members'] and not cleanup['scan_limited']:
                    journal.clear()
                else:
                    self._stop.set()
            elif process.pid is not None and not reaped and process.is_alive():
                process.terminate()
                process.join(timeout=self.settings.stop_grace_s)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
            event_recv.close()
            event_send.close()
            control_send.close()
            control_recv.close()
            try:
                if process.pid is not None and not process.is_alive():
                    process.close()
            finally:
                if group is not None:
                    group.close()
