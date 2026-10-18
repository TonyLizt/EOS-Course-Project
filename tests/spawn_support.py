"""Bounded startup-only allowance and crash-safe gates for actual spawn tests.

Measured DrvFS started latency was 2.81--4.24s (six runs). Keep a separate 8s
bootstrap ceiling; ordinary IPC/stop/identity deadlines remain unchanged.
"""
import math
import os
from pathlib import Path
import time

SPAWN_STARTUP_S = float(os.environ.get("EOS_TEST_SPAWN_STARTUP_S", "8"))
if not math.isfinite(SPAWN_STARTUP_S) or not 1 <= SPAWN_STARTUP_S <= 30:
    raise ValueError("EOS_TEST_SPAWN_STARTUP_S must be finite in [1,30]")


class ProcessGate:
    """One-way durable test witness, no semaphore lock abandoned by SIGKILL."""
    def __init__(self, path):
        self.path = Path(path)

    def set(self):
        self.path.touch(exist_ok=True)

    def is_set(self):
        return self.path.exists()

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.is_set():
            if time.monotonic() >= deadline:
                return False
            time.sleep(.005)
        return True
