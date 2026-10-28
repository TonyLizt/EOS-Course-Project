"""冻结/校验最终场景包；校验模式仅使用Python标准库，可供组员解压后执行。"""
import argparse
from collections import Counter,defaultdict
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import zipfile

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('禁止覆盖发布文件 '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def verify(root):
    manifest=json.loads((root/'SHA256SUMS.json').read_text(encoding='utf-8'))
    for name,digest in manifest.items():
        path=root/name
        if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError('非法路径 '+name)
        if not path.is_file() or sha(path)!=digest:raise ValueError('文件缺失或哈希不匹配 '+name)
    print(json.dumps({'verified_files':len(manifest),'status':'PASS'}))

def finalize(root,output,protected,source_snapshot=None):
    if (root/'SHA256SUMS.json').exists():raise ValueError('该包已冻结；用verify检查，不重写')
    spec=json.loads((root/'dataset_plan.json').read_text());rows=[];stats_by=defaultdict(list);groups=defaultdict(set)
    assert len(spec['allocation'])==66
    for item in spec['allocation']:
        folder=(root/item['relative_path']).parent
        prov=json.loads((folder/'provenance.json').read_text());stats=json.loads((folder/'characterization.json').read_text())
        valid=json.loads((folder/'validation.json').read_text());scene_sha=sha(folder/'scenario.json')
        assert scene_sha==prov['scenario_sha256']==valid['scenario_sha256']
        assert valid['status']=='SAMPLED_PASS' and valid['physics']['checked_segments']>0
        assert stats['zero_opportunity_fraction']==0, '保留未覆盖现场，不能冻结为可用集合'
        assert (stats['satellite_count'],stats['task_count'])==(item['satellite_count'],item['task_count'])
        assert sha(folder/'provenance.json')==sha(folder/'provenance/scenario.json.provenance.json')
        groups[item['split']].add(item['lineage_group_id'])
        stats_by[(item['split'],item['scale'],item['difficulty_profile'])].append(stats)
        rows.append({k:item[k] for k in ('scenario_id','scale','satellite_count','task_count','split','difficulty_profile','lineage_group_id','relative_path')}|
            dict(scenario_sha256=scene_sha,orbital_family_sha256=prov['orbital_family_sha256'],
                task_collection_sha256=prov['task_collection_sha256'],feasible_window_count=stats['feasible_window_count'],
                zero_opportunity_fraction=stats['zero_opportunity_fraction'],window_overlap_fraction=stats['window_overlap_fraction'],
                max_demand_storage_ratio=stats['max_demand_storage_ratio']))
    assert len(groups['final_test'])==15 and len(groups['smoke'])==3 and not groups['final_test']&groups['smoke']
    for scale in ('small','medium','large'):
        for profile in ('low_conflict','mixed','high_conflict','resource_overload'):
            assert len(stats_by[('final_test',scale,profile)])==5
        avg=lambda profile:sum(s['window_overlap_fraction'] for s in stats_by[('final_test',scale,profile)])/5
        assert avg('low_conflict')<avg('high_conflict'), '未达到预定义低/高冲突区分，保留现场'
        assert avg('high_conflict')>.6
        assert min(s['max_demand_storage_ratio'] for s in stats_by[('final_test',scale,'resource_overload')])>1
    # 仅核对旧索引身份字段，不读取旧冻结测试场景、任务或评测成绩。
    known_groups=set();known_hashes=set();inputs=[]
    for path in protected:
        payload=json.loads(path.read_text());inputs.append(dict(name=path.name,sha256=sha(path)))
        def visit(value):
            if isinstance(value,dict):
                if value.get('lineage_group_id'):known_groups.add(value['lineage_group_id'])
                if value.get('orbital_family_sha256'):known_hashes.add(value['orbital_family_sha256'])
                for v in value.values():visit(v)
            elif isinstance(value,list):
                for v in value:visit(v)
        visit(payload)
    assert not (groups['final_test']|groups['smoke'])&known_groups
    assert not {r['orbital_family_sha256'] for r in rows}&known_hashes
    new_seeds={f['seed'] for f in spec['families']}
    assert len(new_seeds)==18 and min(new_seeds)>2**64
    isolation=dict(status='PASS',test_families=15,smoke_families=3,protected_groups=len(known_groups),
        index_inputs=inputs,old_test_content_read=False,overlap_groups=0,
        scope='new synthetic orbital elements and task requests; four profiles per test family are correlated; no claim of real catalog satellites',
        generation_seed_namespace='new independent 96bit seeds; actual seeds exceed legacy 64bit namespace')
    write(root/'reports/isolation.json',isolation)
    write(root/'registry/scenarios.json',rows)
    with (root/'registry/scenarios.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    for split in ('smoke','final_test'):
        plan=dict(dataset_id='eos-final-v1-'+split,allocation=[r|{'relative_path':r['relative_path'].split('/',1)[1]} for r in spec['allocation'] if r['split']==split])
        path=root/split/'dataset_plan.json'
        if path.exists():assert json.loads(path.read_text())==plan
        else:write(path,plan)
    summary=[dict(split=split,scale=scale,profile=profile,count=len(values),
        mean_window_overlap=sum(v['window_overlap_fraction'] for v in values)/len(values),
        min_storage_pressure=min(v['max_demand_storage_ratio'] for v in values),
        max_zero_opportunity_fraction=max(v['zero_opportunity_fraction'] for v in values))
        for (split,scale,profile),values in stats_by.items()]
    write(root/'reports/quality.json',dict(status='PASS',scenes=66,test_scenes=60,smoke_scenes=6,
        profiles=summary,continuous_certification='INCONCLUSIVE',algorithm_quality_screening=False))
    write(root/'registry/freeze.json',dict(dataset='eos-final-course-v1',frozen_at=datetime.now(timezone.utc).isoformat(),
        scenes=66,test_independent_families=15,formal_test_runs_executed=0,
        note='data frozen; algorithms and release source are to be frozen after repository cleanup, before final evaluation'))
    (root/'README.md').write_text('''# 全组最终统一测试场景 eos-final-course-v1

60份正式测试＋6份联调。小10星20任务、中20星80任务、大50星200任务，均为1800秒、无地面站。
每档正式测试含低冲突/混合/高冲突/资源紧张各5份；高负载共30份，已包含在60份内。
15个正式母家族各4种负载变体；另3个联调家族各2变体。60份正式文件不等于60个独立来源。

## 使用

1. 将ZIP解压到WSL Linux文件系统，例如运行根目录下datasets/eos-final-v1；不要改JSON或侧车。
2. 校验：`python verify_package.py --root .`。校验通过后只登记smoke子目录到网页，供日常演示和兼容检查。
3. final_test仅供最终统一测量，算法/参数/模型冻结后再明确登记该子目录，不能用于训练、调参、选算法。
4. registry/scenarios.csv提供规模、负载、家族和相对路径；场景及其provenance/validation/characterization须一起复制。

## 物理与模型合同

实际执行Git 50660f3中已审查的旧课程姿态窗口代码，实际文件及哈希保存在generator_sources。
当前独立审查器按相同旧合同进行0.05秒完整曝光采样；来源由当前公共接口复核，保留地球遮挡。
轨道为独立合成的近地六根数与Keplerian传播，任务来自自身轨道走廊；不是实采业务，也不冒充真实卫星目录。
新姿态/Nadir合同没有追溯用于本包，模型未重训。publication_status=development是现有工程采样证据协议字段，不表示允许训练。
采样核验不等于连续区间证明；所有最终计划仍须由Controller独立核验。无地面站、未验证真实射频/完整电池动力学。

## 统计协议

场景先冻结，不按算法成绩筛选。主目标完成率，每算法60秒，冻结LAVIS-v4及明确参数；随机方法建议3个固定种子，确定性方法无需机械重复。
统一约束、模型、预算、运行机器及并发条件；单Worker做耗时主比较，并行能力另测。
按规模/负载和来源家族分别统计TCR、TP、BD、TM、RT及综合分；失败/超时完整保留，不能伪填0秒成功。
报告每个家族内四变体的相关性；不得将其当作独立重复实验。旧20测试或旧96开发矩阵另列，不能拼为新的独立样本。

SHA256SUMS.json核对包内文件；reports/quality.json和isolation.json记录质量与隔离。smoke_acceptance.json仅为联调接口证据，不是最终排名。
''',encoding='utf-8')
    # 标准库消费者校验脚本，独立于安装完整系统和Git历史。
    (root/'verify_package.py').write_text('''import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.'));r=p.parse_args().root.resolve()
m=json.loads((r/'SHA256SUMS.json').read_text(encoding='utf-8'))
for n,h in m.items():
 f=r/n
 assert not Path(n).is_absolute() and f.resolve().is_relative_to(r) and not f.is_symlink(),n
 assert f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest()==h,n
print('PASS:',len(m),'files verified')
''',encoding='utf-8')
    source_root=Path(source_snapshot).resolve() if source_snapshot else Path(__file__).resolve().parents[1]
    snapshot=json.loads((root/'generator_sources/execution_snapshot.json').read_text())
    with zipfile.ZipFile(root/'generator_sources/generation_source.zip','x',zipfile.ZIP_DEFLATED) as archive:
        for name,expected in snapshot.items():
            path=source_root/name
            assert sha(path)==expected
            archive.write(path,name)
    files=sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    write(root/'SHA256SUMS.json',{p.relative_to(root).as_posix():sha(p) for p in files})
    verify(root)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        for path in files+[root/'SHA256SUMS.json']:archive.write(path,Path('eos-final-v1')/path.relative_to(root))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name,h in json.loads((root/'SHA256SUMS.json').read_text()).items():
            assert hashlib.sha256(archive.read('eos-final-v1/'+name)).hexdigest()==h
    print(json.dumps(dict(archive=str(output),bytes=output.stat().st_size,sha256=sha(output),scenes=66)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['verify','finalize'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path)
    p.add_argument('--protected-index',type=Path,action='append',default=[])
    p.add_argument('--source-snapshot',type=Path,help='实际生成执行源码目录；默认当前源码根目录');a=p.parse_args()
    if a.command=='verify':verify(a.root)
    else:
        if not a.output:raise ValueError('缺少输出ZIP位置')
        finalize(a.root,a.output,a.protected_index,a.source_snapshot)
