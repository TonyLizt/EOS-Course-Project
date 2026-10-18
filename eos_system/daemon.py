"""Independent Linux watchdog for the single FastAPI/Controller service process.

Usage: python -m eos_system.daemon {start,run,status,stop} --help
No SQLite imports, Worker restart logic, shell commands or public HTTP controls.
"""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.request import build_opener, ProxyHandler
import uuid

from .config import Settings
from .process_state import atomic_json, identity, lock_held, matches, pinned_signal, read_json


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def conflict(runtime: Path) -> None:
    # Separate bounded last-event sidecar: never overwrite the live owner's status
    # or race its rotating log handler from a competing process.
    atomic_json(runtime / 'daemon-conflict.json',
                {'time': utc(), 'event': 'DAEMON_LOCK_CONFLICT', 'pid': os.getpid()})


@dataclass(frozen=True)
class Policy:
    interval: float = 1.
    request_timeout: float = 2.
    startup_grace: float = 45.
    progress_timeout: float = 20.
    failures: int = 3
    max_restarts: int = 3
    backoff: float = 2.
    backoff_cap: float = 30.
    stop_grace: float = 25.

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if not math.isfinite(value) or (value < 0 if key == 'max_restarts' else value <= 0):
                raise ValueError(f'{key}: expected finite positive value (max_restarts may be 0)')

    def delay(self, attempt: int) -> float:
        # Avoid unbounded integer exponentiation even with a large configured limit.
        return min(self.backoff_cap, self.backoff * 2. ** min(attempt - 1, 30))


class Watchdog:
    def __init__(self, runtime: Path, port: int, policy: Policy):
        policy.validate()
        self.runtime, self.port, self.policy = runtime, port, policy
        self.lock_path = runtime / 'daemon.lock'
        self.status_path = runtime / 'daemon-status.json'
        self.stop_event = threading.Event()
        self.child = None
        self.child_identity = None
        self.child_token = None
        self.log_thread = None
        self.state = {'daemon': identity(os.getpid()), 'controller': None,
                      'state': 'STARTING', 'port': port, 'restarts': 0,
                      'policy': asdict(policy), 'started_at': utc(),
                      'last_healthy_at': None, 'last_event': None}
        self.http = build_opener(ProxyHandler({}))  # loopback only; never env proxy
        self.logger = logging.getLogger(f'eos.daemon.{id(self)}')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    def event(self, kind: str, **detail) -> None:
        self.state['last_event'] = {'time': utc(), 'event': kind, **detail}
        self.logger.info(json.dumps(self.state['last_event'], ensure_ascii=False))
        self.publish()

    def publish(self) -> None:
        atomic_json(self.status_path, self.state)

    def healthy(self) -> bool:
        try:
            with self.http.open(f'http://127.0.0.1:{self.port}/api/health', timeout=self.policy.request_timeout) as response:
                data = json.loads(response.read(65536))
            beat = data['controller']
            saved = beat['process']
            own = self.child_identity
            valid = (own is not None and all(saved[key] == own[key] for key in ('pid', 'boot_id', 'starttime'))
                     and beat['dispatch_alive'] and not beat['stopping']
                     and math.isfinite(beat['progress_age_s'])
                     and 0 <= beat['progress_age_s'] <= self.policy.progress_timeout
                     and data['status'] == 'ok' and matches(own))
            if valid:
                self.state['last_healthy_at'] = utc()
                self.state['controller_instance_id'] = data['controller_instance_id']
            return bool(valid)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def launch(self) -> None:
        if lock_held(self.runtime / 'controller.lock'):
            raise RuntimeError('EXTERNAL_CONTROLLER: runtime already locked; will not adopt or signal it')
        self.child_token = uuid.uuid4().hex
        env = {**os.environ, 'EOS_RUNTIME_DIR': str(self.runtime), 'EOS_PORT': str(self.port),
               'EOS_SUPERVISION_TOKEN': self.child_token, 'PYTHONUNBUFFERED': '1'}
        project = Path(__file__).resolve().parent.parent
        self.child = subprocess.Popen([sys.executable, '-m', 'eos_system'], cwd=project, env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, start_new_session=True)
        self.child_identity = identity(self.child.pid)
        self.state.update(controller=self.child_identity, state='STARTING')
        # Output draining is a helper thread, NOT the independent watchdog itself.
        child, stream = self.child, self.child.stdout
        def drain():
            try:
                for line in iter(lambda: stream.readline(8192), b''):
                    self.logger.info('controller[%s] %s', child.pid, line.decode(errors='replace').rstrip())
            finally:
                stream.close()
        self.log_thread = threading.Thread(target=drain, name='controller-log', daemon=True)
        self.log_thread.start()
        self.event('CONTROLLER_STARTED', pid=self.child.pid, token=self.child_token)

    def orderly_exit(self, filename: str = 'controller-stopped.json') -> bool:
        try:
            marker = read_json(self.runtime / filename)
            return (marker['token'] == self.child_token
                    and all(marker['process'][key] == self.child_identity[key]
                            for key in ('pid', 'boot_id', 'starttime')))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def terminate_child(self) -> bool:
        if self.child is None or self.child.poll() is not None:
            return True
        pinned_signal(self.child_identity, signal.SIGTERM)
        # A stopped process cannot handle TERM until continued.
        pinned_signal(self.child_identity, signal.SIGCONT)
        try:
            self.child.wait(timeout=self.policy.stop_grace)
        except subprocess.TimeoutExpired:
            self.event('CONTROLLER_KILL_ESCALATION', pid=self.child.pid)
            pinned_signal(self.child_identity, signal.SIGKILL)
            try:
                self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return False  # never launch a second controller beside an unkillable one
        return True

    def reap_adopted(self) -> None:
        # Subreaper only wait()s exited orphans. It NEVER signals/restarts Workers.
        path = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children')
        for value in path.read_text().split():
            pid = int(value)
            if self.child is not None and pid == self.child.pid:
                continue
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass

    def run(self) -> int:
        self.runtime.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open('a+') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                conflict(self.runtime)
                print('已有 Daemon 使用此运行目录；不启动第二个实例', file=sys.stderr)
                return 2
            handler = RotatingFileHandler(self.runtime / 'daemon.log', maxBytes=1024*1024,
                                          backupCount=3, encoding='utf-8')
            self.logger.addHandler(handler)
            try:
                # Linux/WSL subreaper prevents orphan zombies on hosts with a non-reaping PID1.
                libc = ctypes.CDLL(None, use_errno=True)
                if libc.prctl(36, 1, 0, 0, 0) != 0:
                    raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER failed')
                for sig in (signal.SIGTERM, signal.SIGINT):
                    signal.signal(sig, lambda *_: self.stop_event.set())
                self.event('DAEMON_STARTED')
                self.launch()
                started = previous = time.monotonic()
                failures = 0
                ready = False
                orderly_since = None
                while not self.stop_event.is_set():
                    self.reap_adopted()
                    current = time.monotonic()
                    if current - previous > max(5., self.policy.interval * 4 + self.policy.request_timeout * 2):
                        # WSL resume / scheduler suspension: do not count the gap as failed probes.
                        started, failures, ready = current, 0, False
                        self.event('MONITOR_RESUMED_GRACE')
                    previous = current
                    code = self.child.poll()
                    if self.orderly_exit('controller-stopping.json'):
                        if orderly_since is None:
                            orderly_since = current
                            self.state['state'] = 'STOPPING'
                            self.event('CONTROLLER_SHUTDOWN_INTENT')
                        if code is None and current - orderly_since < self.policy.stop_grace:
                            self.stop_event.wait(self.policy.interval)
                            continue
                        if code is None:
                            self.terminate_child()
                        completed = self.orderly_exit()
                        self.state['state'] = 'STOPPED' if completed else 'BLOCKED'
                        self.event('CONTROLLER_ORDERLY_STOP' if completed else 'CONTROLLER_SHUTDOWN_INCOMPLETE')
                        return 0 if completed else 2  # explicit stop NEVER triggers restart
                    if code is not None:
                        if self.orderly_exit():
                            self.event('CONTROLLER_ORDERLY_STOP', exit_code=code)
                            self.state['state'] = 'STOPPED'
                            return 0
                        reason = f'CONTROLLER_EXIT:{code}'
                    elif self.healthy():
                        if not ready:
                            self.event('CONTROLLER_HEALTHY', recovered=self.state['restarts'] > 0)
                        ready, failures = True, 0
                        self.state['state'] = 'HEALTHY'
                        self.publish()
                        self.stop_event.wait(self.policy.interval)
                        continue
                    else:
                        failures += 1
                        expired = current - started >= self.policy.startup_grace
                        if (not ready and not expired) or failures < self.policy.failures:
                            self.stop_event.wait(self.policy.interval)
                            continue
                        reason = 'HEARTBEAT_TIMEOUT' if ready else 'STARTUP_TIMEOUT'
                    self.event(reason, consecutive_failures=failures)
                    self.state['state'] = 'RECOVERING'
                    if not self.terminate_child():
                        raise RuntimeError('CONTROLLER_UNKILLABLE: recovery blocked')
                    self.reap_adopted()
                    if self.state['restarts'] >= self.policy.max_restarts:
                        self.state['state'] = 'EXHAUSTED'
                        self.event('RESTART_LIMIT_REACHED')
                        return 3
                    self.state['restarts'] += 1
                    delay = self.policy.delay(self.state['restarts'])
                    self.state['state'] = 'BACKOFF'
                    self.event('RECOVERY_ATTEMPT', attempt=self.state['restarts'], delay_s=delay)
                    if self.stop_event.wait(delay):
                        break
                    self.launch()
                    started = time.monotonic()
                    ready, failures = False, 0
                    orderly_since = None
                self.state['state'] = 'STOPPING'
                self.event('DAEMON_STOP_REQUESTED')
                if not self.terminate_child():
                    raise RuntimeError('CONTROLLER_UNKILLABLE: shutdown incomplete')
                self.state['state'] = 'STOPPED'
                self.event('DAEMON_STOPPED')
                return 0
            except BaseException as exc:
                self.state['state'] = 'BLOCKED'
                self.event('DAEMON_ERROR', reason=f'{type(exc).__name__}: {exc}')
                # Only our child, never a manually started service or a Worker.
                self.terminate_child()
                return 2
            finally:
                self.reap_adopted()
                self.publish()
                self.logger.removeHandler(handler)
                handler.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'run', 'status', 'stop'))
    parser.add_argument('--runtime-dir', type=Path, default=Settings.from_env().runtime_dir)
    parser.add_argument('--port', type=int, default=int(os.environ.get('EOS_PORT', '8765')))
    for name, field in Policy.__dataclass_fields__.items():
        parser.add_argument('--' + name.replace('_', '-'), type=int if name in {'failures','max_restarts'} else float,
                            default=field.default)
    args = parser.parse_args(argv)
    runtime = args.runtime_dir.expanduser().resolve()
    if runtime == Path('/') or (len(runtime.parts) > 2 and runtime.parts[1] == 'mnt'):
        parser.error('运行目录必须位于 Linux 文件系统，不可使用 / 或 /mnt 下的挂载目录')
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    policy = Policy(**{key: getattr(args, key) for key in Policy.__dataclass_fields__})
    try:
        policy.validate()
    except ValueError as exc:
        parser.error(str(exc))
    lock_path, status_path = runtime / 'daemon.lock', runtime / 'daemon-status.json'
    if args.command in {'stop', 'status'}:
        try:
            state = read_json(status_path)
            live = lock_held(lock_path) and matches(state['daemon'])
        except (OSError, ValueError, KeyError, TypeError):
            state, live = {}, False
        if args.command == 'status':
            print(json.dumps({**state, 'daemon_alive': live}, ensure_ascii=False, indent=2))
            return 0 if live else 1
        if not live:
            print('Daemon 未运行；未向任何历史 PID 发送信号')
            return 1
        pinned_signal(state['daemon'], signal.SIGTERM)
        deadline = time.monotonic() + state['policy']['stop_grace'] + state['policy']['request_timeout'] + 5
        while matches(state['daemon']) and lock_held(lock_path) and time.monotonic() < deadline:
            time.sleep(.05)
        return 0 if not lock_held(lock_path) else 2
    if args.command == 'start':
        if lock_held(lock_path):
            conflict(runtime)
            print('已有 Daemon 使用此运行目录', file=sys.stderr)
            return 2
        runtime.mkdir(parents=True, exist_ok=True)
        # Report readiness from the NEW identity, never from a stale status file.
        forwarded = ['run', '--runtime-dir', str(runtime), '--port', str(args.port)]
        for key, value in asdict(policy).items():
            forwarded.extend(['--' + key.replace('_', '-'), str(value)])
        child = subprocess.Popen([sys.executable, '-m', 'eos_system.daemon', *forwarded],
                                 cwd=Path(__file__).resolve().parent.parent,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        saved = identity(child.pid)
        deadline = time.monotonic() + 5
        while child.poll() is None and time.monotonic() < deadline:
            try:
                state = read_json(status_path)
                if state['daemon']['pid'] == child.pid and state['daemon']['starttime'] == saved['starttime']:
                    print(f'Daemon PID={child.pid}；状态：python -m eos_system.daemon status --runtime-dir {runtime}')
                    return 0
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.05)
        pinned_signal(saved, signal.SIGTERM)
        try:
            child.wait(timeout=policy.stop_grace + 3)
        except subprocess.TimeoutExpired:
            print('Daemon 启动确认超时；请检查 daemon.log', file=sys.stderr)
        return 2
    return Watchdog(runtime, args.port, policy).run()


if __name__ == '__main__':
    raise SystemExit(main())
