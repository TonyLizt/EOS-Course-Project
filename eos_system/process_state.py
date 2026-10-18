"""Small Linux process/sidecar primitives. No business database access."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import tempfile
from dataclasses import asdict
from pathlib import Path

from .worker_process import read_proc


def identity(pid: int) -> dict:
    value = read_proc(pid)
    if value is None:
        raise ProcessLookupError(pid)
    return asdict(value)


def matches(saved: dict) -> bool:
    current = read_proc(saved['pid'])
    return bool(current and current.live and current.boot_id == saved['boot_id']
                and current.starttime == saved['starttime'])


def pinned_signal(saved: dict, sig: int) -> bool:
    """Revalidate after pidfd_open: a PID file alone never grants signal authority."""
    if not matches(saved):
        return False
    try:
        fd = os.pidfd_open(saved['pid'], 0)
    except ProcessLookupError:
        return False
    try:
        if not matches(saved):
            return False
        try:
            signal.pidfd_send_signal(fd, sig)
        except ProcessLookupError:
            return False
        return True
    finally:
        os.close(fd)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def lock_held(path: Path) -> bool:
    try:
        stream = path.open('r')
    except FileNotFoundError:
        return False
    with stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
    return False
