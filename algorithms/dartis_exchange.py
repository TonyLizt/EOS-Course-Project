"""DARTIS 可选两任务撤销重插；限制候选、检查次数和接受轮数，取消与超时由父求解上下文控制。

参考 2026-10-28 交付快照选择性移植；不引入 Score/v2 协议，不修改物理与指标口径。
"""
from collections import defaultdict
from dataclasses import replace
from algorithms.candidate_pool import enumerate_task_candidates
from algorithms.objectives import ObjectiveModel
from schedulers.constraint_model import Schedule

class _Limit(Exception):pass

def exchange(problem,cm,context,initial,params,checkpoint,budget_exception,key):
    objective=ObjectiveModel(problem,context.objective_weights)
    best=Schedule(list(initial.assignments));stats=dict(checks=0,seeds=0,improvements=0,pool=0,changes=[],stop_reason='completed')
    def quality(s):return (objective.score(s), len(s.assignments))
    def better(a,b):return a > b
    def valid(a,s):
        checkpoint()
        if stats['checks']>=params.exchange_max_checks:raise _Limit()
        stats['checks']+=1;return cm.is_feasible_assignment(a,s)
    def replay(rows):
        s=Schedule()
        for a in sorted(rows,key=key):
            if not valid(a,s):return None
            s.assignments.append(a)
        return s
    try:
        pool=[]
        for tid,t in sorted(problem.tasks.items()):
            for w in sorted(t.windows,key=lambda w:(w.start_time,w.satellite_id,w.window_id))[:8]:
                checkpoint()
                rows=enumerate_task_candidates(problem,replace(t,windows=[w]),max_candidates=4096,random_samples_per_window=0,seed=context.seed)
                starts=sorted({a.sat_start_time for a in rows})
                if not starts:continue
                chosen={starts[round((len(starts)-1)*i/15)] for i in range(16)}
                pool.extend(a for a in sorted(rows,key=key) if a.sat_start_time in chosen)
                if len(pool)>=4096:break
            if len(pool)>=4096:break
        pool=pool[:4096];stats['pool']=len(pool)
        # One neighbourhood per incumbent; at most two accepted rounds. Each
        # seed replays the whole plan and is rechecked before becoming incumbent.
        for _ in range(2):
            origin=best;before=quality(best);seen=set();seeds=[]
            for a in pool:
                if a.task_id in origin.assigned_task_ids:continue
                if not valid(a,Schedule()):continue
                blockers=[b for b in origin.assignments if not valid(a,Schedule([b]))]
                if len(blockers)>2:continue
                signature=(a.task_id,a.satellite_id,a.sat_start_time,tuple(sorted(b.task_id for b in blockers)))
                if signature in seen:continue
                seen.add(signature)
                seeds.append((len(blockers),sum(problem.tasks[b.task_id].priority for b in blockers),key(a),a,blockers))
            for _,__,___,a,blockers in sorted(seeds,key=lambda r:r[:3])[:64]:
                if stats['seeds']>=params.exchange_max_seeds:raise _Limit()
                stats['seeds']+=1;drop={b.task_id for b in blockers}
                base=replay([b for b in origin.assignments if b.task_id not in drop]+[a])
                if base is None:continue
                for order in ('chronological','profit'):
                    plan=Schedule(list(base.assignments))
                    options=sorted(pool,key=lambda b:(b.sat_start_time,key(b)) if order=='chronological' else (-problem.tasks[b.task_id].priority,b.sat_start_time,key(b)))
                    for b in options:
                        if b.task_id not in plan.assigned_task_ids and valid(b,plan):plan.assignments.append(b)
                    if better(quality(plan),quality(best)):
                        checked=replay(plan.assignments)
                        if checked is not None:
                            stats['changes'].append(dict(seed_task=a.task_id,ejected=sorted(drop),order=order,
                                before_count=len(best.assignments),after_count=len(checked.assignments),
                                before_TP=sum(problem.tasks[b.task_id].priority for b in best.assignments),
                                after_TP=sum(problem.tasks[b.task_id].priority for b in checked.assignments)))
                            best=checked;stats['improvements']+=1
            if quality(best)==before:break
    except _Limit:stats['stop_reason']='check_or_seed_limit'
    except budget_exception:stats['stop_reason']='budget'
    return best,stats
