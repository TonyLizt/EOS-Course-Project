"""训练与推理共用24维合同；不读取标签、任务ID编码或跨数据集统计。"""
from bisect import bisect_left,bisect_right
from collections import Counter,defaultdict
import math
from .protocol import FEATURE_NAMES

def extract(problem, plan, pool, current, control):
    duration=max(1.,(problem.end_time-problem.start_time).total_seconds()); n=max(1,len(problem.tasks))
    completed=len(set(plan.assigned_task_ids)); remaining=max(1,n-completed-1)
    base=Counter(a.task_id for a in pool);counts=Counter(a.task_id for a in current)
    satellites=defaultdict(set); intervals=defaultdict(lambda:defaultdict(list))
    for a in current:
        control.checkpoint();satellites[a.task_id].add(a.satellite_id)
        intervals[a.satellite_id][a.task_id].append((a.sat_start_time,a.sat_end_time))
    # 每星/任务建立开始和结束有序索引，二分查询重叠，不对全池做两两比较。
    indexes={sid:{tid:(sorted(s for s,e in spans),sorted(e for s,e in spans))
                  for tid,spans in tasks.items()} for sid,tasks in intervals.items()}
    loads=defaultdict(lambda:[0.,0.,0]);ground=Counter();ordered=defaultdict(list)
    for a in plan.assignments:
        loads[a.satellite_id][0]+=(a.sat_end_time-a.sat_start_time).total_seconds()
        loads[a.satellite_id][2]+=1;ordered[a.satellite_id].append(a)
        if a.gs_start_time is not None:
            seconds=(a.gs_end_time-a.gs_start_time).total_seconds()
            loads[a.satellite_id][1]+=seconds;ground[a.ground_station_id]+=seconds
    windows={w.window_id:w for task in problem.tasks.values() for w in task.windows}
    priority=max(1.,max((abs(t.priority) for t in problem.tasks.values()),default=1.))
    result=[]
    for a in current:
        control.checkpoint();task=problem.tasks[a.task_id];w=windows[a.sat_window_id]
        pressure=exclusive=0
        for tid,(starts,ends) in indexes.get(a.satellite_id,{}).items():
            control.checkpoint()
            if tid==a.task_id:continue
            if bisect_left(starts,a.sat_end_time)-bisect_right(ends,a.sat_start_time)>0:
                pressure+=1
                if satellites[tid]=={a.satellite_id}:exclusive+=1
        neighbors=ordered[a.satellite_id]
        before=[b for b in neighbors if b.sat_end_time<=a.sat_start_time]
        after=[b for b in neighbors if b.sat_start_time>=a.sat_end_time]
        prev=max(before,key=lambda b:b.sat_end_time) if before else None
        nxt=min(after,key=lambda b:b.sat_start_time) if after else None
        load=loads[a.satellite_id]
        row=[task.required_duration/duration,task.priority/priority,base[a.task_id]/max(1,len(pool)),
             counts[a.task_id]/max(1,base[a.task_id]),len(satellites[a.task_id])/max(1,len(problem.satellites)),
             (w.start_time-problem.start_time).total_seconds()/duration,
             (w.end_time-problem.start_time).total_seconds()/duration,
             ((w.end_time-w.start_time).total_seconds()-task.required_duration)/duration,
             (a.sat_start_time-problem.start_time).total_seconds()/duration,
             (a.sat_end_time-problem.start_time).total_seconds()/duration,
             completed/n,(n-completed)/n,load[0]/duration,load[1]/duration,load[2]/n,
             pressure/remaining,exclusive/remaining,
             (a.sat_start_time-prev.sat_end_time).total_seconds()/duration if prev else 0.,float(prev is not None),
             (nxt.sat_start_time-a.sat_end_time).total_seconds()/duration if nxt else 0.,float(nxt is not None),
             float(bool(problem.ground_stations)),
             (a.gs_end_time-a.gs_start_time).total_seconds()/duration if a.gs_start_time else 0.,
             ground[a.ground_station_id]/duration if a.ground_station_id else 0.]
        if len(row)!=len(FEATURE_NAMES) or not all(math.isfinite(x) for x in row):raise ValueError('LAVIS_INVALID_FEATURES')
        result.append(row)
    return result
