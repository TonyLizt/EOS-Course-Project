"""Small, explicit development scene construction using the shared physics stack.
Never edits a historical scene or scientific module. Each CLI phase is explicit.
"""
from pathlib import Path
import sys,os,json,time,hashlib,math,random,sqlite3,re,copy,resource,traceback
from collections import defaultdict,Counter
from datetime import datetime,timedelta,timezone
ROOT=Path('/home/mint/projects/EOS-Course-Project')
OUT=Path('/home/mint/eos-course-runtime/f-pilot-v25-web-scenes')
WORK=Path('/mnt/f/EOS-Pilot-Work-v1/web-scenes-v25')
DATA=WORK/'scenarios'
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(OUT.parent/'f-pilot-v24r6-web-promotion'))
from inventory import read,save,sha,http,backup,tables,RUNTIME,PY
from scripts.build_shared_dataset import OrbitGrid,parameters,digest,sampled_check
from scripts.build_f_pilot import _attitude_boundaries,_initial_attitudes
from utils.time_parsing import parse_orbit_epoch
from utils import visibility
from utils.physical_contract import descriptor
from utils.continuous_exposure import window_generation_record
SEED=2026102701

def exclusive_save(p,x):
    p=Path(p)
    if p.exists():raise FileExistsError(p)
    save(p,x)

def init():
    src=Path('/mnt/f/EOS-Bench/output_s50_cc/re_50_satellites/Scenario_S1_50_satellites_Sats50_M100_T7.0d_cities_01.json')
    text=src.open().read(1048576);decoder=json.JSONDecoder();h={}
    for k in ('metadata','satellites','missions'):
        at=text.index(':',text.index(chr(34)+k+chr(34)))+1
        h[k]=decoder.raw_decode(text[at:].lstrip())[0]
    exclusive_save(OUT/'source_header.json',h)
    exclusive_save(OUT/'source_identity.json',dict(path=str(src),sha256=sha(src),size=src.stat().st_size,header_sha256=sha(OUT/'source_header.json'),old_windows_read=False))
    backup(RUNTIME/'results.sqlite3',OUT/'web_before.sqlite3');exclusive_save(OUT/'web_before_tables.json',tables(RUNTIME/'results.sqlite3'))
    exclusive_save(OUT/'scientific_identity.json',read(OUT.parent/'f-pilot-v24r6-web-promotion/deployment_final.json'))
    exclusive_save(OUT/'web_state_before.json',dict(health=http('GET','/api/health'),execution=http('GET','/api/execution-settings'),sources=http('GET','/api/data-sources')))
    plan=dict(version='web-mechanism-development-v1',purpose='explicit RABAS/CAABS-oriented development, not independently sampled performance test',seed=SEED,
        first_id='R30-main-01',satellite_count=30,task_count=144,time_start=h['metadata']['creation_time'],duration_s=21600,grid_s=5,
        orbit_selection='evenly spaced original indices floor(i*50/30), no fabricated satellites',source=read(OUT/'source_identity.json'),
        request_policy='controlled repeat observation requests over real city coordinates; 72 shared and72 single-eligible requests; preserve source family mapping; repeated targets are dependent, not new independent targets',
        task_duration_s=5.,shared_priority=3.,exclusive_priority=9.,window_policy='real regenerated windows; trim only to complete5s endpoints; at most two satellites per shared request and one for exclusive; explicit eligibility restrictions, not claimed geometric impossibility',
        resource_policy='controlled per-orbit power/storage, calibrated from assigned demand only before Solver results; real CM additive W semantics, no fabricated Wh',
        gate=dict(tasks_single_feasible_fraction=1.,minimum_shared_tasks=24,minimum_conflict_edges=30,minimum_legal_plan_tasks=25,minimum_independent_samples=10),
        bank_resources=dict(max_wall_s=900,max_rss_kib=2400000),
        comparison=dict(algorithms=['fcfs','edf','rabas','caabs'],objective_protocol='objective-v1',weights=dict(w_profit=0.,w_completion=1.,w_timeliness=0.,w_balance=0.),time_budget_s=60,seed=SEED,Worker_configuration=4,concurrent_comparison_submissions=1,reason='preserve requested completion-first native/standard adapter semantics; display70/20/10 separately; do not silently relabel Score-v2 as TCR-first'),
        selection_outcomes='retain every scene and every negative result; at most declared main02 revisions, never independent test claim',source_sha256=sha(Path(__file__)))
    exclusive_save(OUT/'design_plan_before_generation.json',plan)
    print('INIT',len(h['satellites']),len(h['missions']),[(s['id'],round(s['orbital_params']['right_ascension_of_ascending_node_deg'],2),round(s['orbital_params']['mean_anomaly_deg'],2)) for s in h['satellites'][:12]],flush=True)

def bank(count=30):
    h=read(OUT/'source_header.json');plan=read(OUT/'design_plan_before_generation.json')
    indices=[math.floor(i*len(h['satellites'])/count) for i in range(count)]
    satellites=[h['satellites'][i] for i in indices];start=parse_orbit_epoch(plan['time_start']);begun=time.perf_counter()
    visibility.ensure_orekit(str(ROOT/'utils/orekit-data.zip'))
    grid=OrbitGrid(satellites,start,5,plan['duration_s']);rows=[]
    for i,m in enumerate(h['missions']):
        for s in satellites:
            for w in grid.windows(s,m):
                lo=parse_orbit_epoch(w['start_time']);hi=parse_orbit_epoch(w['end_time'])
                seconds=math.floor((hi-lo).total_seconds()/5)*5
                if seconds<15:continue
                # Exact aligned endpoint, with current evaluator poses for every boundary.
                end=lo+timedelta(seconds=seconds);ev=visibility.create_visibility_evaluator(**parameters(s,m))
                poses=[ev(lo+timedelta(seconds=k*5)) for k in range(seconds//5+1)]
                if not all(p['visible'] and not p.get('evaluation_error') for p in poses):raise ValueError('fresh endpoint visibility disagreement')
                w.update(end_time=end.isoformat(),agile_data={axis+'_angles':[float(p[axis+'_deg']) for p in poses[:-1]] for axis in ('roll','pitch','yaw')})
                w['agile_data']['boundary_quaternions_xyzw']=[p['inertial_to_body_quaternion_xyzw'] for p in poses]
                rows.append(dict(target_id=m['id'],satellite_id=s['id'],window=w))
        if i%10==9:print('BANK',i+1,len(rows),round(time.perf_counter()-begun,2),flush=True)
        if time.perf_counter()-begun>plan['bank_resources']['max_wall_s']:raise TimeoutError('bounded bank wall limit; do not publish partial bank')
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss>plan['bank_resources']['max_rss_kib']:raise MemoryError('bank memory bound')
    exclusive_save(WORK/f'bank{count}.json',dict(satellites=satellites,windows=rows,start=start.isoformat(),duration_s=plan['duration_s'],source_sha256=plan['source']['sha256'],generation=window_generation_record(5,5,60.),initial_attitudes=_initial_attitudes(satellites,start),elapsed_s=time.perf_counter()-begun,maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,code_sha256=sha(Path(__file__)),old_windows_used=False))
    print('BANK_COMPLETE',len(rows),round(time.perf_counter()-begun,2),flush=True)

if __name__=='__main__':
    action=sys.argv[1]
    if action=='init':init()
    elif action=='bank':bank(int(sys.argv[2]) if len(sys.argv)>2 else 30)
    else:raise ValueError(action)
