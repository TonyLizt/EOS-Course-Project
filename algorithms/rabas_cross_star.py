"""RABAS 可选跨星迁移：移动可替代的共享任务，为资源受阻任务腾出空间；全部方案完整重放。

参考 2026-10-28 交付快照选择性移植；不引入 Score/v2 协议，不修改物理与指标口径。
"""
from schedulers.constraint_model import Schedule
from schedulers.assignment_building import observation_at_index

class RepairLimit(Exception):pass

def improve(auction, incumbent, context, deadline):
    from .auction_bundle import _BudgetExpired,_RoundLimit
    from .objective_adapters.search import BudgetExpired as AdapterBudgetExpired
    p=auction.params;c=auction.control;problem=auction.problem;cm=auction.constraints
    start_checks=c.stats['public_constraint_checks']
    stats=dict(public_checks=0,replay_checks=0,full_replays=0,failed_replays=0,migration_candidates=0,repairs=0,inserted=0,trace=[],stop_reason='exhausted',
        before_count=len(incumbent.assignments),before_TP=sum(problem.tasks[a.task_id].priority for a in incumbent.assignments))
    best=incumbent;best_score=auction.objective.score(best)
    def checkpoint():
        c.checkpoint()
        if c.clock()>=deadline or c.stats['public_constraint_checks']-start_checks>=p.cross_star_max_checks:raise RepairLimit()
    def full_replay(assignments):
        checkpoint()
        if stats['full_replays']>=p.cross_star_max_replays:raise RepairLimit()
        stats['full_replays']+=1;trial=Schedule()
        for a in sorted(assignments,key=lambda a:(a.sat_start_time,a.satellite_id,a.task_id,a.sat_window_id)):
            checkpoint();stats['replay_checks']+=1
            if not c.check(cm,a,trial,award=True):stats['failed_replays']+=1;return None
            trial.assignments.append(a)
        return trial
    try:
        for _ in range(p.cross_star_max_repairs):
            checkpoint();accepted=False
            missing=sorted(set(problem.tasks)-set(best.assigned_task_ids),key=lambda t:(-problem.tasks[t].priority,auction.deadlines[t],t))[:p.cross_star_tasks]
            for tid in missing:
                checkpoint();task=problem.tasks[tid]
                for sid in auction.owners[tid]:
                    for w in auction.selected_windows.get((sid,tid),[])[:p.cross_star_windows]:
                        for k in auction._starts(sid,tid,w,best):
                            checkpoint();target=observation_at_index(problem,task,w,k)
                            if target is None or cm._check_per_orbit_resource(target,best):continue
                            movers=sorted((a for a in best.assignments if a.satellite_id==sid and a.orbit_number==target.orbit_number and len(auction.owners[a.task_id])>1),key=lambda a:(problem.tasks[a.task_id].priority,a.task_id,a.sat_start_time))[:p.cross_star_movers]
                            for moving in movers:
                                base=Schedule([a for a in best.assignments if a is not moving]);alternatives=0
                                for other_sid in auction.owners[moving.task_id]:
                                    if other_sid==sid:continue
                                    for alt in auction.options(other_sid,moving.task_id,base):
                                        checkpoint();alternatives+=1;stats['migration_candidates']+=1
                                        proposal=full_replay(base.assignments+[alt,target])
                                        if proposal is not None:
                                            score=auction.objective.score(proposal)
                                            if score > best_score + 1e-12:
                                                stats['trace'].append(dict(moved_task=moving.task_id,from_satellite=sid,to_satellite=other_sid,inserted_task=tid,
                                                    before_count=len(best.assignments),after_count=len(proposal.assignments),before_score=best_score,after_score=score))
                                                best=proposal;best_score=score;stats['repairs']+=1;stats['inserted']+=1;accepted=True;break
                                        if alternatives>=p.cross_star_alternatives:break
                                    if accepted or alternatives>=p.cross_star_alternatives:break
                                if accepted:break
                            if accepted:break
                        if accepted:break
                    if accepted:break
                if accepted:break
            if not accepted:break
    except (RepairLimit,_BudgetExpired,_RoundLimit,AdapterBudgetExpired):stats['stop_reason']='repair_or_parent_limit'
    stats['public_checks']=c.stats['public_constraint_checks']-start_checks
    stats['after_count']=len(best.assignments);stats['after_TP']=sum(problem.tasks[a.task_id].priority for a in best.assignments)
    return best,stats
