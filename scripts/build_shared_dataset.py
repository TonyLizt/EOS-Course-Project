#!/usr/bin/env python3
"""构建全组100个独立任务来源；大型数据在运行目录，测试集独立冻结。"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import secrets
import shutil
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from utils.time_parsing import parse_orbit_epoch
from utils.continuous_exposure import PlanExposureAuditor, window_generation_record
from utils import visibility as visibility
from scripts.recompute_scenario_windows import validate_structure
from scripts.build_scenario_manifest import build_manifest

VERSION = 'shared-task-sources-v1'
SCALES = [('P10-20', 10, 20), ('P10-40', 10, 40), ('P20-40', 20, 40), ('P20-80', 20, 80)]
REGIONS = [(20,40,70,130), (35,65,-10,60), (20,60,-125,-60), (-30,10,-80,-30), (-30,-10,110,155)]
MANIFEST_FIELDS = ['artifact_id','relative_path','sha256','lineage_group_id','scale','usage',
    'task_seed','raw_satellite_sha256','generation_config_path','generation_code_sha256',
    'physics_version','window_version','validation_report_path']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    """逐文件原子发布，拒绝覆盖，方便中断后按完整侧车安全续跑。"""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): raise ValueError('refusing overwrite: ' + str(path))
    temporary = path.with_suffix(path.suffix + '.partial')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
        temporary.rename(path)
    finally:
        temporary.unlink(missing_ok=True)


def allocation():
    """先固定来源及分层划分，不按算法成绩筛选；各档dist0/dist1为13/12。"""
    result = []
    for scale_index, (scale, sats, tasks) in enumerate(SCALES):
        for slot in range(25):
            number = scale_index * 25 + slot + 1
            split = 'train_development' if slot < 15 else 'validation' if slot < 20 else 'final_test'
            seed = 2026101800 + number
            result.append(dict(artifact_id=f'EOS-G{number:04d}', scale=scale,
                satellite_count=sats, task_count=tasks, duration_s=86400,
                distribution_type=slot % 2, split=split, task_seed=seed,
                position_seed=seed * 10 + 1, priority_seed=seed * 10 + 2,
                duration_seed=seed * 10 + 3, lineage_group_id=f'eos-course-task-source-{number:04d}'))
    return result


def missions(config):
    """三个本地随机流真实控制位置、优先级和曝光长度；不筛掉零窗口任务。"""
    position = random.Random(config['position_seed'])
    priority = random.Random(config['priority_seed'])
    duration = random.Random(config['duration_seed'])
    rows = []
    for index in range(config['task_count']):
        region = (-80,80,-180,180) if config['distribution_type'] == 0 else position.choice(REGIONS)
        lat = round(position.uniform(region[0],region[1]),6)
        lon = round(position.uniform(region[2],region[3]),6)
        rows.append(dict(id=f'M{index+1:03d}', priority=float(priority.randint(1,10)),
            target_location=dict(latitude=lat,longitude=lon,altitude_km=0.),
            observation_requirement=dict(duration_s=float(duration.randint(5,15)),
                min_elevation_angle_deg=None,required_mode=None,required_resolution=None)))
    return rows


def static_satellites(count):
    """只复用已核对的静态能力，不读取或复用任何旧任务/窗口。"""
    template = ROOT / f'experiments/scenarios/small/Scenario_S1_Sats{count}_M20_T1.0d_dist1_epoch_fixed_v1.json'
    raw_path = ROOT / f'input/{count}_satellites.json'
    raw = json.loads(raw_path.read_text(encoding='utf-8'))
    satellites = json.loads(template.read_text(encoding='utf-8'))['satellites']
    if set(raw) != {s['id'] for s in satellites}: raise ValueError('raw satellite identities mismatch')
    keys = ['semi_major_axis_km','eccentricity','inclination_deg','argument_of_perigee_deg',
            'right_ascension_of_ascending_node_deg','mean_anomaly_deg','epoch']
    for sat in satellites:
        op = sat['orbital_params']
        if [op[k] for k in keys] != raw[sat['id']][1:8]: raise ValueError('raw orbit differs: '+sat['id'])
        parse_orbit_epoch(op['epoch'])
    return satellites, dict(raw_satellite_path=raw_path.relative_to(ROOT).as_posix(),
        raw_satellite_sha256=file_sha(raw_path), static_capability_template_sha256=file_sha(template),
        static_satellites_sha256=digest(satellites))


def parameters(satellite, mission):
    o=satellite['orbital_params']; l=satellite['maneuverability_capability']; t=mission['target_location']
    return dict(a_m=o['semi_major_axis_km']*1000,e=o['eccentricity'],i_deg=o['inclination_deg'],
        raan_deg=o['right_ascension_of_ascending_node_deg'],argp_deg=o['argument_of_perigee_deg'],
        m_deg=o['mean_anomaly_deg'],epoch_dt=parse_orbit_epoch(o['epoch']),
        target_lat_deg=t['latitude'],target_lon_deg=t['longitude'],target_alt_m=t['altitude_km']*1000,
        max_yaw_deg=l['max_yaw_angle_deg'],max_pitch_deg=l['max_pitch_angle_deg'],
        max_roll_deg=l['max_roll_angle_deg'],min_elevation_deg=5.)


class OrbitGrid:
    """相同固定星座/时域共享Orekit位置网格；不把近似轨道当作物理核验。"""
    def __init__(self, satellites, start, step):
        from org.orekit.propagation.analytical import KeplerianPropagator
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        self.start, self.step = start, step
        self.seconds = np.arange(0.,86400.+step,step)
        self.times = [start+timedelta(seconds=float(s)) for s in self.seconds]
        self.positions = {}; self.periods = {}
        ctx = visibility._CONTEXT
        first = datetime_to_absolutedate(start)
        dates = [first.shiftedBy(float(s)) for s in self.seconds]
        for sat in satellites:
            op = sat['orbital_params']
            orbit = visibility._build_keplerian_orbit(ctx,op['semi_major_axis_km']*1000,
                op['eccentricity'],op['inclination_deg'],op['right_ascension_of_ascending_node_deg'],
                op['argument_of_perigee_deg'],op['mean_anomaly_deg'],parse_orbit_epoch(op['epoch']))
            provider = KeplerianPropagator(orbit)
            xyz=[]
            for date in dates:
                v=provider.propagateOrbit(date).getPVCoordinates(ctx.itrf).getPosition()
                xyz.append((v.getX(),v.getY(),v.getZ()))
            self.positions[sat['id']] = np.asarray(xyz,dtype=float)
            self.periods[sat['id']] = float(orbit.getKeplerianPeriod())
        print(json.dumps({'phase':'orekit_grid_ready','satellites':len(satellites),'points_per_satellite':len(dates)}),flush=True)

    def windows(self, sat, mission):
        """全时域网格，只有明确低仰角点由向量计算排除；边界仍用原Orekit谓词二分。"""
        from org.orekit.bodies import GeodeticPoint
        ctx=visibility._CONTEXT; target=mission['target_location']
        lat,lon=math.radians(target['latitude']),math.radians(target['longitude'])
        point=ctx.earth.transform(GeodeticPoint(lat,lon,target['altitude_km']*1000))
        ground=np.array([point.getX(),point.getY(),point.getZ()])
        up=np.array([math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)])
        delta=self.positions[sat['id']]-ground
        sine=np.einsum('ij,j->i',delta,up)/np.linalg.norm(delta,axis=1)
        # 1e-9的正弦缓冲远大于普通浮点舍入；临界点交回原始Orekit检查。
        possible=np.flatnonzero(sine >= math.sin(math.radians(5.))-1e-9)
        evaluate=visibility.create_visibility_evaluator(**parameters(sat,mission))
        visible=[]
        for index in possible:
            sample=evaluate(self.times[int(index)])
            if sample.get('evaluation_error'): raise RuntimeError('Orekit attitude unavailable: '+str(sample))
            if sample['visible']: visible.append((int(index),sample))
        # 抽查明确被排除的网格点，防止预筛公式、坐标系或单位错配。
        excluded=np.flatnonzero(sine < math.sin(math.radians(5.))-1e-9)
        if len(excluded):
            for index in excluded[np.linspace(0,len(excluded)-1,min(3,len(excluded)),dtype=int)]:
                if evaluate(self.times[int(index)])['visible']: raise ValueError('elevation prefilter disagrees with Orekit')
        groups=[]
        for item in visible:
            if not groups or item[0]!=groups[-1][-1][0]+1: groups.append([])
            groups[-1].append(item)
        output=[]
        for group in groups:
            first,last=group[0][0],group[-1][0]
            if first==len(self.times)-1: continue
            if last==len(self.times)-1:
                end=self.times[last]
            else:
                end,_=visibility._refine_visibility_exit(self.times[last],self.times[last+1],evaluate)
            begin=self.times[first]
            if end<=begin: continue
            poses=[sample for _,sample in group if sample['time']<end]
            mid=poses[len(poses)//2]
            output.append(dict(start_time=begin.isoformat(),end_time=end.isoformat(),
                orbit_number=1+int((begin-self.start).total_seconds()//self.periods[sat['id']]),
                agile_data={axis+'_angles':[float(s[axis+'_deg']) for s in poses] for axis in ('yaw','pitch','roll')},
                non_agile_data={axis+'_angle':float(mid[axis+'_deg']) for axis in ('yaw','pitch','roll')}))
        return output


def sampled_check(scene, data_path):
    """每场景最多10个预先排序片段，完整曝光0.05秒含端点；不冒充连续认证。"""
    by_task={m['id']:m for m in scene['missions']}
    pieces=[(w,t) for w in scene['observation_windows'] for t in w['time_windows']]
    picked=[pieces[int(i)] for i in np.linspace(0,len(pieces)-1,min(10,len(pieces)),dtype=int)] if pieces else []
    assignments=[]; skipped=[]
    # 每片段单独核验，允许同一任务被不同片段抽查，不把它们组成一个合法调度计划。
    rows=[]; auditor=PlanExposureAuditor(scene,data_path=data_path,min_elevation_deg=5.,step_s=.05)
    for w,t in picked:
        duration=by_task[w['mission_id']]['observation_requirement']['duration_s']
        start=parse_orbit_epoch(t['start_time']);end=start+timedelta(seconds=duration)
        if end>parse_orbit_epoch(t['end_time']):
            skipped.append(dict(task_id=w['mission_id'],satellite_id=w['satellite_id'],reason='NO_FULL_EXPOSURE'));continue
        assignment=dict(task_id=w['mission_id'],satellite_id=w['satellite_id'],sensor_id=w['sensor_id'],
            sat_start_time=start.isoformat(),sat_end_time=end.isoformat())
        result=auditor.audit(dict(scenario_id=scene['scenario_id'],assignments=[assignment]))
        rows.extend(result['rows'])
    if not rows: raise ValueError('no complete exposure available for data checks')
    if any(r.get('sampled_boundaries_status')!='PASS' for r in rows):
        raise ValueError('sampled physics failed: '+json.dumps(rows,ensure_ascii=False)[:1000])
    return dict(sampled_status='PASS',continuous_certification='INCONCLUSIVE',
        continuous_reason='NO_CONTINUITY_CERTIFICATE',step_s=.05,min_elevation_deg=5.,
        segment_selection='evenly_spaced_stable_satellite_mission_window_order_max10',
        checked_segments=len(rows),skipped_segments=skipped,rows=rows)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--step-s',type=int,default=10,choices=[1,2,5,10])
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--finalize',action='store_true')
    parser.add_argument('--plan',type=Path,help='私有冻结分配表；不写入公开包')
    parser.add_argument('--only-final-test',action='store_true')
    args=parser.parse_args(argv)
    root=args.output.expanduser().resolve()
    if root.is_relative_to(ROOT): raise ValueError('large dataset must be outside repository')
    if not 1<=args.limit<=100: raise ValueError('limit must be 1..100')
    root.mkdir(parents=True,exist_ok=True)
    spec_path=root/'dataset_spec.json'
    if args.plan:
        plan=json.loads(args.plan.read_text(encoding='utf-8'))
    elif spec_path.exists():
        plan=json.loads(spec_path.read_text(encoding='utf-8'))['allocation']
    else:
        plan=allocation()
        # 私有测试的真实种子不能由公开脚本或公开训练种子推导。
        for item in plan:
            if item['split']=='final_test':
                seed=secrets.randbelow(2**31)
                item.update(task_seed=seed,position_seed=seed*10+1,priority_seed=seed*10+2,
                    duration_seed=seed*10+3,lineage_group_id='eos-course-final-'+secrets.token_hex(12))
    expected=allocation()
    if len(plan)!=100 or any(any(a[k]!=b[k] for k in ('artifact_id','scale','satellite_count','task_count','duration_s','distribution_type','split')) for a,b in zip(plan,expected)):
        raise ValueError('private plan changes required quota/scale/splits')
    if len({p['lineage_group_id'] for p in plan})!=100 or len({p['position_seed'] for p in plan})!=100:
        raise ValueError('duplicate lineage/seed in private plan')
    source_files={name:file_sha(ROOT/name) for name in [
        'scripts/build_shared_dataset.py','scripts/recompute_scenario_windows.py','scripts/build_scenario_manifest.py', *__import__('utils.certification_identity', fromlist=['SOURCE_NAMES']).SOURCE_NAMES]}
    code_sha=digest(source_files)
    spec=dict(dataset_id='eos-course-v1',generator_version=VERSION,scenario_count=100,
        public_development_count=80,train_development_count=60,validation_count=20,final_test_count=20,
        scan_step_s=args.step_s,exposure_check_step_s=.05,source_files_sha256=source_files,
        generation_code_sha256=code_sha,ensure_each_mission_has_window=False,
        shared_constellation_scope='fixed satellite inputs; independent new task collections; no cross-constellation generalization claim',
        final_test_policy='separate archive; not registered for development; algorithm/model freeze required',
        known_coverage_gaps=['no ground stations/downlink','fixed orbital epoch and constellation','continuous interval prover unavailable'],
        window_scan_limitation='finite grid can miss passes shorter than step; not a continuity proof',
        allocation=plan)
    if spec_path.exists():
        if json.loads(spec_path.read_text())!=spec: raise ValueError('existing dataset spec differs; use a new version directory')
    else: write_json(spec_path,spec)
    templates={n:static_satellites(n) for n in (10,20)}
    all_sats={s['id']:s for sats,_ in templates.values() for s in sats}
    start=parse_orbit_epoch('2025-11-18T12:00:00Z')
    with tempfile.TemporaryDirectory(prefix='eos-shared-data-') as directory:
        local=Path(directory)/'orekit-data.zip';source=ROOT/'utils/orekit-data.zip';shutil.copyfile(source,local)
        if file_sha(local)!=file_sha(source): raise ValueError('Orekit data copy SHA mismatch')
        visibility.ensure_orekit(str(local))
        remaining=[c for c in plan[:args.limit] if (not args.only_final_test or c['split']=='final_test') and not (root/('final_test' if c['split']=='final_test' else 'development')/'scenarios'/'provenance'/(c['artifact_id']+'.json.provenance.json')).exists()]
        grid=OrbitGrid(list(all_sats.values()),start,args.step_s) if remaining else None
        for config in remaining:
            began=time.monotonic(); name=config['artifact_id']; usage='final_test' if config['split']=='final_test' else 'development'
            folder=root/usage; path=folder/'scenarios'/(name+'.json')
            satellites,raw=templates[config['satellite_count']]
            generation={**config,**raw,'time_step':args.step_s,'ensure_each_mission_has_window':False,
                'priority_range':[1,10],'duration_range_s':[5,15],'regions':REGIONS if config['distribution_type'] else [[-80,80,-180,180]],
                'source_files_sha256':source_files,'generation_code_sha256':code_sha,
                'orekit_data_sha256':file_sha(source),'generator_version':VERSION,
                'parent_scenario_sha256':None,'historical_static_capabilities_only':True}
            scene=dict(scenario_id=name,metadata=dict(name=name,creation_time=start.isoformat(),duration=86400.,
                time_step=float(args.step_s),description='Fresh shared independent task source',extra=dict(
                    generator_version=VERSION,generator_seed=config['task_seed'],source_dataset='eos-course-v1',
                    source_group_id=config['lineage_group_id'],distribution_type=config['distribution_type'],
                    visibility_settings=dict(min_elevation_deg=5.,coarse_step_min=60.),
                    window_generation=window_generation_record(args.step_s,5.,60.))),
                satellites=deepcopy(satellites),missions=missions(config),ground_stations=[],observation_windows=[],communication_windows=[])
            for sat in satellites:
                for mission in scene['missions']:
                    windows=grid.windows(sat,mission)
                    if windows: scene['observation_windows'].append(dict(satellite_id=sat['id'],
                        sensor_id=sat['observation_capability']['sensors'][0]['sensor_id'],mission_id=mission['id'],time_windows=windows))
            structure=validate_structure(scene)
            physics=sampled_check(scene,local)
            if source_files!={name:file_sha(ROOT/name) for name in source_files}: raise ValueError('generation source changed during batch')
            write_json(path,scene); sha=file_sha(path)
            generation.update(scenario_sha256=sha,task_collection_sha256=digest(scene['missions']),
                generation_wall_s=round(time.monotonic()-began,3),generated_at=datetime.now(timezone.utc).isoformat())
            check=dict(artifact_id=name,sha256=sha,structure=structure,physics=physics,
                observation_segments=sum(len(w['time_windows']) for w in scene['observation_windows']),
                missions_with_windows=len({w['mission_id'] for w in scene['observation_windows']}),
                zero_window_tasks=[m['id'] for m in scene['missions'] if m['id'] not in {w['mission_id'] for w in scene['observation_windows']}],
                status='WARN',warning='sampled checks passed; continuous certification pending')
            write_json(folder/'generation_configs'/(name+'.json'),generation)
            write_json(folder/'checks'/(name+'.json'),check)
            sidecar=dict(artifact_kind='fresh_generated_shared_v1',scenario_sha256=sha,completion_status='complete',
                calculator_kind='orekit',scenario_physics_version='fresh_epoch_parsed_v1',epoch_parser_version='epoch_parser_v1',
                propagation_version='orekit-keplerian/orekit_jpype-'+importlib.metadata.version('orekit_jpype'),
                window_boundary_version='visibility_exit_refined_v3',window_generation=scene['metadata']['extra']['window_generation'],
                calculation_settings=dict(time_step=args.step_s,min_elevation_deg=5.),provenance_status='verified_generation',
                publication_status='development',formal_release_eligible=False,
                physical_validation=dict(status='SAMPLED_PASS',continuous_status='INCONCLUSIVE'),
                parent_scenario_sha256=None,lineage_group_id=config['lineage_group_id'],
                generation_config_sha256=digest(generation),generation_code_sha256=code_sha,orekit_data_sha256=file_sha(source))
            write_json(path.parent/'provenance'/(path.name+'.provenance.json'),sidecar)
            print(json.dumps(dict(phase='scenario_complete',artifact_id=name,scale=config['scale'],split=config['split'],
                segments=check['observation_segments'],covered=check['missions_with_windows'],seconds=generation['generation_wall_s'])),flush=True)
    if args.finalize:
        finalize(root,spec)


def finalize(root,spec):
    """核对全部100个来源及60/20/20隔离，再产出分开的公开包、私有测试包。"""
    plan=spec['allocation']; splits={'train_development':[],'validation':[],'final_test':[]}
    task_shas=[]
    for usage in ('development','final_test'):
        folder=root/usage; records=[]; lineage=[]; checks=[]
        for config in plan:
            if ('final_test' if config['split']=='final_test' else 'development')!=usage: continue
            name=config['artifact_id'];path=folder/'scenarios'/(name+'.json')
            provenance=path.parent/'provenance'/(path.name+'.provenance.json')
            generation=json.loads((folder/'generation_configs'/(name+'.json')).read_text())
            check=json.loads((folder/'checks'/(name+'.json')).read_text())
            side=json.loads(provenance.read_text());sha=file_sha(path)
            if sha!=generation['scenario_sha256'] or sha!=side['scenario_sha256'] or sha!=check['sha256']: raise ValueError('SHA mismatch '+name)
            if check['physics']['sampled_status']!='PASS': raise ValueError('physics check failed '+name)
            task_shas.append(generation['task_collection_sha256']);lineage.append(generation);checks.append(check)
            item=dict(artifact_id=name,scenario_sha256=sha,lineage_group_id=config['lineage_group_id'])
            splits[config['split']].append(item)
            records.append(dict(artifact_id=name,relative_path='scenarios/'+name+'.json',sha256=sha,
                lineage_group_id=config['lineage_group_id'],scale=config['scale'],usage=usage,task_seed=config['task_seed'],
                raw_satellite_sha256=generation['raw_satellite_sha256'],generation_config_path='generation_configs/'+name+'.json',
                generation_code_sha256=generation['generation_code_sha256'],physics_version='fresh_epoch_parsed_v1',
                window_version='visibility_exit_refined_v3',validation_report_path='checks/'+name+'.json'))
        manifest=folder/'delivery_manifest.csv'
        with manifest.open('x',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=MANIFEST_FIELDS);writer.writeheader();writer.writerows(records)
        write_json(folder/'lineage_manifest.json',lineage)
        write_json(folder/'checks'/'summary.json',dict(scenario_count=len(checks),results=checks,
            sampled_status='PASS',continuous_certification='INCONCLUSIVE'))
        basic=folder/'manifest_basic';report=build_manifest([folder/'scenarios'],basic)
        if any(r['status']=='FAIL' for r in report['results']): raise ValueError('basic manifest validation failed')
    if len(set(task_shas))!=100: raise ValueError('duplicate task collections')
    if [len(splits[k]) for k in ('train_development','validation','final_test')]!=[60,20,20]: raise ValueError('split counts')
    for key in ('train_development','validation'):write_json(root/'splits'/(key+'.json'),splits[key])
    freeze=dict(version='eos-course-v1-final-test-freeze',frozen_at=datetime.now(timezone.utc).isoformat(),
        records=splits['final_test'],records_sha256=digest(splits['final_test']),
        restriction='Do not use for development. All algorithms/parameters and ML model must freeze before unsealing.')
    write_json(root/'final_test'/'test_freeze.json',freeze)
    public_spec={k:v for k,v in spec.items() if k!='allocation'}
    public_spec['allocation']=[c for c in plan if c['split']!='final_test']
    write_json(root/'development'/'dataset_spec.json',public_spec)
    readme='# 全组统一数据 eos-course-v1\n\n100个独立新任务集合，固定卫星输入、时域和静态能力；不代表跨星座泛化。公开包80份（60训练/开发、20验证），私有测试包20份。每档25份：P10-20、P10-40、P20-40、P20-80，均1天，dist0/dist1为13/12。\n\n只登记development/scenarios作为日常网页数据源；final_test不登记，不用于训练、调参或界面反复测试。JSON和来源侧车须一同复制；清单及报告在相邻目录。不要递归扫描整个数据根来训练。\n\n窗口由真实Orekit完整10秒网格计算、退出边界二分至1微秒；位置网格仅作同一Orekit仰角谓词预筛，临界点回到原求值器。有限网格可能漏掉小于步长的短窗口。每场景最多10个均匀选定片段对完整曝光进行0.05秒含端点采样。采样通过不是严格连续区间证明；当前正式认证阻断单独记录，不伪造PASS。\n\n零窗口任务保留，无地面站和下传覆盖。训练/验证/测试按完整任务来源隔离；星座输入共享关系在谱系中明确。最终测试须由数据负责人保管，算法、参数和模型冻结后统一执行。\n'
    (root/'README.md').write_text(readme,encoding='utf-8')
    archives=[]
    for usage in ('development','final_test'):
        target=root.parent/(root.name+'-'+usage+'.zip')
        if target.exists(): raise ValueError('archive exists: '+str(target))
        with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in sorted((root/usage).rglob('*')):
                if path.is_file(): archive.write(path,arcname=(Path('eos-course-v1')/path.relative_to(root)).as_posix())
            archive.write(root/'README.md',arcname='eos-course-v1/README.md')
            if usage=='development':
                for path in sorted((root/'splits').glob('*.json')):archive.write(path,arcname=(Path('eos-course-v1')/path.relative_to(root)).as_posix())
            else:archive.write(root/'dataset_spec.json',arcname='eos-course-v1/dataset_spec.private.json')
        archives.append(dict(filename=target.name,bytes=target.stat().st_size,sha256=file_sha(target)))
    write_json(root.parent/(root.name+'-archives.json'),archives)
    print(json.dumps({'phase':'dataset_finalized','archives':archives}),flush=True)


if __name__=='__main__':main()
