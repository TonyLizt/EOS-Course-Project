"""Portable canonical bundle discovery shared by CLI, API and benchmarks."""
import hashlib
import json
from pathlib import Path


def entries(root, *, satellite_count=None, task_count=None, difficulty_profile=None, scale=None):
    root=Path(root).resolve()
    if not any((root/name).is_file() for name in ('dataset_plan.json','dataset_plan_v2.json','dataset_plan_v3.json')):return None
    rows=[];seen=set()
    for path in sorted(root.rglob('scenario.json')):
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('canonical path escapes root')
        folder=path.parent
        if (folder/'quarantine.json').is_file():continue
        if not all((folder/name).is_file() for name in ('provenance.json','validation.json','characterization.json')):continue
        p=json.loads((folder/'provenance.json').read_text());c=json.loads((folder/'characterization.json').read_text())
        sid=p['scenario_id']
        if sid in seen:raise ValueError('duplicate canonical scenario ID: '+sid)
        seen.add(sid)
        if any(value is not None and value!=actual for value,actual in (
            (satellite_count,c['satellite_count']),(task_count,c['task_count']),
            (difficulty_profile,p['difficulty_profile']),(scale,p['scale']))):continue
        rows.append(dict(scenario_id=sid,name=sid,path=path.relative_to(root).as_posix(),
            sha256=p['scenario_sha256'],satellite_count=c['satellite_count'],mission_count=c['task_count'],
            duration_s=c['duration_s'],difficulty_profile=p['difficulty_profile'],scale=p['scale'],seed=p['seed'],
            lineage_group_id=p['lineage_group_id'],publication_status=p['publication_status'],
            physical_validation_status=p['physical_validation']['status']))
    return rows


def resolve(root,scenario_id):
    root=Path(root).resolve()
    # Fixed plans provide an authoritative path for core/retained trial IDs.
    # Resolve one bundle rather than recursively opening the whole corpus for
    # every submitted Run. The actual scenario bytes are still hashed below.
    for name in ('dataset_plan_v3.json','dataset_plan_v2.json','dataset_plan.json'):
        plan=root/name
        if not plan.is_file():continue
        allocation=json.loads(plan.read_text()).get('allocation',[])
        declared=next((r for r in allocation if r.get('scenario_id')==scenario_id),None)
        if declared is None:continue
        relative=Path(declared['relative_path']);path=root/relative
        if relative.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('canonical plan path escapes root')
        folder=path.parent
        if (folder/'quarantine.json').exists() or not all((folder/file).is_file() for file in
                ('scenario.json','provenance.json','validation.json','characterization.json')):
            raise FileNotFoundError('canonical bundle incomplete or quarantined: '+scenario_id)
        provenance=folder/'provenance.json'
        if provenance.stat().st_size>1024*1024:raise ValueError('canonical provenance too large')
        record=json.loads(provenance.read_text())
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if record.get('scenario_id')!=scenario_id or sha!=record.get('scenario_sha256'):
            raise ValueError('canonical scenario ID or SHA mismatch')
        return path,sha
    rows=entries(root)
    if rows is None:return None
    row=next((r for r in rows if r['scenario_id']==scenario_id),None)
    if row is None:raise FileNotFoundError('Unregistered canonical scenario: '+scenario_id)
    path=Path(root)/row['path'];sha=hashlib.sha256(path.read_bytes()).hexdigest()
    if sha!=row['sha256']:raise ValueError('canonical scenario SHA mismatch')
    return path,sha
