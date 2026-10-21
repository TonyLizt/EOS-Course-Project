"""Opt-in real R1 API -> Controller -> isolated Worker -> Verifier matrix.

Run with the project WSL Python, --model-source /path/to/runtime/models,
--scenario-source /path/to/development/scenarios and --artifacts a NEW directory.
No mocks/certification injection. Copies input bytes; only writes artifacts.
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
TP = dict(w_profit=1.,w_completion=0.,w_timeliness=0.,w_balance=0.)
TCR = dict(w_profit=0.,w_completion=1.,w_timeliness=0.,w_balance=0.)
MIXED = dict(w_profit=.5,w_completion=.3,w_timeliness=.1,w_balance=.1)
GOALS = dict(TP=TP,TCR=TCR,Mixed=MIXED)
TUNING = dict(sa=dict(max_iterations=2,neighbor_attempts=2),ga=dict(population_size=4,generations=1),aco=dict(ants=2,iterations=1))
TERMINAL = {'SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'}


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def tree(path): return {str(p.relative_to(path)):digest(p) for p in sorted(path.rglob('*')) if p.is_file()}
def write(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-source',type=Path,required=True)
    parser.add_argument('--scenario-source',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--phase',choices=('core','extended','negative'),default='core')
    args=parser.parse_args(); out=args.artifacts.resolve();out.mkdir(parents=True,exist_ok=False)
    for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[name]='1'
    os.environ.update(PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(out),MPLCONFIGDIR=str(out/'mpl'),EOS_RUNTIME_DIR=str(out/'runtime'),EOS_OREKIT_DATA=str(ROOT/'utils/orekit-data.zip'))
    import tempfile
    tempfile.tempdir=str(out)
    scenes=out/'scenes';(scenes/'provenance').mkdir(parents=True)
    names=['EOS-G0020'] if args.phase!='extended' else ['EOS-G0020','EOS-G0034','EOS-G0087']
    originals={}
    for name in names:
        for rel in (Path(name+'.json'),Path('provenance')/(name+'.json.provenance.json')):
            src=args.scenario_source/rel;dst=scenes/rel;shutil.copyfile(src,dst)
            assert digest(src)==digest(dst);originals[str(src)]=digest(src)
    before=tree(args.model_source);shutil.copytree(args.model_source,out/'runtime/models')
    assert before==tree(out/'runtime/models')
    from eos_system.api import create_app
    from eos_system.config import Settings,algorithm_source_sha256
    from eos_system.algorithm_registry import COMPARISON_ALGORITHMS
    from test_replay_backend import _DirectClient
    from algorithms.ppo.model import freeze as pfreeze,inference_code_sha as pcode
    from algorithms.lavis.model import freeze as lfreeze,inference_code_sha as lcode
    settings=Settings(out/'runtime',scenes,max_workers=2,max_queued=8,startup_timeout_s=60)
    app=create_app(settings);client=_DirectClient(app);owner=app.state.controller
    result=dict(phase=args.phase,source_sha=algorithm_source_sha256(),scene_input_sha=originals,
        original_models_sha=before,models={'ppo':pfreeze('ppo-dev-20261020-01'),'lavis':lfreeze('lavis-v1')},
        inference_sha={'ppo':pcode(),'lavis':lcode()},cases=[],negative=[])
    def save():write(out/'results.json',result)
    def request(aid,goal,scene='EOS-G0020',seed=42):
        params={'model_id':'ppo-dev-20261020-01'} if aid=='ppo' else {'model_id':'lavis-v1'} if aid=='lavis' else TUNING.get(aid,{})
        return dict(scenario_id=scene,algorithm_id=aid,algorithm_params=params,objective_weights=goal,execution_mode='physical_validation',time_budget_s=5.,seed=seed)
    def run_case(label,aids,goal,scene='EOS-G0020',seed=42,tamper=False):
        runs=[request(aid,goal,scene,seed) for aid in aids]
        response=client.post('/api/experiments',json={'runs':runs})
        case=dict(label=label,request={'runs':runs},http_status=response.status_code,submission=response.json());result['cases'].append(case);save()
        print('SUBMIT',label,response.status_code,flush=True)
        if response.status_code!=202:return
        eid=case['submission']['experiment_id'];changed=None
        if tamper:
            changed=out/'runtime/models/ppo/ppo-dev-20261020-01/model.pt'
            original=changed.read_bytes();changed.write_bytes(original+b'R1_TEMP_TEST_TAMPER')
        owner.start()
        try:
            deadline=time.monotonic()+max(180,45*len(aids))
            while time.monotonic()<deadline:
                detail=app.state.experiments.detail(eid)
                if all(r['status'] in TERMINAL for r in detail['runs']):break
                time.sleep(.2)
            else:
                case['wait_timeout']=True
                for r in detail['runs']:app.state.database.request_cancel(r['run_id'])
            case['detail']=client.get('/api/experiments/'+eid).json()
            with app.state.database.connect() as db:
                case['events']={r['run_id']:[dict(e) for e in db.execute('SELECT * FROM run_events WHERE run_id=? ORDER BY event_id',(r['run_id'],))] for r in detail['runs']}
                case['attempts']=[dict(e) for r in detail['runs'] for e in db.execute('SELECT * FROM run_attempts WHERE run_id=?',(r['run_id'],))]
            case['objectives_consistent']=all(r['config']['objective_weights']==goal and r['config']['objective_adapter']['requested_objective']==goal and r['config']['objective_adapter']['effective_objective']==goal for r in case['detail']['runs'])
            case['metrics']={r['config']['algorithm_id']:dict(status=r['status'],metrics=r.get('metrics'),error=r.get('error')) for r in case['detail']['runs']}
            print('RESULT',label,[(k,v['status'],(v['metrics'] or {}).get('TCR'),v['error']) for k,v in case['metrics'].items()],flush=True);save()
        finally:
            owner.stop()
            if changed:changed.write_bytes(original)
    try:
        if args.phase=='core':
            for name,goal in GOALS.items():
                for aids in (['ppo'],['lavis'],['ppo','lavis'],['ppo','lavis','caabs']):
                    run_case(name+'-'+ '+'.join(aids),aids,goal)
        elif args.phase=='extended':
            others=[a for a in COMPARISON_ALGORITHMS if a not in ('ppo','lavis')]
            for name,goal in GOALS.items():
                for start in (0,7):run_case(name+'-others-'+str(start),others[start:start+7],goal)
            for scene,seed in (('EOS-G0034',7),('EOS-G0087',101)):
                for name,goal in GOALS.items():run_case(scene+'-'+str(seed)+'-'+name,['ppo','lavis'],goal,scene,seed)
        else:
            for label,change in [('zero',{'objective_weights':dict(TP,w_profit=0)}),('negative',{'objective_weights':dict(TP,w_profit=-1)}),('overflow',{'objective_weights':dict(TP,w_profit=1e308,w_completion=1e308)}),('missing_model',{'algorithm_params':{'model_id':'missing'}}),('incompatible_model',{'algorithm_params':{'model_id':'ppo-v1-20261020'}}),('center',{'placement_mode':'center'})]:
                req=request('ppo',MIXED)|change;response=client.post('/api/experiments',json={'runs':[req]});result['negative'].append(dict(label=label,status=response.status_code,body=response.json()));save()
            response=client.post('/api/experiments',json={'runs':[request('ppo',TP),request('lavis',TCR)]});result['negative'].append(dict(label='different_common_weights',status=response.status_code,body=response.json()));save()
            run_case('member-model-replaced',['ppo','lavis','caabs'],MIXED,tamper=True)
        result['inputs_preserved']=before==tree(args.model_source) and all(digest(Path(p))==sha for p,sha in originals.items())
        result['copied_models_preserved']=before==tree(out/'runtime/models')
        result['completed']=True;save()
    finally:owner.stop();app.state.replay.close()
    if not result.get('inputs_preserved') or not result.get('copied_models_preserved'):raise RuntimeError('Input preservation failed')
    if args.phase=='negative':
        assert all(n['status']==(409 if n['label']=='different_common_weights' else 422) for n in result['negative'])
        errors={n['label']:str(n['body']) for n in result['negative']}
        assert 'PPO_INCOMPATIBLE_MODEL' in errors['incompatible_model']
        statuses={r['config']['algorithm_id']:r['status'] for r in result['cases'][0]['detail']['runs']}
        assert statuses==dict(ppo='FAILED',lavis='SUCCEEDED',caabs='SUCCEEDED'),statuses
    if args.phase!='negative' and any(c['http_status']!=202 or not c.get('objectives_consistent') or any(r['status']!='SUCCEEDED' for r in c.get('detail',{}).get('runs',[])) for c in result['cases']):raise RuntimeError('Real matrix contains failures; inspect results.json')


if __name__=='__main__':main()
