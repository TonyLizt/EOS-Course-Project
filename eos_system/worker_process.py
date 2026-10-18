"""Linux Worker 身份核验及有界回收；不使用数据库中的历史 PID 发信号。"""

from __future__ import annotations

import os
import errno
import signal
import time
from dataclasses import dataclass
from pathlib import Path


MAX_GROUP_MEMBERS = 128


@dataclass(frozen=True)
class ProcIdentity:
    pid: int
    ppid: int
    pgrp: int
    sid: int
    state: str
    starttime: int
    boot_id: str

    @property
    def live(self) -> bool:
        return self.state not in {"Z", "X", "x"}


def parse_stat(raw: str, boot_id: str) -> ProcIdentity:
    """comm 可含空格和右括号；从最后一个 ') ' 后解析固定字段。"""
    end = raw.rfind(") ")
    if end < 0:
        raise ValueError("/proc stat 缺少 comm 结束符")
    pid = int(raw[:raw.find(" (")])
    fields = raw[end + 2:].split()
    if len(fields) < 20:
        raise ValueError("/proc stat 字段不足")
    return ProcIdentity(pid, int(fields[1]), int(fields[2]), int(fields[3]),
                        fields[0], int(fields[19]), boot_id)


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def read_proc(pid: int, current_boot_id: str | None = None) -> ProcIdentity | None:
    if pid <= 0:
        return None
    try:
        value = Path(f"/proc/{pid}/stat").read_text()
        identity = parse_stat(value, boot_id() if current_boot_id is None else current_boot_id)
    except (OSError, ValueError):
        return None
    return identity if identity.pid == pid else None


class WorkerGroup:
    """仅跟踪本次 Process 的 session；pidfd 固定每个可发信号的 PID。"""

    def __init__(self, pid: int):
        self.pid = pid
        try:
            self.boot_id = boot_id()
        except OSError:
            self.boot_id = ""
        self.leader = read_proc(pid, self.boot_id) if self.boot_id else None
        try:
            self.leader_fd = self._open_pidfd(pid) if self.leader else None
        except OSError:
            self.leader_fd = None
        if self.leader_fd is not None and not self._same(read_proc(pid, self.boot_id), self.leader):
            os.close(self.leader_fd)
            self.leader_fd = None
        self.controller_pgrp = os.getpgrp()
        self.controller_sid = os.getsid(0)
        self.confirmed = False
        self.identity_failed = self.leader is None
        self.members: dict[int, tuple[ProcIdentity, int]] = {}
        self.unpinned: dict[int, ProcIdentity] = {}
        self.scan_limited = False
        self.group_signals: list[str] = []
        self.member_signals: list[str] = []
        self.signal_errors: list[str] = []

    @staticmethod
    def _open_pidfd(pid: int) -> int | None:
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise OSError(errno.ENOSYS, "pidfd signalling is unavailable")
        try:
            return os.pidfd_open(pid, 0)
        except ProcessLookupError:
            # ESRCH is distinct from an active process whose identity cannot be pinned.
            return None

    @staticmethod
    def _same(current: ProcIdentity | None, saved: ProcIdentity) -> bool:
        return (current is not None and current.pid == saved.pid
                and current.starttime == saved.starttime and current.boot_id == saved.boot_id)

    def leader_current(self) -> ProcIdentity | None:
        current = read_proc(self.pid, self.boot_id)
        if self.leader and self._same(current, self.leader):
            return current
        if current is not None and self.leader is not None:
            self.identity_failed = True
        return None

    def _confirmed_gone(self, pid: int, saved: ProcIdentity) -> bool:
        current = read_proc(pid, self.boot_id)
        if current is not None:
            return not self._same(current, saved) or not current.live
        try:
            os.kill(pid, 0)  # existence check only; never sends a signal
        except ProcessLookupError:
            return True
        except OSError:
            pass  # permission or an unreadable /proc entry is ambiguous
        return False

    def refresh(self) -> None:
        for pid, saved in list(self.unpinned.items()):
            if self._confirmed_gone(pid, saved):
                del self.unpinned[pid]
        self.scan_limited = False
        leader = self.leader_current()
        safe_leader = (leader is not None and leader.live and leader.pgrp == self.pid
                       and leader.sid == self.pid and self.pid > 0
                       and self.pid not in {self.controller_pgrp, self.controller_sid})
        if safe_leader and self.leader_fd is not None:
            self.confirmed = True
        if not self.confirmed:
            self.scan_limited = bool(self.unpinned)
            return
        # A pinned leader PID anchors the session number even after the leader has
        # exited and been reaped. Use it only to discover members, never to killpg.
        # Without this anchor a stale PGID could belong to a different session.
        if not safe_leader and self.leader_fd is None:
            self.scan_limited = True
            return
        try:
            entries = os.scandir("/proc")
            with entries:
                for entry in entries:
                    if not entry.name.isdecimal():
                        continue
                    pid = int(entry.name)
                    if pid == self.pid or pid in self.members:
                        continue
                    current = read_proc(pid, self.boot_id)
                    if (current is None or not current.live or current.pgrp != self.pid
                            or current.sid != self.pid or current.starttime < self.leader.starttime):
                        continue
                    if len(self.members) >= MAX_GROUP_MEMBERS:
                        self.scan_limited = True
                        continue
                    try:
                        fd = self._open_pidfd(pid)
                    except OSError:
                        if not self._confirmed_gone(pid, current):
                            self.unpinned[pid] = current
                            self.scan_limited = True
                        continue
                    if fd is None:
                        # ESRCH can race with the /proc scan. A now absent or
                        # terminal process needs no signal and is not a leak.
                        if not self._confirmed_gone(pid, current):
                            self.unpinned[pid] = current
                            self.scan_limited = True
                        continue
                    # pidfd 已固定 PID 对象；再次确认进程没有在读取与打开之间复用。
                    if self._same(read_proc(pid, self.boot_id), current):
                        self.members[pid] = (current, fd)
                        self.unpinned.pop(pid, None)
                    else:
                        os.close(fd)
                        if not self._confirmed_gone(pid, current):
                            self.unpinned[pid] = current
                            self.scan_limited = True
        except OSError:
            self.scan_limited = True
        self.scan_limited = self.scan_limited or bool(self.unpinned)

    def live_members(self) -> list[int]:
        self.refresh()
        return [pid for pid, (saved, _) in self.members.items()
                if (current := read_proc(pid, self.boot_id)) is not None
                and self._same(current, saved) and current.live
                and current.pgrp == self.pid and current.sid == self.pid]

    def signal_group(self, sig: signal.Signals) -> bool:
        """组长当前仍可证明且 pidfd 钉住数字 PID 时才允许 killpg。"""
        self.refresh()
        current = self.leader_current()
        if (not self.confirmed or self.leader_fd is None or current is None
                or not current.live or current.pgrp != self.pid or current.sid != self.pid
                or self.pid <= 0 or self.pid in {self.controller_pgrp, self.controller_sid}):
            return False
        try:
            os.killpg(self.pid, sig)
            self.group_signals.append(sig.name)
            return True
        except ProcessLookupError:
            return False
        except OSError as exc:
            self.signal_errors.append(f"group:{sig.name}:{type(exc).__name__}")
            return False

    def signal_members(self, sig: signal.Signals) -> int:
        count = 0
        for pid in self.live_members():
            saved, fd = self.members[pid]
            current = read_proc(pid, self.boot_id)
            if (not self._same(current, saved) or not current.live
                    or current.pgrp != self.pid or current.sid != self.pid):
                continue
            try:
                signal.pidfd_send_signal(fd, sig)
                count += 1
            except ProcessLookupError:
                continue
            except OSError as exc:
                self.signal_errors.append(f"member:{sig.name}:{type(exc).__name__}")
        if count:
            self.member_signals.append(f"{sig.name}:{count}")
        return count

    def close(self) -> None:
        if self.leader_fd is not None:
            os.close(self.leader_fd)
            self.leader_fd = None
        for _, fd in self.members.values():
            os.close(fd)
        self.members.clear()
        self.unpinned.clear()


def reap_worker(process, group: WorkerGroup, initial_grace_s: float,
                term_grace_s: float, kill_grace_s: float = 2.0, *, on_progress=None) -> dict:
    """直接进程与已固定身份的同 session 成员均按固定时限回收。"""
    action = "exited"

    def wait(duration: float) -> None:
        deadline = time.monotonic() + max(0.0, duration)
        while True:
            if on_progress is not None:
                on_progress()  # real bounded wait progress, not a separate heartbeat thread
            group.refresh()
            if not process.is_alive() and not group.live_members():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            process.join(timeout=min(0.02, remaining))
            if not process.is_alive():
                time.sleep(min(0.02, remaining))

    wait(initial_grace_s)
    if process.is_alive() or group.live_members():
        action = "terminate"
        sent = group.signal_group(signal.SIGTERM)
        if not sent and process.is_alive():
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        group.signal_members(signal.SIGTERM)
        wait(term_grace_s)
    if process.is_alive() or group.live_members():
        action = "kill"
        sent = group.signal_group(signal.SIGKILL)
        if not sent and process.is_alive():
            try:
                process.kill()
            except ProcessLookupError:
                pass
        group.signal_members(signal.SIGKILL)
        wait(kill_grace_s)
    process.join(timeout=0)
    live = group.live_members()
    return {"action": action, "exit_code": process.exitcode, "alive": process.is_alive(),
            "live_members": len(live), "identity_confirmed": group.confirmed,
            "identity_failed": group.identity_failed, "scan_limited": group.scan_limited,
            "group_signals": group.group_signals, "member_signals": group.member_signals,
            "signal_errors": group.signal_errors[:8]}
