#!/usr/bin/env python3
"""从头生成新轨道家族和高冲突目标走廊；家族分组先冻结，禁用验证/测试裁剪。"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib,json,math,random,secrets,shutil,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_shared_dataset import OrbitGrid,digest,file_sha,write_json,sampled_check,parameters
from scripts.recompute_scenario_windows import validate_structure
from utils import visibility
from utils.time_parsing import parse_orbit_epoch
from utils.continuous_exposure import window_generation_record

VERSION='independent-conflict-families-v1'
PROFILES=[
 dict(name='paired_corridors',satellites=4,tasks=64,horizon_s=7200,duration_min=12,duration_max=60,along_s=150,cross_deg=1.4),
 dict(name='short_exposures',satellites=6,tasks=96,horizon_s=10800,duration_min=5,duration_max=35,along_s=110,cross_deg=1.1),
 dict(name='long_exposures',satellites=4,tasks=64,horizon_s=10800,duration_min=25,duration_max=90,along_s=200,cross_deg=1.8),
 dict(name='mixed_load',satellites=8,tasks=112,horizon_s=14400,duration_min=8,duration_max=70,along_s=180,cross_deg=1.6)]

def protected_groups(base,freeze_path):
    """只读取冻结索引的身份字段，不打开测试场景、任务或私有生成种子。"""
    public=[]
    for key in ('train_development','validation'):
        public+=json.loads((Path(base)/'splits'/(key+'.json')).read_text())
    raw=Path(freeze_path).read_bytes();record=json.loads(raw)
    test=record['records']
    if len(test)!=20 or any(not all(k in r for k in ('artifact_id','lineage_group_id','scenario_sha256')) for r in test):
        raise ValueError('PROTECTED_FREEZE_INDEX_INVALID')
    groups={r['lineage_group_id'] for r in public+test}
    return groups,{'public_source_count':len(public),'protected_test_source_count':len(test),
        'protected_freeze_index_sha256':hashlib.sha256(raw).hexdigest(),
        'protected_scene_content_read':False,'protected_targets_or_labels_used':False}

def family_plan(count=48,seed=202610190071):
    """种子命名空间远离原数据seed范围；每个新轨道家族两个变体同组。"""
    rng=random.Random(seed);result=[]
    for index in range(count):
        number=index+1;profile=deepcopy(PROFILES[index%4])
        source_seed=(1<<63)+rng.getrandbits(62)
        group='lavis-hc-family-'+hashlib.sha256(str(source_seed).encode()).hexdigest()[:20]
        # 每profile前8家族训练、后4家族验证，48家族为32/16；在生成前固定。
        slot=index//4;split='train_development' if slot < (count//4)*2//3 else 'validation'
        start=datetime(2025,12,1,tzinfo=timezone.utc)+timedelta(days=index%24,hours=(index*5)%20)
        result.append(dict(family_number=number,lineage_group_id=group,seed=source_seed,
                           split=split,start_utc=start.isoformat(),profile=profile))
    return result

def satellites(config,attempts=None):
    """独立随机六根数；不读取上游/既有场景的卫星轨道、窗口或目标。"""
    out=[];attempts=attempts or {}
    for pair in range(config['profile']['satellites']//2):
        rng=random.Random(config['seed']+pair*1000003+attempts.get(pair,0)*1000000007)
        semi=rng.uniform(6878.,7278.);inc=rng.choice([53.,70.,97.5])+rng.uniform(-2.,2.)
        raan=rng.uniform(0,360);mean=rng.uniform(0,360);arg=rng.uniform(0,360)
        for member in range(2):
            sid=f'HC{config["family_number"]:03d}-S{pair*2+member+1:02d}'
            out.append(dict(id=sid,orbital_type='LEO',orbital_params=dict(semi_major_axis_km=semi,
                eccentricity=rng.uniform(.0001,.0015),inclination_deg=inc+member*rng.uniform(.15,.8),
                right_ascension_of_ascending_node_deg=(raan+member*rng.uniform(.8,2.5))%360,
                argument_of_perigee_deg=arg,mean_anomaly_deg=(mean+member*rng.uniform(.4,1.8))%360,
                epoch=config['start_utc']),
                maneuverability_capability=dict(maneuverability_type='agile',max_pitch_angle_deg=45.,
                    max_roll_angle_deg=45.,max_yaw_angle_deg=45.,slew_rate_deg_per_s=1.,stabilization_time_s=10.),
                observation_capability={'sensors':[dict(sensor_id=sid+'-camera',sensor_mode='visible',resolution='medium',
                    data_rate_Mbps=.1,power_consumption_W=50.,field_of_view_deg=45.,min_elevation_angle_deg=5.)]},
                satellite_specs=dict(max_power_W=500.,max_data_storage_GB=1000.,max_battery_capacity_Wh=2000.)))
    return out


def physical_anchors(config,grid,sat):
    """按固定网格找满足原姿态约束的星下点；仅用物理条件，不查询算法成绩。"""
    start=parse_orbit_epoch(config['start_utc']);duration=config['profile']['horizon_s'];candidates=[]
    for second in range(300,duration-299,300):
        xyz=grid.positions[sat['id']][second//5]
        latitude=math.degrees(math.atan2(float(xyz[2]),math.hypot(float(xyz[0]),float(xyz[1]))))
        longitude=math.degrees(math.atan2(float(xyz[1]),float(xyz[0])))
        mission={'target_location':dict(latitude=latitude,longitude=longitude,altitude_km=0.)}
        value=visibility.create_visibility_evaluator(**parameters(sat,mission))(start+timedelta(seconds=second))
        if value['visible']:
            margin=min(45.-abs(value[key+'_deg']) for key in ('yaw','pitch','roll'))
            candidates.append((margin,second))
    return sorted(candidates,reverse=True)

def family_geometry(config):
    """每对卫星独立提案直到有物理合法锚点；记录实际提案编号，不扩张能力。"""
    attempts={};chosen=[];combined=None;anchors={};start=parse_orbit_epoch(config['start_utc'])
    for pair in range(config['profile']['satellites']//2):
        for attempt in range(64):
            attempts[pair]=attempt
            sats=satellites(config,attempts)[pair*2:pair*2+2]
            grid=OrbitGrid(sats,start,5,duration_s=config['profile']['horizon_s'])
            valid=physical_anchors(config,grid,sats[0])
            if valid:
                anchors[pair]=valid[0][1];chosen.extend(sats)
                if combined is None:combined=grid
                else:combined.positions.update(grid.positions);combined.periods.update(grid.periods)
                break
        else:raise ValueError('NO_PHYSICAL_CORRIDOR_WITHIN_PROPOSAL_LIMIT')
    return chosen,combined,dict(pair_proposal_attempts={str(k):v for k,v in attempts.items()},
        pair_anchor_seconds={str(k):v for k,v in anchors.items()},
        selection='max stored-axis margin among 300s own-orbit ground-point probes; physical only')


def mission_set(config,variant,grid,sats):
    """目标沿自身轨道的独立走廊展开，保留不同卫星的替代机会与独占边缘。"""
    rng=random.Random(config['seed']+1000+variant);profile=config['profile'];result=[]
    pair_count=len(sats)//2
    for index in range(profile['tasks']+(variant-1)*16):
        pair=index%pair_count;sid=sats[pair*2]['id']
        center=config['physical_selection']['pair_anchor_seconds'][str(pair)]
        seconds=max(60.,min(profile['horizon_s']-60.,center+rng.uniform(-profile['along_s'],profile['along_s'])))
        xyz=grid.positions[sid][round(seconds/grid.step)]
        lon=math.degrees(math.atan2(float(xyz[1]),float(xyz[0])))
        lat=math.degrees(math.atan2(float(xyz[2]),math.hypot(float(xyz[0]),float(xyz[1]))))
        lat=max(-84.,min(84.,lat+rng.uniform(-profile['cross_deg'],profile['cross_deg'])))
        lon=((lon+rng.uniform(-profile['cross_deg'],profile['cross_deg'])+180)%360)-180
        # 混合负载中少量背景目标按预定比例生成，不因没有窗口而删除。
        if profile['name']=='mixed_load' and index%10==0:lat,lon=rng.uniform(-70,70),rng.uniform(-180,180)
        result.append(dict(id=f'M{index+1:03d}',priority=float(rng.randint(1,10)),
            target_location=dict(latitude=round(lat,6),longitude=round(lon,6),altitude_km=0.),
            observation_requirement=dict(duration_s=float(rng.randint(profile['duration_min'],profile['duration_max'])),
                min_elevation_angle_deg=None,required_mode=None,required_resolution=None)))
    return result

def conflict_stats(path):
    from schedulers.scenario_loader import load_scheduling_problem_from_json
    from schedulers.constraint_model import ConstraintModel
    from algorithms.lavis.candidates import build_pool
    from algorithms.lavis.protocol import Control
    problem=load_scheduling_problem_from_json(path);problem.execution_mode='physical_validation'
    constraints=ConstraintModel(problem,agility_profile='Standard-Agility',non_agile_transition_s=10.)
    pool,stats=build_pool(problem,constraints,Control());by_sat=defaultdict(list);by_task=defaultdict(set)
    for a in pool:by_sat[a.satellite_id].append(a);by_task[a.task_id].add(a.satellite_id)
    overlaps=pairs=0
    for rows in by_sat.values():
        for i,a in enumerate(rows):
            for b in rows[i+1:]:
                if a.task_id==b.task_id:continue
                pairs+=1
                if a.sat_start_time<b.sat_end_time and b.sat_start_time<a.sat_end_time:overlaps+=1
    return dict(pool=stats,executable_tasks=len(by_task),total_tasks=len(problem.tasks),
                candidate_overlap_fraction=overlaps/max(1,pairs),same_satellite_candidate_pairs=pairs,
                conflicting_candidate_pairs=overlaps,exclusive_task_fraction=sum(len(v)==1 for v in by_task.values())/max(1,len(by_task)),
                multi_satellite_tasks=sum(len(v)>1 for v in by_task.values()))

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--base-dataset',type=Path,required=True)
    parser.add_argument('--freeze-index',type=Path,required=True)
    parser.add_argument('--families',type=int,default=48,choices=[12,24,48])
    parser.add_argument('--limit-families',type=int);parser.add_argument('--finalize',action='store_true')
    args=parser.parse_args(argv);root=args.output.resolve();base=args.base_dataset.resolve()
    if root.is_relative_to(ROOT) or root.is_relative_to(base) or base.is_relative_to(root):raise ValueError('OUTPUT_MUST_BE_SEPARATE')
    blocked,protection=protected_groups(base,args.freeze_index)
    plan=family_plan(args.families)
    if any(c['lineage_group_id'] in blocked for c in plan):raise ValueError('PROTECTED_LINEAGE_COLLISION')
    if len({c['seed'] for c in plan})!=len(plan):raise ValueError('DUPLICATE_NEW_FAMILY_SEED')
    root.mkdir(parents=True,exist_ok=True)
    files=['scripts/build_conflict_dataset.py','scripts/build_shared_dataset.py']
    from utils.certification_identity import SOURCE_NAMES
    files+=list(SOURCE_NAMES)
    snapshots={name:file_sha(ROOT/name) for name in files}
    spec=dict(dataset_id='lavis-conflict-v1',generator=VERSION,scan_step_s=5,exposure_check_step_s=.05,
        source_isolation='independent synthetic orbital elements, new epochs, new task targets; grouped siblings',
        no_parent_scenario=True,protection=protection,family_count=len(plan),scenario_count=2*len(plan),families=plan,
        source_files_sha256=snapshots,continuous_certification='NOT_CERTIFIED',
        limitations=['finite 5s window grid may miss shorter passes','finite 0.05s exposure samples are not continuous proof',
                    'synthetic target corridors, no claim of operational mission distribution'])
    spec_path=root/'dataset_spec.json'
    if spec_path.exists():
        if json.loads(spec_path.read_text())!=spec:raise ValueError('GENERATION_PROTOCOL_CHANGED_USE_NEW_DATASET')
    else:write_json(spec_path,spec)
    source=root/'generation_source'
    for name,sha in snapshots.items():
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copyfile(ROOT/name,target)
        if file_sha(target)!=sha:raise ValueError('SOURCE_SNAPSHOT_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='eos-conflict-data-') as directory:
        local=Path(directory)/'orekit-data.zip';original=ROOT/'utils/orekit-data.zip';shutil.copyfile(original,local)
        if file_sha(local)!=file_sha(original):raise ValueError('OREKIT_COPY_MISMATCH')
        visibility.ensure_orekit(str(local))
        for family in plan[:args.limit_families]:
            start=parse_orbit_epoch(family['start_utc']);profile=family['profile']
            names=[f'HC-F{family["family_number"]:03d}-V{v}' for v in (1,2)]
            if all((root/'development/scenarios/provenance'/(name+'.json.provenance.json')).exists() for name in names):continue
            sat,grid,selection=family_geometry(family)
            actual_family=family|{'physical_selection':selection}
            for variant,name in enumerate(names,1):
                path=root/'development/scenarios'/(name+'.json');sidepath=path.parent/'provenance'/(path.name+'.provenance.json')
                if sidepath.exists():continue
                began=time.monotonic();tasks=mission_set(actual_family,variant,grid,sat)
                scene=dict(scenario_id=name,metadata=dict(name=name,creation_time=start.isoformat(),duration=float(profile['horizon_s']),
                    time_step=5.,description='Fresh synthetic high-conflict corridor source',extra=dict(
                    source_dataset='lavis-conflict-v1',source_group_id=family['lineage_group_id'],
                    family_id=family['lineage_group_id'],variant=variant,
                    visibility_settings=dict(min_elevation_deg=5.,coarse_step_min=60.),window_generation=window_generation_record(5,5.,60.))),
                    satellites=deepcopy(sat),missions=tasks,ground_stations=[],observation_windows=[],communication_windows=[])
                for satellite in sat:
                    for mission in tasks:
                        windows=grid.windows(satellite,mission)
                        if windows:scene['observation_windows'].append(dict(satellite_id=satellite['id'],
                            sensor_id=satellite['observation_capability']['sensors'][0]['sensor_id'],mission_id=mission['id'],time_windows=windows))
                structure=validate_structure(scene);physics=sampled_check(scene,local)
                if snapshots!={n:file_sha(ROOT/n) for n in files}:raise ValueError('SOURCE_CHANGED_DURING_GENERATION')
                write_json(path,scene);sha=file_sha(path)
                generation=dict(actual_family,variant=variant,artifact_id=name,scenario_sha256=sha,
                    task_collection_sha256=digest(tasks),orbital_family_sha256=digest([s['orbital_params'] for s in sat]),
                    orbital_parent_scenario=None,task_parent_scenario=None,
                    origin='new synthetic orbital elements and own-orbit target corridors',source_files_sha256=snapshots,
                    generation_code_sha256=digest(snapshots),orekit_data_sha256=file_sha(original))
                write_json(root/'development/generation_configs'/(name+'.json'),generation)
                sidecar=dict(artifact_kind='fresh_generated_shared_v1',scenario_sha256=sha,completion_status='complete',calculator_kind='orekit',
                    scenario_physics_version='fresh_epoch_parsed_v1',epoch_parser_version='epoch_parser_v1',propagation_version='orekit-keplerian',
                    window_boundary_version='visibility_exit_refined_v3',window_generation=scene['metadata']['extra']['window_generation'],
                    calculation_settings=dict(time_step=5,min_elevation_deg=5.),provenance_status='verified_generation',
                    publication_status='development',formal_release_eligible=False,
                    physical_validation=dict(status='SAMPLED_PASS',continuous_status='INCONCLUSIVE'),parent_scenario_sha256=None,
                    lineage_group_id=family['lineage_group_id'],generation_config_sha256=digest(generation),
                    generation_code_sha256=digest(snapshots),orekit_data_sha256=file_sha(original))
                write_json(sidepath,sidecar)
                check=dict(artifact_id=name,scenario_sha256=sha,physics=physics,structure=structure,conflict=conflict_stats(path),
                           seconds=time.monotonic()-began)
                write_json(root/'development/checks'/(name+'.json'),check)
                print(json.dumps(dict(phase='conflict_scene_complete',artifact_id=name,split=family['split'],
                    executable=check['conflict']['executable_tasks'],tasks=len(tasks),
                    overlap=round(check['conflict']['candidate_overlap_fraction'],3),
                    multi_satellite=check['conflict']['multi_satellite_tasks'],seconds=round(check['seconds'],2))),flush=True)
    if args.finalize:finalize(root,spec)

def finalize(root,spec):
    splits={'train_development':[],'validation':[]};all_orbits={};all_tasks=set();groups=defaultdict(set)
    for family in spec['families']:
        for variant in (1,2):
            name=f'HC-F{family["family_number"]:03d}-V{variant}';path=root/'development/scenarios'/(name+'.json')
            generation=json.loads((root/'development/generation_configs'/(name+'.json')).read_text())
            check=json.loads((root/'development/checks'/(name+'.json')).read_text())
            if file_sha(path)!=generation['scenario_sha256'] or generation['scenario_sha256']!=check['scenario_sha256']:raise ValueError('SCENARIO_CHANGED')
            group=family['lineage_group_id'];groups[group].add(family['split'])
            orbit=generation['orbital_family_sha256']
            if orbit in all_orbits and all_orbits[orbit]!=group:raise ValueError('ORBIT_FAMILY_CROSSED_GROUPS')
            all_orbits[orbit]=group
            if generation['task_collection_sha256'] in all_tasks:raise ValueError('DUPLICATE_TASK_COLLECTION')
            all_tasks.add(generation['task_collection_sha256'])
            splits[family['split']].append(dict(artifact_id=name,scenario_sha256=generation['scenario_sha256'],
                lineage_group_id=group,data_origin='lavis-conflict-v1',orbital_family_sha256=orbit))
    if any(len(v)!=1 for v in groups.values()):raise ValueError('FAMILY_SPLIT_LEAKAGE')
    for key,rows in splits.items():write_json(root/'splits'/(key+'.json'),rows)
    write_json(root/'isolation_report.json',dict(family_count=len(groups),all_family_siblings_same_split=True,
        orbital_families=len(all_orbits),distinct_task_collections=len(all_tasks),protected_groups_disjoint=True,
        protection=spec['protection'],splits={key:len(value) for key,value in splits.items()},
        labels_or_model_scores_used_for_allocation=False,final_test_content_used=False))
    print(json.dumps({'phase':'conflict_dataset_finalized','splits':{k:len(v) for k,v in splits.items()}}),flush=True)

if __name__=='__main__':main()
