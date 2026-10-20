"""隔离真实服务验收并行、评分、取消与临时对照；不修改原实验数据库。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eos_system.worker_process import read_proc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios',required=True,type=Path,help='公开高冲突开发场景目录')
    parser.add_argument('--models',required=True,type=Path,help='原LAVIS模型登记根目录')
    parser.add_argument('--orekit-data',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model-id',default='lavis-v3-ranking')
    parser.add_argument('--base-main',default='unspecified')
    args=parser.parse_args()
    import re
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',args.model_id):
        parser.error('model-id必须为登记ID，不能是路径')
    if args.output.exists() or args.output.resolve().is_relative_to(ROOT):
        parser.error('报告必须是仓库外的新文件')
    for sid in ('HC-F033-V1','HC-F035-V1','HC-F036-V1'):
        if not (args.scenarios/(sid+'.json')).is_file():parser.error('缺少公开开发场景 '+sid)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    originals={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.models.glob('*/*')
               if p.name in ('manifest.json','model.joblib')}
    result={'base_main':args.base_main,'model_id':args.model_id,'runs':[],'max_observed_live_workers':0,'training_performed':False,
            'scope':'real isolated HTTP/Worker/Controller/physics/SQLite; no frozen test access'}
    with tempfile.TemporaryDirectory(prefix='eos-parallel-acceptance-') as folder:
        temp=Path(folder);runtime=temp/'runtime';runtime.mkdir()
        model=runtime/'models/lavis'/args.model_id;model.mkdir(parents=True)
        for name in ('model.joblib','manifest.json'):shutil.copyfile(args.models/args.model_id/name,model/name)
        data=temp/'orekit-data.zip';shutil.copyfile(args.orekit_data,data)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=os.environ|{'EOS_RUNTIME_DIR':str(runtime),'EOS_SCENARIO_DIR':str(args.scenarios.resolve()),
            'EOS_OREKIT_DATA':str(data),'EOS_PORT':str(port),'PYTHONDONTWRITEBYTECODE':'1'}
        env.pop('EOS_MAX_WORKERS',None)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url='http://127.0.0.1:'+str(port)
        def request(path,payload=None,method=None,raw=False):
            req=urllib.request.Request(url+path,data=None if payload is None else json.dumps(payload).encode(),
                headers={'Content-Type':'application/json'},method=method)
            with opener.open(req,timeout=30) as response:data=response.read()
            return data if raw else json.loads(data)
        def wait(predicate,timeout=180):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                value=predicate()
                if value:return value
                time.sleep(.1)
            raise TimeoutError('验收等待超时')
        log=(temp/'service.log').open('w+');service=None
        def launch():
            proc=subprocess.Popen([sys.executable,'-B','-m','eos_system'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            def ready():
                try:return request('/api/health')
                except Exception:
                    if proc.poll() is not None:raise RuntimeError('服务启动失败')
                    return False
            try:wait(ready,60)
            except BaseException:
                stop(proc);raise
            return proc
        def stop(proc):
            proc.terminate()
            try:proc.wait(timeout=40)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)
            result.setdefault('service_exit_codes',[]).append(proc.returncode)
        try:
            service=launch()
            assert request('/api/execution-settings')['max_workers']==2
            for invalid in (0,9,True,1.5):
                try:request('/api/execution-settings',{'max_workers':invalid},method='PUT');raise AssertionError('非法并发数被接受')
                except urllib.error.HTTPError as exc:assert exc.code==422
            result['invalid_limits']='422'
            common={'source_id':'runtime','scenario_id':'HC-F033-V1','execution_mode':'physical_validation',
                    'seed':42,'time_budget_s':30,'objective_weights':{'w_profit':0,'w_completion':1}}
            params={'model_id':args.model_id,'search_mode':'multistart','candidate_strategy':'expanded','max_branches':8}
            configs=[common|{'algorithm_id':aid,'algorithm_params':params if aid=='lavis' else {}}
                     for aid in ('lavis','rabas','profit_first','caabs')]
            exp=request('/api/experiments',{'runs':configs});eid=exp['experiment_id']
            def finished():
                detail=request('/api/experiments/'+eid)
                live=[]
                for run in detail['runs']:
                    for attempt in run.get('attempts',[]):
                        pid=attempt.get('worker_pid');identity=read_proc(pid) if pid else None
                        if identity and identity.live:live.append(pid)
                result['max_observed_live_workers']=max(result['max_observed_live_workers'],len(set(live)))
                return detail if detail['status'] in ('SUCCEEDED','FAILED','PARTIAL','CANCELLED') else False
            exp=wait(finished)
            assert exp['status']=='SUCCEEDED',[(x['status'],x.get('error')) for x in exp['runs']]
            assert result['max_observed_live_workers']==2,result['max_observed_live_workers']
            for run in exp['runs']:
                rid=run['run_id'];score=run['ranking_score'];m=run['metrics']
                expected=70*m['TCR']+20*m['TP']/score['total_priority']+10*(1-m['TM'])
                assert abs(score['value']-expected)<1e-5
                exported=request('/api/runs/'+rid+'/export?format=json')
                csv=request('/api/runs/'+rid+'/export?format=csv',raw=True)
                assert exported['ranking_score']['policy']==score['policy'] and b'ranking_score' in csv
                assert request('/api/runs/'+rid+'/visualization/schedule')['assignments']
                assert request('/visualization/gantt/'+rid,raw=True)
                row={'algorithm':run['config']['algorithm_id'],'run_id':rid,'status':run['status'],
                    'completed':m['completed_tasks'],'score':score['value'],'RT':m['RT'],
                    'worker_pid':run['attempts'][-1]['worker_pid'],'worker_limit':run['execution_resources']['worker_limit']}
                result['runs'].append(row);print(json.dumps(row),flush=True)
            # 真实算法搜索期间取消一个任务，不影响另一个槽位。
            target=request('/api/runs',common|{'scenario_id':'HC-F036-V1','algorithm_id':'lavis','algorithm_params':params})['run_id']
            friend=request('/api/runs',common|{'scenario_id':'HC-F035-V1','algorithm_id':'profit_first'})['run_id']
            def searching():
                row=request('/api/runs/'+target)
                return any(e['event_type']=='heartbeat' and (e.get('payload') or {}).get('phase')=='SEARCHING' for e in row['events'])
            wait(searching,60);request('/api/runs/'+target+'/cancel',{})
            def terminal_run(rid):
                row=request('/api/runs/'+rid)
                return row if row['status'] in ('CANCELLED','FAILED','SUCCEEDED','TIMED_OUT') else False
            cancelled=wait(lambda:terminal_run(target))
            assert cancelled['status']=='CANCELLED' and cancelled['ranking_score'] is None,cancelled.get('error')
            other=wait(lambda:terminal_run(friend))
            assert other['status']=='SUCCEEDED',other.get('error')
            result['cancel_isolation']={'cancelled':target,'unaffected_success':friend}
            with sqlite3.connect(str(runtime/'results.sqlite3')) as db:count=db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
            temporary=request('/api/experiments/'+eid+'/temporary-control',{'schedule_model':'adaptive_repair'})
            tid=temporary['experiment_id']
            def temporary_done():
                row=request('/api/temporary-controls/'+tid)
                return row if row['status'] in ('SUCCEEDED','FAILED','PARTIAL') else False
            temp_result=wait(temporary_done)
            assert temp_result['status']=='SUCCEEDED',temp_result
            assert all(run.get('ranking_score') for run in temp_result['runs'])
            with sqlite3.connect(str(runtime/'results.sqlite3')) as db:assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==count
            request('/api/temporary-controls/'+tid,method='DELETE');result['temporary_scoring_no_db_writes']='PASS'
            request('/api/execution-settings',{'max_workers':3},method='PUT')
            stop(service);service=None;service=launch()
            assert request('/api/execution-settings')['max_workers']==3
            result['persisted_limit_after_restart']=3
            html=request('/',raw=True)
            assert b'worker-limit' in html
            # 排序已移入动态表头，不再要求已删除的下拉框DOM。
            assert b'data-sort-metric' in request('/static/experiment-ui.js',raw=True)
            result['controls_and_exports']='PASS'
        except Exception as exc:
            result['error']=type(exc).__name__+': '+str(exc);raise
        finally:
            if service is not None:stop(service)
            log.flush();log.seek(0);result['service_log_tail']=log.read()[-2500:];log.close()
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    result['temporary_runtime_cleaned']=not temp.exists()
    result['original_models_unchanged']=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in originals.items())
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));print('FINAL',args.output,flush=True)


if __name__=='__main__':main()
