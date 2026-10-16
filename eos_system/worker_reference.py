"""参考 Worker 的双单向 Pipe IPC 和协作取消入口。

Controller 仍负责发送取消、决定终态和强制回收；这些属于 W2。
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from pathlib import Path

from .config import sha256_file
from .contracts import RunConfig
from .runner import prepare, run_prepared


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
CONTROL_POLL_S = 0.05
CANCEL_GRACE_S = 2.0
_FIELDS = {"protocol_version", "run_id", "attempt", "seq", "kind", "sent_at", "payload"}


def _validate_message(message: object) -> dict:
    if not isinstance(message, dict):
        raise ValueError("IPC 消息必须是 JSON 对象")
    # v0.2.1 Controller 发送的 start 只有 kind/run_id/attempt/config。
    # 保留该格式，W2 可改用带完整信封且把 config 放在 payload 中的 start。
    if message.get("kind") == "start" and "protocol_version" not in message:
        if not isinstance(message.get("run_id"), str) or not message["run_id"]:
            raise ValueError("start 缺少有效 run_id")
        attempt = message.get("attempt")
        if type(attempt) is not int or attempt < 1 or not isinstance(message.get("config"), dict):
            raise ValueError("start 缺少有效 attempt/config")
        return message
    if not _FIELDS.issubset(message):
        raise ValueError("IPC 消息缺少协议字段")
    if type(message["protocol_version"]) is not int or message["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("IPC 协议版本不受支持")
    if not isinstance(message["run_id"], str) or not message["run_id"]:
        raise ValueError("IPC run_id 无效")
    if type(message["attempt"]) is not int or message["attempt"] < 1:
        raise ValueError("IPC attempt 无效")
    if type(message["seq"]) is not int or message["seq"] < 1:
        raise ValueError("IPC seq 无效")
    if not isinstance(message["kind"], str) or not message["kind"]:
        raise ValueError("IPC kind 无效")
    if not isinstance(message["payload"], dict):
        raise ValueError("IPC payload 必须是 JSON 对象")
    if not isinstance(message["sent_at"], str):
        raise ValueError("IPC sent_at 无效")
    try:
        sent_at = datetime.fromisoformat(message["sent_at"])
    except ValueError as exc:
        raise ValueError("IPC sent_at 无效") from exc
    if sent_at.tzinfo is None:
        raise ValueError("IPC sent_at 必须带时区")
    return message


def send_message(connection: Connection, message: dict) -> None:
    """在 Pipe 上只传 JSON 字节，保持参考实现的 4 MiB 限额。"""
    connection.send_bytes(encode_message_bytes(message))


def encode_message_bytes(message: dict) -> bytes:
    """供 Controller 的有界 Pipe 写入复用同一校验和 JSON 编码。"""
    _validate_message(message)
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC 消息超过参考 Worker 的 4 MiB 限额")
    return data


def receive_message(connection: Connection) -> dict:
    return decode_message_bytes(connection.recv_bytes(MAX_MESSAGE_BYTES))


def decode_message_bytes(data: bytes) -> dict:
    """供 Controller 的有界 Pipe 读取复用同一协议验证。"""
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("IPC 消息不是有效 JSON") from exc
    return _validate_message(message)


def _check_control(command: dict, run_id: str, attempt: int, expected_kind: str) -> None:
    if command["kind"] != expected_kind:
        raise ValueError("Worker 控制命令类型错误")
    if command["run_id"] != run_id or command["attempt"] != attempt:
        raise ValueError("控制消息与 Worker 身份不一致")


def worker_main(run_id: str, attempt: int, event_pipe: Connection, control_pipe: Connection) -> None:
    """一次进程只执行一个 attempt；主线程独占控制读取和事件写入。"""
    seq = 0
    cancelled = threading.Event()
    progress: queue.Queue[tuple[str, object]] = queue.Queue()

    def report(kind: str, payload: dict) -> None:
        nonlocal seq
        seq += 1
        send_message(event_pipe, {
            "protocol_version": PROTOCOL_VERSION, "run_id": run_id, "attempt": attempt, "seq": seq,
            "kind": kind, "sent_at": datetime.now(timezone.utc).isoformat(), "payload": payload,
        })

    try:
        if os.name == "posix":
            os.setsid()
        report("started", {"worker_pid": os.getpid(), "worker_start_token": str(uuid.uuid4()), "pgid": os.getpgrp(), "phase": "STARTING"})
        command = receive_message(control_pipe)
        _check_control(command, run_id, attempt, "start")
        raw_config = command.get("config") if "protocol_version" not in command else command["payload"].get("config")
        config = RunConfig.model_validate(raw_config)
        if config.run_id != run_id:
            raise ValueError("启动配置的 run_id 与 Worker 身份不一致")

        def execute() -> None:
            try:
                if sha256_file(Path(config.scenario_path)) != config.scenario_sha256:
                    raise ValueError("场景 SHA-256 不一致")
                solver, problem, constraints, context = prepare(config)
                context = replace(context, is_cancelled=cancelled.is_set)
                progress.put(("phase", "SEARCHING"))
                plan, runtime = run_prepared(solver, problem, constraints, context)
                progress.put(("result", (plan, runtime)))
            except BaseException as exc:
                progress.put(("error", exc))

        report("heartbeat", {"phase": "LOADING"})
        execution = threading.Thread(target=execute, name="eos-solve", daemon=True)
        execution.start()
        last_control_seq = command.get("seq", 0)
        cancel_deadline: float | None = None
        result: tuple[dict, float] | None = None
        while True:
            # 主线程是 control_pipe 唯一读取者，也是 event_pipe 唯一写入者。
            if control_pipe.poll(CONTROL_POLL_S):
                try:
                    command = receive_message(control_pipe)
                except EOFError as exc:
                    cancelled.set()
                    raise ConnectionError("Worker 控制 Pipe 已关闭") from exc
                _check_control(command, run_id, attempt, "cancel")
                if "protocol_version" not in command:
                    raise ValueError("cancel 必须使用完整协议字段")
                if command["seq"] > last_control_seq:
                    last_control_seq = command["seq"]
                    cancelled.set()
                    if cancel_deadline is None:
                        cancel_deadline = time.monotonic() + CANCEL_GRACE_S
                    report("cancel_ack", {"accepted": True})
            try:
                kind, value = progress.get_nowait()
            except queue.Empty:
                kind = ""
                value = None
            if kind == "phase":
                report("heartbeat", {"phase": value})
            elif kind == "error":
                if cancelled.is_set():
                    return
                raise value
            elif kind == "result":
                result = value

            if result is not None:
                # 已排队的取消优先于候选；发送前再次读取取消标记。
                if control_pipe.poll(0):
                    continue
                if cancelled.is_set():
                    return
                plan, runtime = result
                report("heartbeat", {"phase": "SERIALIZING"})
                if cancelled.is_set():
                    return
                report("candidate_result", {"plan": plan, "algorithm_runtime_s": runtime})
                return
            if cancel_deadline is not None and time.monotonic() >= cancel_deadline:
                # solve 不合作时不让 Worker 主流程无限等待；W2 负责后代进程回收。
                return
    except BaseException as exc:
        # 只上报受控摘要；详细堆栈可由系统运行日志查看，避免把本机路径送到浏览器。
        try:
            report("failed", {"code": type(exc).__name__, "message": str(exc)[:300]})
        except (BrokenPipeError, OSError, ValueError):
            pass
    finally:
        cancelled.set()
        event_pipe.close()
        control_pipe.close()
