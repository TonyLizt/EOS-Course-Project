"""Opt-in real ASGI -> Controller -> Worker -> independent physical verification.

Copies only named public development scenes and optional frozen models into a
NEW artifact directory. Never rewrites production inputs or certifies fixtures.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario-source', type=Path, required=True)
    parser.add_argument('--scenes', nargs='+', default=['EOS-G0020','EOS-G0034','EOS-G0087'])
    parser.add_argument('--model-source', type=Path)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--budget', type=float, default=5.)
    args = parser.parse_args()
    out = args.artifacts.resolve(); out.mkdir(parents=True, exist_ok=False)
    for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ.setdefault('EOS_OREKIT_DATA', str(ROOT/'utils/orekit-data.zip'))
    os.environ.update(EOS_RUNTIME_DIR=str(out/'runtime'),
                      PYTHONDONTWRITEBYTECODE='1', MPLCONFIGDIR=str(out/'mpl'), TMPDIR=str(out))
    import tempfile
    tempfile.tempdir = str(out)
    scenes = out/'scenes'; (scenes/'provenance').mkdir(parents=True)
    original = {}
    for name in args.scenes:
        for rel in (Path(name+'.json'), Path('provenance')/(name+'.json.provenance.json')):
            src = args.scenario_source/rel
            original[str(src)] = digest(src)
            shutil.copyfile(src, scenes/rel)
    model_ids = {'ppo':'ppo-dev-20261020-01', 'lavis':'lavis-v1'}
    if args.model_source:
        for family, model_id in model_ids.items():
            src = args.model_source/family/model_id
            for path in src.rglob('*'):
                if path.is_file(): original[str(path)] = digest(path)
            shutil.copytree(src, out/'runtime/models'/family/model_id)

    from algorithms.basic import BASIC_ALGORITHMS
    from eos_system.api import create_app
    from eos_system.config import Settings, algorithm_source_sha256
    from eos_system.algorithm_registry import COMPARISON_ALGORITHMS
    from test_replay_backend import _DirectClient
    app = create_app(Settings(out/'runtime', scenes, max_workers=2, max_queued=32, startup_timeout_s=60))
    async def transport(scope, receive, send):
        # The existing small ASGI client has no query-string convenience API.
        path, _, query = scope['path'].partition('?')
        await app(dict(scope, path=path, raw_path=path.encode(), query_string=query.encode()), receive, send)
    client = _DirectClient(transport); owner = app.state.controller
    report = dict(source_sha=algorithm_source_sha256(), inputs=original, cases=[])
    def save():
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    catalog = client.get('/api/algorithms').json()
    (out/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
    available = {row['algorithm_id'] for row in catalog['items'] if row['availability']=='ready'}
    tuning = dict(sa={'max_iterations':2,'neighbor_attempts':2}, ga={'population_size':4,'generations':1},
                  aco={'ants':2,'iterations':1})
    goals = [dict(w_profit=.5,w_completion=.3,w_timeliness=.1,w_balance=.1),
             dict(w_profit=0.,w_completion=1.,w_timeliness=0.,w_balance=0.),
             dict(w_profit=1.,w_completion=0.,w_timeliness=0.,w_balance=0.)]
    try:
        owner.start()
        for index, scene in enumerate(args.scenes):
            ids = [a for a in COMPARISON_ALGORITHMS if a in available] if index == 0 else list(BASIC_ALGORITHMS)
            requests = [dict(scenario_id=scene, algorithm_id=aid, execution_mode='physical_validation',
                algorithm_params=({'model_id':model_ids[aid]} if aid in model_ids else tuning.get(aid,{})),
                objective_weights=goals[index % len(goals)], time_budget_s=args.budget, seed=42+index) for aid in ids]
            response = client.post('/api/experiments',json={'runs':requests})
            case = dict(scene=scene, request=requests, http_status=response.status_code, submission=response.json())
            report['cases'].append(case); save()
            print('SUBMIT',scene,response.status_code,len(ids),flush=True)
            if response.status_code != 202:
                continue
            eid = response.json()['experiment_id']
            deadline = time.monotonic()+max(240,60*len(ids))
            while time.monotonic() < deadline:
                detail = app.state.experiments.detail(eid)
                if all(r['status'] in {'SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'} for r in detail['runs']):
                    break
                time.sleep(.2)
            else:
                case['wait_timeout'] = True
                for r in detail['runs']: app.state.database.request_cancel(r['run_id'])
            case['detail'] = client.get('/api/experiments/'+eid).json()
            with app.state.database.connect() as db:
                case['attempts'] = [dict(row) for r in detail['runs'] for row in
                    db.execute('SELECT * FROM run_attempts WHERE run_id=?',(r['run_id'],))]
            case['exports'] = {}
            for r in case['detail']['runs']:
                if r['status'] == 'SUCCEEDED':
                    rid = r['run_id']
                    for suffix in ('json','csv'):
                        exported = client.get(f'/api/runs/{rid}/export?format={suffix}')
                        case['exports'][rid+'/'+suffix] = exported.status_code
            print('RESULT',scene,[(r['config']['algorithm_id'],r['status'],(r.get('metrics') or {}).get('completed_tasks'),r.get('error'))
                                  for r in case['detail']['runs']],flush=True)
            save()
        report['inputs_preserved'] = all(digest(Path(path))==sha for path,sha in original.items())
        report['completed'] = True; save()
    finally:
        owner.stop(); app.state.replay.close()
    failures = [case for case in report['cases'] if case['http_status'] != 202 or case.get('wait_timeout') or
                any(r['status'] != 'SUCCEEDED' for r in case.get('detail',{}).get('runs',[])) or
                any(status != 200 for status in case.get('exports',{}).values())]
    if failures or not report.get('inputs_preserved'):
        raise RuntimeError('Compatibility validation failed; inspect results.json')


if __name__ == '__main__':
    main()
