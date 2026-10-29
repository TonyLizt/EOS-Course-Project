"""构建冻结课程测试包：15测试家族×4负载＋3联调家族×2负载。

不运行比较算法，不读取旧测试任务，不按成绩筛选。实际执行已审查的旧姿态
窗口代码，并由当前独立审查器按相同合同采样核验；不伪填旧源码哈希。
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import secrets
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import build_shared_dataset as shared
from scripts.characterize_scenarios import characterize
from scripts.recompute_scenario_windows import validate_structure
from utils.course_compatibility import LEGACY_ATTITUDE, LEGACY_WINDOW_SOURCES
from utils.time_parsing import parse_orbit_epoch

VERSION='eos-final-course-v1'
SCALES={'small':(10,20),'medium':(20,80),'large':(50,200)}
PROFILES=['low_conflict','mixed','high_conflict','resource_overload']
HORIZON=1800

def digest(value):
    return hashlib.sha256((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()

def legacy_module(root):
    """保存实际使用的Git源文件，严格匹配已审查的物理源身份。"""
    source=root/'generator_sources/visibility_50660f3.py'
    if not source.exists():
        raw=subprocess.check_output(['git','show','50660f3:utils/visibility.py'],cwd=ROOT)
        source.parent.mkdir(parents=True,exist_ok=True);source.write_bytes(raw)
    physics={'utils/visibility.py':hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        'utils/time_parsing.py':hashlib.sha256((ROOT/'utils/time_parsing.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest()}
    if physics!=LEGACY_WINDOW_SOURCES:raise ValueError('实际执行的旧物理源码不符合已审查身份')
    spec=importlib.util.spec_from_file_location('utils._final_legacy_visibility',source)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    # 只改变此离线生成进程里的helper引用；主平台源码和运行实例完全不变。
    shared.visibility=module
    record=dict(window_algorithm_version=module.VISIBILITY_ALGORITHM_VERSION,
        boundary_refinement_version='visible_side_bisection_v1',exit_precision_us=1,
        endpoint_semantics='visible_side_exit_or_evaluated_horizon',entry_semantics='first_visible_grid_sample',
        precision_scope='detected_exit_brackets_only',horizon_semantics='evaluated_endpoint_not_interval_proof',
        scan_step_s=5,min_elevation_deg=5.,coarse_step_min=60.,interval_semantics='half_open',
        continuous_certification={'status':'NOT_RUN'},physics_provenance_schema='orekit-window-physics-lf-v1',
        physics_sources_sha256_lf=physics)
    return module,record

def plan(root):
    path=root/'dataset_plan.json'
    if path.exists():return json.loads(path.read_text())
    families=[];allocation=[]
    for scale,(satellites,tasks) in SCALES.items():
        for split,count in [('smoke',1),('final_test',5)]:
            for number in range(1,count+1):
                seed=secrets.randbits(96)
                group='eos-final-'+hashlib.sha256(str(seed).encode()).hexdigest()[:24]
                family=dict(scale=scale,satellite_count=satellites,task_count=tasks,split=split,
                    family_number=number,lineage_group_id=group,seed=seed,
                    start_utc=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=len(families),hours=number)).isoformat())
                families.append(family)
                for profile in (['mixed','high_conflict'] if split=='smoke' else PROFILES):
                    sid=f'FINAL-{scale.upper()}-{split.upper()}-F{number:02d}-{profile}'
                    allocation.append(dict(family,scenario_id=sid,difficulty_profile=profile,
                        relative_path=f'{split}/{scale}/{sid}/scenario.json'))
    result=dict(dataset_id=VERSION,generator_version=VERSION,independent_test_families=15,
        smoke_families=3,scenario_count=66,allocation=allocation,families=families,
        policy='freeze before results; group variants are correlated; no training or model selection on final_test')
    shared.write_json(path,result)
    return result

def make_pair(family,pair,attempt):
    """新合成六根数，近邻卫星的轨道仍各不相同；不读取旧任务、轨道或窗口。"""
    rng=random.Random(family['seed']+pair*1000003+attempt*1000000007)
    semi=rng.uniform(6878,7278);inc=rng.choice([53.,70.,97.5])+rng.uniform(-2,2)
    raan=rng.uniform(0,360);mean=rng.uniform(0,360);arg=rng.uniform(0,360)
    out=[]
    for member in range(2):
        sid=f'FS{pair*2+member+1:03d}'
        out.append(dict(id=sid,orbital_type='LEO',orbital_params=dict(semi_major_axis_km=semi,
            eccentricity=rng.uniform(.0001,.0015),inclination_deg=inc+member*rng.uniform(.15,.8),
            right_ascension_of_ascending_node_deg=(raan+member*rng.uniform(.8,2.5))%360,
            argument_of_perigee_deg=arg,mean_anomaly_deg=(mean+member*rng.uniform(.4,1.8))%360,epoch=family['start_utc']),
            maneuverability_capability=dict(maneuverability_type='agile',max_pitch_angle_deg=45.,
                max_roll_angle_deg=45.,max_yaw_angle_deg=45.,slew_rate_deg_per_s=1.,stabilization_time_s=10.),
            observation_capability={'sensors':[dict(sensor_id=sid+'-camera',sensor_mode='visible',resolution='medium',
                data_rate_Mbps=.1,power_consumption_W=50.,field_of_view_deg=45.,min_elevation_angle_deg=5.)]},
            satellite_specs=dict(max_power_W=100000.,max_data_storage_GB=1.,max_battery_capacity_Wh=2000.)))
    return out

def target(grid,sid,second,ctx):
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    point=ctx.earth.transform(Vector3D(*map(float,grid.positions[sid][second//5])),ctx.itrf,None)
    return dict(latitude=math.degrees(point.getLatitude()),longitude=math.degrees(point.getLongitude()),altitude_km=0.)

def family_geometry(family,module):
    sats=[];combined=None;anchors={};attempts={};start=parse_orbit_epoch(family['start_utc'])
    for pair in range(family['satellite_count']//2):
        for attempt in range(256):
            proposal=make_pair(family,pair,attempt)
            grid=shared.OrbitGrid(proposal,start,5,HORIZON)
            legal=[]
            for second in range(180,1621,120):
                mission={'target_location':target(grid,proposal[0]['id'],second,module._CONTEXT)}
                value=module.create_visibility_evaluator(**shared.parameters(proposal[0],mission))(start+timedelta(seconds=second))
                if value['visible'] and max(abs(value[a+'_deg']) for a in ('yaw','pitch','roll'))<40:
                    legal.append(second)
            if legal:
                if combined is None:combined=grid
                else:
                    combined.positions.update(grid.positions);combined.periods.update(grid.periods)
                sats.extend(proposal);anchors[str(pair)]=legal;attempts[str(pair)]=attempt
                break
        else:raise ValueError('NO_LEGAL_PHYSICAL_ANCHOR_WITHIN_256_PROPOSALS')
    return sats,combined,dict(anchors=anchors,proposal_attempts=attempts,
        selection='fixed own-orbit WGS84 anchors with >5deg stored-axis margin; physical preconditions only')

def tasks(config,sats,grid,geometry,module):
    # 同家族共用优先级；资源过载与高冲突共用位置，专门观察资源约束的作用。
    profile=config['difficulty_profile'];positions=random.Random(config['seed']+(10 if profile=='low_conflict' else 20 if profile=='mixed' else 30))
    attributes=random.Random(config['seed']+99);out=[];pairs=len(sats)//2
    for i in range(config['task_count']):
        if profile=='low_conflict':pair=i%pairs
        elif profile=='mixed':pair=i%pairs if i%2==0 else i%min(2,pairs)
        else:pair=i%min(2,pairs)
        anchors=geometry['anchors'][str(pair)]
        second=positions.choice(anchors) if profile=='low_conflict' else anchors[len(anchors)//2]
        loc=target(grid,sats[pair*2]['id'],second,module._CONTEXT)
        jitter=.05 if profile=='low_conflict' else .015
        loc['latitude']=round(max(-89.,min(89.,loc['latitude']+positions.uniform(-jitter,jitter))),7)
        loc['longitude']=round((loc['longitude']+positions.uniform(-jitter,jitter)+180)%360-180,7)
        priority=attributes.randint(1,10);duration=attributes.randint(5,15)
        if profile=='resource_overload':duration+=15
        out.append(dict(id=f'M{i+1:03d}',priority=float(priority),target_location=loc,
            observation_requirement=dict(duration_s=float(duration),min_elevation_angle_deg=None,required_mode=None,required_resolution=None)))
    return out

def audit(scene,data):
    """当前独立审查器按旧课程合同检查稳定抽取的完整曝光，不复用生成判定。"""
    from utils.continuous_exposure import PlanExposureAuditor
    auditor=PlanExposureAuditor(scene,data_path=data,min_elevation_deg=5.,step_s=.05,attitude_contract=LEGACY_ATTITUDE)
    taskmap={m['id']:m for m in scene['missions']};pieces=[]
    for row in scene['observation_windows']:
        for w in row['time_windows']:
            start=parse_orbit_epoch(w['start_time']);end=start+timedelta(seconds=taskmap[row['mission_id']]['observation_requirement']['duration_s'])
            if end<=parse_orbit_epoch(w['end_time']):pieces.append((row,start,end))
    if not pieces:raise ValueError('NO_COMPLETE_EXPOSURES')
    picked=sorted({i*(len(pieces)-1)//min(9,len(pieces)-1) for i in range(min(10,len(pieces)))}) if len(pieces)>1 else [0]
    rows=[]
    for index in picked:
        row,start,end=pieces[index]
        result=auditor.audit({'scenario_id':scene['scenario_id'],'assignments':[dict(task_id=row['mission_id'],
            satellite_id=row['satellite_id'],sensor_id=row['sensor_id'],sat_start_time=start.isoformat(),sat_end_time=end.isoformat())]})
        rows.extend(result['rows'])
    if any(r.get('sampled_boundaries_status')!='PASS' for r in rows):raise ValueError('PHYSICAL_SAMPLE_REJECTED:'+json.dumps(rows)[:1000])
    return dict(status='SAMPLED_PASS',continuous_status='INCONCLUSIVE',step_s=.05,checked_segments=len(rows),rows=rows)

def build(root,spec,module,record,split,limit):
    data=ROOT/'utils/orekit-data.zip';module.ensure_orekit(str(data))
    source_sha=shared.file_sha(Path(__file__))
    selected=[f for f in spec['families'] if split=='all' or f['split']==split]
    if limit:selected=selected[:limit]
    for family in selected:
        configs=[r for r in spec['allocation'] if r['lineage_group_id']==family['lineage_group_id']]
        if all((root/Path(c['relative_path']).parent/'provenance.json').exists() for c in configs):continue
        began=time.monotonic();sats,grid,selection=family_geometry(family,module);cache={}
        for config in configs:
            folder=root/Path(config['relative_path']).parent
            if (folder/'provenance.json').exists():
                prior=json.loads((folder/'provenance.json').read_text())
                if shared.file_sha(folder/'scenario.json')!=prior['scenario_sha256']:raise ValueError('已完成场景哈希改变')
                continue
            if folder.exists():raise ValueError('发现不完整场景，保留现场并停止：'+str(folder))
            local_sats=deepcopy(sats)
            if config['difficulty_profile']=='resource_overload':
                for sat in local_sats:sat['satellite_specs']['max_data_storage_GB']=.0015
            missions=tasks(config,sats,grid,selection,module)
            scene=dict(scenario_id=config['scenario_id'],metadata=dict(name=config['scenario_id'],creation_time=family['start_utc'],
                duration=float(HORIZON),time_step=5.,description='Frozen synthetic course workload; final_test is not for tuning',
                extra=dict(source_dataset=VERSION,source_group_id=family['lineage_group_id'],generator_version=VERSION,
                    generator_seed=family['seed'],window_generation=record,visibility_settings=dict(min_elevation_deg=5.,coarse_step_min=60.))),
                satellites=local_sats,missions=missions,ground_stations=[],observation_windows=[],communication_windows=[])
            for sat in sats:
                for mission in missions:
                    key=(sat['id'],digest(mission['target_location']))
                    if key not in cache:cache[key]=grid.windows(sat,mission)
                    windows=cache[key]
                    if windows:scene['observation_windows'].append(dict(satellite_id=sat['id'],mission_id=mission['id'],
                        sensor_id=sat['observation_capability']['sensors'][0]['sensor_id'],time_windows=windows))
            structure=validate_structure(scene);physics=audit(scene,data);stats=characterize(scene)
            folder.mkdir(parents=True)
            shared.write_json(folder/'scenario.json',scene);sha=shared.file_sha(folder/'scenario.json')
            provenance=dict(config,artifact_kind='fresh_generated_shared_v1',scenario_sha256=sha,completion_status='complete',
                calculator_kind='orekit',scenario_physics_version='fresh_epoch_parsed_v1',epoch_parser_version='epoch_parser_v1',
                propagation_version='orekit-keplerian',window_boundary_version='visibility_exit_refined_v3',window_generation=record,
                calculation_settings=dict(time_step=5,min_elevation_deg=5.),provenance_status='verified_generation',
                publication_status='development',formal_release_eligible=False,
                physical_validation=dict(status='SAMPLED_PASS',continuous_status='INCONCLUSIVE'),parent_scenario_sha256=None,
                generation_code_sha256=source_sha,orekit_data_sha256=shared.file_sha(data),
                task_collection_sha256=digest(missions),orbital_family_sha256=digest([s['orbital_params'] for s in sats]),
                physical_selection=selection,synthetic=True,usage_split=family['split'],
                publication_note='development denotes engineering-sampled provenance contract, not training permission',
                generated_at=datetime.now(timezone.utc).isoformat())
            shared.write_json(folder/'validation.json',dict(status='SAMPLED_PASS',structure=structure,physics=physics,
                scenario_sha256=sha,algorithm_results_not_examined=True))
            shared.write_json(folder/'characterization.json',stats)
            shared.write_json(folder/'provenance/scenario.json.provenance.json',provenance)
            shared.write_json(folder/'provenance.json',provenance)
            from eos_system.provenance import capture_provenance
            captured=capture_provenance(folder/'scenario.json',sha)
            if captured['attitude_model_version']!=LEGACY_ATTITUDE:raise ValueError('来源接入使用了不同姿态合同')
            print(json.dumps(dict(phase='scene_complete',scenario=config['scenario_id'],seconds=round(time.monotonic()-began,2),
                covered=round(1-stats['zero_opportunity_fraction'],3),overlap=round(stats['window_overlap_fraction'],3),
                storage_pressure=round(stats['max_demand_storage_ratio'],3))),flush=True)
            if source_sha!=shared.file_sha(Path(__file__)):raise ValueError('生成过程中源码改变')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--split',choices=['smoke','final_test','all'],default='smoke')
    p.add_argument('--limit-families',type=int);p.add_argument('--plan-only',action='store_true')
    args=p.parse_args();root=args.output.expanduser().resolve()
    if root.is_relative_to(ROOT):raise ValueError('数据必须放在仓库外')
    root.mkdir(parents=True,exist_ok=True);spec=plan(root)
    if args.plan_only:return
    module,record=legacy_module(root)
    build(root,spec,module,record,args.split,args.limit_families)

if __name__=='__main__':main()
