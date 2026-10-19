#!/usr/bin/env python3
"""冻结模型在原验证及可选高冲突验证来源上独立重跑；可选共享Controller核验器的真实Orekit全曝光检查。"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ.setdefault(name,'1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from algorithms.lavis.training import splits,load_source,write_new,safe_output
from algorithms.lavis.model import freeze
from eos_system.config import algorithm_source_sha256
from eos_system.contracts import RunConfig
from eos_system.runner import calculate
from eos_system.verification import verify_candidate
from eos_system.storage import now

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--algorithm',choices=['lavis','completion_first','adaptive_repair'],default='lavis')
    parser.add_argument('--model-id',default='lavis-v1')
    parser.add_argument('--extra-dataset',type=Path)
    parser.add_argument('--cohort',choices=['all','original','conflict'],default='all')
    parser.add_argument('--budget',type=float,default=15.)
    parser.add_argument('--audit',action='store_true')
    args=parser.parse_args();safe_output(args.output,args.dataset)
    if args.output.exists():parser.error('output已存在；请用新的报告文件名')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    snapshot=freeze(args.model_id) if args.algorithm=='lavis' else {}
    config_sha=algorithm_source_sha256();results=[];started=time.perf_counter()
    for row in splits(args.extra_dataset)['validation']:
        origin=row.get('data_origin','eos-course-v1')
        if args.cohort=='original' and origin!='eos-course-v1':continue
        if args.cohort=='conflict' and origin!='lavis-conflict-v1':continue
        path,_,_,provenance=load_source(args.dataset,row,args.extra_dataset)
        config=RunConfig(run_id=str(uuid.uuid4()),created_at=now(),algorithm_id=args.algorithm,
            algorithm_version='0.1.0' if args.algorithm=='lavis' else 'baseline-1',
            algorithm_params={'model_id':args.model_id} if snapshot else {},model_provenance=snapshot,
            scenario_id=row['artifact_id'],scenario_path=str(path),scenario_sha256=row['scenario_sha256'],
            scenario_provenance=provenance,algorithm_code_sha=config_sha,
            execution_mode='physical_validation',objective_weights={'w_profit':0,'w_completion':1},
            time_budget_s=args.budget)
        stamp=time.perf_counter();candidate,runtime=calculate(config)
        record=dict(row,completed=len(candidate['assignments']),total=len(candidate['assignments'])+len(candidate['unassigned_tasks']),
                    RT=runtime,end_to_end_seconds=time.perf_counter()-stamp)
        if args.audit:
            official,metrics,receipt=verify_candidate(config,candidate,runtime)
            record.update(status='SAMPLED_PHYSICAL_PASS',audit_seconds=time.perf_counter()-stamp-record['end_to_end_seconds'],
                          physical_validation=json.loads(receipt.evidence_json) if hasattr(receipt,'evidence_json') else 'passed')
        results.append(record);print(json.dumps({k:v for k,v in record.items() if k!='physical_validation'},ensure_ascii=False),flush=True)
    if not results:raise ValueError('EMPTY_SELECTED_VALIDATION_COHORT')
    write_new(args.output,dict(cohort=args.cohort,algorithm=args.algorithm,model=snapshot,time_budget_s=args.budget,
        code_sha256=config_sha,results=results,completed=sum(r['completed'] for r in results),
        macro_TCR=sum(r['completed']/r['total'] for r in results)/len(results),
        seconds=time.perf_counter()-started,final_test_used=False,
        scope='Controller verifier/Orekit finite sampling; NOT_CERTIFIED' if args.audit else 'solver only'))

if __name__=='__main__':main()
