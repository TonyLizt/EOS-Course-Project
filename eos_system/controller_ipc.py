"""Controller 侧有界、非阻塞 Pipe 帧传输。

仅在 Linux Controller 进程中使用。帧沿用 multiprocessing.Connection 对不超过
4 MiB 的 send_bytes 消息使用的四字节网络序长度头；Worker 的协议和 Pipe 不变。
"""

from __future__ import annotations

import errno
import os
import struct
import time
from collections import deque
from multiprocessing.connection import Connection

from .worker_reference import MAX_MESSAGE_BYTES, decode_message_bytes, encode_message_bytes


class IpcError(Exception):
    """一次 attempt 的 IPC 错误；由 Controller 决定正式终态。"""


class IpcProtocolError(IpcError):
    pass


class IpcTransferInterrupted(IpcError):
    pass


class IpcMessageTooLarge(IpcError):
    pass


class IpcTransferTimeout(IpcError):
    pass


class IpcSendTimeout(IpcError):
    pass


EOF = object()


class EventReader:
    """事件 Pipe 的唯一读取者；每次调用只返回一条完整消息或 EOF。"""

    def __init__(self, connection: Connection):
        self.fd = connection.fileno()
        os.set_blocking(self.fd, False)
        self.header = bytearray()
        self.body = bytearray()
        self.expected: int | None = None
        self.frame_started_at: float | None = None

    def read_one(self):
        # 单次最多读取 1 MiB，防止事件洪泛饿死 Controller 的时钟检查。
        for _ in range(16):
            target = self.header if self.expected is None else self.body
            needed = (4 if self.expected is None else self.expected) - len(target)
            try:
                chunk = os.read(self.fd, min(65536, needed))
            except BlockingIOError:
                return None
            except OSError as exc:
                raise IpcError(f"事件 Pipe 读取失败：{exc}") from exc
            if not chunk:
                if self.header or self.expected is not None:
                    raise IpcTransferInterrupted("事件 Pipe 在消息帧中途关闭")
                return EOF
            if self.frame_started_at is None:
                self.frame_started_at = time.monotonic()
            target.extend(chunk)
            if self.expected is None and len(self.header) == 4:
                self.expected = struct.unpack("!i", self.header)[0]
                if self.expected < 0:
                    raise IpcProtocolError("事件消息帧长度为负数")
                if self.expected == 0:
                    raise IpcProtocolError("事件消息帧长度为零，缺少 JSON 消息")
                if self.expected > MAX_MESSAGE_BYTES:
                    raise IpcMessageTooLarge(f"事件消息长度超出 4 MiB 限额：{self.expected}")
            if self.expected is not None and len(self.body) == self.expected:
                data = bytes(self.body)
                self.header.clear()
                self.body.clear()
                self.expected = None
                self.frame_started_at = None
                try:
                    return decode_message_bytes(data)
                except ValueError as exc:
                    raise IpcProtocolError(str(exc)) from exc
        return None

    def check_deadline(self, now: float, timeout_s: float) -> None:
        if self.frame_started_at is not None and now - self.frame_started_at >= timeout_s:
            raise IpcTransferTimeout("事件消息帧未在传输期限内完成")


class ControlWriter:
    """控制 Pipe 的唯一写入者；start 与 cancel 按序排队，不阻塞状态循环。"""

    def __init__(self, connection: Connection):
        self.fd = connection.fileno()
        os.set_blocking(self.fd, False)
        self.pending: deque[tuple[bytes, float, str]] = deque()
        self.offset = 0

    def enqueue(self, message: dict, deadline: float) -> None:
        if len(self.pending) >= 2:
            raise IpcError("控制消息队列已满")
        data = encode_message_bytes(message)
        self.pending.append((struct.pack("!i", len(data)) + data, deadline, message["kind"]))

    def check_deadline(self, now: float) -> None:
        if self.pending and now >= self.pending[0][1]:
            raise IpcSendTimeout(f"{self.pending[0][2]} 控制消息未在期限内写完")

    def pump(self) -> None:
        # 大 start 消息可分段；每次最多写 1 MiB，其他事件仍有机会处理。
        for _ in range(16):
            if not self.pending:
                return
            frame, deadline, kind = self.pending[0]
            if time.monotonic() >= deadline:
                raise IpcSendTimeout(f"{kind} 控制消息未在期限内写完")
            try:
                count = os.write(self.fd, frame[self.offset:self.offset + 65536])
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno == errno.EPIPE:
                    raise IpcError("控制 Pipe 已断开") from exc
                raise IpcError(f"控制 Pipe 写入失败：{exc}") from exc
            if count <= 0:
                raise IpcError("控制 Pipe 写入无进展")
            self.offset += count
            if self.offset == len(frame):
                self.pending.popleft()
                self.offset = 0
