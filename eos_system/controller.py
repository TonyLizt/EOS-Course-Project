"""实验队列和参考 Worker 的 Controller。

持久排队以 SQLite 为准；本线程只负责串行取件，避免内存队列在重启后丢任务。
"""

from __future__ import annotations

import fcntl
import multiprocessing as mp
import os
import threading
import time

from .config import Settings
from .contracts import RunConfig
from .exporting import persist_directory_exports
from .storage import Database
from .verification import verify_candidate
from .worker_reference import receive_message, send_message, worker_main


class Controller:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_file = None
        self.instance_id = f"{os.getpid()}-{int(time.time())}"

    def start(self) -> None:
        """单实例文件锁与数据库恢复由 Controller 在启动时完成。"""
        # spawn 子进程会继承环境变量；固定哈希种子可消除集合迭代的跨进程差异。
        os.environ.setdefault("PYTHONHASHSEED", "0")
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = self.settings.lock_path.open("a+")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lock_file.close()
            raise RuntimeError("已有 Controller 正在使用此运行目录") from exc
        self.database.recover_interrupted()
        self._thread = threading.Thread(target=self._loop, name="eos-controller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
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
            started = self.database.start_attempt(queued["run_id"])
            if started is None:
                continue
            attempt, config_data = started
            try:
                self._execute(RunConfig.model_validate(config_data), attempt)
            except BaseException as exc:
                # 队列线程不能因单次实验故障而退出，否则后续 QUEUED 将无人处理。
                self.database.finish_failure(queued["run_id"], attempt, "FAILED", type(exc).__name__, str(exc))

    def _execute(self, config: RunConfig, attempt: int) -> None:
        context = mp.get_context("spawn")
        event_recv, event_send = context.Pipe(duplex=False)
        control_recv, control_send = context.Pipe(duplex=False)
        process = context.Process(
            target=worker_main,
            args=(config.run_id, attempt, event_send, control_recv),
            name=f"eos-worker-{config.run_id[:8]}",
        )
        try:
            process.start()
            event_send.close()
            control_recv.close()
            send_message(control_send, {"kind": "start", "run_id": config.run_id, "attempt": attempt, "config": config.model_dump()})
            started_at = time.monotonic()
            searching_at: float | None = None
            candidate: dict | None = None
            reported_runtime: float | None = None
            failure: tuple[str, str] | None = None
            while not self._stop.is_set():
                state = self.database.get_status(config.run_id)
                if not state or state["status"] in {"CANCELLED", "FAILED", "TIMED_OUT"}:
                    failure = ("CANCELLED", "实验已停止")
                    break
                if state["cancel_requested_at"]:
                    failure = ("CANCELLED", "用户取消运行")
                    break
                clock = time.monotonic()
                if searching_at is None and clock - started_at > self.settings.startup_timeout_s:
                    failure = ("STARTUP_TIMEOUT", "Worker 启动或加载超时")
                    break
                if searching_at is not None and clock - searching_at > config.time_budget_s + self.settings.transfer_timeout_s:
                    failure = ("TIMED_OUT", "算法运行或结果传输超时")
                    break
                if event_recv.poll(0.1):
                    try:
                        message = receive_message(event_recv)
                    except EOFError:
                        message = None
                    if message is None:
                        if not process.is_alive():
                            break
                        continue
                    if message.get("protocol_version") != 1 or message.get("run_id") != config.run_id or message.get("attempt") != attempt:
                        continue
                    if not self.database.record_worker_event(message):
                        continue
                    kind, payload = message["kind"], message["payload"]
                    if kind == "started" and payload.get("worker_pid") != process.pid:
                        failure = ("WORKER_IDENTITY", "Worker 身份与所启动进程不一致")
                        break
                    if kind == "heartbeat" and payload.get("phase") == "SEARCHING":
                        searching_at = time.monotonic()
                    elif kind == "candidate_result":
                        candidate = payload["plan"]
                        reported_runtime = float(payload["algorithm_runtime_s"])
                        break
                    elif kind == "failed":
                        failure = (payload.get("code", "WORKER_ERROR"), payload.get("message", "Worker 报告失败"))
                        break
                elif not process.is_alive():
                    # 退出后再尝试取一次尾部消息，避免把成功结果误判为断链。
                    if not event_recv.poll(0.1):
                        break

            process.join(timeout=self.settings.stop_grace_s)
            if process.is_alive():
                process.terminate()
                process.join(timeout=self.settings.stop_grace_s)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if failure:
                status = "CANCELLED" if failure[0] == "CANCELLED" else "TIMED_OUT" if "TIMEOUT" in failure[0] or failure[0] == "TIMED_OUT" else "FAILED"
                self.database.finish_failure(config.run_id, attempt, status, failure[0], failure[1])
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
            if not self.database.set_verifying(config.run_id, attempt):
                self.database.finish_failure(config.run_id, attempt, "CANCELLED", "CANCELLED_DURING_VERIFY", "核验前已取消")
                return
            verify_started = time.perf_counter()
            plan, metrics = verify_candidate(config, candidate, reported_runtime)
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
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            event_recv.close()
            control_send.close()
