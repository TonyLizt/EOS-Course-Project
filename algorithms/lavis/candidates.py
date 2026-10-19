"""稳定轮转的有限候选池；来源先核验一次，池冻结后不修改Assignment。"""
from collections import defaultdict, deque
from dataclasses import replace
from schedulers.constraint_model import Schedule, TimePlacementStrategy
from schedulers.assignment_building import configured_observation
from schedulers.source_windows import observation_source_matches
from .protocol import POOL_CONFIG

def key(a):
    return (a.task_id,a.satellite_id,a.sensor_id,a.sat_window_id,a.sat_start_time.isoformat(),
            a.sat_end_time.isoformat(),a.ground_station_id or '',a.gs_window_id or 0,
            a.gs_start_time.isoformat() if a.gs_start_time else '',
            a.gs_end_time.isoformat() if a.gs_end_time else '')

def round_robin(groups):
    active=deque(deque(group) for group in groups if group)
    while active:
        group=active.popleft();yield group.popleft()
        if group:active.append(group)

def build_pool(problem, constraints, control, config=None):
    config=config or POOL_CONFIG
    empty=Schedule(); comm=defaultdict(list); per_task=[]
    records=0; admitted=0; selected_windows=0
    stats={'source_records':0,'source_records_truncated':False,'window_quota_truncated_tasks':0}
    # 先数源记录且每条轮询取消；上限触发明确失败，避免把残缺扫描当全量池。
    for task in problem.tasks.values():
        for _ in task.windows:
            control.checkpoint();records+=1
            if records>config['max_source_records']:raise ValueError('LAVIS_SOURCE_RECORD_LIMIT')
    for cw in problem.comm_windows:
        control.checkpoint();records+=1
        if records>config['max_source_records']:raise ValueError('LAVIS_SOURCE_RECORD_LIMIT')
        comm[cw.satellite_id].append(cw)
    for windows in comm.values():windows.sort(key=lambda w:(w.start_time,w.end_time,w.window_id))
    for tid,task in sorted(problem.tasks.items()):
        control.checkpoint();groups=defaultdict(list)
        for w in task.windows:groups[w.satellite_id].append(w)
        ordered=[sorted(groups[sid],key=lambda w:(w.start_time,w.end_time,w.window_id)) for sid in sorted(groups)]
        if len(task.windows)>config['max_source_windows_per_task']:stats['window_quota_truncated_tasks']+=1
        result=[];seen=set()
        for index,w in enumerate(round_robin(ordered)):
            control.checkpoint()
            if index>=config['max_source_windows_per_task']:break
            selected_windows+=1
            a=configured_observation(problem,task,w,constraints.placement_mode)
            if a is None:continue
            options=[]
            if not problem.ground_stations:options=[a]
            else:
                for cw in comm.get(a.satellite_id,[]):
                    control.checkpoint()
                    # 公共模型要求严格晚于观测完成；不自行加epsilon改变物理语义。
                    if cw.start_time<=a.sat_end_time:continue
                    interval=TimePlacementStrategy.place(cw.start_time,cw.end_time,
                        task.required_duration*constraints.downlink_duration_ratio,mode=constraints.placement_mode)
                    if interval:
                        options.append(replace(a,ground_station_id=cw.ground_station_id,gs_window_id=cw.window_id,
                                               gs_start_time=interval[0],gs_end_time=interval[1]))
                    if len(options)>=config['max_downlink_options_per_observation']:break
            for candidate in options:
                control.checkpoint();identity=key(candidate)
                if identity in seen:continue
                seen.add(identity)
                if (observation_source_matches(problem,task,w,vars(candidate),candidate.sat_start_time,candidate.sat_end_time)
                    and control.check(constraints,candidate,empty,static=True)):
                    result.append(candidate)
                if len(result)>=config['max_candidates_per_task']:break
            if len(result)>=config['max_candidates_per_task']:break
        admitted+=len(result);per_task.append(result)
    pool=[]
    for a in round_robin(per_task):
        control.checkpoint()
        if len(pool)>=config['max_candidates_total']:break
        pool.append(a)
    stats.update(source_records=records,selected_windows=selected_windows,admitted_before_total_limit=admitted,
                 candidates=len(pool),total_quota_truncated=admitted>len(pool),
                 omitted_candidate_tasks=len([items for items in per_task if items])-len({a.task_id for a in pool}))
    return sorted(pool,key=key),stats

def feasible(pool, plan, constraints, control):
    assigned=set(plan.assigned_task_ids)
    return [a for a in pool if a.task_id not in assigned and control.check(constraints,a,plan)]
