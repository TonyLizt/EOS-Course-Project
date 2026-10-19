"""离线反事实续排标签；推理模块不导入本模块，不在线运行教师。"""
from collections import Counter,defaultdict
import hashlib
from schedulers.constraint_model import Schedule
from .candidates import feasible,key,round_robin
from .features import extract
from .protocol import Control,BudgetExpired,LABEL_VERSION

def random_key(seed,state,identity):
    return hashlib.sha256(repr((seed,state,identity)).encode()).hexdigest()

def choose(current,mode,seed,state):
    if mode=='scarcity':
        counts=Counter(a.task_id for a in current)
        return min(current,key=lambda a:(counts[a.task_id],key(a)))
    if mode=='constant':return min(current,key=key)
    return min(current,key=lambda a:random_key(seed,state,key(a)))

def rollout(pool,plan,constraints,mode,seed,state,limit=10000):
    result=Schedule(list(plan.assignments));control=Control(check_limit=limit)
    try:
        while True:
            current=feasible(pool,result,constraints,control)
            if not current:break
            result.assignments.append(choose(current,mode,seed,state))
    except BudgetExpired:pass
    return len(result.assignments),control.checks

def sample_options(current,limit):
    # 先覆盖不同任务，任务内按星轮转；不把未打标签候选当负例。
    tasks=defaultdict(lambda:defaultdict(list))
    for a in current:tasks[a.task_id][a.satellite_id].append(a)
    groups=[list(round_robin([tasks[tid][sid] for sid in sorted(tasks[tid])])) for tid in sorted(tasks)]
    result=[]
    for a in round_robin(groups):
        result.append(a)
        if len(result)>=limit:break
    return result

def conflict_options(current,matrix,limit,seed,state):
    """先采同任务不同卫星的高/低压力对，再补稀缺任务和稳定随机覆盖。"""
    positions={key(a):i for i,a in enumerate(current)};tasks=defaultdict(list)
    for a in current:tasks[a.task_id].append(a)
    pressure=lambda a:matrix[positions[key(a)]][15]+matrix[positions[key(a)]][16]
    order=sorted(tasks,key=lambda tid:(-(max(map(pressure,tasks[tid]))-min(map(pressure,tasks[tid]))),random_key(seed,state,tid)))
    selected=[];seen=set()
    def push(a):
        if key(a) not in seen and len(selected)<limit:seen.add(key(a));selected.append(a)
    for tid in order[:2]:
        ranked=sorted(tasks[tid],key=lambda a:(pressure(a),key(a)))
        push(ranked[0]);push(ranked[-1])
    for a in sorted(current,key=lambda a:(len(tasks[a.task_id]),-pressure(a),random_key(seed,state,key(a)))):
        push(a)
        if len(selected)>=limit:break
    return selected

def label_state(problem,constraints,pool,plan,current,source,seed,state,limit=8,sampler='legacy'):
    control=Control();matrix=extract(problem,plan,pool,current,control)
    positions={key(a):i for i,a in enumerate(current)}
    options=conflict_options(current,matrix,limit,seed,state) if sampler=='conflict-v2' else sample_options(current,limit)
    state_keys=[key(a) for a in plan.assignments]
    state_identity=(source['scenario_sha256'],sorted(state_keys)) if sampler=='conflict-v2' else state_keys
    state_hash=hashlib.sha256(repr(state_identity).encode()).hexdigest()
    for a in options:
        fixed=Schedule(plan.assignments+[a])
        n1,c1=rollout(pool,fixed,constraints,'scarcity',seed,state)
        n2,c2=rollout(pool,fixed,constraints,'random',seed,state)
        n0=len(plan.assignments);remaining=len(problem.tasks)-n0
        yield dict(source,state_id=state,state_hash=state_hash,parent_trace_id=state.split(':')[0],
                   fixed_assignments=state_keys,candidate=key(a),features=matrix[positions[key(a)]],
                   n0=n0,r=remaining,n1=n1,n2=n2,y=((n1+n2)/2-n0)/remaining,
                   rollout_seed=seed,checks=[c1,c2],check_limit=10000,label_status='complete',
                   sampling_rule='conflict-paired-diversity-v2' if sampler=='conflict-v2' else 'task-satellite-round-robin-first-8-v1',label_version=LABEL_VERSION)

def collect(problem,constraints,pool,source,seed=42,states=10,policy=None,sampler='legacy'):
    if sampler=='conflict-v2':return collect_reachable(problem,constraints,pool,source,seed,states,policy)

    rows=[];seen=set();target=max(1,states//2)
    checkpoints={round(i*max(1,len(problem.tasks)-2)/max(1,target-1)) for i in range(target)}
    for mode in (('model',) if policy else ('scarcity','random')):
        plan=Schedule();index=0
        while True:
            current=feasible(pool,plan,constraints,Control())
            if not current:break
            signature=tuple(key(a) for a in plan.assignments)
            state=f'{mode}:{index}'
            if index in checkpoints and len(problem.tasks)-len(plan.assignments)>1 and signature not in seen:
                seen.add(signature);rows.extend(label_state(problem,constraints,pool,plan,current,source,seed,state))
            if mode=='model':
                scores=policy.predict(extract(problem,plan,pool,current,Control()))
                a=current[min(range(len(current)),key=lambda i:(-float(scores[i]),key(current[i])))]
            else:a=choose(current,mode,seed,state)
            plan.assignments.append(a);index+=1
    return rows


def collect_reachable(problem,constraints,pool,source,seed,states,policy):
    """先得到可达构造轨迹，再均匀取中间状态，避免高冲突实例只能采到空计划。"""
    rows=[];seen=set();modes=('model',) if policy else ('scarcity','random')
    per_trace=max(1,states//len(modes))
    for mode in modes:
        plan=Schedule();trajectory=[]
        while True:
            current=feasible(pool,plan,constraints,Control())
            if not current:break
            trajectory.append(list(plan.assignments))
            if mode=='model':
                scores=policy.predict(extract(problem,plan,pool,current,Control()))
                a=current[min(range(len(current)),key=lambda i:(-float(scores[i]),key(current[i])))]
            else:a=choose(current,mode,seed,f'{source["artifact_id"]}:{len(plan.assignments)}')
            plan.assignments.append(a)
        checkpoints=sorted({round(i*max(0,len(trajectory)-1)/max(1,per_trace-1)) for i in range(per_trace)})
        for index in checkpoints:
            if index>=len(trajectory):continue
            plan=Schedule(trajectory[index]);identity=tuple(sorted(key(a) for a in plan.assignments))
            if identity in seen or len(problem.tasks)-len(plan.assignments)<=1:continue
            seen.add(identity);current=feasible(pool,plan,constraints,Control())
            rows.extend(label_state(problem,constraints,pool,plan,current,source,seed,
                f'{mode}:{index}',sampler='conflict-v2'))
    return rows
