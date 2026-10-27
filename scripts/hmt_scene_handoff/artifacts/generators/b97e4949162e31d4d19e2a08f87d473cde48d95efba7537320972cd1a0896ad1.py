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

def clipped(row,seconds=100,shift=0):
    w=copy.deepcopy(row['window']);start=parse_orbit_epoch(w['start_time'])+timedelta(seconds=shift)
    available=(parse_orbit_epoch(w['end_time'])-start).total_seconds();n=int(min(seconds,available)//5)
    if n<3:raise ValueError('no complete aligned request interval')
    offset=shift//5;original=row['window']['agile_data']
    w['start_time']=start.isoformat();w['end_time']=(start+timedelta(seconds=5*n)).isoformat()
    w['agile_data']={axis+'_angles':original[axis+'_angles'][offset:offset+n] for axis in ('yaw','pitch','roll')}
    w['agile_data']['boundary_quaternions_xyzw']=original['boundary_quaternions_xyzw'][offset:offset+n+1]
    return w

def build(sid='R30-main-01',count=30,task_count=144,kind='R'):
    from scripts.recompute_scenario_windows import validate_structure
    from scripts.characterize_scenarios import characterize
    from schedulers.scenario_loader import load_scheduling_problem_from_json
    from schedulers.constraint_model import ConstraintModel,Schedule
    from algorithms.candidate_pool import enumerate_task_candidates
    from schedulers.schedule_output import schedule_to_dict
    from utils.continuous_exposure import PlanExposureAuditor
    from importlib.metadata import version
    if (DATA/sid).exists():raise FileExistsError('immutable candidate; use a new id')
    h=read(OUT/'source_header.json');b=read(WORK/f'bank{count}.json');rows=b['windows'];by=defaultdict(list)
    for r in rows:by[r['target_id']].append(r)
    length=lambda r:(parse_orbit_epoch(r['window']['end_time'])-parse_orbit_epoch(r['window']['start_time'])).total_seconds()
    eligible=[]
    for a in rows:
        if length(a)<100:continue
        alts=[z for z in by[a['target_id']] if z['satellite_id']!=a['satellite_id'] and length(z)>=100]
        private=[z for z in rows if z['target_id']!=a['target_id'] and z['satellite_id']==a['satellite_id'] and z['window']['orbit_number']==a['window']['orbit_number'] and 120<=(parse_orbit_epoch(z['window']['start_time'])-parse_orbit_epoch(a['window']['start_time'])).total_seconds()<=1800 and length(z)>=100]
        if alts and private:eligible.append((a,alts,private))
    eligible.sort(key=lambda x:(parse_orbit_epoch(x[0]['window']['start_time']),digest([SEED,x[0]['satellite_id'],x[0]['target_id']])))
    clusters=[];primary=set();alternate=set();num_clusters=min(count//2,task_count//12)
    for a,alts,private in eligible:
        p=a['satellite_id']
        if p in primary or p in alternate:continue
        alts=[z for z in alts if z['satellite_id'] not in primary and z['satellite_id'] not in alternate and z['satellite_id']!=p]
        if not alts:continue
        alt=min(alts,key=lambda z:(z['window']['start_time'],z['satellite_id']))
        ex=min(private,key=lambda z:(z['window']['start_time'],digest([SEED,z['target_id']])))
        clusters.append(dict(shared=a,alternative=alt,exclusive=ex));primary.add(p);alternate.add(alt['satellite_id'])
        if len(clusters)==num_clusters:break
    if len(clusters)!=num_clusters:raise ValueError(('insufficient independent real resource clusters',len(clusters),num_clusters))
    per_cluster=[task_count//num_clusters+(i<task_count%num_clusters) for i in range(num_clusters)]
    # Freeze exact physical identities/resources before candidate evaluation or any Solver.
    design=dict(id=sid,kind=kind,scale=[count,task_count],seed=SEED,bank_sha256=sha(WORK/f'bank{count}.json'),clusters=clusters,requests_per_cluster=per_cluster,window_width_s=100,
        controlled_resources=dict(primary_capacity_exposures=6,alternate_capacity_exposures=10,storage_and_additive_power_both_binding=True),
        duration_priority_policy=(dict(duration_s=[20,5,5,10,5,5],priority=[10,3,3,7,3,3],rule='repeat ordinal mod6, cost/value branch competition') if kind=='C' else dict(duration_s=[5],priority='shared3 exclusive9')),
        goal='RABAS cross-star shared-vs-exclusive allocation' if kind=='R' else 'CAABS bounded competing repeated-observation clusters',
        repeated_requests='distinct controlled repeat observation requests, same true coordinate/track; not independent samples',
        eligibility='explicit requester satellite eligibility sets; excluded alternatives not claimed physically invisible',
        objective_protocol='objective-score-v2',mode='SCORE_70_20_10',schedule_model='completion_first',time_budget_s=60,native_effective_s=29.5,public_hard_checks=140000,
        correction_to_initial_planning_draft='use current accepted Score hard-budget protocol with completion_first initial model, not the draft pure-TCR objective-v1; before any Solver/result',
        generation_code_sha256=sha(Path(__file__)),independent_test=False)
    exclusive_save(OUT/(sid+'_design_frozen.json'),design)
    satellites=copy.deepcopy(b['satellites']);satmap={s['id']:s for s in satellites};ms={m['id']:m for m in h['missions']}
    resource_ledger=[]
    for s in satellites:
        cap=6 if s['id'] in primary else 10
        sensor=s['observation_capability']['sensors'][0];unit=5*float(sensor['data_rate_Mbps'])/(8*1024)
        old=copy.deepcopy(s['satellite_specs'])
        s['satellite_specs']['max_power_W']=cap*float(sensor['power_consumption_W'])
        s['satellite_specs']['max_data_storage_GB']=cap*unit
        resource_ledger.append(dict(satellite=s['id'],old_specs=old,used_specs=s['satellite_specs'],controlled=True))
    missions=[];windows=[];ledger=[]
    for i,(c,n) in enumerate(zip(clusters,per_cluster)):
        shared_n=n//2
        for j in range(n):
            shared=j<shared_n;origin=c['shared'] if shared else c['exclusive'];tid=f'{kind}{count}-G{i+1:02d}-'+('S' if shared else 'X')+f'{j+1:02d}'
            mission=copy.deepcopy(ms[origin['target_id']]);old=copy.deepcopy(mission);mission['id']=tid
            mission['priority']=3. if shared else 9.;mission['observation_requirement']['duration_s']=5.
            if kind=='C':
                mission['priority']=[10.,3.,3.,7.,3.,3.][j%6]
                mission['observation_requirement']['duration_s']=[20.,5.,5.,10.,5.,5.][j%6]
            missions.append(mission);chosen=[origin,c['alternative']] if shared else [origin]
            for r in chosen:
                windows.append(dict(satellite_id=r['satellite_id'],mission_id=tid,sensor_id=satmap[r['satellite_id']]['observation_capability']['sensors'][0]['sensor_id'],time_windows=[clipped(r)]))
            ledger.append(dict(task_id=tid,source_target_id=origin['target_id'],source_duration_s=old['observation_requirement']['duration_s'],actual_duration_s=mission['observation_requirement']['duration_s'],source_priority=old['priority'],actual_priority=mission['priority'],request_role='SHARED' if shared else 'EXCLUSIVE_ELIGIBILITY',eligible_satellites=[r['satellite_id'] for r in chosen],controlled_repeat_request=True))
    assert len(missions)==task_count
    scene=dict(scenario_id=sid,metadata=dict(name=sid,creation_time=b['start'],duration=b['duration_s'],time_step=5.,description='真实EOS-Bench轨道/城市；显式受控重复观测与异构资源；偏机制开发集',extra=dict(source_dataset='EOS-Bench-F50',source_sha256=b['source_sha256'],source_group_id='F50-cities01-repeated-development',generator_seed=SEED,generator_version='web-mechanism-development-v1',window_generation=b['generation'],physical_contract=descriptor(),initial_attitudes=b['initial_attitudes'],visibility_settings=dict(min_elevation_deg=5.,coarse_step_min=60.),controlled_resources=resource_ledger,controlled_requests=ledger,not_independent_test=True)),satellites=satellites,missions=missions,ground_stations=[],observation_windows=windows,communication_windows=[])
    folder=DATA/sid;folder.mkdir(parents=True);path=folder/'scenario.json';exclusive_save(path,scene);scene_sha=sha(path)
    structure=validate_structure(scene);exclusive_save(folder/'structure.json',structure)
    visibility.ensure_orekit(str(ROOT/'utils/orekit-data.zip'));sampling_started=time.perf_counter();physics=sampled_check(scene,ROOT/'utils/orekit-data.zip');sample_wall=time.perf_counter()-sampling_started
    exclusive_save(folder/'sampled_physics.json',physics)
    sidecar=dict(artifact_kind='fresh_generated_shared_v1',scenario_id=sid,scenario_sha256=scene_sha,completion_status='complete',calculator_kind='orekit',scenario_physics_version='fresh_epoch_parsed_v1',epoch_parser_version='epoch_parser_v1',propagation_version='orekit-keplerian/orekit_jpype-'+version('orekit_jpype'),window_boundary_version='visibility_exit_refined_v3',window_generation=b['generation'],calculation_settings=dict(time_step=5.,min_elevation_deg=5.),provenance_status='verified_generation',publication_status='development',formal_release_eligible=False,physical_validation=dict(status='SAMPLED_PASS',continuous_status='INCONCLUSIVE'),parent_scenario_sha256=None,lineage_group_id='F50-cities01-repeated-development',generation_code_sha256=sha(Path(__file__)),orekit_data_sha256=sha(ROOT/'utils/orekit-data.zip'),source_path=read(OUT/'source_identity.json')['path'],source_sha256=b['source_sha256'],selection_plan_sha256=sha(OUT/(sid+'_design_frozen.json')))
    sidecar.update(difficulty_profile='resource_competition' if kind=='R' else 'high_conflict',scale=f'S{count}',seed=SEED)
    exclusive_save(folder/'provenance/scenario.json.provenance.json',sidecar);exclusive_save(folder/'provenance.json',sidecar)
    p=load_scheduling_problem_from_json(path);p.execution_mode='physical_validation';cm=ConstraintModel(p);opts={};single=[]
    for tid,t in p.tasks.items():
        allopts=enumerate_task_candidates(p,t,max_candidates=128,random_samples_per_window=0,seed=SEED)
        good=[a for a in allopts if cm.is_feasible_assignment(a,Schedule())]
        opts[tid]=good;single.append(dict(task_id=tid,raw=len(allopts),single_valid=len(good),satellites=sorted({a.satellite_id for a in good})))
    if any(not x['single_valid'] for x in single):
        exclusive_save(folder/'quarantine.json',dict(reason='zero single-task candidates',rows=[x for x in single if not x['single_valid']]));raise ValueError('candidate gate failure')
    plans={}
    roles={x['task_id']:x['request_role'] for x in ledger}
    for order in ('chronological','exclusive_first','value_first'):
        ids=sorted(opts,key=lambda tid:(min(a.sat_start_time for a in opts[tid]),tid)) if order=='chronological' else sorted(opts,key=lambda tid:(roles[tid]!='EXCLUSIVE_ELIGIBILITY',min(a.sat_start_time for a in opts[tid]),tid)) if order=='exclusive_first' else sorted(opts,key=lambda tid:(-float(p.tasks[tid].priority),min(a.sat_start_time for a in opts[tid]),tid))
        plan=Schedule()
        for tid in ids:
            a=next((a for a in sorted(opts[tid],key=lambda a:(a.sat_start_time,a.satellite_id)) if cm.is_feasible_assignment(a,plan)),None)
            if a is not None:plan.assignments.append(a)
        plans[order]=schedule_to_dict(plan,p)
    edges=set();parts=[(r['mission_id'],r['satellite_id'],w) for r in windows for w in r['time_windows']]
    for k,(t,s,w) in enumerate(parts):
        for t2,s2,w2 in parts[k+1:]:
            if t!=t2 and s==s2 and w['start_time']<w2['end_time'] and w2['start_time']<w['end_time']:edges.add(tuple(sorted((t,t2))))
    stats=dict(scenario_id=sid,scenario_sha256=scene_sha,satellites=count,active_satellites=len({r['satellite_id'] for r in windows}),tasks=task_count,windows=len(parts),multi_satellite_tasks=sum(len(x['satellites'])>1 for x in single),conflict_edges=len(edges),lower_bound=max(len(v['assignments']) for v in plans.values()),optimistic_upper_bound=task_count,upper_bound_certificate='one assignment per task; optimistic not a guarantee',neutral_plans={k:dict(completed=len(v['assignments']),TP=sum(a['priority'] for a in v['assignments'])) for k,v in plans.items()},all_tasks_individually_feasible=True,Loader=True,structure=structure,physics=dict(status='SAMPLED_PASS',segments=physics['checked_segments'],sample_wall_s=sample_wall),candidate_coverage=single,resource_clusters=num_clusters,resource_ledger=resource_ledger,development_not_independent=True,Controller_validation='NOT_RUN')
    assert stats['multi_satellite_tasks']>=24 and len(edges)>=30 and stats['lower_bound']>=25
    exclusive_save(folder/'neutral_legal_plans.json',plans);exclusive_save(folder/'conflict_graph.json',dict(edges=sorted(edges)));exclusive_save(folder/'design_assessment.json',stats);exclusive_save(folder/'characterization.json',characterize(scene));exclusive_save(folder/'validation.json',dict(scenario_sha256=scene_sha,Loader=True,structure=structure,physics=stats['physics'],single_task_feasible=task_count,continuous_certification='NOT_CERTIFIED',Controller='NOT_RUN'))
    exclusive_save(folder/'source_snapshot.json',dict(source=read(OUT/'source_identity.json'),selected_satellites=[s['id'] for s in satellites],bank_sha256=sha(WORK/f'bank{count}.json'),controlled_requests=ledger,controlled_resources=resource_ledger,design_sha256=sha(OUT/(sid+'_design_frozen.json'))))
    print('SCENE_GATE_PASS',sid,count,task_count,len(parts),stats['multi_satellite_tasks'],len(edges),'LB',stats['lower_bound'],'UB',task_count,stats['neutral_plans'],flush=True)

def prepare_evidence(sid):
    from schedulers.scenario_loader import load_scheduling_problem_from_json
    from schedulers.assignment_building import observation_at_index
    from schedulers.source_windows import observation_source_matches
    from schedulers.preview_exposure import candidate_exposure
    from utils.continuous_exposure import ExposureStatus
    from utils.physical_candidate_evidence import EvidenceWriter,PhysicalCandidateEvidenceStore
    os.environ.pop('EOS_PHYSICAL_EVIDENCE_DIR',None)
    folder=DATA/sid;path=folder/'scenario.json';scene_sha=sha(path)
    # Complete public source-grid coverage, never selected from a Solver plan.
    p=load_scheduling_problem_from_json(path);p.execution_mode='physical_validation';visibility.ensure_orekit(str(ROOT/'utils/orekit-data.zip'))
    count=sum(max(0,int(((w.end_time-w.start_time).total_seconds()-t.required_duration)//w.time_step)+1) for t in p.tasks.values() for w in t.windows)
    exclusive_save(OUT/(sid+'_evidence_plan.json'),dict(scene_sha256=scene_sha,grid_upper_bound=count,max_wall_s=600,max_rss_kib=2400000,max_records_bytes=256*1024*1024,coverage='every public source-grid start, no Solver information',Builder='unchanged EvidenceWriter and ExposurePhysics authoritative predicate',all_algorithms_share=True))
    writer=EvidenceWriter(WORK/'evidence',p.physical_context);begun=time.perf_counter();cpu=time.process_time();n=0;skipped=0
    for tid,t in sorted(p.tasks.items()):
        for w in sorted(t.windows,key=lambda w:w.window_id):
            for k in range(max(0,math.floor(((w.end_time-w.start_time).total_seconds()-t.required_duration)/w.time_step)+1)):
                a=observation_at_index(p,t,w,k)
                if a is None or not observation_source_matches(p,t,w,vars(a),a.sat_start_time,a.sat_end_time) or candidate_exposure(p,w,a.sat_start_time,a.sat_end_time,t.required_duration).status is not ExposureStatus.PLANNING_FEASIBLE:
                    skipped+=1;continue
                decision=p.physical_context.check(a,w,t.required_duration)
                writer.add(p.physical_context.candidate_identity(a,w,t.required_duration),decision);n+=1
                if time.perf_counter()-begun>600:raise TimeoutError('evidence predeclared600s limit')
        if n%500<40:print('EVIDENCE',sid,tid,n,round(time.perf_counter()-begun,2),flush=True)
    ref=writer.finish();local=Path(read(OUT.parent/'f-pilot-v24r6-web-promotion/environment.json')['EOS_PHYSICAL_EVIDENCE_DIR'])/scene_sha
    if local.exists():raise FileExistsError('do not replace evidence')
    import shutil
    mirror_start=time.perf_counter();shutil.copytree(WORK/'evidence'/scene_sha,local);files={}
    for f in local.rglob('*'):
        if f.is_file():
            authoritative=WORK/'evidence'/scene_sha/f.relative_to(local)
            assert sha(f)==sha(authoritative);files[str(f)]=sha(f);f.chmod(0o444)
    store=PhysicalCandidateEvidenceStore(local.parent,scene_sha);store.load();assert store.loaded and len(store.records)==n
    exclusive_save(OUT/(sid+'_evidence_receipt.json'),dict(status='PASS',scene_sha256=scene_sha,entries=n,source_rejected=skipped,grid_upper_bound=count,evidence=ref,build_wall_s=time.perf_counter()-begun,build_cpu_s=time.process_time()-cpu,mirror_verify_wall_s=time.perf_counter()-mirror_start,maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,files=files,physics_stats=p.physical_context.stats))
    print('EVIDENCE_COMPLETE',sid,n,round(time.perf_counter()-begun,2),flush=True)

def register(sid):
    folder=DATA/sid
    # Add exact required canonical index fields to the new, unpublished sidecar.
    for path in (folder/'provenance.json',folder/'provenance/scenario.json.provenance.json'):
        s=read(path)
        if 'scale' not in s:
            s.update(scale='S'+str(len(read(folder/'scenario.json')['satellites'])),difficulty_profile='resource_competition' if sid.startswith('R') else 'high_conflict',seed=SEED)
            save(path,s)
    plan_path=DATA/'dataset_plan_v1.json';plan=read(plan_path) if plan_path.exists() else dict(version='web-mechanism-development-v1',purpose='explicit targeted Discovery',allocation=[])
    if not any(r['scenario_id']==sid for r in plan['allocation']):
        plan['allocation'].append(dict(scenario_id=sid,relative_path=sid+'/scenario.json'));save(plan_path,plan)
    sources=http('GET','/api/data-sources')['body']['items'];source=next((s for s in sources if s['root_path']==str(DATA)),None)
    if source is None:source=http('POST','/api/data-sources',dict(name='新机制开发场景 · S10/S30/S50',path=str(DATA)))['body']
    assert source['root_path']==str(DATA)
    listing=http('GET','/api/scenarios?source_id='+source['source_id']+'&execution_mode=physical_validation')
    exclusive_save(OUT/(sid+'_web_registration.json'),dict(source=source,response=listing))
    row=next(r for r in listing['body']['items'] if r['scenario_id']==sid)
    assert row['availability']=='ready',row
    print('REGISTERED_ORIGINAL_WORKBENCH',source['source_id'],sid,row['satellite_count'],row['mission_count'],flush=True)

if __name__=='__main__':
    action=sys.argv[1]
    if action=='init':init()
    elif action=='bank':bank(int(sys.argv[2]) if len(sys.argv)>2 else 30)
    elif action=='build':build(sys.argv[2],int(sys.argv[3]) if len(sys.argv)>3 else 30,int(sys.argv[4]) if len(sys.argv)>4 else 144,sys.argv[5] if len(sys.argv)>5 else 'R')
    elif action=='evidence':prepare_evidence(sys.argv[2])
    elif action=='register':register(sys.argv[2])
    else:raise ValueError(action)
