"""Real, isolated Worker process used for supervision fault tests."""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from eos_system.worker_reference import send_message, receive_message


def loading_prepare(config):
    time.sleep(60)  # real Worker IPC loop remains active; no actual solver needed
    raise RuntimeError('test loading sentinel')


def waiting_worker(run_id, attempt, events, controls):
    os.setsid()
    def report(seq, kind, payload):
        send_message(events, {'protocol_version': 1, 'run_id': run_id,
            'attempt': attempt, 'seq': seq, 'kind': kind,
            'sent_at': datetime.now(timezone.utc).isoformat(), 'payload': payload})
    report(1, 'started', {'worker_pid': os.getpid()})
    receive_message(controls)
    if os.environ.get('EOS_DAEMON_FIXTURE_CHILD') == '1':
        subprocess.Popen([sys.executable, '-S', '-c', 'import time; time.sleep(60)'])
    report(2, 'heartbeat', {'phase': 'SEARCHING'})
    # Intentionally ignore EOF: crash recovery MUST reap this Worker itself.
    while True:
        if controls.poll(.05):
            try:
                message = receive_message(controls)
            except EOFError:
                time.sleep(.05)
                continue
            if message['kind'] == 'cancel':
                report(3, 'cancel_ack', {'accepted': True})
                return
