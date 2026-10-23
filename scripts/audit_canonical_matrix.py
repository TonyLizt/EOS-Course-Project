"""Independently check actual matrix coverage, identities, goals and receipts."""
import argparse
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from eos_system.dataset_registry import entries,resolve
from scripts.matrix_journal import atomic_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--matrix',type=Path,default=ROOT/'experiments/runs/eos-v1/matrix-full.json')
    p.add_argument('--root',type=Path,default=ROOT/'data/scenarios/eos-v1')
    p.add_argument('--output',type=Path,default=ROOT/'experiments/runs/eos-v1/matrix-integrity.json')
    p.add_argument('--allow-partial',action='store_true');args=p.parse_args()
    from eos_system.algorithm_registry import list_algorithms
    from eos_system.config import algorithm_source_sha256
    source=algorithm_source_sha256();checkpoint=json.loads(args.matrix.read_text())
    assert checkpoint['source_sha256']==source
    # Replay independently, without relying on the producer's recovery method.
    # This also permits checking an older immutable execution harness snapshot.
    report=dict(checkpoint);latest={c['key']:c for c in checkpoint['cases']}
    journal=args.matrix.with_suffix('.jsonl')
    if journal.is_file():
        with journal.open() as stream:
            for line in stream:
                try:record=json.loads(line)
                except json.JSONDecodeError:
                    if args.allow_partial and not line.endswith('\n'):break
                    raise
                assert record['source_sha256']==source and record['models']==checkpoint['models']
                if 'case' in record:latest[record['case']['key']]=record['case']
    report['cases']=list(latest.values())
    if not args.allow_partial:
        assert {c['key']:c for c in checkpoint['cases']}==latest,'final checkpoint differs from journal'
    rows=entries(args.root);identities={r['scenario_id']:resolve(args.root,r['scenario_id'])[1] for r in rows}
    algorithms={a['algorithm_id']:a for a in list_algorithms()}
    from algorithms.ppo.model import freeze as freeze_ppo
    from algorithms.lavis.model import freeze as freeze_lavis
    current_models={aid:freeze(model_id) for aid,model_id,freeze in (
        ('ppo',report['models']['ppo'],freeze_ppo),('lavis',report['models']['lavis'],freeze_lavis))}
    goals={'TP':dict(w_profit=1.,w_completion=0.,w_timeliness=0.,w_balance=0.),
        'TCR':dict(w_profit=0.,w_completion=1.,w_timeliness=0.,w_balance=0.)}
    expected={f'{sid}/{aid}/{goal}' for sid in identities for aid in algorithms for goal in goals}
    seen=set();terminal=set();constraints=defaultdict(set);resources=Counter();good=0;empty=0;classified=[]
    for c in report['cases']:
        key=c['key'];assert key in expected and key not in seen,key
        seen.add(key);sid=c['scenario_id'];weights=goals[c['objective']]
        assert key==f"{sid}/{c['algorithm_id']}/{c['objective']}"
        assert c['scenario_sha256']==identities[sid] and c['objective_weights']==weights
        if not c.get('terminal'):continue
        terminal.add(key)
        detail=c.get('detail') or {};error=detail.get('error') or {}
        code=(error.get('code') if isinstance(error,dict) else None) or c.get('failure_code')
        success=c['run_status']=='SUCCEEDED'
        category=c['outcome'] if success else 'SOLVER_TIMEOUT' if code=='ALGORITHM_TIMEOUT' else c['run_status']
        if code=='WORKER_EXIT_TIMEOUT':category='WORKER_LIFECYCLE_ERROR'
        if code=='PHYSICS_ERROR' and 'PREVIEW_INVALID_RESPONSE' in str(error):category='VERIFICATION_PROTOCOL_ERROR'
        record={k:c.get(k) for k in ('key','run_id','scenario_id','scenario_sha256','satellite_count','task_count',
            'difficulty_profile','algorithm_id','objective','objective_weights','model_identity','run_status',
            'runtime_seconds','assigned_task_count','budget_state')}
        record.update(result_category=category,
            feasibility_status='PASS' if success else 'NOT_ESTABLISHED',
            verification_status='SAMPLED_PASS' if success else 'NOT_RUN' if code in ('ALGORITHM_TIMEOUT','WORKER_EXIT_TIMEOUT') or c['run_status']=='REQUEST_REJECTED' else 'ERROR' if category=='VERIFICATION_PROTOCOL_ERROR' else 'NOT_ESTABLISHED',
            raw_harness_verification_status=c.get('verification_status'),
            failure_code=code,failure_reason=c.get('failure_reason'),
            worker_limit=(detail.get('execution_resources') or {}).get('worker_limit'))
        record.update({k:(detail.get('metrics') or {}).get(k) for k in ('TP','TCR','TM','BD','RT')})
        classified.append(record)
        if c['run_status']=='REQUEST_REJECTED':continue
        d=c['detail'];cfg=d['config'];assert d['status']==c['run_status']
        assert cfg['scenario_sha256']==identities[sid] and cfg['scenario_id']==sid
        assert cfg['algorithm_id']==c['algorithm_id'] and cfg['objective_weights']==weights
        assert cfg['algorithm_code_sha']==source and cfg['algorithm_version']==algorithms[c['algorithm_id']]['version']
        assert cfg['time_budget_s']==5 and cfg['execution_mode']=='physical_validation'
        constraints[sid].add(json.dumps({k:cfg[k] for k in ('constraints','placement_mode','schedule_model')},sort_keys=True))
        adapter=cfg.get('objective_adapter')
        if adapter:
            assert adapter['requested_objective']==weights and adapter['effective_objective']==weights
        if c['algorithm_id'] in report['models']:
            assert cfg['model_provenance']['model_id']==report['models'][c['algorithm_id']]
            assert c['model_identity']==cfg['model_provenance']
            for field in ('model_id','model_sha256','manifest_sha256','inference_code_sha256_lf'):
                assert cfg['model_provenance'][field]==current_models[c['algorithm_id']][field]
        limit=(d.get('execution_resources') or {}).get('worker_limit')
        if limit:resources[limit]+=1
        if c['run_status']=='SUCCEEDED':
            receipt=d['preview_validation'];metrics=d['metrics']
            assert d['result_kind']=='physical_validation' and receipt['status']=='SAMPLED_PHYSICAL_PASS'
            assert receipt['scenario_sha256']==identities[sid] and receipt['run_id']==c['run_id']
            assert receipt['completed_tasks']==c['assigned_task_count']==metrics['completed_tasks']
            if c['assigned_task_count']:
                assert receipt['audit_summary']['counts']['FAIL']==0
            else:
                assert receipt['audit_summary']==dict(reason='EMPTY_PREVIEW_PLAN',rows=[])
            assert c['verification_status']=='SAMPLED_PASS' and c['feasibility_status']=='PASS'
            assert c['assigned_task_count']<=c['task_count']
            good+=bool(c['assigned_task_count']);empty+=not c['assigned_task_count']
    assert all(len(v)==1 for v in constraints.values()),'algorithm-dependent public constraints'
    result=dict(source_sha256=source,registry_algorithms=len(algorithms),scenarios=len(identities),
        expected=len(expected),recorded=len(seen),terminal=len(terminal),missing=sorted(expected-terminal),
        unexpected=sorted(seen-expected),statuses=dict(Counter(c['run_status'] for c in report['cases'] if c.get('terminal'))),
        nonempty_verified=good,empty_verified=empty,worker_limits=dict(resources),
        scenario_sha_objective_model_and_receipt_checks='PASS',identical_public_constraints='PASS',
        scope='JSON evidence consistency; not a new physical solver run or cryptographic attestation')
    atomic_json(args.output,result)
    atomic_json(args.output.parent/'compatibility_matrix.json',dict(expected=len(expected),terminal=len(terminal),
        source_sha256=source,definition='Actual run statuses retained. ALGORITHM_TIMEOUT means no physical verification was reached, not a physical-predicate failure.',cases=classified))
    if classified:
        with (args.output.parent/'compatibility_matrix.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,list(classified[0]));writer.writeheader()
            writer.writerows([{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in c.items()} for c in classified])
    if not args.allow_partial:assert not result['missing'],'matrix incomplete; see output'
    print('MATRIX_INTEGRITY_PASS',len(terminal),'/',len(expected),'missing',len(result['missing']),flush=True)


if __name__=='__main__':main()
