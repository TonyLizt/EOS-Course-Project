"""仅对smoke划分做真实HTTP/Worker联调；禁止用于最终测试成绩选型。"""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen,build_opener,ProxyHandler
from urllib.error import HTTPError

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--base-url',default='http://127.0.0.1:8765');args=p.parse_args()
    root=args.root.expanduser().resolve();spec=json.loads((root/'dataset_plan.json').read_text())
    rows=[r for r in spec['allocation'] if r['split']=='smoke']
    assert len(rows)==6 and all('SMOKE' in r['scenario_id'] for r in rows)
    split_plan=dict(dataset_id='eos-final-v1-smoke',allocation=[r|{'relative_path':r['relative_path'].split('/',1)[1]} for r in rows])
    marker=root/'smoke/dataset_plan.json'
    if marker.exists():assert json.loads(marker.read_text())==split_plan
    else:marker.write_text(json.dumps(split_plan,sort_keys=True))
    for row in rows:assert (root/row['relative_path']).is_file()
    http=build_opener(ProxyHandler({}))
    def call(path,body=None):
        request=Request(args.base_url+path,data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json'})
        try:
            with http.open(request,timeout=60) as response:return json.load(response)
        except HTTPError as exc:raise RuntimeError(exc.read().decode()) from exc
    sources=call('/api/data-sources')['items'];source=next((s for s in sources if s['root_path']==str(root/'smoke')),None)
    if source is None:source=call('/api/data-sources',{'name':'最终发布联调（6份，不计最终成绩）','path':str(root/'smoke')})
    source_id=source.get('source_id') or source['id']
    algorithm_rows=call('/api/algorithms')['items']
    all_algos=[r['algorithm_id'] for r in algorithm_rows if r['availability']=='ready' and r['algorithm_id'] not in {'mip','ppo'}]
    out=root/'reports';out.mkdir(exist_ok=True)
    evidence=out/'smoke_acceptance.json'
    report=json.loads(evidence.read_text()) if evidence.exists() else {'purpose':'compatibility only; not final scores',
        'source_id':source_id,'budget_s':10,'seed':42,'experiments':{},'records':[]}
    for row in rows:
        sid=row['scenario_id'];algos=all_algos if row['scale']=='small' and row['difficulty_profile']=='mixed' else ['fcfs','caabs','rabas','dartis','lavis']
        eid=report['experiments'].get(sid)
        for algo in algos:
            params={'model_id':'lavis-v4-opportunity','candidate_strategy':'expanded','search_mode':'multistart'} if algo=='lavis' else {}
            request=dict(source_id=source_id,scenario_id=sid,algorithm_id=algo,algorithm_params=params,execution_mode='physical_validation',
                schedule_model='completion_first',seed=42,time_budget_s=10,
                objective_weights=dict(w_completion=1,w_profit=0,w_timeliness=0,w_balance=0))
            if eid is None:
                experiment=call('/api/experiments',{'runs':[request]});eid=experiment['experiment_id']
                report['experiments'][sid]=eid
            else:
                experiment=call('/api/experiments/'+eid)
                if not any(r['config']['algorithm_id']==algo for r in experiment['runs']):
                    experiment=call('/api/experiments/'+eid+'/algorithms',{'algorithm_id':algo,'algorithm_params':params})
            run=next(r for r in experiment['runs'] if r['config']['algorithm_id']==algo);rid=run['run_id']
            deadline=time.monotonic()+180
            while run['status'] not in {'SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'}:
                if time.monotonic()>deadline:raise RuntimeError('等待运行终态超时，保留现场 '+rid)
                time.sleep(.5);run=call('/api/runs/'+rid)
            record=dict(scenario_id=sid,algorithm=algo,run_id=rid,status=run['status'],error=run.get('error'),
                completed_tasks=(run.get('metrics') or {}).get('completed_tasks'),scenario_sha256=run['config']['scenario_sha256'])
            report['records']=[r for r in report['records'] if (r['scenario_id'],r['algorithm'])!=(sid,algo)]+[record]
            evidence.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps(record,ensure_ascii=False),flush=True)
    report['passed']=all(r['status']=='SUCCEEDED' and (r['completed_tasks'] or 0)>0 for r in report['records'])
    report['final_test_used']=False
    evidence.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
