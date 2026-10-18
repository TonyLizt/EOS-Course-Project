"""Controller-owned crash journal; watchdog never reads or modifies business state.

Only kernel identities captured by the live Controller authorize signalling.
An unknown surviving session member blocks recovery rather than guessing ownership.
"""
from __future__ import annotations

import os
import signal
import time
from dataclasses import asdict
from pathlib import Path

from .process_state import atomic_json, matches, pinned_signal, read_json
from .worker_process import WorkerGroup, read_proc


class WorkerJournal:
    def __init__(self, runtime: Path):
        self.path = runtime / 'worker-lease.json'
        self.saved = None

    def capture(self, group: WorkerGroup, run_id: str, attempt: int) -> None:
        if not group.confirmed or group.leader is None or group.scan_limited:
            raise RuntimeError('WORKER_JOURNAL_IDENTITY_UNCONFIRMED')
        value = {'run_id': run_id, 'attempt': attempt, 'leader': asdict(group.leader),
                 'members': [asdict(item[0]) for item in group.members.values()]}
        if value != self.saved:
            atomic_json(self.path, value)  # must be durable BEFORE granting start
            self.saved = value

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.saved = None

    def recover(self, grace: float) -> None:
        if not self.path.exists():
            return
        saved = read_json(self.path)  # malformed/ambiguous journal fails closed
        leader = saved['leader']
        known = [leader, *saved['members']]
        if any(item['pid'] in {os.getpid(), os.getpgrp(), os.getsid(0)} for item in known):
            raise RuntimeError('WORKER_RECOVERY_UNSAFE_IDENTITY')
        group = None
        try:
            if matches(leader):
                current = read_proc(leader['pid'])
                if current.sid != leader['pid'] or current.pgrp != leader['pid']:
                    raise RuntimeError('WORKER_RECOVERY_SESSION_CHANGED')
                group = WorkerGroup(leader['pid'])
                group.refresh()
                if not group.confirmed or group.scan_limited:
                    raise RuntimeError('WORKER_RECOVERY_CANNOT_PIN_SESSION')
                known.extend(asdict(item[0]) for item in group.members.values())

            def scan() -> list[dict]:
                # No historical PGID signalling. With a dead leader only exact
                # journalled identities may be signalled; unknown members block.
                live = []
                for entry in Path('/proc').iterdir():
                    if not entry.name.isdecimal():
                        continue
                    proc = read_proc(int(entry.name))
                    if proc and proc.live and proc.boot_id == leader['boot_id'] and proc.sid == leader['pid']:
                        if not any(item['pid'] == proc.pid and item['starttime'] == proc.starttime for item in known):
                            raise RuntimeError('WORKER_RECOVERY_UNKNOWN_SESSION_MEMBER: manual investigation required')
                        live.append(asdict(proc))
                # Include journalled members even if they left their original session.
                return live + [item for item in known if matches(item)]

            for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 2.0)):
                targets = scan()
                if not targets:
                    self.clear()
                    return
                for item in targets:
                    pinned_signal(item, sig)
                deadline = time.monotonic() + wait
                while scan() and time.monotonic() < deadline:
                    time.sleep(.02)
            if scan():
                raise RuntimeError('WORKER_RECOVERY_INCOMPLETE')
            self.clear()
        finally:
            if group is not None:
                group.close()
