"""Read-only real-scene evaluation with the unchanged Controller verifier.
No formal success is inferred from preview success. Outputs outside source tree.
"""
import sys, json, time, hashlib, signal, argparse, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'algorithms').is_dir(): ROOT=Path('/home/asus/projects/eos-course-runtime-rabas-cross-scale')
sys.path.insert(0,str(ROOT))
from eos_system.contracts import RunConfig
from eos_system.provenance import capture_provenance
from eos_system.runner import prepare, run_prepared
from eos_system.verification import verify_candidate
from eos_system.algorithm_registry import get_algorithm, availability
from utils.continuous_exposure import certification_runtime
from schedulers.scenario_loader import load_scheduling_problem_from_json

class StudyDeadline(BaseException):
    pass

SCENES=[('Small','experiments/scenarios/small/Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1.json'),
        ('Small','experiments/scenarios/small/Scenario_S2_Sats20_M20_T1.0d_dist0_epoch_fixed_v1.json'),
        ('Medium','experiments/scenarios/medium/Scenario_S2_Sats50_M100_T3.0d_dist0_epoch_fixed_v1.json'),
        ('Large','docs/Scenario_S1_Sats20_M500_T0.5d_dist0.json')]

def run(scene,aid,budget,seed,mode):
    path=ROOT/scene;digest=hashlib.sha256(path.read_bytes()).hexdigest()
    prov=capture_provenance(path,digest);spec=get_algorithm(aid)
    cfg=RunConfig(run_id='rabas-study-'+digest[:8]+'-'+aid+'-'+str(seed),scenario_id=path.stem,scenario_path=str(path),
        scenario_sha256=digest,algorithm_id=aid,algorithm_version=spec.version,time_budget_s=budget,seed=seed,
        created_at='2026-10-20T00:00:00Z',execution_mode=mode,objective_weights={'w_profit':0,'w_completion':1},scenario_provenance=prov)
    solver,p,cm,ctx=prepare(cfg)
    row=dict(algorithm=aid,scenario=scene,sha256=digest,provenance=prov,n=len(p.tasks),satellites=len(p.satellites),
        windows=sum(len(t.windows) for t in p.tasks.values()),ground_stations=len(p.ground_stations),mode=mode,seed=seed,budget=budget,
        constraints=cfg.constraints.model_dump(),weights=cfg.objective_weights.model_dump())
    def expired(*unused):raise StudyDeadline('solver wall-clock ceiling')
    signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,budget)
    try:candidate,rt=run_prepared(solver,p,cm,ctx)
    except StudyDeadline:return row|{'status':'TIMED_OUT'}
    except Exception as e:return row|{'status':'SOLVER_FAILED','reason':repr(e)}
    finally:signal.setitimer(signal.ITIMER_REAL,0)
    if rt > budget:return row|{'status':'OVER_BUDGET','runtime':rt}
    row.update(runtime=rt,candidate_count=len(candidate['assignments']),diagnostics=candidate.get('solver_diagnostics',{}))
    t=time.monotonic()
    try:
        with certification_runtime(time.monotonic()+60, None):
            official,metrics,receipt=verify_candidate(cfg,candidate,rt)
        row.update(status='CONTROLLER_VERIFIER_PASS',metrics=metrics,receipt=receipt.evidence(),candidate=official)
    except Exception as e:row.update(status='VERIFICATION_REJECTED',reason=repr(e))
    row['verification_runtime']=time.monotonic()-t
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    return row

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--budget',type=float,default=3)
    ap.add_argument('--algorithms',nargs='+',default=['rabas','completion_first','adaptive_repair','profit_first','timeliness_first','balance_first','pressure_repair','caabs','dartis'])
    ap.add_argument('--job',type=Path);a=ap.parse_args()
    if a.job:
        j=json.loads(a.job.read_text())
        try:row=run(**j)
        except Exception as e:row=j|{'status':'PREPARATION_FAILED','reason':repr(e)}
        a.output.write_text(json.dumps(row,indent=2,default=str));return
    a.output.mkdir(parents=True,exist_ok=False);rows=[]
    for scale,scene in SCENES:
      for aid in a.algorithms:
        jid=f'{scale}-{Path(scene).stem}-{aid}'
        jp=a.output/(jid+'.job.json');rp=a.output/(jid+'.result.json')
        jp.write_text(json.dumps(dict(scene=scene,aid=aid,budget=a.budget,seed=41,mode='planning_preview')))
        with (a.output/(jid+'.log')).open('w') as stream:
          try:subprocess.run([sys.executable,__file__,'--job',str(jp),'--output',str(rp)],stdout=stream,stderr=stream,timeout=120,check=False)
          except subprocess.TimeoutExpired:pass
        row=json.loads(rp.read_text()) if rp.exists() else {'status':'PROCESS_TIMEOUT','algorithm':aid,'scenario':scene}
        row['scale']=scale;rows.append(row);(a.output/'results.json').write_text(json.dumps(rows,indent=2,default=str))
        print(scale,aid,row['status'],row.get('metrics',{}).get('completed_tasks'),row.get('runtime'),row.get('reason','')[:120],flush=True)
if __name__=='__main__':main()
