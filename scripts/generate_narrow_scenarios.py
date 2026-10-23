"""Derive explicit narrow request intervals inside verified parent opportunities.

No parent bytes change. Every new attitude and exact boundary is evaluated by
Orekit, and the common exposure sampler checks the child independently.
"""
import argparse
from copy import deepcopy
from datetime import timedelta,datetime,timezone
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.build_shared_dataset import file_sha,write_json,parameters,sampled_check
from scripts.recompute_scenario_windows import validate_structure
from scripts.characterize_scenarios import characterize
from utils.time_parsing import parse_orbit_epoch
from utils import visibility


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT/'data/scenarios/eos-v1');args=p.parse_args()
    names=['SCN-S2-mixed-0-r3','SCN-S4-high_conflict-0-r3','SCN-S8-high_conflict-0-r3']
    from eos_system.dataset_registry import resolve
    with tempfile.TemporaryDirectory(prefix='eos-narrow-') as directory:
        local=Path(directory)/'orekit-data.zip';shutil.copyfile(ROOT/'utils/orekit-data.zip',local);visibility.ensure_orekit(str(local))
        for parent_id in names:
            path,parent_sha=resolve(args.root,parent_id);began=time.monotonic()
            parent=json.loads(path.read_text());pp=json.loads(path.with_name('provenance.json').read_text())
            name=f"SCN-{pp['scale']}-narrow_window-0-r3";folder=args.root/'stress/narrow_window'/name
            if (folder/'provenance.json').exists():
                assert file_sha(folder/'scenario.json')==json.loads((folder/'provenance.json').read_text())['scenario_sha256']
                continue
            if folder.exists():raise ValueError('incomplete narrow bundle retained: '+str(folder))
            scene=deepcopy(parent);scene['scenario_id']=name;scene['metadata']['name']=name
            scene['metadata']['description']='Synthetic narrow request subintervals within actual parent physical visibility'
            scene['metadata']['extra']['request_interval_policy']='center of each parent window; required exposure + 2 seconds; exact attitudes recomputed'
            tasks={m['id']:m for m in scene['missions']};sats={s['id']:s for s in scene['satellites']}
            for row in scene['observation_windows']:
                task=tasks[row['mission_id']];duration=task['observation_requirement']['duration_s'];step=5
                evaluate=visibility.create_visibility_evaluator(**parameters(sats[row['satellite_id']],task))
                for w in row['time_windows']:
                    begin,end=map(parse_orbit_epoch,(w['start_time'],w['end_time']))
                    slack=max(0,(end-begin).total_seconds()-duration-2)
                    begin+=timedelta(seconds=math.floor(slack/(2*step))*step)
                    end=min(end,begin+timedelta(seconds=duration+2))
                    n=max(1,math.ceil((end-begin).total_seconds()/step-1e-9))
                    poses=[evaluate(begin+timedelta(seconds=k*step)) for k in range(n)]
                    final=evaluate(end)
                    if not all(v['visible'] for v in poses+[final]):raise ValueError('child requested endpoint not visible')
                    w.update(start_time=begin.isoformat(),end_time=end.isoformat(),
                        agile_data={axis+'_angles':[v[axis+'_deg'] for v in poses] for axis in ('roll','pitch','yaw')},
                        non_agile_data={axis+'_angle':poses[len(poses)//2][axis+'_deg'] for axis in ('roll','pitch','yaw')})
                    w['agile_data']['boundary_quaternions_xyzw']=[v['inertial_to_body_quaternion_xyzw'] for v in poses+[final]]
            structure=validate_structure(scene);physics=sampled_check(scene,local);stats=characterize(scene)
            folder.mkdir(parents=True);write_json(folder/'scenario.json',scene);sha=file_sha(folder/'scenario.json')
            provenance=deepcopy(pp);provenance.update(scenario_id=name,relative_path=(folder/'scenario.json').relative_to(args.root).as_posix(),
                scenario_sha256=sha,difficulty_profile='narrow_window',parent_scenario_id=parent_id,parent_scenario_sha256=parent_sha,
                generator_version='canonical-narrow-subinterval-v1',generation_code_sha256=file_sha(Path(__file__)),
                generation_wall_s=time.monotonic()-began,generated_at=datetime.now(timezone.utc).isoformat(),
                method='Derived request availability inside real parent intervals; complete common sampled physics rechecked',
                lineage_group_id=pp['lineage_group_id'])
            write_json(folder/'validation.json',dict(scenario_sha256=sha,structure=structure,physics=physics,
                status='SAMPLED_DEVELOPMENT_PASS',continuous_certification='INCONCLUSIVE',full_matrix_status='PENDING'))
            write_json(folder/'characterization.json',stats)
            write_json(folder/'provenance/scenario.json.provenance.json',provenance);write_json(folder/'provenance.json',provenance)
            assert file_sha(path)==parent_sha,'parent changed'
            print(name,'windows',stats['feasible_window_count'],'seconds',provenance['generation_wall_s'],flush=True)


if __name__=='__main__':main()
