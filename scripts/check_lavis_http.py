#!/usr/bin/env python3
"""真实HTTP验收：指定验证来源各一实验，对照基线，核对模型快照及JSON/CSV/Gantt。每个来源新增2条运行。"""
import argparse,json,time,urllib.request,urllib.error
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8765')
    parser.add_argument('--source-id',required=True)
    parser.add_argument('--model-id',default='lavis-v1')
    parser.add_argument('--budget',type=float,default=15.)
    parser.add_argument('--scenario-ids',nargs='+',default=['EOS-G0016','EOS-G0041','EOS-G0066','EOS-G0091'],
                        help='同一登记目录内的开发/验证场景ID；不登记冻结测试集')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('报告已存在，请使用新的输出文件名')
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):parser.error('报告写运行目录，不写仓库')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path,payload=None,raw=False):
        req=urllib.request.Request(args.url+path,data=json.dumps(payload).encode() if payload is not None else None,
                                   headers={'Content-Type':'application/json'})
        with opener.open(req,timeout=30) as response:data=response.read()
        return data if raw else json.loads(data)
    model=next(m for m in request('/api/models')['items'] if m['model_id']==args.model_id)
    experiments=[]
    for scene in args.scenario_ids:
        common=dict(source_id=args.source_id,scenario_id=scene,execution_mode='physical_validation',
                    seed=42,time_budget_s=args.budget,objective_weights={'w_profit':0,'w_completion':1})
        runs=[common|{'algorithm_id':aid,'algorithm_params':{'model_id':args.model_id} if aid=='lavis' else {}}
              for aid in ('lavis','profit_first')]
        experiments.append(request('/api/experiments',{'runs':runs}))
    deadline=time.monotonic()+max(240, len(args.scenario_ids)*(2*args.budget+60));results=[]
    for exp in experiments:
        path='/api/experiments/'+exp['experiment_id']
        while True:
            record=request(path)
            if record['status'] in ('SUCCEEDED','FAILED','PARTIAL','CANCELLED'):break
            if time.monotonic()>deadline:raise TimeoutError('HTTP integration deadline')
            time.sleep(.5)
        if record['status']!='SUCCEEDED':
            raise ValueError(json.dumps({'experiment_id':record['experiment_id'],'status':record['status'],
                'runs':[{'run_id':r['run_id'],'status':r['status'],'error':r.get('error')} for r in record['runs']]},ensure_ascii=False))
        for run in record['runs']:
            rid=run['run_id'];is_ml=run['config']['algorithm_id']=='lavis'
            full=request('/api/runs/'+rid)
            assert full['attempts'][-1]['exit_code']==0
            assert full['attempts'][-1]['worker_pid']>0
            exported=request('/api/runs/'+rid+'/export?format=json')
            csv=request('/api/runs/'+rid+'/export?format=csv',raw=True)
            assert exported['result_kind']=='physical_validation' and csv
            if is_ml:
                assert exported['provenance']['model_provenance']['model_sha256']==model['model_sha256']
                assert run['config']['model_provenance']['model_sha256']==model['model_sha256']
            assert request('/api/runs/'+rid+'/visualization/schedule')['assignments']
            assert request('/visualization/gantt/'+rid,raw=True)
            results.append({'experiment_id':record['experiment_id'],'run_id':rid,
                'scene':run['config']['scenario_id'],'algorithm':run['config']['algorithm_id'],
                'status':run['status'],'completed':run['metrics']['completed_tasks'],
                'total':run['metrics']['total_tasks'],'RT':run['metrics']['RT'],
                'worker_pid':full['attempts'][-1]['worker_pid'],'model_sha256':model['model_sha256'] if is_ml else None,
                'json_csv_schedule_gantt':'PASS'})
        print(json.dumps(results[-2:],ensure_ascii=False),flush=True)
    # 目标域与路径输入错误必须在入队前拒绝；不会为这些请求创建实验。
    invalid=dict(common,algorithm_id='lavis',algorithm_params={'model_id':args.model_id},
                 objective_weights={'w_profit':1,'w_completion':0})
    try:request('/api/runs',invalid);raise AssertionError('wrong objective accepted')
    except urllib.error.HTTPError as exc:assert exc.code==422
    invalid.update(objective_weights={'w_profit':0,'w_completion':1},algorithm_params={'model_id':'../model'})
    try:request('/api/runs',invalid);raise AssertionError('arbitrary path accepted')
    except urllib.error.HTTPError as exc:assert exc.code==422
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:json.dump({'model':model,'results':results,'negative_requests':'PASS'},stream,ensure_ascii=False,indent=2)

if __name__=='__main__':main()
