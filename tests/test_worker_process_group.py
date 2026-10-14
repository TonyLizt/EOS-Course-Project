"""W2-C Linux 身份与回收测试；仅向本测试创建的进程发真实信号。"""

import dataclasses
import errno
import multiprocessing as mp
import os
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from eos_system.worker_process import WorkerGroup, parse_stat, read_proc, reap_worker


def _session_worker(pipe, before_setsid=False):
    if before_setsid:
        pipe.send(("before", os.getpid()))
        time.sleep(0.6)
    os.setsid()
    pipe.send(("ready", os.getpid()))
    pipe.close()
    time.sleep(6)


def _worker_with_child(pipe, leader_exits):
    os.setsid()
    child = subprocess.Popen([
        sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(6)",
    ], close_fds=True)
    time.sleep(0.15)  # 子进程先安装 SIGTERM 处理器，再通知测试端。
    pipe.send((os.getpid(), child.pid))
    if leader_exits:
        pipe.recv()  # 测试端先在组长存活时固定后代 pidfd。
        os._exit(0)
    time.sleep(6)


def _worker_with_unseen_child(pipe, crash):
    os.setsid()
    pipe.send(("ready", os.getpid()))
    pipe.recv()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(6)"],
                             close_fds=True)
    pipe.send(("child", child.pid))
    if crash:
        os._exit(23)
    pipe.recv()
    child.terminate()
    child.wait(timeout=2)
    pipe.send(("reaped", child.pid))
    time.sleep(0.2)


class WorkerIdentityTests(unittest.TestCase):
    def spawn(self, before_setsid=False):
        context = mp.get_context("spawn")
        recv, send = context.Pipe(duplex=False)
        process = context.Process(target=_session_worker, args=(send, before_setsid))
        process.start()
        send.close()
        guard = WorkerGroup(process.pid)
        self.addCleanup(self.cleanup_process, process, guard, recv)
        return process, guard, recv

    @staticmethod
    def cleanup_process(process, guard, recv):
        guard.signal_members(signal.SIGKILL)
        if process.is_alive():
            process.kill()
        process.join(timeout=2)
        if not process.is_alive():
            process.close()
        guard.close()
        recv.close()

    def test_stat_parser_accepts_comm_with_parentheses_and_spaces(self):
        fields = ["S", "11", "22", "33"] + ["0"] * 15 + ["445566"] + ["0"] * 5
        identity = parse_stat("123 (name ) with spaces) " + " ".join(fields), "boot")
        self.assertEqual((identity.pid, identity.ppid, identity.pgrp, identity.sid,
                          identity.starttime, identity.boot_id),
                         (123, 11, 22, 33, 445566, "boot"))

    def test_real_setsid_is_bound_to_process_identity(self):
        process, guard, recv = self.spawn()
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        current = read_proc(process.pid, guard.boot_id)
        self.assertTrue(guard.confirmed)
        self.assertEqual((current.pgrp, current.sid), (process.pid, process.pid))
        self.assertNotEqual(current.pgrp, os.getpgrp())
        self.assertEqual(current.starttime, guard.leader.starttime)

    def test_guard_close_releases_pidfd(self):
        process, guard, recv = self.spawn()
        self.assertEqual(recv.recv()[0], "ready")
        self.assertIsNotNone(guard.leader_fd)
        before = len(os.listdir("/proc/self/fd"))
        guard.close()
        self.assertLess(len(os.listdir("/proc/self/fd")), before)

    def test_before_setsid_has_no_group_signal(self):
        process, guard, recv = self.spawn(before_setsid=True)
        self.assertEqual(recv.recv()[0], "before")
        self.assertFalse(guard.signal_group(signal.SIGTERM))
        self.assertTrue(process.is_alive())
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        self.assertTrue(guard.confirmed)

    def test_cancel_before_setsid_uses_direct_process_fallback(self):
        process, guard, recv = self.spawn(before_setsid=True)
        self.assertEqual(recv.recv()[0], "before")
        result = reap_worker(process, guard, 0.0, 0.1, 0.5)
        self.assertFalse(result["alive"])
        self.assertEqual(result["group_signals"], [])
        self.assertEqual(result["action"], "terminate")

    def test_wrong_starttime_rejects_group_signal(self):
        process, guard, recv = self.spawn()
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        guard.leader = dataclasses.replace(guard.leader, starttime=guard.leader.starttime + 1)
        with patch("eos_system.worker_process.os.killpg") as killpg:
            self.assertFalse(guard.signal_group(signal.SIGTERM))
            killpg.assert_not_called()
        self.assertTrue(process.is_alive())

    def test_identity_failure_downgrades_to_direct_reap(self):
        process, guard, recv = self.spawn()
        self.assertEqual(recv.recv()[0], "ready")
        guard.leader = dataclasses.replace(guard.leader, starttime=guard.leader.starttime + 1)
        result = reap_worker(process, guard, 0.0, 0.1, 0.5)
        self.assertTrue(result["identity_failed"])
        self.assertEqual(result["group_signals"], [])
        self.assertFalse(result["alive"])

    def test_missing_boot_id_downgrades_without_group_signal(self):
        process, guard, recv = self.spawn()
        self.assertEqual(recv.recv()[0], "ready")
        with patch("eos_system.worker_process.boot_id", side_effect=OSError("test")):
            degraded = WorkerGroup(process.pid)
        try:
            result = reap_worker(process, degraded, 0.0, 0.1, 0.5)
            self.assertTrue(result["identity_failed"])
            self.assertEqual(result["group_signals"], [])
            self.assertFalse(result["alive"])
        finally:
            degraded.close()

    def test_controller_group_number_is_never_signalled(self):
        process, guard, recv = self.spawn()
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        guard.pid = os.getpgrp()
        with patch("eos_system.worker_process.os.killpg") as killpg:
            self.assertFalse(guard.signal_group(signal.SIGTERM))
            killpg.assert_not_called()
        self.assertTrue(process.is_alive())

    def test_reap_real_isolated_worker(self):
        process, guard, recv = self.spawn()
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        result = reap_worker(process, guard, 0.0, 0.1, 0.5)
        self.assertEqual(result["action"], "terminate")
        self.assertFalse(result["alive"])
        self.assertIn("SIGTERM", result["group_signals"])

    def test_child_ignores_term_then_receives_verified_kill(self):
        context = mp.get_context("spawn")
        recv, send = context.Pipe(duplex=True)
        process = context.Process(target=_worker_with_child, args=(send, False))
        process.start()
        send.close()
        guard = WorkerGroup(process.pid)
        self.addCleanup(self.cleanup_process, process, guard, recv)
        _, child_pid = recv.recv()
        guard.refresh()
        self.assertIn(child_pid, guard.live_members())
        result = reap_worker(process, guard, 0.0, 0.1, 0.5)
        self.assertFalse(result["alive"])
        self.assertEqual(result["live_members"], 0)
        self.assertIn("SIGKILL", " ".join(result["member_signals"]))

    def test_leader_exit_still_allows_pinned_child_recovery(self):
        context = mp.get_context("spawn")
        recv, send = context.Pipe(duplex=True)
        process = context.Process(target=_worker_with_child, args=(send, True))
        process.start()
        send.close()
        guard = WorkerGroup(process.pid)
        self.addCleanup(self.cleanup_process, process, guard, recv)
        _, child_pid = recv.recv()
        guard.refresh()
        self.assertIn(child_pid, guard.live_members())
        recv.send("exit")
        process.join(timeout=2)
        self.assertFalse(process.is_alive())
        self.assertIn(child_pid, guard.live_members())
        self.assertFalse(guard.signal_group(signal.SIGKILL))
        result = reap_worker(process, guard, 0.0, 0.1, 0.5)
        self.assertEqual(result["live_members"], 0)
        self.assertNotIn("SIGKILL", result["group_signals"])

    def test_crashed_leader_discovers_unseen_child_after_reap(self):
        context = mp.get_context("spawn")
        recv, send = context.Pipe(duplex=True)
        process = context.Process(target=_worker_with_unseen_child, args=(send, True))
        process.start()
        send.close()
        guard = WorkerGroup(process.pid)
        self.addCleanup(self.cleanup_process, process, guard, recv)
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        self.assertTrue(guard.confirmed)
        self.assertEqual(guard.members, {})
        recv.send("create")
        _, child_pid = recv.recv()
        child_identity = read_proc(child_pid, guard.boot_id)
        self.assertIsNotNone(child_identity)
        child_fd = os.pidfd_open(child_pid, 0)
        self.addCleanup(os.close, child_fd)
        self.addCleanup(self._kill_test_child, child_pid, child_identity, child_fd)
        process.join(timeout=2)
        self.assertEqual(process.exitcode, 23)
        self.assertIn(child_pid, guard.live_members())
        self.assertFalse(guard.signal_group(signal.SIGTERM))
        result = reap_worker(process, guard, 0.0, 0.1, 0.5)
        self.assertEqual(result["live_members"], 0)
        self.assertEqual(result["group_signals"], [])
        self.assertFalse(result["scan_limited"])

    @staticmethod
    def _kill_test_child(pid, identity, fd):
        current = read_proc(pid, identity.boot_id)
        if current and current.live and current.starttime == identity.starttime:
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _track_test_child(self, pid, guard):
        identity = read_proc(pid, guard.boot_id)
        self.assertIsNotNone(identity)
        fd = os.pidfd_open(pid, 0)
        self.addCleanup(os.close, fd)
        self.addCleanup(self._kill_test_child, pid, identity, fd)

    def test_child_exits_between_scan_and_pidfd_open(self):
        context = mp.get_context("spawn")
        recv, send = context.Pipe(duplex=True)
        process = context.Process(target=_worker_with_unseen_child, args=(send, False))
        process.start()
        send.close()
        guard = WorkerGroup(process.pid)
        self.addCleanup(self.cleanup_process, process, guard, recv)
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        self.assertTrue(guard.confirmed)
        recv.send("create")
        _, child_pid = recv.recv()
        self._track_test_child(child_pid, guard)
        original_open = WorkerGroup._open_pidfd
        raced = []

        def open_after_child_exit(pid):
            if pid == child_pid:
                recv.send("reap")
                self.assertEqual(recv.recv(), ("reaped", child_pid))
                raced.append(pid)
            return original_open(pid)

        with patch.object(WorkerGroup, "_open_pidfd", side_effect=open_after_child_exit):
            guard.refresh()
        self.assertEqual(raced, [child_pid])
        self.assertNotIn(child_pid, guard.members)
        self.assertFalse(guard.scan_limited)
        result = reap_worker(process, guard, 0.0, 0.1, 0.5)
        self.assertFalse(result["scan_limited"])
        self.assertEqual(result["live_members"], 0)

    def test_live_unpinned_child_risk_clears_after_confirmed_exit(self):
        context = mp.get_context("spawn")
        recv, send = context.Pipe(duplex=True)
        process = context.Process(target=_worker_with_unseen_child, args=(send, False))
        process.start()
        send.close()
        guard = WorkerGroup(process.pid)
        self.addCleanup(self.cleanup_process, process, guard, recv)
        self.assertEqual(recv.recv()[0], "ready")
        guard.refresh()
        recv.send("create")
        _, child_pid = recv.recv()
        self._track_test_child(child_pid, guard)
        original_open = WorkerGroup._open_pidfd

        def deny_child(pid):
            if pid == child_pid:
                raise PermissionError(errno.EPERM, "test pidfd denial")
            return original_open(pid)

        with patch.object(WorkerGroup, "_open_pidfd", side_effect=deny_child):
            guard.refresh()
        self.assertTrue(guard.scan_limited)
        self.assertIn(child_pid, guard.unpinned)
        recv.send("reap")
        self.assertEqual(recv.recv(), ("reaped", child_pid))
        guard.refresh()
        self.assertNotIn(child_pid, guard.unpinned)
        self.assertFalse(guard.scan_limited)


if __name__ == "__main__":
    unittest.main()
