"""在同一公开验证来源、候选与预算下比较冻结LAVIS模型，可做独立物理采样核验。"""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(name,'1')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from algorithms.lavis.training import splits,load_source,safe_output,write_new
from algorithms.lavis.model import freeze
from eos_system.config import algorithm_source_sha256
from eos_system.contracts import RunConfig
from eos_system.runner import calculate
from eos_system.storage import now


def summarize(rows):
    """兄弟场景先组内平均再求家族宏平均；错误另列，不当零分补入。"""
    result={}
    for model in sorted({r['model_id'] for r in rows}):
        groups={}
        for origin in ('eos-course-v1','lavis-conflict-v1'):
            subset=[r for r in rows if r['model_id']==model and r['origin']==origin]
            good=[r for r in subset if r['status']!='FAILED']
            families=defaultdict(list)
            for r in good:families[r['source_group']].append(r['completed']/r['total'])
            groups[origin]=dict(completed=sum(r['completed'] for r in good),
                total=sum(r['total'] for r in good),failed=len(subset)-len(good),sources=len(good),
                family_macro_TCR=sum(sum(v)/len(v) for v in families.values())/len(families) if families else None)
        result[model]=groups
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',required=True,type=Path)
    parser.add_argument('--extra-dataset',required=True,type=Path)
    parser.add_argument('--model-ids',required=True,nargs='+')
    parser.add_argument('--scenario-ids',nargs='+')
    parser.add_argument('--search-mode',choices=['greedy','multistart'],default='multistart')
    parser.add_argument('--candidate-strategy',choices=['configured','expanded'],default='expanded')
    parser.add_argument('--budget',type=float,default=30.)
    parser.add_argument('--audit',action='store_true')
    parser.add_argument('--orekit-data',type=Path,default=ROOT/'utils/orekit-data.zip')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    safe_output(args.output,args.dataset);safe_output(args.output,args.extra_dataset)
    if args.output.exists():parser.error('请使用新的报告文件名')
    if not .2<args.budget<=600:parser.error('预算应大于0.2且不超过600')
    sources=splits(args.extra_dataset)['validation']
    if args.scenario_ids:
        selected=set(args.scenario_ids);known={r['artifact_id'] for r in sources}
        if selected-known:parser.error('只能选择公开验证来源')
        sources=[r for r in sources if r['artifact_id'] in selected]
    snapshots={mid:freeze(mid) for mid in args.model_ids}
    code=algorithm_source_sha256();rows=[];started=time.perf_counter()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    old_data=os.environ.get('EOS_OREKIT_DATA')
    with tempfile.TemporaryDirectory(prefix='eos-lavis-v4-audit-') as tempdir:
        temp=Path(tempdir)
        if args.audit:
            copied=temp/'orekit-data.zip';shutil.copyfile(args.orekit_data,copied)
            os.environ['EOS_OREKIT_DATA']=str(copied)
        try:
            for source in sources:
                path,_,_,provenance=load_source(args.dataset,source,args.extra_dataset)
                for mid,snapshot in snapshots.items():
                    config=RunConfig(run_id=str(uuid.uuid4()),created_at=now(),algorithm_id='lavis',
                        algorithm_version='model-comparison',model_provenance=snapshot,
                        algorithm_params=dict(model_id=mid,search_mode=args.search_mode,candidate_strategy=args.candidate_strategy,max_branches=8),
                        scenario_id=source['artifact_id'],scenario_path=str(path),scenario_sha256=source['scenario_sha256'],
                        scenario_provenance=provenance,algorithm_code_sha=code,execution_mode='physical_validation',
                        objective_weights={'w_profit':0,'w_completion':1},time_budget_s=args.budget,seed=42)
                    record=dict(scenario=source['artifact_id'],scenario_sha256=source['scenario_sha256'],
                        source_group=source['lineage_group_id'],origin=source.get('data_origin','eos-course-v1'),model_id=mid)
                    try:
                        candidate,runtime=calculate(config)
                        record.update(status='SOLVER_RETURNED',completed=len(candidate['assignments']),
                            total=len(candidate['assignments'])+len(candidate['unassigned_tasks']),RT=runtime)
                        if args.audit:
                            from eos_system.verification import verify_candidate
                            _,metrics,receipt=verify_candidate(config,candidate,runtime)
                            record.update(status='SAMPLED_PHYSICAL_PASS',metrics=metrics,
                                attitude_model_version=receipt.evidence().get('attitude_model_version'))
                    except Exception as exc:
                        record.update(status='FAILED',error=type(exc).__name__+': '+str(exc))
                    rows.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
        finally:
            if old_data is None:os.environ.pop('EOS_OREKIT_DATA',None)
            else:os.environ['EOS_OREKIT_DATA']=old_data
    report=dict(models=snapshots,algorithm_code_sha256=code,rows=rows,summary=summarize(rows),
        seed=42,time_budget_s=args.budget,search_mode=args.search_mode,candidate_strategy=args.candidate_strategy,max_branches=8,
        final_test_used=False,training_performed=False,temporary_data_cleaned=not temp.exists(),
        seconds=time.perf_counter()-started,scope='public development validation; sampled physics is not continuous certification')
    write_new(args.output,report)
    print(json.dumps({'summary':report['summary'],'output':str(args.output)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
