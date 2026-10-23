"""Interrupt our matrix driver only after proving its stopped Controller is idle.

Linux audit helper. SIGSTOP prevents a queue race between observing the DB and
sending SIGINT. Busy observations are resumed without cancelling work. Original
Worker/source/budget identities are not changed by this helper.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import sqlite3
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int,required=True)
    p.add_argument('--database',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    command=Path(f'/proc/{args.pid}/cmdline').read_bytes().replace(b'\0',b' ').decode()
    if 'scripts/validate_scenarios.py matrix' not in command:raise ValueError('not our matrix driver')
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        with sqlite3.connect(args.database) as db:
            active=db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('QUEUED','RUNNING','VERIFYING')").fetchone()[0]
        if active:time.sleep(.1);continue
        os.kill(args.pid,signal.SIGSTOP)
        try:
            # Re-read after stopping ALL driver threads, not from an old txn.
            with sqlite3.connect(args.database) as db:
                active=db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('QUEUED','RUNNING','VERIFYING')").fetchone()[0]
                terminal=db.execute("SELECT status,COUNT(*) FROM runs GROUP BY status").fetchall()
            if active:continue
            args.report.write_text(json.dumps(dict(driver_command=command,paused_pid=args.pid,
                stopped_active_runs=active,status_counts=dict(terminal),
                time_utc=datetime.now(timezone.utc).isoformat(),reason='bounded concurrency change; unchanged algorithms/models/scenarios/budget'),indent=2)+'\n')
            os.kill(args.pid,signal.SIGINT)
            print('IDLE_INTERRUPT',args.pid,dict(terminal),flush=True)
            return
        finally:os.kill(args.pid,signal.SIGCONT)
    raise TimeoutError('no safe idle boundary; original process left running')


if __name__=='__main__':main()
