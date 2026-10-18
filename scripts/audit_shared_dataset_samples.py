#!/usr/bin/env python3
"""为已生成场景补充可重放的逐采样物理测量；不修改场景或认证声明。"""
from __future__ import annotations
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_shared_dataset import file_sha, write_json
from utils.continuous_exposure import PlanExposureAuditor, audit_interval
from utils.time_parsing import parse_orbit_epoch
import numpy as np


def replace_json(path,value):
    """只替换本工具的派生检查报告；原场景和配置始终只读。"""
    temporary=path.with_suffix('.updated.partial')
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
            stream.write('\n')
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--repack-only',action='store_true')
    parser.add_argument('--only-final-test',action='store_true')
    args=parser.parse_args();root=args.dataset.resolve()
    if args.repack_only:
        print(json.dumps({'phase':'archives_repacked','archives':repack_archives(root)}),flush=True)
        return
    spec=json.loads((root/'dataset_spec.json').read_text())
    source=ROOT/'utils/orekit-data.zip'
    summaries=[]
    with tempfile.TemporaryDirectory(prefix='eos-dataset-audit-') as directory:
        local=Path(directory)/'data.zip';shutil.copyfile(source,local)
        if file_sha(source)!=file_sha(local):raise ValueError('Orekit copy SHA mismatch')
        for item in spec['allocation']:
            if args.only_final_test and item['split']!='final_test':continue
            usage='final_test' if item['split']=='final_test' else 'development'
            folder=root/usage;name=item['artifact_id'];path=folder/'scenarios'/(name+'.json')
            sha=file_sha(path);scene=json.loads(path.read_text())
            pieces=[(w,t) for w in scene['observation_windows'] for t in w['time_windows']]
            picked=[pieces[int(i)] for i in np.linspace(0,len(pieces)-1,min(10,len(pieces)),dtype=int)]
            satellites={s['id']:s for s in scene['satellites']};missions={m['id']:m for m in scene['missions']}
            auditor=PlanExposureAuditor(scene,data_path=local,min_elevation_deg=5.,step_s=.05)
            rows=[];skipped=[]
            for w,window in picked:
                mission=missions[w['mission_id']];duration=mission['observation_requirement']['duration_s']
                start=parse_orbit_epoch(window['start_time']);end=start+timedelta(seconds=duration)
                if end>parse_orbit_epoch(window['end_time']):
                    skipped.append(dict(task_id=mission['id'],reason='NO_FULL_EXPOSURE'));continue
                evaluate,certificate=auditor.evaluator(satellites[w['satellite_id']],mission)
                points=[]
                def measured(moment):
                    value=evaluate(moment)
                    points.append({**value,'time':moment.isoformat()})
                    return value
                result=audit_interval(measured,start,end,duration,step_s=.05,certificate=certificate)
                if result.get('sampled_boundaries_status')!='PASS':raise ValueError(name+': actual sampled physics failed')
                rows.append(dict(task_id=mission['id'],satellite_id=w['satellite_id'],start_utc=start.isoformat(),
                    end_utc=end.isoformat(),step_s=.05,min_elevation_deg=5.,result=result,samples=points,
                    minimum_sampled_elevation_deg=min(p['elevation_deg'] for p in points),
                    maximum_sampled_abs_axis_deg={axis:max(abs(p[axis+'_deg']) for p in points) for axis in ('yaw','pitch','roll')}))
            if not rows:raise ValueError(name+': no measured exposures')
            if file_sha(path)!=sha:raise ValueError('scenario changed during audit')
            report=dict(artifact_id=name,scenario_sha256=sha,orekit_data_sha256=file_sha(source),
                checker_sha256=file_sha(Path(__file__)),checked_segments=len(rows),skipped_segments=skipped,
                sampled_status='PASS',continuous_status='INCONCLUSIVE',continuous_reason='NO_CONTINUITY_CERTIFICATE',rows=rows)
            target=folder/'checks'/'exposure_samples'/(name+'.json')
            write_json(target,report)
            check_path=folder/'checks'/(name+'.json');check=json.loads(check_path.read_text())
            check['measured_exposure_report']='checks/exposure_samples/'+name+'.json'
            check['measured_exposure_report_sha256']=file_sha(target);replace_json(check_path,check)
            summaries.append(dict(artifact_id=name,checked_segments=len(rows),samples=sum(len(r['samples']) for r in rows),
                minimum_sampled_elevation_deg=min(r['minimum_sampled_elevation_deg'] for r in rows)))
            if len(summaries)%10==0:print(json.dumps({'phase':'measured_exposure_audit','completed':len(summaries)}),flush=True)
    for usage in ('development','final_test'):
        if args.only_final_test and usage!='final_test':continue
        folder=root/usage;summary_path=folder/'checks'/'summary.json';summary=json.loads(summary_path.read_text())
        summary['results']=[json.loads(p.read_text()) for p in sorted((folder/'checks').glob('EOS-G*.json'))]
        summary['measured_exposure_scope']='all sampled timestamps and geometry values in checks/exposure_samples'
        replace_json(summary_path,summary)
    summary_file=root/'measured_exposure_summary.private.json'
    if summary_file.exists():
        replaced={row['artifact_id'] for row in summaries}
        summaries=sorted([row for row in json.loads(summary_file.read_text()) if row['artifact_id'] not in replaced]+summaries,
                         key=lambda row:row['artifact_id'])
        replace_json(summary_file,summaries)
    else:write_json(summary_file,summaries)
    archives=repack_archives(root)
    print(json.dumps({'phase':'measured_audit_complete','scenes':len(summaries),
        'segments':sum(s['checked_segments'] for s in summaries),'samples':sum(s['samples'] for s in summaries),
        'archives':archives}),flush=True)


def repack_archives(root):
    # 更新本批两个受管压缩包，严格核对旧包校验和后才替换；不累积旧ZIP副本。
    catalog=root.parent/(root.name+'-archives.json');archives=json.loads(catalog.read_text())
    for record,usage in zip(archives,('development','final_test')):
        path=root.parent/record['filename']
        if path.parent!=root.parent or file_sha(path)!=record['sha256']:raise ValueError('archive identity changed')
        pending=path.with_suffix('.zip.partial')
        try:
            with zipfile.ZipFile(pending,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
                for source_path in sorted((root/usage).rglob('*')):
                    if source_path.is_file():archive.write(source_path,(Path('eos-course-v1')/source_path.relative_to(root)).as_posix())
                archive.write(root/'README.md','eos-course-v1/README.md')
                if usage=='development':
                    for source_path in sorted((root/'splits').glob('*.json')):archive.write(source_path,(Path('eos-course-v1')/source_path.relative_to(root)).as_posix())
                else:archive.write(root/'dataset_spec.json','eos-course-v1/dataset_spec.private.json')
            pending.replace(path)
        finally:pending.unlink(missing_ok=True)
        record.update(sha256=file_sha(path),bytes=path.stat().st_size)
    replace_json(catalog,archives)
    return archives


if __name__=='__main__':main()
