"""机会成本监督训练：只读训练白名单；验证选择与最终测试严格分开。"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(name, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from algorithms.lavis import training
from algorithms.lavis.candidates import build_pool, feasible, key
from algorithms.lavis.features import extract
from algorithms.lavis.labels import conflict_options, random_key
from algorithms.lavis.model import FrozenPredictor, freeze, digest, inference_code_sha, dependencies, model_root
from algorithms.lavis.protocol import Control, BudgetExpired, LavisParams, FEATURE_NAMES, FEATURE_VERSION, CANDIDATE_VERSION, DOMAIN, POOL_CONFIG
from algorithms.lavis.solver import LavisScheduler
from schedulers.constraint_model import Schedule

LABEL_SCHEMA = 'lavis-opportunity-cost-v1'


def opportunity_target(before, after, chosen_task):
    """优先惩罚其他任务完全失去机会；辅项区分保留的候选多样性。"""
    old = Counter(a.task_id for a in before if a.task_id != chosen_task)
    new = Counter(a.task_id for a in after if a.task_id != chosen_task)
    lost = sum(new[t] == 0 for t in old)
    fraction = sum(1-min(1., new[t]/count) for t, count in old.items()) / max(1, len(old))
    return -lost - .25*fraction, lost, fraction


def sample_actions(current, matrix, predictor, seed, state, limit=12):
    """模型/压力/随机三种覆盖；不把未采样候选标成低分。"""
    if len(current) <= limit:
        return list(current)
    scores = list(map(float, predictor.predict(matrix)))
    import math
    if len(scores) != len(current) or not all(map(math.isfinite, scores)):
        raise ValueError('INVALID_SAMPLE_PREDICTIONS')
    ordered = sorted(range(len(current)), key=lambda i: (-scores[i], key(current[i])))
    selected = [current[i] for i in ordered[:4]]
    pressure = conflict_options(current, matrix, 4, seed, state)
    random = sorted(current, key=lambda a: random_key(seed, state, key(a)))
    seen = set(); result = []
    for a in selected + pressure + random:
        if key(a) not in seen:
            seen.add(key(a)); result.append(a)
        if len(result) >= limit:
            break
    return result


def label_state(problem, constraints, pool, plan, predictor, source, state, seed=42):
    """全池重新核验反事实，不假设增加观测只会删除旧候选。"""
    current = feasible(pool, plan, constraints, Control())
    if not current:
        return []
    matrix = extract(problem, plan, pool, current, Control())
    positions = {key(a): i for i, a in enumerate(current)}
    identity = digest(training.encode([source['scenario_sha256'], sorted(key(a) for a in plan.assignments)]))
    result = []
    for a in sample_actions(current, matrix, predictor, seed, identity):
        after = feasible(pool, Schedule(plan.assignments + [a]), constraints, Control())
        target, lost, fraction = opportunity_target(current, after, a.task_id)
        result.append(dict(source, state_hash=identity, state_id=state, candidate=key(a),
            features=matrix[positions[key(a)]], y=target, lost_tasks=lost,
            opportunity_fraction_loss=fraction, label_schema=LABEL_SCHEMA,
            fixed_assignments=[key(item) for item in plan.assignments]))
    # 消除不同状态可达规模带来的绝对偏移，只学习同状态相对决策。
    mean = sum(r['y'] for r in result)/len(result)
    for r in result:
        r['raw_target'] = r['y']; r['y'] -= mean
    return result


def collect(dataset, extra_dataset, output, limit=None):
    output = training.safe_output(output, dataset); training.safe_output(output, extra_dataset)
    folder = output/'opportunity-labels'; folder.mkdir(parents=True, exist_ok=True)
    reference = freeze('lavis-v3-ranking'); predictor = FrozenPredictor(reference)
    protocol = dict(schema=LABEL_SCHEMA, seed=42, states=4, actions=12, candidate_strategy='expanded',
        trajectory='v3-configured-greedy', feature_version=FEATURE_VERSION,
        split_sha256=training.split_sha(extra_dataset), inference_code_sha256_lf=inference_code_sha(),
        script_sha256=digest(Path(__file__).read_bytes()), reference_weight_sha256=reference['model_sha256'])
    target = folder/'protocol.json'
    if target.exists():
        if json.loads(target.read_text()) != protocol:
            raise ValueError('LABEL_PROTOCOL_CHANGED_USE_NEW_OUTPUT')
    else:
        training.write_new(target, protocol)
    rows = training.splits(extra_dataset)['train_development']
    if limit: rows = rows[:limit]
    for row in rows:
        dest = folder/(row['artifact_id']+'.json')
        if dest.exists():
            continue
        started = time.perf_counter()
        _, problem, constraints, provenance = training.load_source(dataset, row, extra_dataset)
        trace = LavisScheduler(predictor).solve(problem, constraints, training.context(15))
        pool, stats = build_pool(problem, constraints, Control(), strategy='expanded')
        indices = sorted({round(f*len(trace.assignments)) for f in (0., .33, .67, .9)})
        labels = []
        for index in indices:
            labels.extend(label_state(problem, constraints, pool, Schedule(trace.assignments[:index]),
                predictor, row, str(index)))
        report = dict(source=row, protocol_sha256=digest(training.encode(protocol)),
            scenario_physics_version=provenance['scenario_physics_version'], labels=labels,
            pool=stats, seconds=time.perf_counter()-started)
        partial = dest.with_suffix('.partial')
        try:
            training.write_new(partial, report); partial.rename(dest)
        finally:
            partial.unlink(missing_ok=True)
        print(json.dumps(dict(stage='labels', source=row['artifact_id'], labels=len(labels),
            seconds=round(report['seconds'],3))), flush=True)
    return folder


def read_labels(output, extra_dataset):
    folder = output/'opportunity-labels'; protocol = json.loads((folder/'protocol.json').read_text())
    if (protocol['schema'] != LABEL_SCHEMA or protocol['split_sha256'] != training.split_sha(extra_dataset)
        or protocol['inference_code_sha256_lf'] != inference_code_sha()
        or protocol['script_sha256'] != digest(Path(__file__).read_bytes())):
        raise ValueError('STALE_LABEL_PROTOCOL')
    records = []; sources = []; versions = set()
    for source in training.splits(extra_dataset)['train_development']:
        path = folder/(source['artifact_id']+'.json'); raw=path.read_bytes(); report=json.loads(raw)
        if report['source'] != source or report['protocol_sha256'] != digest(training.encode(protocol)):
            raise ValueError('LABEL_SOURCE_MISMATCH')
        for r in report['labels']:
            if any(r[k] != v for k,v in source.items()) or r['label_schema'] != LABEL_SCHEMA:
                raise ValueError('LABEL_ROW_MISMATCH')
        records.extend(report['labels']); sources.append(dict(source=source, sha256=digest(raw)))
        versions.add(report['scenario_physics_version'])
    if len(versions) != 1:
        raise ValueError('MIXED_PHYSICS')
    groups = defaultdict(list)
    for r in records: groups[r['lineage_group_id'],r['state_hash']].append(r)
    informative = [r for group in groups.values() if max(r['y'] for r in group)-min(r['y'] for r in group)>1e-12 for r in group]
    if not informative: raise ValueError('NO_INFORMATIVE_LABELS')
    return informative, sources, protocol, next(iter(versions)), len(records)


def evaluate(dataset, extra_dataset, predictor, budget=10, search='greedy'):
    rows = []
    for source in training.splits(extra_dataset)['validation']:
        _, p, cm, _ = training.load_source(dataset, source, extra_dataset)
        context = replace(training.context(budget), params=LavisParams(search_mode=search, candidate_strategy='expanded'))
        start = time.perf_counter(); plan = LavisScheduler(predictor).solve(p, cm, context)
        training.validate_schedule(p, cm, plan)
        rows.append(dict(source, completed=len(plan.assignments), total=len(p.tasks), RT=time.perf_counter()-start))
    cohorts = {}
    for origin in ('eos-course-v1','lavis-conflict-v1'):
        subset = [r for r in rows if r.get('data_origin','eos-course-v1')==origin]
        groups=defaultdict(list)
        for r in subset: groups[r['lineage_group_id']].append(r['completed']/r['total'])
        cohorts[origin] = dict(completed=sum(r['completed'] for r in subset),
            total=sum(r['total'] for r in subset), family_macro_TCR=sum(sum(v)/len(v) for v in groups.values())/len(groups))
    return dict(cohorts=cohorts, rows=rows, budget_s=budget, search_mode=search,
        candidate_strategy='expanded', scope='shared model replay, not independent Orekit audit')


def train(dataset, extra_dataset, output, model_id):
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor, ExtraTreesRegressor
    from threadpoolctl import threadpool_limits
    import re
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',model_id):
        raise ValueError('INVALID_MODEL_ID')
    target=model_root()/model_id
    if target.exists() or (output/'training-report.json').exists():
        raise ValueError('USE_NEW_MODEL_ID_AND_OUTPUT')
    rows,sources,protocol,physics,total=read_labels(output,extra_dataset)
    X,y,w,rows=training.weighted_arrays(rows)
    reference=freeze('lavis-v3-ranking'); start=time.perf_counter()
    baseline=evaluate(dataset,extra_dataset,FrozenPredictor(reference))
    print(json.dumps(dict(stage='reference',cohorts=baseline['cohorts'])),flush=True)
    models=[('hgb15',HistGradientBoostingRegressor(max_iter=180,max_leaf_nodes=15,learning_rate=.05,min_samples_leaf=5,l2_regularization=1.,early_stopping=False,random_state=42)),
            ('hgb31',HistGradientBoostingRegressor(max_iter=180,max_leaf_nodes=31,learning_rate=.05,min_samples_leaf=5,l2_regularization=1.,early_stopping=False,random_state=42)),
            ('extra96',ExtraTreesRegressor(n_estimators=96,min_samples_leaf=3,max_features=1.,random_state=42,n_jobs=1))]
    trials=[]; best=None
    with threadpool_limits(limits=1):
        for name,model in models:
            model.fit(X,y,sample_weight=w)
            result=evaluate(dataset,extra_dataset,training.Predictor(model))
            old=result['cohorts']['eos-course-v1']; hard=result['cohorts']['lavis-conflict-v1']
            ref_old=baseline['cohorts']['eos-course-v1']; ref_hard=baseline['cohorts']['lavis-conflict-v1']
            eligible=(old['completed']>=ref_old['completed'] and hard['completed']>=ref_hard['completed']
                and hard['family_macro_TCR']>ref_hard['family_macro_TCR']+1e-12)
            trials.append(dict(name=name,params=model.get_params(),validation=result,eligible=eligible))
            rank=(hard['family_macro_TCR'],hard['completed'],old['completed'])
            if eligible and (best is None or rank>best[0]): best=(rank,name,model,result)
            print(json.dumps(dict(stage='trial',name=name,eligible=eligible,cohorts=result['cohorts'])),flush=True)
    report=dict(status='REJECTED_KEEP_V3' if best is None else 'CANDIDATE_PENDING_SEARCH_AUDIT',
        reference=reference,reference_validation=baseline,trials=trials,label_protocol=protocol,
        label_sources=sources,total_labels=total,informative_rows=len(rows),
        effective_families=len({r['lineage_group_id'] for r in rows}),seconds=time.perf_counter()-start,
        final_test_used=False,selection_scope='development validation, not final test')
    if best:
        _,name,model,result=best; buffer=io.BytesIO();joblib.dump(model,buffer,compress=3);data=buffer.getvalue()
        manifest=dict(model_id=model_id,model_version='0.4.0',format='team-joblib-v1',
            model_sha256=digest(data),feature_version=FEATURE_VERSION,features=list(FEATURE_NAMES),
            candidate_version=CANDIDATE_VERSION,label_version=LABEL_SCHEMA,pool_config=POOL_CONFIG,
            domain=DOMAIN,dependencies=dependencies(),inference_code_sha256_lf=inference_code_sha(),
            training_candidate_strategy='expanded',training_protocol=LABEL_SCHEMA,
            training_script_sha256=digest(Path(__file__).read_bytes()),split_sha256=training.split_sha(extra_dataset),
            training_sources_sha256=digest(training.encode(training.splits(extra_dataset)['train_development'])),
            validation_sources_sha256=digest(training.encode(training.splits(extra_dataset)['validation'])),
            training_label_sources_sha256=digest(training.encode(sources)),label_protocol=protocol,
            training_params=model.get_params(),training_rows=len(rows),training_seed=42,
            scenario_physics_version=physics,selected_training=name,quality_status='pending_independent_audit')
        report['model']=manifest;report['validation']=result
        target.mkdir(parents=True)
        try:
            (target/'model.joblib').write_bytes(data)
            training.write_new(target/'training_report.json',report)
            training.write_new(target/'manifest.json',manifest)
        except BaseException:
            for filename in ('model.joblib','training_report.json','manifest.json'):
                (target/filename).unlink(missing_ok=True)
            target.rmdir();raise
    training.write_new(output/'training-report.json',report)
    print(json.dumps(dict(stage='finished',status=report['status'],model_id=model_id if best else None)),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['collect','train'])
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--extra-dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-id',default='lavis-v4-opportunity')
    parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    args.output=training.safe_output(args.output,args.dataset);training.safe_output(args.output,args.extra_dataset)
    if args.limit is not None and args.limit<1:parser.error('limit必须为正整数')
    if args.stage=='collect':collect(args.dataset,args.extra_dataset,args.output,args.limit)
    else:
        if args.limit:parser.error('train不支持训练子集')
        train(args.dataset,args.extra_dataset,args.output,args.model_id)

if __name__=='__main__':main()
