"""可复现离线流水线：只读公开训练/验证白名单，支持独立高冲突扩充，不访问私有测试场景。"""
from __future__ import annotations
import hashlib
import json
import time
from collections import Counter,defaultdict
from pathlib import Path

from algorithms.objectives import ObjectiveWeights
from algorithms.solver_contracts import SolveContext
from schedulers.constraint_model import ConstraintModel,Schedule
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.source_windows import SourceWindowIndex
from .protocol import *
from .candidates import build_pool,key
from .labels import collect
from .model import digest,inference_code_sha,dependencies,FrozenPredictor,freeze,model_root
from .solver import LavisScheduler

REPO=Path(__file__).resolve().parents[2]

def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2)+'\n').encode()

def write_new(path,value):
    with Path(path).open('xb') as f:f.write(encode(value))

def splits(extra_dataset=None):
    folder=REPO/'experiments/datasets/eos-course-v1/splits'
    result={key:json.loads((folder/(key+'.json')).read_text()) for key in ('train_development','validation')}
    train=result['train_development'];val=result['validation']
    if len(train)!=60 or len(val)!=20:raise ValueError('LAVIS_SPLIT_SIZE')
    for field in ('artifact_id','lineage_group_id','scenario_sha256'):
        a=[r[field] for r in train];b=[r[field] for r in val]
        if len(set(a))!=len(a) or len(set(b))!=len(b) or set(a)&set(b):raise ValueError('LAVIS_SPLIT_LEAKAGE:'+field)
    if extra_dataset:
        extra=Path(extra_dataset).resolve()
        isolation=json.loads((extra/'isolation_report.json').read_text())
        spec=json.loads((extra/'dataset_spec.json').read_text())
        if (spec.get('dataset_id')!='lavis-conflict-v1' or not isolation.get('all_family_siblings_same_split')
            or not isolation.get('protected_groups_disjoint') or isolation.get('final_test_content_used') is not False):
            raise ValueError('LAVIS_EXTRA_SOURCE_ISOLATION_REQUIRED')
        groups={};orbits={};original_groups={r['lineage_group_id'] for rows in result.values() for r in rows}
        expected={c['lineage_group_id']:c['split'] for c in spec['families']}
        for cohort in ('train_development','validation'):
            additions=json.loads((extra/'splits'/(cohort+'.json')).read_text())
            for row in additions:
                group=row['lineage_group_id'];orbit=row['orbital_family_sha256']
                if (row.get('data_origin')!='lavis-conflict-v1' or group in original_groups
                    or expected.get(group)!=cohort or groups.get(group,cohort)!=cohort
                    or orbits.get(orbit,cohort)!=cohort):raise ValueError('LAVIS_EXTRA_FAMILY_LEAKAGE')
                groups[group]=cohort;orbits[orbit]=cohort
            result[cohort]+=additions
        for field in ('artifact_id','scenario_sha256'):
            a=[r[field] for r in result['train_development']];b=[r[field] for r in result['validation']]
            if len(set(a))!=len(a) or len(set(b))!=len(b) or set(a)&set(b):raise ValueError('LAVIS_EXTRA_DUPLICATE_SOURCE')
    return result

def split_sha(extra_dataset=None):return digest(encode(splits(extra_dataset)))

def load_source(dataset,row,extra_dataset=None):
    from eos_system.provenance import capture_provenance
    origin=row.get('data_origin','eos-course-v1')
    if origin not in ('eos-course-v1','lavis-conflict-v1'):raise ValueError('LAVIS_UNKNOWN_DATA_ORIGIN')
    if origin=='lavis-conflict-v1' and extra_dataset is None:raise ValueError('LAVIS_EXTRA_ROOT_REQUIRED')
    data_root=extra_dataset if origin=='lavis-conflict-v1' else dataset
    path=Path(data_root).resolve()/'development'/'scenarios'/(row['artifact_id']+'.json')
    if path.is_symlink() or not path.is_file():raise ValueError('LAVIS_SOURCE_PATH')
    raw=path.read_bytes()
    if digest(raw)!=row['scenario_sha256']:raise ValueError('LAVIS_SCENARIO_SHA_CHANGED')
    evidence=capture_provenance(path,row['scenario_sha256'])
    if evidence.get('lineage_group_id')!=row['lineage_group_id']:raise ValueError('LAVIS_LINEAGE_MISMATCH')
    problem=load_scheduling_problem_from_json(path);problem.execution_mode='physical_validation'
    if problem.ground_stations:raise ValueError('LAVIS_V1_TRAINING_DOMAIN_NO_GROUND_STATIONS')
    constraints=ConstraintModel(problem,placement_mode='earliest',unassigned_penalty=1000.,
        downlink_duration_ratio=1.,agility_profile='Standard-Agility',non_agile_transition_s=10.)
    return path,problem,constraints,evidence

def safe_output(output,dataset):
    output=Path(output).resolve();dataset=Path(dataset).resolve()
    if output.is_relative_to(REPO) or output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise ValueError('LAVIS_OUTPUT_MUST_BE_OUTSIDE_REPO_AND_INPUT')
    return output

def build_dataset(dataset,output,limit=None,states=10,seed=42,policy=None,tag='base',extra_dataset=None):
    output=safe_output(output,dataset);output.mkdir(parents=True,exist_ok=True)
    folder=output/('labels-'+tag);folder.mkdir(exist_ok=True)
    if extra_dataset:safe_output(output,extra_dataset)
    rows=splits(extra_dataset)['train_development'];rows=rows[:limit] if limit else rows
    config={'seed':seed,'states':states,'tag':tag,'feature_version':FEATURE_VERSION,
            'candidate_version':CANDIDATE_VERSION,'label_version':LABEL_VERSION,'pool_config':POOL_CONFIG,
            'domain':DOMAIN,'split_sha256':split_sha(extra_dataset),'sampler':'conflict-v2' if extra_dataset else 'legacy','inference_code_sha256_lf':inference_code_sha(),
            'label_code_sha256':digest((REPO/'algorithms/lavis/labels.py').read_bytes()),
            'policy_sha256':getattr(policy,'snapshot_sha256',None)}
    cfg=folder/'protocol.json'
    if cfg.exists():
        if json.loads(cfg.read_text())!=config:raise ValueError('LAVIS_LABEL_PROTOCOL_CHANGED_USE_NEW_OUTPUT')
    else:write_new(cfg,config)
    for row in rows:
        path=folder/(row['artifact_id']+'.json')
        if path.exists():continue
        started=time.perf_counter();_,problem,constraints,evidence=load_source(dataset,row,extra_dataset)
        pool,stats=build_pool(problem,constraints,Control())
        source=dict(row,scenario_physics_version=evidence['scenario_physics_version'],
                    feature_version=FEATURE_VERSION,candidate_version=CANDIDATE_VERSION,constraint_domain=DOMAIN)
        labels=collect(problem,constraints,pool,source,seed,states,policy=policy,sampler='conflict-v2' if extra_dataset else 'legacy')
        report={'source':row,'protocol_sha256':digest(encode(config)),'pool':stats,
                'seconds':time.perf_counter()-started,'labels':labels}
        # 单来源文件完整写入后才登记；失败的.partial只清理本工具创建的文件。
        partial=path.with_suffix('.partial')
        try:
            write_new(partial,report);partial.rename(path)
        finally:partial.unlink(missing_ok=True)
        size=sum(p.stat().st_size for p in folder.glob('*.json'))
        if size>1024**3:raise ValueError('LAVIS_LABEL_STORAGE_LIMIT')
        print(json.dumps({'stage':tag,'source':row['artifact_id'],'labels':len(labels),'seconds':round(report['seconds'],3),'pool':len(pool)},ensure_ascii=False),flush=True)
    return folder

def training_rows(output,tag='base',extra_dataset=None):
    folder=Path(output)/('labels-'+tag);config=json.loads((folder/'protocol.json').read_text());records=[];sources=[]
    if config['split_sha256']!=split_sha(extra_dataset) or config['inference_code_sha256_lf']!=inference_code_sha():raise ValueError('LAVIS_STALE_LABEL_PROTOCOL')
    for row in splits(extra_dataset)['train_development']:
        report=json.loads((folder/(row['artifact_id']+'.json')).read_text())
        if report['source']!=row or report['protocol_sha256']!=digest(encode(config)):raise ValueError('LAVIS_LABEL_SOURCE_MISMATCH')
        for item in report['labels']:
            if any(item[k]!=row[k] for k in row) or item['label_status']!='complete':raise ValueError('LAVIS_LABEL_LEDGER_MISMATCH')
        records.extend(report['labels']);sources.append({'source':row,'sha256':digest(encode(report)),'seconds':report['seconds']})
    return records,sources,config

def weighted_arrays(rows,static=False):
    import numpy as np
    # 同来源/同状态完全重复样本只保留一条；来源与状态各自等权。
    unique={(r['lineage_group_id'],r['state_hash'],tuple(r['candidate'])):r for r in rows}
    rows=list(unique.values());groups=defaultdict(set);counts=Counter()
    for r in rows:
        g=r['lineage_group_id'];s=r['state_hash'];groups[g].add(s);counts[g,s]+=1
    weights=[1/(len(groups[r['lineage_group_id']])*counts[r['lineage_group_id'],r['state_hash']]) for r in rows]
    X=np.asarray([r['features'] for r in rows],dtype=float);y=np.asarray([r['y'] for r in rows],dtype=float)
    if not len(rows) or not np.isfinite(X).all() or not np.isfinite(y).all():raise ValueError('LAVIS_INVALID_TRAINING_ROWS')
    if static:X=static_features(X)
    weights=np.asarray(weights);weights*=len(rows)/weights.sum()
    return X,y,weights,rows

def static_features(X):
    import numpy as np
    out=np.array(X,dtype=float,copy=True);dynamic=set(range(24))-{0,1,2,5,6,7,8,9,21,22}
    out[:,sorted(dynamic)]=0.;return out

class Predictor:
    def __init__(self,model,static=False):self.model=model;self.static=static
    def predict(self,X):return self.model.predict(static_features(X) if self.static else X)

class RulePredictor:
    def __init__(self,mode,seed=42):self.mode=mode;self.seed=seed
    def predict(self,X):
        # 所有消融共用同一构造器。随机分数为固定流，显式标记消融，不注册为ML。
        import numpy as np
        if self.mode=='constant':return np.zeros(len(X))
        if self.mode=='scarcity':return [-row[2]*row[3] for row in X]
        if not hasattr(self,'rng'):self.rng=np.random.default_rng(self.seed)
        return self.rng.random(len(X))

def context(budget=15):return SolveContext(42,budget,ObjectiveWeights(0,1,0,0),LavisParams())

def validate_schedule(problem,constraints,plan):
    checked=Schedule()
    for a in sorted(plan.assignments,key=lambda a:(a.sat_start_time,key(a))):
        if not constraints.is_feasible_assignment(a,checked):raise ValueError('LAVIS_VALIDATION_PLAN_REJECTED')
        checked.assignments.append(a)

def evaluate(dataset,predictor,budget=15,extra_dataset=None):
    results=[]
    for row in splits(extra_dataset)['validation']:
        _,problem,constraints,_=load_source(dataset,row,extra_dataset);started=time.perf_counter()
        plan=LavisScheduler(predictor).solve(problem,constraints,context(budget))
        seconds=time.perf_counter()-started;validate_schedule(problem,constraints,plan)
        results.append(dict(row,completed=len(plan.assignments),total=len(problem.tasks),RT=seconds,
                            trace=plan.metadata['lavis']['trace'],pool=plan.metadata['lavis']['pool']))
    cohorts={}
    for origin in sorted({r.get('data_origin','eos-course-v1') for r in results}):
        subset=[r for r in results if r.get('data_origin','eos-course-v1')==origin];families=defaultdict(list)
        for r in subset:families[r['lineage_group_id']].append(r['completed']/r['total'])
        cohorts[origin]={'completed':sum(r['completed'] for r in subset),'total':sum(r['total'] for r in subset),
            'sources':len(subset),'families':len(families),
            'family_macro_TCR':sum(sum(v)/len(v) for v in families.values())/len(families)}
    return {'cohorts':cohorts,'completed':sum(r['completed'] for r in results),'total':sum(r['total'] for r in results),
            'macro_TCR':sum(r['completed']/r['total'] for r in results)/len(results),
            'mean_RT':sum(r['RT'] for r in results)/len(results),'rows':results,
            'scope':'shared_source_geometry_slew_resource_checks; not independent Orekit certification'}


def validation_rank(result,params,reference=None):
    """旧分布不退步优先，再比较按新家族等权的高冲突验证成绩。"""
    if reference:
        old=result['cohorts']['eos-course-v1']['completed'];threshold=reference['cohorts']['eos-course-v1']['completed']
        return (max(0,threshold-old),-result['cohorts']['lavis-conflict-v1']['family_macro_TCR'],-old,json.dumps(params,sort_keys=True))
    return (-result['completed'],json.dumps(params,sort_keys=True))


def train(dataset,output,model_id='lavis-v1',budget=15,augment=True,extra_dataset=None):
    import io,joblib,numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits
    output=Path(output);target=model_root()/model_id
    if target.exists():raise ValueError('LAVIS_MODEL_ID_ALREADY_EXISTS_USE_NEW_ID')
    rows,sources,protocol=training_rows(output,extra_dataset=extra_dataset)
    X,y,w,dedup=weighted_arrays(rows)
    states=defaultdict(list)
    for r in dedup:states[r['lineage_group_id'],r['state_hash']].append(r['y'])
    informative=sum(max(values)-min(values)>1e-12 for values in states.values())
    if informative==0:raise ValueError('LAVIS_NO_DISTINGUISHING_LABELS')
    base_arrays=(X,y,w,dedup); base_sources=list(sources)
    started=time.perf_counter(); trials=[];best=None
    reference=evaluate(dataset,FrozenPredictor(freeze('lavis-v1')),budget,extra_dataset) if extra_dataset else None
    def rank_result(result,params):return validation_rank(result,params,reference)
    with threadpool_limits(limits=1):
        for leaves in ((15,31) if extra_dataset else (7,15)):
            for rate in (.05,.1):
                for leaf in ((5,15) if extra_dataset else (10,20)):
                    params=dict(max_iter=180 if extra_dataset else 100,max_leaf_nodes=leaves,learning_rate=rate,min_samples_leaf=leaf,
                                l2_regularization=1.,early_stopping=False,random_state=42)
                    model=HistGradientBoostingRegressor(**params).fit(X,y,sample_weight=w)
                    result=evaluate(dataset,Predictor(model),budget,extra_dataset)
                    trial={'params':params,'validation':result};trials.append(trial)
                    rank=rank_result(result,params)
                    if best is None or rank<best[0]:best=(rank,model,params,result)
                    print(json.dumps({'stage':'train','trial':len(trials),'completed':result['completed'],'macro_TCR':result['macro_TCR']},ensure_ascii=False),flush=True)
        _,model,params,initial=best
        # 新版不能因所有候选都退步而自动发布“最少退步”的模型；旧权重继续可用。
        if reference and initial['cohorts']['eos-course-v1']['completed'] < reference['cohorts']['eos-course-v1']['completed']:
            rejection=output/'rejected-validation-trials.json'
            write_new(rejection,{'reason':'ORIGINAL_VALIDATION_REGRESSION','reference':reference,'trials':trials,'final_test_used':False})
            raise ValueError('LAVIS_ORIGINAL_VALIDATION_REGRESSION_KEEP_PREVIOUS_MODEL')
        base_model_validation=initial
        # 仅在训练白名单补一次当前模型轨迹；验证结果不能进入特征或标签。
        if augment:
            policy=Predictor(model);buf=io.BytesIO();joblib.dump(model,buf);policy.snapshot_sha256=digest(buf.getvalue())
            build_dataset(dataset,output,states=10,policy=policy,tag='on-policy',extra_dataset=extra_dataset)
            extra,extra_sources,_=training_rows(output,'on-policy',extra_dataset=extra_dataset);rows+=extra
            X,y,w,dedup=weighted_arrays(rows);sources+=extra_sources
            retrained=HistGradientBoostingRegressor(**params).fit(X,y,sample_weight=w)
            result=evaluate(dataset,Predictor(retrained),budget,extra_dataset)
            # 验证不改善时保留原模型，同时如实记录补采样结果。
            adaptation={'validation':result,'accepted':rank_result(result,params)<rank_result(initial,params)}
            if adaptation['accepted']:model=retrained;initial=result
            else:
                X,y,w,dedup=base_arrays; sources=base_sources
        else:adaptation={'skipped':True}
        ablations={}
        for mode in ('scarcity','constant','random'):
            ablations[mode]=evaluate(dataset,RulePredictor(mode),budget,extra_dataset)
        static=HistGradientBoostingRegressor(**params).fit(static_features(X),y,sample_weight=w)
        ablations['static_features']=evaluate(dataset,Predictor(static,True),budget,extra_dataset)
        data_only_comparison=None
        if extra_dataset:
            # 同参数、同新采样器，仅去掉高冲突来源，避免把调参或采样改动的收益都归给数据。
            original_rows=[r for r in base_arrays[3] if r.get('data_origin','eos-course-v1')=='eos-course-v1']
            X0,y0,w0,_=weighted_arrays(original_rows)
            without_extra=HistGradientBoostingRegressor(**params).fit(X0,y0,sample_weight=w0)
            data_only_comparison={'same_hyperparameters':params,'same_sampler':'conflict-v2',
                'with_conflict_base_validation':base_model_validation,
                'without_conflict_validation':evaluate(dataset,Predictor(without_extra),budget,extra_dataset)}
        # 最佳配置的另外两个学习种子，报告稳定性，不把重复训练当新场景。
        seeds=[]
        for seed in (43,44):
            alt=HistGradientBoostingRegressor(**(params|{'random_state':seed})).fit(X,y,sample_weight=w)
            result=evaluate(dataset,Predictor(alt),budget,extra_dataset);seeds.append({'seed':seed,'validation':result})
    # 清单只绑定最终权重真正使用的标签，拒绝把未采用的补采样算进训练行数。
    physics_versions={r['scenario_physics_version'] for r in dedup}
    if len(physics_versions)!=1:raise ValueError('LAVIS_MIXED_PHYSICS_TRAINING_DOMAIN')
    with threadpool_limits(limits=1): predictions=model.predict(X)
    grouped=defaultdict(list)
    for index,r in enumerate(dedup):grouped[r['lineage_group_id'],r['state_hash']].append(index)
    regrets=[];hits=[]
    for indices in grouped.values():
        winner=max(indices,key=lambda i:float(predictions[i]));top=max(float(y[i]) for i in indices)
        regrets.append(top-float(y[winner]));hits.append(float(abs(top-float(y[winner]))<1e-12))
    diagnostics={'scope':'training_labels_only; not out-of-source performance',
                 'weighted_MAE':float(np.average(np.abs(predictions-y),weights=w)),
                 'mean_state_regret':sum(regrets)/len(regrets),'best_set_hit_rate':sum(hits)/len(hits)}
    buffer=io.BytesIO();joblib.dump(model,buffer,compress=3);data=buffer.getvalue()
    manifest=dict(model_id=model_id,model_version='0.2.0' if extra_dataset else '0.1.0',format='team-joblib-v1',model_sha256=digest(data),
        feature_version=FEATURE_VERSION,features=list(FEATURE_NAMES),candidate_version=CANDIDATE_VERSION,
        label_version=LABEL_VERSION,pool_config=POOL_CONFIG,domain=DOMAIN,dependencies=dependencies(),
        split_sha256=split_sha(extra_dataset),training_sources_sha256=digest(encode(splits(extra_dataset)['train_development'])),
        validation_sources_sha256=digest(encode(splits(extra_dataset)['validation'])),
        inference_code_sha256_lf=inference_code_sha(),training_code_sha256=digest(Path(__file__).read_bytes()),
        label_protocol=protocol,training_params=params,training_rows=len(dedup),
        scenario_physics_version=next(iter(physics_versions)),training_label_sources_sha256=digest(encode(sources)),
        selected_training='on-policy' if adaptation.get('accepted') else 'base',training_seed=42,
        extra_dataset_identity=({'dataset_id':'lavis-conflict-v1',
            'spec_sha256':digest((Path(extra_dataset)/'dataset_spec.json').read_bytes()),
            'isolation_report_sha256':digest((Path(extra_dataset)/'isolation_report.json').read_bytes()),
            'train_scenes':len(splits(extra_dataset)['train_development']),
            'train_families':len({r['lineage_group_id'] for r in splits(extra_dataset)['train_development']})}
            if extra_dataset else None))
    report=dict(model=manifest,reference_model_validation=reference,training_seconds=time.perf_counter()-started,sources=sources,
                label_rows=len(rows),unique_rows=len(dedup),states=len(states),informative_states=informative,
                initial_validation_trials=trials,adaptation=adaptation,validation=initial,ablations=ablations,
                seed_repeats=seeds,data_only_comparison=data_only_comparison,training_label_diagnostics=diagnostics,final_test_used=False)
    # 冻结ID不可覆盖，权重仅存运行目录。最后写manifest作为完整登记标志。
    target.mkdir(parents=True)
    try:
        (target/'model.joblib').write_bytes(data);write_new(target/'training_report.json',report)
        write_new(target/'manifest.json',manifest)
    except BaseException:
        # 只清理本次新建目录中的三个已知文件，不递归删除用户目录。
        for name in ('model.joblib','training_report.json','manifest.json'):(target/name).unlink(missing_ok=True)
        target.rmdir();raise
    print(json.dumps({'stage':'registered','model_id':model_id,'model_sha256':manifest['model_sha256'],
                      'validation_completed':initial['completed'],'macro_TCR':initial['macro_TCR'],
                      'report':str(target/'training_report.json')},ensure_ascii=False),flush=True)
    return report
