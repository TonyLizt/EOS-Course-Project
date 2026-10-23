"""Canonical eos-v1: real catalog orbits, synthetic controlled requests, real Orekit windows.

Extends shared OrbitGrid/structure/physics tooling without changing historical generators.
All 96 slots are planned first. Completed bundles are immutable; resume verifies hashes.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import importlib.metadata
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_shared_dataset import OrbitGrid,parameters,file_sha,write_json,digest,sampled_check
from scripts.recompute_scenario_windows import validate_structure
from scripts.characterize_scenarios import characterize
from utils.continuous_exposure import window_generation_record
from utils.time_parsing import parse_orbit_epoch
from utils import visibility

VERSION='canonical-eos-v1-3'
SCALES=[(10,10),(10,20),(20,30),(20,40),(40,80),(50,80),(50,100),(100,200)]
PROFILES=['low_conflict','mixed','high_conflict','resource_overload']


def plan():
    return [dict(scenario_id=f'SCN-S{i+1}-{profile}-{seed}-r3',scale=f'S{i+1}',satellite_count=s,
                 task_count=t,difficulty_profile=profile,seed=2026102300+i*100+j*10+seed,
                 split='train_development' if seed==0 else 'validation',replicate=seed,
                 relative_path=f'{"standard" if j==0 else "realistic" if j==1 else "stress/"+profile}/SCN-S{i+1}-{profile}-{seed}-r3/scenario.json')
            for i,(s,t) in enumerate(SCALES) for j,profile in enumerate(PROFILES) for seed in range(3)]


def satellites(count,profile):
    from core.models import (Satellite,OrbitalType,OrbitalParameters,SatelliteSpecs,ObservationSensor,
        ObservationCapability,SensorResolution,SensorMode)
    raw_path=ROOT/f'input/{count if count!=40 else 50}_satellites.json'
    raw=json.loads(raw_path.read_text()); ids=sorted(raw)[:count]
    result=[]
    for sid in ids:
        row=raw[sid]
        sensor=ObservationSensor(sid+'_sensor',SensorResolution.MEDIUM,SensorMode.VISIBLE,45.,50.,.1,50.,0.)
        sat=Satellite(sid,OrbitalType[row[0]],OrbitalParameters(*row[1:]),
            satellite_specs=SatelliteSpecs(),observation_capability=ObservationCapability([sensor])).to_dict()
        if profile=='resource_overload':sat['satellite_specs']['max_data_storage_GB']=.0007
        result.append(sat)
    assert len(result)==count and len({s['id'] for s in result})==count
    return result,dict(path=raw_path.relative_to(ROOT).as_posix(),sha256=file_sha(raw_path),
        selection='sorted actual satellite IDs; first 40 of actual 50 for S5; no orbit cloning',
        capability_policy='shared core synthetic agile payload defaults; overload max_data_storage_GB=0.0007, enforced per orbit by shared ConstraintModel')


def missions(config,sats,grid):
    import math
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    ctx=visibility._CONTEXT;rng=random.Random(config['seed']);result=[]
    profile=config['difficulty_profile']
    for i in range(config['task_count']):
        if profile=='low_conflict':sid=sats[i%len(sats)]['id'];second=rng.randrange(100,1700,5)
        elif profile=='mixed':sid=sats[i%min(5,len(sats))]['id'];second=900+rng.randrange(-300,301,5)
        else:sid=sats[0]['id'];second=900+rng.randrange(-10,11,5)
        point=ctx.earth.transform(Vector3D(*map(float,grid.positions[sid][second//5])),ctx.itrf,None)
        jitter=.01 if profile in ('high_conflict','resource_overload') else .05
        lat=max(-89.,min(89.,math.degrees(point.getLatitude())+rng.uniform(-jitter,jitter)))
        lon=(math.degrees(point.getLongitude())+rng.uniform(-jitter,jitter)+180)%360-180
        duration=rng.randint(20,30) if profile=='resource_overload' else rng.randint(5,15)
        result.append(dict(id=f'M{i+1:03d}',priority=float(rng.randint(1,10)),
            target_location=dict(latitude=round(lat,7),longitude=round(lon,7),altitude_km=0.),
            observation_requirement=dict(duration_s=float(duration),min_elevation_angle_deg=None,
                required_mode=None,required_resolution=None)))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT/'data/scenarios/eos-v1')
    p.add_argument('--all',action='store_true',help='Otherwise the five required pilot scales only')
    p.add_argument('--limit',type=int);args=p.parse_args();root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    allocation=plan();spec=root/'dataset_plan_v3.json'
    payload=dict(dataset_id='eos-v1',generator_version=VERSION,development_only=True,allocation=allocation)
    if spec.exists():assert json.loads(spec.read_text())==payload,'existing plan differs'
    else:write_json(spec,payload)
    pilot={(0,'low_conflict'),(1,'mixed'),(3,'high_conflict'),(6,'resource_overload'),(7,'high_conflict')}
    selected=allocation if args.all else [r for r in allocation if r['replicate']==0 and (int(r['scale'][1:])-1,r['difficulty_profile']) in pilot]
    if args.limit:selected=selected[:args.limit]
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    source_sha=file_sha(Path(__file__));grids={};start=parse_orbit_epoch('2025-11-18T12:00:00Z')
    with tempfile.TemporaryDirectory(prefix='eos-v1-orbit-') as directory:
        local=Path(directory)/'orekit-data.zip';shutil.copyfile(ROOT/'utils/orekit-data.zip',local)
        visibility.ensure_orekit(str(local))
        for config in selected:
            folder=root/Path(config['relative_path']).parent
            if (folder/'provenance.json').exists():
                old=json.loads((folder/'provenance.json').read_text())
                assert old['scenario_sha256']==file_sha(folder/'scenario.json'),'completed source changed'
                continue
            if folder.exists():raise ValueError('Incomplete bundle retained; inspect before resuming: '+str(folder))
            began=time.monotonic();sats,raw=satellites(config['satellite_count'],config['difficulty_profile'])
            key=digest([s['orbital_params'] for s in sats])
            if key not in grids:grids[key]=OrbitGrid(sats,start,5,duration_s=1800)
            grid=grids[key];tasks=missions(config,sats,grid)
            from org.orekit.attitudes import NadirPointing
            from org.orekit.propagation.analytical import KeplerianPropagator
            from orekit_jpype.pyhelpers import datetime_to_absolutedate
            initial={};ctx=visibility._CONTEXT
            for sat in sats:
                op=sat['orbital_params']
                orbit=visibility._build_keplerian_orbit(ctx,op['semi_major_axis_km']*1000,op['eccentricity'],
                    op['inclination_deg'],op['right_ascension_of_ascending_node_deg'],op['argument_of_perigee_deg'],
                    op['mean_anomaly_deg'],parse_orbit_epoch(op['epoch']))
                provider=KeplerianPropagator(orbit)
                q=NadirPointing(ctx.inertial,ctx.earth).getAttitude(provider,datetime_to_absolutedate(start),ctx.inertial).getRotation()
                initial[sat['id']]=dict(time=start.isoformat(),inertial_to_body_quaternion_xyzw=[float(q.getQ1()),float(q.getQ2()),float(q.getQ3()),float(q.getQ0())])
            record=window_generation_record(5,5.,60.)
            scene=dict(scenario_id=config['scenario_id'],metadata=dict(name=config['scenario_id'],creation_time=start.isoformat(),
                duration=1800.,time_step=5.,description='Synthetic development requests on actual catalog orbits',
                extra=dict(source_dataset='eos-v1',source_group_id=config['scenario_id'],generator_version=VERSION,
                    generator_seed=config['seed'],initial_attitudes=initial,window_generation=record,visibility_settings=dict(min_elevation_deg=5.,coarse_step_min=60.))),
                satellites=sats,missions=tasks,ground_stations=[],observation_windows=[],communication_windows=[])
            for sat in sats:
                for task in tasks:
                    windows=grid.windows(sat,task)
                    # Preserve true body rotations at each boundary for shared slew checks.
                    if windows:
                        evaluate=visibility.create_visibility_evaluator(**parameters(sat,task))
                        from datetime import timedelta
                        for w in windows:
                            n=len(w['agile_data']['roll_angles']);first=parse_orbit_epoch(w['start_time'])
                            times=[first+timedelta(seconds=k*5) for k in range(n)]+[parse_orbit_epoch(w['end_time'])]
                            q=[evaluate(t).get('inertial_to_body_quaternion_xyzw') for t in times]
                            if all(v is not None for v in q):w['agile_data']['boundary_quaternions_xyzw']=q
                        scene['observation_windows'].append(dict(satellite_id=sat['id'],mission_id=task['id'],
                            sensor_id=sat['observation_capability']['sensors'][0]['sensor_id'],time_windows=windows))
            structure=validate_structure(scene);physical=sampled_check(scene,local)
            stats=characterize(scene);folder.mkdir(parents=True)
            write_json(folder/'scenario.json',scene);sha=file_sha(folder/'scenario.json')
            provenance=dict(config,artifact_kind='fresh_generated_shared_v1',scenario_sha256=sha,completion_status='complete',
                calculator_kind='orekit',scenario_physics_version='fresh_epoch_parsed_v1',epoch_parser_version='epoch_parser_v1',
                propagation_version='orekit-keplerian/'+importlib.metadata.version('orekit-jpype'),
                window_boundary_version='visibility_exit_refined_v3',window_generation=record,
                calculation_settings=dict(time_step=5,min_elevation_deg=5.),provenance_status='verified_generation',
                publication_status='development',formal_release_eligible=False,
                physical_validation=dict(status='SAMPLED_PASS',continuous_status='INCONCLUSIVE'),
                lineage_group_id=config['scenario_id'],parent_scenario_sha256=None,raw_inputs=[raw],
                generator_version=VERSION,generator_git_commit=commit,generation_code_sha256=source_sha,
                orekit_data_sha256=file_sha(local),generated_at=datetime.now(timezone.utc).isoformat(),
                generation_wall_s=time.monotonic()-began,synthetic=True,
                method='real input orbits; own-orbit subpoint requests; difficulty controlled before scan; no fabricated windows')
            write_json(folder/'validation.json',dict(scenario_sha256=sha,structure=structure,physics=physical,
                status='SAMPLED_DEVELOPMENT_PASS',continuous_certification='INCONCLUSIVE',full_matrix_status='PENDING'))
            write_json(folder/'characterization.json',stats)
            # Existing loader-compatible sidecar is byte-identical to authoritative provenance.
            write_json(folder/'provenance/scenario.json.provenance.json',provenance)
            write_json(folder/'provenance.json',provenance)
            assert source_sha==file_sha(Path(__file__)),'generator changed during run'
            print(json.dumps(dict(scenario=config['scenario_id'],seconds=provenance['generation_wall_s'],
                windows=stats['feasible_window_count'],overlap=stats['window_overlap_fraction'],pressure=stats['max_demand_capacity_ratio'])),flush=True)


if __name__=='__main__':main()
