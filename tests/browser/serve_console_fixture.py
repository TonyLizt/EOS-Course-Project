"""Isolated console QA server. Historical success uses UNIT_TEST_INJECTION_ONLY receipts.

New submissions execute real Controller/Worker and the unchanged certification gate.
No production database or scenario is modified.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import threading
import uvicorn
from urllib.request import urlopen

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))
from test_integrated_replay import fixture
from certification_fixtures import storage_receipt
from eos_system.config import algorithm_source_sha256
from eos_system.storage import now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coord', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18769)
    args = parser.parse_args()
    with fixture(duration_s=86400) as f:
        ids = []
        for i, algorithm in enumerate(('completion_first', 'adaptive_repair')):
            rid = f'00000000-0000-4000-8000-{90+i:012d}'
            cfg = f.config.model_copy(update=dict(run_id=rid, algorithm_id=algorithm,
                          algorithm_code_sha=algorithm_source_sha256(),
                          scenario_provenance={'scenario_physics_version': 'legacy_unknown'},
                          created_at=now()))
            f.db.enqueue(cfg, 8)
            attempt, _ = f.db.start_attempt(rid)
            f.db.set_verifying(rid, attempt)
            plan = f.db.get_run(f.run_id)['plan']
            metrics = dict(completed_tasks=2, total_tasks=2, task_profit=2,
                           task_completion_rate=1, balance_degree=1,
                           timeliness_metric=.3-i*.1, runtime_efficiency=.01+i*.01,
                           robustness_variance=None, mip_gap=None)
            f.db.finish_success(rid, attempt, plan, metrics, .001,
                                certification=storage_receipt(f.db, rid, plan))
            ids.append(rid)
        empty = f.scene.parent / 'empty.json'
        empty.write_text(json.dumps({'scenario_id': 'empty', 'metadata': {
            'creation_time': '2026-01-01T00:00:00Z', 'duration': 60},
            'satellites': [], 'missions': [], 'observation_windows': []}))
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        os.environ['MPLCONFIGDIR'] = '/tmp/eos-console-mpl'
        base = f'http://127.0.0.1:{args.port}'
        # Receipts are process-bound: seed and serve inside the same trusted process.
        server = uvicorn.Server(uvicorn.Config(f.app, host='127.0.0.1', port=args.port,
                                             log_level='warning'))
        thread = threading.Thread(target=server.run)
        thread.start()
        try:
            for _ in range(100):
                if not thread.is_alive():
                    raise RuntimeError('QA server stopped')
                try:
                    urlopen(base+'/api/health', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise TimeoutError('QA server not ready')
            args.coord.write_text(json.dumps({'url': base, 'runs': ids, 'gantt_run': f.run_id}))
            print('CONSOLE_QA_READY ' + str(args.coord), flush=True)
            deadline = time.monotonic()+240
            while args.coord.exists() and time.monotonic() < deadline:
                time.sleep(.5)
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            args.coord.unlink(missing_ok=True)
            print('CONSOLE_QA_STOPPED', flush=True)


if __name__ == '__main__':
    main()
