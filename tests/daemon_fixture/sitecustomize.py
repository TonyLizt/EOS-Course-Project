"""Opt-in subprocess fixture, imported ONLY through the tests' PYTHONPATH.

Uses the real API, Controller, spawn IPC, SQLite and watchdog. No real solver or
physical certification is claimed; Workers wait for cancellation/fault injection.
"""
import os

if os.environ.get('EOS_DAEMON_FIXTURE') in {'1', 'native'}:
    import time
    from pathlib import Path
    from eos_system import controller
    from eos_system.storage import Database
    from daemon_worker import waiting_worker, loading_prepare

    if os.environ['EOS_DAEMON_FIXTURE'] == 'native':
        from eos_system import worker_reference
        worker_reference.prepare = loading_prepare
    else:
        controller.worker_main = waiting_worker
    original_next = Database.next_queued

    def next_queued(self):
        while (Path(os.environ['EOS_RUNTIME_DIR']) / 'hang-dispatch').exists():
            time.sleep(.05)
        return original_next(self)

    Database.next_queued = next_queued
    if os.environ.get('EOS_DAEMON_SLOW_STOP') == '1':
        from eos_system.replay_service import ReplayService
        original_close = ReplayService.close
        def slow_close(self):
            time.sleep(2)  # exceeds multiple failed HTTP probes; must NOT restart
            return original_close(self)
        ReplayService.close = slow_close
