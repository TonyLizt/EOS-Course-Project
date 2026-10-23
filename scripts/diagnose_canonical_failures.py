"""Reproduce only actual FAILED cases once, serially; preserve primary results.

Not a replacement matrix, not a retry-until-success tool. The original failing
run and parallel resource conditions remain in matrix-full and SQLite.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--matrix',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--orekit-data',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise FileExistsError('diagnostic output must be new; do not fish for success')
    os.environ['EOS_RUNTIME_DIR']=str(args.runtime.resolve());os.environ['EOS_OREKIT_DATA']=str(args.orekit_data.resolve())
    for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[name]='1'
    from eos_system.api import create_app
    from eos_system.config import Settings
    from eos_system.contracts import RunRequest
    from test_replay_backend import _DirectClient
    from scripts.matrix_journal import atomic_json
    primary=json.loads(args.matrix.read_text());failed=[c for c in primary['cases'] if c['run_status']=='FAILED']
    report=dict(scope='one serial reproduction per FAILED record only; original full parallel matrix unchanged',worker_limit=1,cases=[])
    app=create_app(Settings(args.runtime.resolve(),args.root.resolve(),max_workers=1,startup_timeout_s=90));owner=app.state.controller
    client=_DirectClient(app)
    try:
        owner.start()
        for c in failed:
            old=c['detail']['config'];request={k:v for k,v in old.items() if k in RunRequest.model_fields}
            r=client.post('/api/experiments',json={'runs':[request]})
            row=dict(original_key=c['key'],original_run_id=c['run_id'],original_error=c['failure_reason'],submission_status=r.status_code)
            report['cases'].append(row);assert r.status_code==202,r.text
            rid=r.json()['runs'][0]['run_id'];row['run_id']=rid;atomic_json(args.output,report)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                d=client.get('/api/runs/'+rid).json()
                if d['status'] in ('SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'):break
                time.sleep(.25)
            assert d['status'] in ('SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'),'diagnostic deadline'
            for key in ('algorithm_id','algorithm_version','algorithm_code_sha','scenario_id','scenario_sha256',
                'algorithm_params','objective_weights','constraints','placement_mode','schedule_model','seed','time_budget_s','model_provenance'):
                assert d['config'][key]==old[key],('diagnostic condition changed',key)
            row.update(status=d['status'],error=d['error'],detail=d,identical_request_conditions=True)
            atomic_json(args.output,report);print('SERIAL_DIAGNOSTIC',c['key'],d['status'],flush=True)
    finally:owner.stop();app.state.replay.close()


if __name__=='__main__':main()
