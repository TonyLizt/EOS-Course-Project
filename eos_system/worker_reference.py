"""可替换的最小参考 Worker。

负责真实独立进程和消息收发；完整取消、进程组与后代回收由何明涛模块接替。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from pathlib import Path

from .config import sha256_file
from .contracts import RunConfig
from .runner import prepare, run_prepared


MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def send_message(connection: Connection, message: dict) -> None:
    """在 Pipe 上只传 JSON 字节，避免向接收方反序列化任意 Python 对象。"""
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC 消息超过参考 Worker 的 4 MiB 限额")
    connection.send_bytes(data)


def receive_message(connection: Connection) -> dict:
    data = connection.recv_bytes(MAX_MESSAGE_BYTES)
    message = json.loads(data.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("IPC 消息必须是 JSON 对象")
    return message


def worker_main(run_id: str, attempt: int, event_pipe: Connection, control_pipe: Connection) -> None:
    """子进程入口：一次进程只执行一次实验 attempt。"""
    seq = 0

    def report(kind: str, payload: dict) -> None:
        nonlocal seq
        seq += 1
        send_message(event_pipe, {
            "protocol_version": 1, "run_id": run_id, "attempt": attempt, "seq": seq,
            "kind": kind, "sent_at": datetime.now(timezone.utc).isoformat(), "payload": payload,
        })

    try:
        if os.name == "posix":
            os.setsid()
        report("started", {"worker_pid": os.getpid(), "worker_start_token": str(uuid.uuid4()), "pgid": os.getpgrp(), "phase": "STARTING"})
        command = receive_message(control_pipe)
        if command.get("kind") != "start" or command.get("run_id") != run_id or command.get("attempt") != attempt:
            raise ValueError("启动消息与 Worker 身份不一致")
        config = RunConfig.model_validate(command["config"])
        report("heartbeat", {"phase": "LOADING"})
        if sha256_file(Path(config.scenario_path)) != config.scenario_sha256:
            raise ValueError("场景 SHA-256 不一致")
        engine, problem = prepare(config)
        report("heartbeat", {"phase": "SEARCHING"})
        plan, runtime = run_prepared(engine, problem)
        report("heartbeat", {"phase": "SERIALIZING"})
        report("candidate_result", {"plan": plan, "algorithm_runtime_s": runtime})
    except BaseException as exc:
        # 只上报受控摘要；详细堆栈可由系统运行日志查看，避免把本机路径送到浏览器。
        try:
            report("failed", {"code": type(exc).__name__, "message": str(exc)[:300]})
        except (BrokenPipeError, OSError, ValueError):
            pass
    finally:
        event_pipe.close()
        control_pipe.close()
