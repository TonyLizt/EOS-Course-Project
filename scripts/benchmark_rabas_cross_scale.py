"""Pre-registered RABAS cross-scale study; all run artifacts stay outside source.
Synthetic groups are public-model stress tests, NEVER physical certificates.
Run serially; child-side wall clock includes initial-schedule construction.
"""
from __future__ import annotations
import argparse, json, sys, os, signal, time, subprocess, hashlib, platform, statistics
from pathlib import Path
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'algorithms').is_dir(): ROOT=Path('/home/asus/projects/eos-course-runtime-rabas-cross-scale')
sys.path.insert(0,str(ROOT))
# The fixture implementation is installed alongside this script.
from scripts.rabas_study_fixtures import fixture
from eos_system.algorithm_registry import get_algorithm, availability
from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.evaluation_metrics import compute_evaluation_metrics

SPLITS={'development': [('uniform',101)],'validation':[('clustered',211),('capacity',211)],
        'heldout':[('hub',307),('downlink',307)]}
ALGORITHMS=['rabas_baseline','rabas','completion_first','adaptive_repair','profit_first','timeliness_first',
            'balance_first','pressure_repair','caabs','dartis','sa','ga','aco','mip','lavis','ppo']
RANDOM={'completion_first','sa','ga','aco'}

class StudyDeadline(BaseException):
    """A benchmark stop must not be swallowed by solver helper except Exception."""


def module_at(sha):
    import importlib.util, types
    data=subprocess.check_output(['git','show',sha+':algorithms/auction_bundle.py'],cwd=ROOT,text=True)
    mod=types.ModuleType('study_baseline');sys.modules[mod.__name__]=mod
    exec(compile(data,sha+':algorithms/auction_bundle.py','exec'),mod.__dict__)
    return mod

def job_run(job):
    row=dict(job)
    aid=job['algorithm']
    if aid!='rabas_baseline':
        state,why=availability(aid)
        if state!='ready':return row|{'status':'UNAVAILABLE','reason':why}
    p=fixture(job['n'],job['family'],job['scenario_seed']);cm=ConstraintModel(p)
    digest=hashlib.sha256(json.dumps(asdict(p),sort_keys=True,default=str).encode()).hexdigest()
    row.update(sha256=digest,satellites=len(p.satellites),windows=sum(len(t.windows) for t in p.tasks.values()),
               ground_stations=len(p.ground_stations),shared_tasks=sum(len({w.satellite_id for w in t.windows})>1 for t in p.tasks.values()),
               physics='SYNTHETIC_PUBLIC_MODEL_ONLY',initial_group='completion_first_seeded' if aid in {'sa','ga','aco'} else 'empty_or_rebuilt')
    params=job.get('params',{})
    weights=ObjectiveWeights(w_profit=0,w_completion=1)
    if aid=='rabas_baseline':
        mod=module_at(job['baseline']);par=mod.RABASParams(**params);solver=mod.ResourceAwareBundleAuctionScheduler()
    else:
        spec=get_algorithm(aid);par=spec.parse_params(params)
        solver=spec.build(SolveContext(job['seed'],job['budget'],weights,par))
    context=SolveContext(job['seed'],job['budget'],weights,par)
    row['effective_params']=par.model_dump()
    def expire(*unused): raise StudyDeadline('solver wall-clock ceiling')
    signal.signal(signal.SIGALRM,expire)
    start=time.perf_counter();signal.setitimer(signal.ITIMER_REAL,job['budget'])
    try:
        plan=solver.solve(p,cm,context)
        rt=time.perf_counter()-start
    except StudyDeadline:
        return row|{'status':'TIMED_OUT','runtime':time.perf_counter()-start,'budget_used':1.0,'completed':None}
    except Exception as e:
        return row|{'status':'FAILED','runtime':time.perf_counter()-start,'reason':repr(e),'completed':None}
    finally:signal.setitimer(signal.ITIMER_REAL,0)
    if rt > job['budget']:
        return row|{'status':'OVER_BUDGET','runtime':rt,'budget_used':rt/job['budget'],
                    'completed':None,'diagnostic_returned_count':len(plan.assignments)}
    replay=Schedule()
    try:
        for a in sorted(plan.assignments,key=lambda a:a.sat_start_time):
            if not cm.is_feasible_assignment(a,replay):raise ValueError('public replay rejected '+a.task_id)
            replay.assignments.append(a)
        if len(plan.assigned_task_ids)!=len(plan.assignments):raise ValueError('duplicate task')
    except Exception as e:return row|{'status':'REJECTED','reason':repr(e),'runtime':rt,'completed':None}
    if hashlib.sha256(json.dumps(asdict(p),sort_keys=True,default=str).encode()).hexdigest()!=digest:
        raise AssertionError('solver mutated input')
    return row|{'status':'PUBLIC_PASS','completed':len(plan.assignments),'runtime':rt,'budget_used':rt/job['budget'],
                'metrics':asdict(compute_evaluation_metrics(p,plan,rt)),'diagnostics':plan.metadata,
                'formal_certification':'NOT_CERTIFIED'}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--split',choices=SPLITS,default='heldout')
    ap.add_argument('--budget',type=float,default=2);ap.add_argument('--algorithms',nargs='+',default=ALGORITHMS)
    ap.add_argument('--baseline',default='89dff80f881ed4c2a49b43906071ba07012be46c')
    ap.add_argument('--output',type=Path);ap.add_argument('--job',type=Path);ap.add_argument('--result',type=Path)
    ap.add_argument('--params',default='{}');args=ap.parse_args()
    if args.job:
        args.result.write_text(json.dumps(job_run(json.loads(args.job.read_text())),indent=2));return
    if not args.output:ap.error('--output required')
    args.output.mkdir(parents=True,exist_ok=False)
    manifest=dict(split=args.split,budget=args.budget,algorithms=args.algorithms,baseline=args.baseline,
        code_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        implementation_sha256=hashlib.sha256((ROOT/'algorithms/auction_bundle.py').read_bytes()).hexdigest(),
        parameters=json.loads(args.params),python=sys.version,platform=platform.platform(),
        cpu=Path('/proc/cpuinfo').read_text().split('model name')[1].split('\n')[0] if Path('/proc/cpuinfo').exists() else None,
        note='family split frozen before evaluation; synthetic NOT physical; seeds 41/43/47 for stochastic solvers',
        weights={'w_completion':1,'w_profit':0,'w_timeliness':0,'w_balance':0})
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    rows=[]
    for family,scene_seed in SPLITS[args.split]:
      for n in (20,100,300):
       for aid in args.algorithms:
        for seed in ([41,43,47] if aid in RANDOM else [41]):
         job=dict(split=args.split,family=family,scenario_seed=scene_seed,n=n,algorithm=aid,seed=seed,
                  budget=args.budget,baseline=args.baseline,params=json.loads(args.params) if aid=='rabas' else {})
         jid=f'{family}-{n}-{aid}-{seed}';jp=args.output/(jid+'.job.json');rp=args.output/(jid+'.result.json')
         jp.write_text(json.dumps(job));log=args.output/(jid+'.log')
         with log.open('w') as stream:
          process=subprocess.Popen([sys.executable,__file__,'--job',str(jp),'--result',str(rp)],stdout=stream,stderr=stream,start_new_session=True)
          try:process.wait(timeout=args.budget+30)
          except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
         row=json.loads(rp.read_text()) if rp.exists() else job|{'status':'PROCESS_FAILED','completed':None}
         rows.append(row);(args.output/'results.json').write_text(json.dumps(rows,indent=2))
         print(jid,row['status'],row.get('completed'),round(row.get('runtime',0),3),flush=True)
if __name__=='__main__':main()
