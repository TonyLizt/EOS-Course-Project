"""Index/check canonical bundles and run a resumable dynamic two-goal API matrix."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from eos_system.dataset_registry import entries,resolve
from scripts.build_shared_dataset import file_sha,digest
from scripts.matrix_journal import MatrixJournal,atomic_json


def save(path,value):
    atomic_json(path,value)


def index(root):
    from scripts.build_scenario_manifest import audit_file
    from schedulers.scenario_loader import load_scheduling_problem_from_json
    from eos_system.provenance import capture_execution_provenance
    rows=entries(root);result=[]
    matrix_path=ROOT/'experiments/runs/eos-v1/matrix-full.json'
    matrix={}
    if matrix_path.is_file():
        checkpoint=json.loads(matrix_path.read_text())
        matrix=MatrixJournal(matrix_path,checkpoint['source_sha256'],checkpoint['models']).load(checkpoint,allow_incomplete_tail=True)
    observations={}
    for case in matrix.get('cases',[]):
        observations.setdefault(case['scenario_id'],[]).append(case)
    algorithm_ids=[a['algorithm_id'] for a in matrix.get('algorithm_catalog',[])]
    initial_path=ROOT/'experiments/runs/eos-v1/initial-models-full.json'
    initial=json.loads(initial_path.read_text()) if initial_path.is_file() else {'cases':[]}
    initial_observations={}
    for case in initial['cases']:initial_observations.setdefault(case['scenario_id'],[]).append(case)
    core_task_hashes=[]
    for row in rows:
        path,sha=resolve(root,row['scenario_id']);audit=audit_file(path)
        assert audit['status']!='FAIL',audit
        assert audit['record']['internal_scenario_id']==row['scenario_id'],'internal ID differs from Registry'
        model=load_scheduling_problem_from_json(path)
        assert (len(model.satellites),len(model.tasks))==(row['satellite_count'],row['mission_count'])
        evidence=capture_execution_provenance(path,sha,'physical_validation')
        assert (path.parent/'provenance.json').read_bytes()==(path.parent/'provenance/scenario.json.provenance.json').read_bytes()
        raw=json.loads(path.read_text());provenance=json.loads(path.with_name('provenance.json').read_text())
        role='narrow_window' if row['difficulty_profile']=='narrow_window' else 'core' if row['scenario_id'].endswith('-r3') else 'retained_trial'
        task_sha=digest(raw['missions'])
        if role=='core':core_task_hashes.append(task_sha)
        checked=[]
        for c in observations.get(row['scenario_id'],[]):
            assert c['scenario_sha256']==sha,'matrix belongs to different scenario bytes'
            if not c.get('terminal'):continue
            checked.append(dict(algorithm_id=c['algorithm_id'],objective=c['objective'],objective_weights=c['objective_weights'],
                run_id=c.get('run_id'),status=c['run_status'],outcome=c.get('outcome'),
                verification_status='NOT_RUN' if c.get('failure_code') in ('ALGORITHM_TIMEOUT','WORKER_EXIT_TIMEOUT') else 'ERROR' if c.get('failure_code')=='PHYSICS_ERROR' and 'PREVIEW_INVALID_RESPONSE' in str(c.get('failure_reason')) else c.get('verification_status'),
                raw_harness_verification_status=c.get('verification_status'),assigned_task_count=c.get('assigned_task_count'),
                failure_code=c.get('failure_code'),budget_state=c.get('budget_state'),
                model_identity={k:(c.get('model_identity') or {}).get(k) for k in ('model_id','model_sha256','manifest_sha256')} if c.get('model_identity') else None))
        expected=len(algorithm_ids)*2
        passed=sum(c['status']=='SUCCEEDED' and (c.get('assigned_task_count') or 0)>0 and c['verification_status']=='SAMPLED_PASS' for c in checked)
        state='NOT_RUN' if not checked else 'IN_PROGRESS' if len(checked)<expected else 'ALL_NONEMPTY_PLANS_VERIFIED' if passed==expected else 'FULLY_ATTEMPTED_WITH_LIMITS'
        initial_checked=[]
        for c in initial_observations.get(row['scenario_id'],[]):
            assert c['scenario_sha256']==sha,'initial-model matrix belongs to different scenario bytes'
            initial_checked.append({k:c.get(k) for k in ('algorithm_id','role','objective','objective_weights','run_status',
                'outcome','verification_status','assigned_task_count','runtime_seconds','failure_code','failure_reason')})
        result.append(dict(row,relative_path=path.relative_to(ROOT).as_posix(),schema_status=audit['status'],dataset_role=role,
            provenance_status=evidence['provenance_status'],physics_status='SAMPLED_PASS',continuous_status='INCONCLUSIVE',
            split=provenance['split'],task_semantic_sha256=task_sha,
            lineage_equivalence_group=digest(dict(orbits=[s['orbital_params'] for s in raw['satellites']],missions=raw['missions'])),
            parent_scenario_id=provenance.get('parent_scenario_id'),parent_scenario_sha256=provenance.get('parent_scenario_sha256'),
            raw_inputs=provenance['raw_inputs'],generator_version=provenance['generator_version'],generator_git_commit=provenance['generator_git_commit'],
            generation_code_sha256=provenance['generation_code_sha256'],generation_wall_s=provenance['generation_wall_s'],
            provenance_path=path.with_name('provenance.json').relative_to(ROOT).as_posix(),provenance_sha256=file_sha(path.with_name('provenance.json')),
            validation_path=path.with_name('validation.json').relative_to(ROOT).as_posix(),characterization_path=path.with_name('characterization.json').relative_to(ROOT).as_posix(),
            all_algorithm_validation_status=state,expected_algorithm_goals=expected,observed_algorithm_goals=len(checked),
            verified_nonempty_algorithm_goals=passed,algorithm_objective_results=checked,formal_release_eligible=False))
        result[-1]['initial_model_objective_results']=initial_checked
    assert len(core_task_hashes)==len(set(core_task_hashes)),'duplicate core task collections; not independent seeds'
    folder=ROOT/'data/registry';manifest=dict(dataset_id='eos-v1',publication_status='development',scenarios=result)
    save(folder/'scenario_manifest.json',manifest)
    csv_text=io.StringIO();writer=csv.DictWriter(csv_text,fieldnames=list(result[0]) if result else ['scenario_id'])
    writer.writeheader();writer.writerows([{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in result]);(folder/'scenario_manifest.csv').write_text(csv_text.getvalue(),encoding='utf-8-sig')
    plan_path=next(root/name for name in ('dataset_plan_v3.json','dataset_plan_v2.json','dataset_plan.json') if (root/name).exists())
    planned=json.loads(plan_path.read_text())['allocation'];done={r['scenario_id'] for r in rows}
    planned_ids={r['scenario_id'] for r in planned}
    observed=[c for c in matrix.get('cases',[]) if c['scenario_id'] in done and c.get('terminal')]
    expected_goals=len(rows)*len(algorithm_ids)*2
    save(folder/'dataset_manifest.json',dict(dataset_id='eos-v1',publication_status='development',
        planned=len(planned),generated_core=len(done&planned_ids),additional_instances=len(done-planned_ids),total_available=len(rows),
        independent_core_task_collections=len(set(core_task_hashes)),pending=[r for r in planned if r['scenario_id'] not in done],
        manifest_path='data/registry/scenario_manifest.json',canonical_root='data/scenarios/eos-v1',
        final_test_used=False,
        comparison_registry_algorithms=len(algorithm_ids),expected_algorithm_goal_combinations=expected_goals,
        terminal_algorithm_goal_combinations=len(observed),pending_algorithm_goal_combinations=expected_goals-len(observed),
        comparison_matrix_path='experiments/runs/eos-v1/compatibility_matrix.json',
        initial_model_matrix_path='experiments/runs/eos-v1/initial-models-full.json',
        initial_model_observed_combinations=sum(len(r['initial_model_objective_results']) for r in result),
        all_algorithm_matrix_status='NOT_RUN' if not observed else 'IN_PROGRESS' if len(observed)<expected_goals else
            'ALL_NONEMPTY_PLANS_VERIFIED' if all(r['verified_nonempty_algorithm_goals']==r['expected_algorithm_goals'] for r in result) else 'FULLY_ATTEMPTED_WITH_LIMITS'))
    save(folder/'provenance/index.json',dict(authority='canonical bundle provenance.json; compatibility mirrors checked byte-identical',
        scenarios=[{k:r[k] for k in ('scenario_id','sha256','provenance_path','provenance_sha256','lineage_group_id','lineage_equivalence_group','parent_scenario_id','parent_scenario_sha256')} for r in result]))
    print('INDEX',len(result),'of',len(planned),flush=True)


def matrix(args):
    for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[n]='1'
    os.environ['EOS_RUNTIME_DIR']=str(args.runtime.resolve())
    os.environ['EOS_OREKIT_DATA']=str(args.orekit_data.resolve())
    from eos_system.api import create_app
    from eos_system.config import Settings,algorithm_source_sha256
    from eos_system.algorithm_registry import list_algorithms,list_schedule_models
    from test_replay_backend import _DirectClient
    app=create_app(Settings(args.runtime.resolve(),args.root.resolve(),max_workers=args.workers,max_queued=32,startup_timeout_s=90))
    client=_DirectClient(app);owner=app.state.controller
    report_path=args.output;source=algorithm_source_sha256()
    journal=MatrixJournal(report_path,source,args.models)
    report=journal.load(dict(source_sha256=source,cases=[],models=args.models,
        scope='all comparison algorithms from Registry; initial-model roles listed separately',initial_model_registry=list_schedule_models()))
    current_harness=file_sha(Path(__file__))
    prior_harness=report.get('current_persistence_harness_sha256')
    if prior_harness and prior_harness!=current_harness:
        report.setdefault('harness_history',[]).append(dict(harness_sha256=prior_harness,
            journal_code_sha256=report.get('current_journal_code_sha256'),
            completed_at_transition=sum(c.get('terminal',False) for c in report['cases']),
            reason='resumable bounded rolling submission; same algorithm source/models/scenarios/budget'))
    report['current_persistence_harness_sha256']=current_harness
    report['current_journal_code_sha256']=file_sha(Path(__file__).with_name('matrix_journal.py'))
    assert report['source_sha256']==source and report['models']==args.models,'matrix code/model identity changed; use new report'
    catalog=list_algorithms();report['algorithm_catalog']=catalog
    rows=entries(args.root)
    if args.scenario_ids:rows=[r for r in rows if r['scenario_id'] in args.scenario_ids]
    if args.limit:rows=rows[:args.limit]
    goals=dict(TP=dict(w_profit=1.,w_completion=0.,w_timeliness=0.,w_balance=0.),
               TCR=dict(w_profit=0.,w_completion=1.,w_timeliness=0.,w_balance=0.))
    expected=len(rows)*len(catalog)*len(goals);report['expected_generated_combinations']=expected
    def persist(force=False):
        journal.persist(report,force=force)
    def submissions():
        for scene in rows:
            for goal,weights in goals.items():
                for algorithm in catalog:
                    aid=algorithm['algorithm_id'];key=scene['scenario_id']+'/'+aid+'/'+goal
                    old=next((c for c in report['cases'] if c['key']==key),None)
                    if old:
                        assert old['scenario_sha256']==scene['sha256'],'resume scenario bytes changed; use a new matrix'
                        assert old['objective_weights']==weights,'resume objective changed; use a new matrix'
                        prior_config=(old.get('detail') or {}).get('config')
                        if prior_config:
                            assert prior_config['time_budget_s']==args.budget,'resume budget changed; use a new matrix'
                    if old and old.get('terminal'):
                        if old.get('run_status')=='SUCCEEDED' or not args.retry_failed:continue
                        history=old.setdefault('attempt_history',[])
                        history.append({k:v for k,v in old.items() if k!='attempt_history'})
                        old.pop('run_id',None);old['terminal']=False
                    case=old or dict(key=key,scenario_id=scene['scenario_id'],scenario_sha256=scene['sha256'],
                        satellite_count=scene['satellite_count'],task_count=scene['mission_count'],difficulty_profile=scene['difficulty_profile'],
                        algorithm_id=aid,objective=goal,objective_weights=weights,model_identity=None,terminal=False)
                    if not old:report['cases'].append(case)
                    if not case.get('run_id'):
                        request=dict(scenario_id=scene['scenario_id'],algorithm_id=aid,objective_weights=weights,
                            algorithm_params={'model_id':args.models[aid]} if aid in args.models else {},
                            time_budget_s=args.budget,seed=scene['seed'],execution_mode='physical_validation')
                        response=client.post('/api/experiments',json={'runs':[request]})
                        case['submission_http_status']=response.status_code
                        if response.status_code!=202:
                            case.update(run_status='REQUEST_REJECTED',failure_reason=str(response.json()),failure_code='API_REJECTED',
                                verification_status='NOT_RUN',feasibility_status='NOT_RUN',terminal=True);persist();continue
                        case['run_id']=response.json()['runs'][0]['run_id'];persist()
                    yield case
    pending=[];iterator=submissions();finished=False;deadlines={}
    report.setdefault('execution_phases',[]).append(dict(harness_sha256=file_sha(Path(__file__)),
        workers=args.workers,submission_window=args.submission_window,
        starting_completed=sum(c.get('terminal',False) for c in report['cases'])))
    try:
        owner.start()
        while pending or not finished:
            while not finished and len(pending)<args.submission_window:
                case=next(iterator,None)
                if case is None:finished=True;break
                pending.append(case);deadlines[case['key']]=time.monotonic()+max(600,args.submission_window*(args.budget+45))
            for case in pending[:]:
                run=app.state.database.get_run(case['run_id'])
                if run['status'] not in ('SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'):continue
                detail=client.get('/api/runs/'+case['run_id']).json()
                # Database API retains the exact frozen request and independent receipt.
                metrics=detail.get('metrics') or {};config=detail.get('config',{})
                assert config['scenario_sha256']==case['scenario_sha256'] and config['objective_weights']==case['objective_weights']
                case.update(run_status=run['status'],runtime_seconds=metrics.get('RT'),assigned_task_count=metrics.get('completed_tasks'),
                    model_identity=config.get('model_provenance'),failure_reason=detail.get('error'),
                    verification_status='SAMPLED_PASS' if run['status']=='SUCCEEDED' else 'FAILED',
                    feasibility_status='PASS' if run['status']=='SUCCEEDED' else 'NOT_ESTABLISHED',
                    failure_code=(detail.get('error') or {}).get('code') if isinstance(detail.get('error'),dict) else None,
                    terminal=True,detail=detail)
                case['outcome']='EMPTY_VALID_PLAN' if run['status']=='SUCCEEDED' and metrics.get('completed_tasks')==0 else run['status']
                diag=next(((e.get('payload') or {}).get('untrusted_solver_diagnostics') for e in detail.get('events',[])
                           if isinstance((e.get('payload') or {}).get('untrusted_solver_diagnostics'),dict)),{})
                case['solver_diagnostics']=diag
                def exhausted(value):
                    return isinstance(value,dict) and (value.get('budget_exit') is True or any(exhausted(v) for v in value.values()))
                case['budget_state']='REPORTED_EXHAUSTED' if exhausted(diag) else 'NO_EXHAUSTION_REPORTED' if diag else 'NOT_REPORTED'
                if run['status']=='SUCCEEDED' and exhausted(diag):case['outcome']='FEASIBLE_PLAN_AT_BUDGET' if metrics.get('completed_tasks') else 'EMPTY_PLAN_AT_BUDGET'
                pending.remove(case);deadlines.pop(case['key']);persist()
                if report['completed_combinations']%20==0:
                    print('MATRIX_PIPELINE',report['completed_combinations'],'/',expected,'in_flight',len(pending),flush=True)
            if any(time.monotonic()>deadlines[c['key']] for c in pending):
                persist();raise TimeoutError('matrix per-run queue/start/solve/verification wait deadline; actual pending retained')
            if pending:time.sleep(.25)
    finally:
        persist(force=True);owner.stop();app.state.replay.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['index','matrix','list'])
    p.add_argument('--root',type=Path,default=ROOT/'data/scenarios/eos-v1')
    p.add_argument('--runtime',type=Path,default=ROOT/'experiments/runs/eos-v1')
    p.add_argument('--output',type=Path,default=ROOT/'experiments/runs/eos-v1/matrix.json')
    p.add_argument('--orekit-data',type=Path,default=ROOT/'utils/orekit-data.zip')
    p.add_argument('--budget',type=float,default=5);p.add_argument('--workers',type=int,default=2)
    p.add_argument('--submission-window',type=int,default=24,choices=range(1,25),
        help='Bound unfinished submissions across scenes; does not change per-run budget or Worker limit')
    p.add_argument('--limit',type=int);p.add_argument('--scenario-ids',nargs='+')
    p.add_argument('--retry-failed',action='store_true',help='Keep prior attempt records and execute failed combinations again')
    p.add_argument('--satellites',type=int);p.add_argument('--tasks',type=int);p.add_argument('--difficulty');p.add_argument('--scale')
    p.add_argument('--ppo-model',default='ppo-eos-v1-dev-20261023');p.add_argument('--lavis-model',default='lavis-eos-v1-dev-20261023')
    args=p.parse_args();args.models=dict(ppo=args.ppo_model,lavis=args.lavis_model)
    if args.command=='index':index(args.root)
    elif args.command=='matrix':matrix(args)
    else:print(json.dumps(entries(args.root,satellite_count=args.satellites,task_count=args.tasks,difficulty_profile=args.difficulty,scale=args.scale),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
