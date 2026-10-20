"""仅用公开验证来源比较原LAVIS、多分支LAVIS与最新基线；禁止读冻结测试。"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(name, '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.lavis.training import splits, load_source, safe_output, write_new
from algorithms.lavis.model import freeze
from eos_system.contracts import RunConfig
from eos_system.config import algorithm_source_sha256
from eos_system.runner import calculate
from eos_system.storage import now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--extra-dataset', required=True, type=Path)
    parser.add_argument('--model-id', default='lavis-v3-ranking')
    parser.add_argument('--scenario-ids', nargs='+', required=True)
    parser.add_argument('--budget', type=float, default=30)
    parser.add_argument('--max-branches', type=int, default=8)
    parser.add_argument('--candidate-strategy', choices=['configured','expanded'], default='expanded')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--variants', nargs='+', choices=['lavis-greedy','lavis-multistart','profit_first','rabas'], default=['lavis-greedy','lavis-multistart','profit_first','rabas'])
    args = parser.parse_args()
    safe_output(args.output, args.dataset); safe_output(args.output, args.extra_dataset)
    if args.output.exists(): parser.error('报告已存在，请使用新文件名')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    allowed = {r['artifact_id']: r for r in splits(args.extra_dataset)['validation']}
    if set(args.scenario_ids) - set(allowed): parser.error('只允许公开验证划分中的场景ID')
    snapshot = freeze(args.model_id); rows = []; started = time.monotonic()
    for sid in args.scenario_ids:
        source = allowed[sid]
        path, _, _, provenance = load_source(args.dataset, source, args.extra_dataset)
        for variant in args.variants:
            algorithm = 'lavis' if variant.startswith('lavis-') else variant
            params = ({'model_id': args.model_id, 'search_mode': variant.split('-')[1],
                       'max_branches': args.max_branches,
                       'candidate_strategy': args.candidate_strategy if variant=='lavis-multistart' else 'configured'} if algorithm == 'lavis' else {})
            config = RunConfig(run_id=str(uuid.uuid4()), created_at=now(), algorithm_id=algorithm,
                algorithm_version='study', algorithm_params=params,
                model_provenance=snapshot if algorithm == 'lavis' else {},
                scenario_id=sid, scenario_path=str(path), scenario_sha256=source['scenario_sha256'],
                scenario_provenance=provenance, algorithm_code_sha=algorithm_source_sha256(),
                execution_mode='physical_validation', objective_weights={'w_profit': 0, 'w_completion': 1},
                time_budget_s=args.budget, seed=42)
            row = {'scenario': sid, 'variant': variant, 'source_group': source['lineage_group_id']}
            try:
                candidate, runtime = calculate(config)
                row.update(completed=len(candidate['assignments']),
                           total=len(candidate['assignments'])+len(candidate['unassigned_tasks']), RT=runtime,
                           diagnostics=candidate.get('solver_diagnostics', {}), status='SOLVER_RETURNED')
                if args.audit:
                    from eos_system.verification import verify_candidate
                    _, metrics, receipt = verify_candidate(config, candidate, runtime)
                    row.update(status='SAMPLED_PHYSICAL_PASS', metrics=metrics,
                               attitude_model_version=receipt.evidence().get('attitude_model_version'))
            except Exception as exc:
                row.update(status='FAILED', error=type(exc).__name__+': '+str(exc))
            rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k!='diagnostics'},ensure_ascii=False),flush=True)
    result = {'model': snapshot, 'budget_s': args.budget, 'max_branches': args.max_branches,
              'seed': 42, 'candidate_strategy': args.candidate_strategy, 'rows': rows, 'seconds': time.monotonic()-started,
              'final_test_used': False, 'training_performed': False,
              'scope': 'serial solver and optional independent physical verifier; not parallel speed comparison'}
    write_new(args.output, result)


if __name__ == '__main__':
    main()
