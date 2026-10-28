"""DARTIS 可选聚合资源修复；尝试释放或迁移同轨资源，只保存公共约束完整通过的更优计划。

参考 2026-10-28 交付快照选择性移植；不引入 Score/v2 协议，不修改物理与指标口径。
"""
from dataclasses import replace
from itertools import combinations
from math import fsum
import time
from algorithms.candidate_pool import enumerate_task_candidates
from algorithms.objectives import ObjectiveModel
from schedulers.constraint_model import Schedule

class _Stop(Exception):pass

def explain(problem,cm,candidate,plan):
    group=[a for a in plan.assignments if (a.satellite_id,a.orbit_number)==(candidate.satellite_id,candidate.orbit_number)]
    sat=problem.satellites[candidate.satellite_id]
    used=(fsum(a.data_volume_GB for a in group),fsum(a.power_cost_W for a in group))
    caps=(sat.max_data_storage_GB,sat.max_power_W);cost=(candidate.data_volume_GB,candidate.power_cost_W)
    deficits=tuple(max(0.,used[i]+cost[i]-caps[i]) if caps[i]>0 else 0. for i in (0,1))
    overlaps=[];slew=[]
    for a in plan.get_assignments_for_satellite(candidate.satellite_id):
        if candidate.sat_start_time<a.sat_end_time and a.sat_start_time<candidate.sat_end_time:overlaps.append(a.task_id)
        first,second=sorted([a,candidate],key=lambda a:a.sat_start_time)
        needed=cm._transition_time_s(candidate.satellite_id,first,second);gap=(second.sat_start_time-first.sat_end_time).total_seconds()
        if gap<needed:slew.append(dict(task=a.task_id,available_s=gap,required_s=needed))
    return dict(satellite=candidate.satellite_id,orbit=candidate.orbit_number,contributors=[a.task_id for a in group],
        used_storage_GB=used[0],used_additive_power_W=used[1],capacity_storage_GB=caps[0],capacity_additive_power_W=caps[1],
        demand_storage_GB=cost[0],demand_additive_power_W=cost[1],storage_deficit_GB=deficits[0],additive_power_deficit_W=deficits[1],
        time_overlap=overlaps,slew_blockers=slew,semantics='per-satellite/per-orbit additive W budget, not battery Wh or instantaneous physical power')

def improve(problem,cm,context,initial,params,checkpoint,budget_exception,key,grid_steps):
    begun=time.monotonic();deadline=begun+3.;objective=ObjectiveModel(problem,context.objective_weights);best=Schedule(list(initial.assignments))
    stats=dict(public_checks=0,aggregate_blockages=0,zero_pair_aggregate_blockages=0,release_sets=0,migration_attempts=0,
        accepted=0,migrations=0,replacements=0,windows_skipped=0,stop_reason='completed',changes=[],blockage_examples=[])
    def ck():
        checkpoint()
        if time.monotonic()>=deadline:stats['stop_reason']='repair_time';raise _Stop()
    def valid(a,s):
        ck()
        if stats['public_checks']>=12000:stats['stop_reason']='check_limit';raise _Stop()
        stats['public_checks']+=1;return cm.is_feasible_assignment(a,s)
    def replay(rows):
        s=Schedule()
        for a in sorted(rows,key=key):
            if not valid(a,s):return None
            s.assignments.append(a)
        return s
    def better(a,b):
        return (objective.score(a),len(a.assignments))>(objective.score(b),len(b.assignments))
    pool={}
    try:
        for tid,t in sorted(problem.tasks.items()):
            rows=[]
            for w in sorted(t.windows,key=lambda w:(w.start_time,w.satellite_id,w.window_id))[:8]:
                ck()
                if not 0<grid_steps(problem,t,w)<=1024:stats['windows_skipped']+=1;continue
                options=enumerate_task_candidates(problem,replace(t,windows=[w]),placement_mode=cm.placement_mode,
                    downlink_duration_ratio=cm.downlink_duration_ratio,max_candidates=4096,random_samples_per_window=0,seed=context.seed)
                starts=sorted({a.sat_start_time for a in options})
                if starts:
                    chosen={starts[round((len(starts)-1)*i/5)] for i in range(6)}
                    rows.append([a for a in sorted(options,key=key) if a.sat_start_time in chosen])
            # Interleave source windows; no first-window monopoly.
            opts=[]
            for depth in range(12):
                for group in rows:
                    if depth<len(group) and len(opts)<12 and valid(group[depth],Schedule()):opts.append(group[depth])
            pool[tid]=opts
        for _ in range(4):
            origin=best;accepted=False
            missing=sorted(set(problem.tasks)-set(origin.assigned_task_ids),key=lambda t:(-problem.tasks[t].priority,t))
            for tid in missing:
                for a in pool[tid]:
                    ck();d=explain(problem,cm,a,origin)
                    if d['storage_deficit_GB']<=1e-9 and d['additive_power_deficit_W']<=1e-9:continue
                    stats['aggregate_blockages']+=1
                    pairs=[b for b in origin.assignments if not valid(a,Schedule([b]))]
                    if not pairs:stats['zero_pair_aggregate_blockages']+=1
                    if len(stats['blockage_examples'])<12:stats['blockage_examples'].append(dict(task=tid,diagnosis=d,pair_blockers=[b.task_id for b in pairs]))
                    if len(pairs)>2:continue
                    contributors=[b for b in origin.assignments if b.task_id in d['contributors']]
                    owners=lambda b:len({w.satellite_id for w in problem.tasks[b.task_id].windows})
                    candidates=[]
                    for n in (1,2):
                        for release in combinations(contributors,n):
                            ck();byid={b.task_id:b for b in list(release)+pairs};released=list(byid.values())
                            if len(released)>2:continue
                            sg=fsum(b.data_volume_GB for b in released if b in contributors);pw=fsum(b.power_cost_W for b in released if b in contributors)
                            if sg+1e-9<d['storage_deficit_GB'] or pw+1e-9<d['additive_power_deficit_W']:continue
                            candidates.append((len(released),-sum(owners(b)>1 for b in released),sum(problem.tasks[b.task_id].priority for b in released),tuple(sorted(byid)),released))
                    seen=set()
                    for *_,released in sorted(candidates,key=lambda v:v[:4]):
                        ids=tuple(sorted(b.task_id for b in released))
                        if ids in seen:continue
                        seen.add(ids)
                        if len(seen)>8:break
                        stats['release_sets']+=1
                        seed=replay([b for b in origin.assignments if b.task_id not in ids]+[a])
                        if seed is None:continue
                        moved=[]
                        if params.resource_migrations:
                            for old in sorted(released,key=lambda b:(-owners(b),b.task_id)):
                                for alternate in pool[old.task_id]:
                                    ck()
                                    if alternate.satellite_id==old.satellite_id:continue
                                    if stats['migration_attempts']>=48:break
                                    stats['migration_attempts']+=1
                                    proposed=replay(seed.assignments+[alternate])
                                    if proposed is not None:
                                        seed=proposed;moved.append(dict(task=old.task_id,from_satellite=old.satellite_id,to_satellite=alternate.satellite_id));break
                        # Reinsert any displaced task on remaining source options.
                        for old in sorted(released,key=lambda b:b.task_id):
                            if old.task_id in seed.assigned_task_ids:continue
                            for option in pool[old.task_id]:
                                if option.satellite_id!=old.satellite_id:continue
                                if valid(option,seed):seed.assignments.append(option);break
                        if better(seed,best):
                            checked=replay(seed.assignments)
                            if checked is None:continue
                            stats['changes'].append(dict(inserted=tid,released=list(ids),moved=moved,
                                dropped=sorted(set(best.assigned_task_ids)-set(checked.assigned_task_ids)),added=sorted(set(checked.assigned_task_ids)-set(best.assigned_task_ids)),
                                count_before=len(best.assignments),count_after=len(checked.assignments),TP_before=sum(problem.tasks[b.task_id].priority for b in best.assignments),TP_after=sum(problem.tasks[b.task_id].priority for b in checked.assignments),diagnosis=d))
                            best=checked;stats['accepted']+=1;stats['migrations']+=len(moved);stats['replacements']+=int(not moved);accepted=True;break
                    if accepted:break
                if accepted:break
            if not accepted:break
    except _Stop:pass
    except budget_exception:stats['stop_reason']='solver_budget'
    stats['wall_s']=time.monotonic()-begun
    return best,stats
