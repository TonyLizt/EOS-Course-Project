"""实验队列和参考 Worker 的 Controller。

持久排队以 SQLite 为准；本线程只负责串行取件，避免内存队列在重启后丢任务。
"""

from __future__ import annotations

import fcntl
import math
import multiprocessing as mp
import os
import threading
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
from .verification import verify_candidate
from .worker_reference import CANCEL_GRACE_S, PROTOCOL_VERSION, worker_main
from .worker_process import WorkerGroup, reap_worker


class Controller:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self._stop = threading.Event()
        self._dispatch_lock = threading.Lock()
        # 终态写入及目录导出期间，API 删除须等待，避免刚成功就被删导致导出写入悬空。
        self.finalization_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._lock_file = None
        self._shutdown_timeout_s = max(10.0, CANCEL_GRACE_S + 3 * settings.stop_grace_s + 3)
        self.instance_id = f"{os.getpid()}-{int(time.time())}"

    def start(self) -> None:
        """单实例文件锁与数据库恢复由 Controller 在启动时完成。"""
        # spawn 子进程会继承环境变量；固定哈希种子可消除集合迭代的跨进程差异。
        os.environ.setdefault("PYTHONHASHSEED", "0")
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        if self._lock_file is not None:
            raise RuntimeError("Controller 已启动")
        self._stop.clear()
        self._lock_file = self.settings.lock_path.open("a+")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.database.recover_interrupted()
            self._thread = threading.Thread(target=self._loop, name="eos-controller", daemon=True)
            self._thread.start()
        except BaseException as exc:
            if self._thread is not None and self._thread.is_alive():
                self._stop.set()
                self._thread.join(timeout=self._shutdown_timeout_s)
                if self._thread.is_alive():
                    raise RuntimeError("Controller 启动异常后线程仍存活；实例锁仍保留") from exc
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None
            self._thread = None
            if isinstance(exc, BlockingIOError):
                raise RuntimeError("已有 Controller 正在使用此运行目录") from exc
            raise

    def stop(self) -> None:
        self._stop.set()
        # 与 start_attempt 串行：一旦取得锁，后续不会再领取新 attempt。
        if not self._dispatch_lock.acquire(timeout=max(1.0, self.settings.stop_grace_s)):
            raise RuntimeError("Controller 停机未能等待任务领取结束；实例锁仍保留")
        self._dispatch_lock.release()
        if self._thread:
            self._thread.join(timeout=self._shutdown_timeout_s)
            if self._thread.is_alive():
                raise RuntimeError("Controller 执行线程尚未退出；实例锁仍保留")
        if self._lock_file:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            queued = self.database.next_queued()
            if queued is None:
                self._stop.wait(0.2)
                continue
            with self._dispatch_lock:
                if self._stop.is_set():
                    break
                started = self.database.start_attempt(queued["run_id"])
            if started is None:
                continue
            attempt, config_data = started
            try:
                self._execute(RunConfig.model_validate(config_data), attempt)
            except BaseException as exc:
                # 队列线程不能因单次实验故障而退出，否则后续 QUEUED 将无人处理。
                self.database.finish_failure(queued["run_id"], attempt, "FAILED", type(exc).__name__, str(exc))

    def _reap_worker(self, process: mp.Process, group: WorkerGroup,
                     initial_grace_s: float) -> dict:
        return reap_worker(process, group, initial_grace_s, self.settings.stop_grace_s)

    def _execute(self, config: RunConfig, attempt: int) -> None:
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
                group.refresh()
                state = self.database.get_status(config.run_id)
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
                    if not self.database.record_worker_event(message):
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
                self.database.record_system_event(config.run_id, attempt, "IPC_ERROR",
                                                  {"code": ipc_diagnostic[0], "message": ipc_diagnostic[1][:300]})
            grace = 0.0 if stop_reason is not None or candidate_exit_deadline is not None else self.settings.stop_grace_s
            reap = self._reap_worker(process, group, grace)
            reaped = True
            self.database.record_attempt_exit(config.run_id, attempt, reap["exit_code"],
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
                self.database.record_system_event(config.run_id, attempt, "WORKER_IDENTITY",
                                                  {"code": "WORKER_IDENTITY_UNCONFIRMED",
                                                   "message": "本次 Worker 独立 Session 未经内核身份核验",
                                                   "direct_worker_exited": not reap["alive"]})
            if reap["alive"] or reap["live_members"] or reap["scan_limited"]:
                self.database.finish_failure(config.run_id, attempt, "FAILED", "WORKER_CLEANUP_INCOMPLETE", "Worker 或已识别后代未能确认退出")
                return
            if stop_reason == "USER_CANCEL":
                message = "用户取消运行" if cancel_ack_received else "用户取消运行；未收到 Worker 确认"
                self.database.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED", message)
                return
            if stop_reason == "ALGORITHM_TIMEOUT":
                self.database.finish_failure(config.run_id, attempt, "TIMED_OUT", "ALGORITHM_TIMEOUT", "算法运行或结果传输超过墙钟期限")
                return
            if stop_reason == "CONTROLLER_STOP" or self._stop.is_set():
                self.database.finish_failure(config.run_id, attempt, "FAILED", "CONTROLLER_STOP", "Controller 主动停机中断运行")
                return
            if failure:
                self.database.finish_failure(config.run_id, attempt, *failure)
                return
            if not reap["identity_confirmed"] or not start_queued:
                self.database.finish_failure(config.run_id, attempt, "FAILED",
                                             "WORKER_IDENTITY_UNCONFIRMED",
                                             "Worker 独立 Session 或 start 放行未能确认")
                return
            if candidate is None or reported_runtime is None:
                self.database.finish_failure(config.run_id, attempt, "FAILED", "WORKER_EXIT", f"Worker 未返回候选计划，退出码 {process.exitcode}")
                return
            if process.exitcode != 0:
                self.database.finish_failure(config.run_id, attempt, "FAILED", "WORKER_EXIT", f"Worker 返回计划后异常退出，退出码 {process.exitcode}")
                return
            if reported_runtime < 0 or reported_runtime > config.time_budget_s:
                self.database.finish_failure(config.run_id, attempt, "TIMED_OUT", "SEARCH_BUDGET", "算法搜索超过预算")
                return
            # 候选到达和 join 期间可能收到取消；事务检查仍负责最终裁决。
            state = self.database.get_status(config.run_id)
            if state and state["current_attempt"] == attempt and state["cancel_requested_at"]:
                self.database.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED", "用户取消运行")
                return
            if not self.database.set_verifying(config.run_id, attempt):
                self.database.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED_DURING_VERIFY", "核验前已取消")
                return
            verify_started = time.perf_counter()
            plan, metrics = verify_candidate(config, candidate, reported_runtime)
            with self.finalization_lock:
                if self._stop.is_set():
                    self.database.finish_failure(config.run_id, attempt, "FAILED", "CONTROLLER_STOP", "Controller 停机中断核验")
                    return
                if not self.database.finish_success(config.run_id, attempt, plan, metrics, time.perf_counter() - verify_started):
                    # 核验期间可能收到取消请求；成功事务会拒绝提交，此处补上明确终态。
                    self.database.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED_DURING_VERIFY", "核验期间已取消")
                else:
                    try:
                        persist_directory_exports(self.database, config)
                    except (OSError, ValueError) as exc:
                        # 正式计划已在库中提交，外部目录故障只记诊断事件，不篡改成功状态。
                        self.database.record_system_event(config.run_id, attempt, "EXPORT_FAILED", {"message": str(exc)[:300]})
        finally:
            if process.pid is not None and not reaped and group is not None:
                self._reap_worker(process, group, 0)
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
