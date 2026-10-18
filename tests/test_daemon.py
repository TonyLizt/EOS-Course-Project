"""Small real Linux subprocess fault demonstrations; never use the user's runtime."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from eos_system.daemon import Policy, Watchdog
from eos_system.process_state import atomic_json, identity, lock_held, matches, pinned_signal, read_json
from eos_system.worker_recovery import WorkerJournal


PROJECT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('timed out waiting for isolated test condition')


class IdentityTests(unittest.TestCase):
    def test_pid_reuse_identity_never_signalled(self):
        saved = identity(os.getpid())
        saved['starttime'] += 1
        with patch('signal.pidfd_send_signal') as send:
            self.assertFalse(pinned_signal(saved, signal.SIGTERM))
            send.assert_not_called()

    def test_policy_validation_and_backoff(self):
        self.assertEqual([Policy().delay(n) for n in range(1, 7)], [2, 4, 8, 16, 30, 30])
        for kwargs in ({'interval': 0}, {'request_timeout': float('nan')}, {'max_restarts': -1}):
            with self.assertRaises(ValueError):
                Policy(**kwargs).validate()
        Policy(max_restarts=0).validate()

    def test_health_checks_dispatch_not_just_live_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            dog = Watchdog(Path(directory), 19000, Policy(progress_timeout=2))
            dog.child_identity = identity(os.getpid())
            beat = {'status': 'ok', 'controller_instance_id': 'fixture', 'controller': {
                'process': dog.child_identity, 'dispatch_alive': True, 'stopping': False,
                'progress_age_s': 0}}
            with patch.object(dog.http, 'open') as request:
                response = request.return_value.__enter__.return_value
                for age, alive, expected in ((0, True, True), (3, True, False), (0, False, False)):
                    beat['controller'].update(progress_age_s=age, dispatch_alive=alive)
                    response.read.return_value = json.dumps(beat).encode()
                    self.assertEqual(dog.healthy(), expected)

    def test_external_controller_lock_blocks_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            with (runtime / 'controller.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with patch('subprocess.Popen') as launch:
                    with self.assertRaisesRegex(RuntimeError, 'EXTERNAL_CONTROLLER'):
                        Watchdog(runtime, 19000, Policy()).launch()
                    launch.assert_not_called()

    def test_unknown_orphan_blocks_without_signalling(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = WorkerJournal(Path(directory))
            leader = identity(os.getpid())
            leader['pid'] = 2147483000
            atomic_json(journal.path, {'leader': leader, 'members': []})
            from eos_system.worker_process import ProcIdentity
            unknown = ProcIdentity(123, 1, leader['pid'], leader['pid'], 'S', 3, leader['boot_id'])
            with patch('eos_system.worker_recovery.read_proc', return_value=unknown), \
                    patch('eos_system.worker_recovery.pinned_signal') as send:
                with self.assertRaisesRegex(RuntimeError, 'UNKNOWN_SESSION_MEMBER'):
                    journal.recover(.1)
                send.assert_not_called()
            self.assertTrue(journal.path.exists())

    def test_ambiguous_lease_cannot_certify_clean_shutdown(self):
        from eos_system.config import Settings
        from eos_system.controller import Controller
        from eos_system.storage import Database
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            controller = Controller(Settings(runtime, runtime / 'scenarios'), Database(runtime / 'results.sqlite3'))
            controller.start()
            try:
                # A lease pointing at this Controller must NEVER authorize a kill.
                atomic_json(controller.worker_journal.path, {'leader': identity(os.getpid()), 'members': []})
                with self.assertRaisesRegex(RuntimeError, 'UNSAFE_IDENTITY'):
                    controller.stop()
                self.assertTrue(lock_held(runtime / 'controller.lock'))
            finally:
                controller.worker_journal.clear()
                controller.stop()


@unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'pidfd_open'), 'Linux pidfd required')
class DaemonProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='eos-watchdog-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        self.scenarios = self.root / 'scenarios'
        self.scenarios.mkdir()
        with socket.socket() as stream:
            stream.bind(('127.0.0.1', 0))
            self.port = stream.getsockname()[1]
        self.env = {**os.environ, 'EOS_RUNTIME_DIR': str(self.runtime),
            'EOS_SCENARIO_DIR': str(self.scenarios), 'EOS_DAEMON_FIXTURE': '1',
            'PYTHONPATH': str(PROJECT / 'tests/daemon_fixture') + os.pathsep + str(PROJECT)}
        self.command = [sys.executable, '-m', 'eos_system.daemon', 'run',
            '--runtime-dir', str(self.runtime), '--port', str(self.port), '--interval', '.15',
            '--request-timeout', '.2', '--startup-grace', '12', '--progress-timeout', '.8',
            '--failures', '3', '--max-restarts', '2', '--backoff', '.3',
            '--backoff-cap', '.6', '--stop-grace', '6']
        self.dog = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        (self.runtime / 'hang-dispatch').unlink(missing_ok=True)
        if self.dog is not None and self.dog.poll() is None:
            self.dog.terminate()
            self.dog.wait(timeout=12)
        # Assert, don't kill unknown historical PIDs or touch other runtimes.
        self.assertFalse(lock_held(self.runtime / 'controller.lock'))
        if self.dog is not None:
            self.dog.stdout.close()

    def status(self):
        try:
            return read_json(self.runtime / 'daemon-status.json')
        except (OSError, ValueError):
            return {}

    def start(self):
        self.dog = subprocess.Popen(self.command, cwd=PROJECT, env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return wait_for(lambda: self.status() if self.status().get('state') == 'HEALTHY' else None)

    def seed_run(self):
        from eos_system.contracts import RunConfig
        from eos_system.storage import Database
        from datetime import datetime, timezone
        scene = self.scenarios / 'fixture.json'
        scene.write_text(json.dumps({'scenario_id': 'fixture', 'metadata': {'duration': 60},
                                    'satellites': [], 'missions': [], 'ground_stations': []}))
        run_id = str(uuid.uuid4())
        database = Database(self.runtime / 'results.sqlite3')
        database.enqueue(RunConfig(run_id=run_id, scenario_id='fixture',
            scenario_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(), scenario_path=str(scene),
            algorithm_id='completion_first', algorithm_version='baseline-1', time_budget_s=30,
            created_at=datetime.now(timezone.utc).isoformat()), max_queued=8)
        return database, run_id

    def enqueue(self):
        database, run_id = self.seed_run()
        lease = self.runtime / 'worker-lease.json'
        def lease_for_run():
            if not lease.exists():
                return None
            saved = read_json(lease)
            return saved if saved['run_id'] == run_id else None
        saved = wait_for(lease_for_run)
        wait_for(lambda: any(event['event_type'] == 'heartbeat' for event in database.get_run(run_id)['events']))
        return database, run_id, saved['leader']

    def test_crash_recovery_three_processes_and_worker_failure(self):
        self.env['EOS_DAEMON_FIXTURE_CHILD'] = '1'
        initial = self.start()
        database, run_id, worker = self.enqueue()
        descendants = wait_for(lambda: read_json(self.runtime / 'worker-lease.json')['members'])
        ps = subprocess.check_output(['ps', '-o', 'pid,ppid,stat,cmd', '-p',
            f"{self.dog.pid},{initial['controller']['pid']},{worker['pid']}"], text=True)
        print('\nPROCESS EVIDENCE\n' + ps, flush=True)
        _, queued_id = self.seed_run()
        self.assertEqual(database.get_run(queued_id)['status'], 'QUEUED')
        pinned_signal(initial['controller'], signal.SIGKILL)
        recovered = wait_for(lambda: self.status() if self.status().get('state') == 'HEALTHY'
                            and self.status().get('restarts') == 1 else None)
        self.assertIsNone(self.dog.poll())
        self.assertNotEqual(initial['controller']['pid'], recovered['controller']['pid'])
        wait_for(lambda: not matches(worker))
        for child in descendants:
            wait_for(lambda: not matches(child))
        record = database.get_run(run_id)
        self.assertEqual((record['status'], record['error']['code']), ('FAILED', 'CONTROLLER_RESTART'))
        self.assertIsNone(record['plan'])
        self.assertIsNone(record['metrics'])
        self.assertEqual(len(record['attempts']), 1)
        print(f"RECOVERY EVIDENCE daemon={self.dog.pid} old={initial['controller']['pid']} new={recovered['controller']['pid']} worker={worker['pid']} reaped", flush=True)
        # Worker fault stays a Controller responsibility; watchdog count remains 1.
        wait_for(lambda: database.get_run(queued_id)['status'] == 'RUNNING')
        lease = wait_for(lambda: read_json(self.runtime / 'worker-lease.json')
                         if (self.runtime / 'worker-lease.json').exists() else None)
        self.assertEqual(lease['run_id'], queued_id)
        worker, run_id = lease['leader'], queued_id
        pinned_signal(worker, signal.SIGKILL)
        wait_for(lambda: database.get_run(run_id)['status'] == 'FAILED')
        self.assertEqual(self.status()['restarts'], 1)
        self.assertIn(database.get_run(run_id)['error']['code'], {'WORKER_EXIT', 'IPC_DISCONNECTED'})
        self.assertEqual(len(database.get_run(run_id)['attempts']), 1)
        self.assertFalse((self.runtime / 'worker-lease.json').exists())

    def test_persistently_stopped_service_is_recovered(self):
        initial = self.start()
        pinned_signal(initial['controller'], signal.SIGSTOP)
        recovered = wait_for(lambda: self.status() if self.status().get('state') == 'HEALTHY'
                            and self.status().get('restarts') == 1 else None)
        self.assertNotEqual(initial['controller']['pid'], recovered['controller']['pid'])

    def test_dispatch_hang_short_delay_and_singleton(self):
        initial = self.start()
        duplicate = subprocess.run(self.command, cwd=PROJECT, env=self.env,
                                   capture_output=True, text=True, timeout=5)
        self.assertEqual(duplicate.returncode, 2)
        pinned_signal(initial['controller'], signal.SIGSTOP)
        time.sleep(.1)  # shorter than the consecutive-failure budget
        pinned_signal(initial['controller'], signal.SIGCONT)
        time.sleep(.7)
        self.assertEqual(self.status()['restarts'], 0)
        (self.runtime / 'hang-dispatch').touch()
        wait_for(lambda: self.status().get('state') == 'BACKOFF', timeout=15)
        (self.runtime / 'hang-dispatch').unlink()
        recovered = wait_for(lambda: self.status() if self.status().get('state') == 'HEALTHY'
                            and self.status().get('restarts') == 1 else None)
        self.assertNotEqual(initial['controller']['pid'], recovered['controller']['pid'])
        self.assertIn('HEARTBEAT_TIMEOUT', (self.runtime / 'daemon.log').read_text())

    def test_reference_worker_parent_death(self):
        self.env['EOS_DAEMON_FIXTURE'] = 'native'
        initial = self.start()
        database, run_id, worker = self.enqueue()
        pinned_signal(initial['controller'], signal.SIGKILL)
        wait_for(lambda: not matches(worker))
        wait_for(lambda: self.status().get('state') == 'HEALTHY' and self.status().get('restarts') == 1)
        self.assertEqual(database.get_run(run_id)['error']['code'], 'CONTROLLER_RESTART')
        self.assertFalse((self.runtime / 'worker-lease.json').exists())

    def test_bounded_failure_and_backoff(self):
        (self.runtime / 'results.sqlite3').mkdir()  # isolated intentional startup failure
        self.dog = subprocess.Popen(self.command, cwd=PROJECT, env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(self.dog.wait(timeout=25), 3)
        state = self.status()
        self.assertEqual((state['state'], state['restarts']), ('EXHAUSTED', 2))
        events = [json.loads(line) for line in (self.runtime / 'daemon.log').read_text().splitlines()
                  if line.startswith('{')]
        attempts = [event for event in events if event['event'] == 'RECOVERY_ATTEMPT']
        self.assertEqual([event['delay_s'] for event in attempts], [.3, .6])
        self.assertEqual(sum(event['event'] == 'CONTROLLER_STARTED' for event in events), 3)
        from datetime import datetime
        for attempt in attempts:
            launch = next(event for event in events if event['event'] == 'CONTROLLER_STARTED'
                          and event['time'] > attempt['time'])
            delta = (datetime.fromisoformat(launch['time']) - datetime.fromisoformat(attempt['time'])).total_seconds()
            self.assertGreaterEqual(delta, attempt['delay_s'] - .02)

    def test_normal_controller_stop_is_not_restarted(self):
        self.env['EOS_DAEMON_SLOW_STOP'] = '1'
        initial = self.start()
        pinned_signal(initial['controller'], signal.SIGTERM)
        self.assertEqual(self.dog.wait(timeout=12), 0)
        self.assertEqual((self.status()['state'], self.status()['restarts']), ('STOPPED', 0))

    def test_detached_start_status_stop_commands(self):
        start = self.command.copy()
        start[3] = 'start'
        result = subprocess.run(start, cwd=PROJECT, env=self.env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.status()
        self.addCleanup(lambda: pinned_signal(state['daemon'], signal.SIGTERM) if matches(state['daemon']) else None)
        wait_for(lambda: self.status().get('state') == 'HEALTHY')
        command = [sys.executable, '-m', 'eos_system.daemon', 'stop', '--runtime-dir', str(self.runtime)]
        result = subprocess.run(command, cwd=PROJECT, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status()['state'], 'STOPPED')
        self.assertFalse(lock_held(self.runtime / 'daemon.lock'))


if __name__ == '__main__':
    unittest.main()
