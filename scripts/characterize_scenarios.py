"""Measure opportunity competition from actual canonical source windows."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utils.time_parsing import parse_orbit_epoch


def characterize(scene):
    tasks={m['id']:m for m in scene['missions']}
    choices={tid:set() for tid in tasks}; counts=dict.fromkeys(tasks,0)
    timelines=defaultdict(list)
    for row in scene['observation_windows']:
        for w in row['time_windows']:
            start,end=map(parse_orbit_epoch,(w['start_time'],w['end_time']))
            if (end-start).total_seconds()<tasks[row['mission_id']]['observation_requirement']['duration_s']:
                continue
            tid,sid=row['mission_id'],row['satellite_id']
            choices[tid].add(sid);counts[tid]+=1
            timelines[sid].append((start,end,tid))
    pairs=overlap=0; satellite_load={}; demand_pressure={}; storage_pressure={}
    for sat in scene['satellites']:
        sid=sat['id'];rows=sorted(timelines[sid]); pairs_here=0
        for i,(a,b,tid) in enumerate(rows):
            for c,d,other in rows[i+1:]:
                if other==tid: continue
                pairs+=1
                if c<b and a<d: overlap+=1;pairs_here+=1
        unique={r[2] for r in rows}; seconds=sum(tasks[t]['observation_requirement']['duration_s'] for t in unique)
        capacity=scene['metadata']['duration']
        storage=sat['satellite_specs'].get('max_data_storage_GB') or 0
        rate=sat.get('observation_capability',{}).get('sensors',[{}])[0].get('data_rate_Mbps',0)
        storage_pressure[sid]=seconds*rate/(8*1024*storage) if storage else 0
        satellite_load[sid]=dict(candidate_tasks=len(unique),windows=len(rows),overlap_pairs=pairs_here)
        demand_pressure[sid]=seconds/capacity
    sets=list(choices.values());total=len(sets)*(len(sets)-1)//2
    intersection=sum(len(a&b)/max(1,len(a|b)) for i,a in enumerate(sets) for b in sets[i+1:])
    return dict(satellite_count=len(scene['satellites']),task_count=len(tasks),duration_s=scene['metadata']['duration'],
        feasible_window_count=sum(counts.values()),windows_per_task=counts,
        candidate_satellites_per_task={k:len(v) for k,v in choices.items()},
        zero_opportunity_fraction=sum(not v for v in choices.values())/max(1,len(tasks)),
        window_overlap_fraction=overlap/max(1,pairs),overlapping_window_pairs=overlap,
        same_satellite_window_pairs=pairs,candidate_satellite_jaccard_mean=intersection/max(1,total),
        satellite_load=satellite_load,demand_capacity_ratio_by_satellite=demand_pressure,
        max_demand_capacity_ratio=max(demand_pressure.values(),default=0),
        demand_storage_ratio_by_satellite=storage_pressure,max_demand_storage_ratio=max(storage_pressure.values(),default=0),
        definition='All full-exposure source intervals, not a bounded algorithm candidate pool; ratios are descriptive, not feasibility certificates.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('scenario',type=Path)
    print(json.dumps(characterize(json.loads(p.parse_args().scenario.read_text())),indent=2))
