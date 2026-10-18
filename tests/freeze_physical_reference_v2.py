"""Freeze numerical regression inputs using ONLY the independent point oracle.

Manual maintenance utility: existing output is never replaced. Not a generator
of scenarios, provenance, planning evidence or continuous certificates.
"""
import argparse
from copy import deepcopy
from datetime import timedelta
import hashlib
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physical_reference_v2 import reference, exit_bracket
from utils.time_parsing import parse_orbit_epoch as utc


def freeze(output, data):
    from utils.visibility import ensure_orekit
    ensure_orekit(str(data))
    from orekit_jpype.pyhelpers import datetime_to_absolutedate
    import math
    original = Path('/home/meteor/eos-course-runtime/epoch-acceptance/s1-20s20m-1d-20261016/candidate/Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1.json')
    raw = original.read_bytes()
    scene = json.loads(raw)
    result = dict(schema='physics-regression-relative-nadir-v2',
        scope='NUMERICAL_TEST_REFERENCE_ONLY_NOT_PROVENANCE_OR_CERTIFICATION',
        original_scene_sha256=hashlib.sha256(raw).hexdigest(),
        data_sha256=hashlib.sha256(data.read_bytes()).hexdigest(),
        reference_sha256=hashlib.sha256(inspect.getsource(reference).encode()).hexdigest(),
        baseline='c5090ba72819493c5f91ce8c1aa0a6a26e8cf58d', cases=[], historical=[])
    for sid in ('ALOS-2_39766','GPM-CORE_39574'):
        sat = next(s for s in scene['satellites'] if s['id']==sid)
        start = utc(sat['orbital_params']['epoch'])
        oracle = reference(sat,dict(latitude=0.,longitude=0.,altitude_km=0.))
        moment = start+timedelta(seconds=100)
        pos = oracle.prop.propagateOrbit(datetime_to_absolutedate(moment)).getPVCoordinates(oracle.inertial).getPosition()
        geo = oracle.earth.transform(pos,oracle.inertial,datetime_to_absolutedate(moment))
        location = dict(latitude=math.degrees(geo.getLatitude()),longitude=math.degrees(geo.getLongitude()),altitude_km=0.)
        oracle = reference(sat,location)
        windows=[];begin=previous=None
        for i in range(601):
            t=start+timedelta(seconds=i)
            visible=oracle(t)['visible']
            if visible and begin is None: begin=t
            if not visible and begin is not None:
                low,high=exit_bracket(oracle,previous,t)
                windows.append(dict(start=begin.isoformat(),safe_exit=low.isoformat(),exit_upper=high.isoformat()))
                begin=None
            previous=t
        if begin is not None: windows.append(dict(start=begin.isoformat(),safe_exit=previous.isoformat(),exit_upper=None))
        assert windows and any((utc(w['safe_exit'])-utc(w['start'])).total_seconds()>=10 for w in windows)
        result['cases'].append(dict(satellite=sat,location=location,start=start.isoformat(),duration_s=600,
            windows=windows,nadir_time=moment.isoformat(),nadir_point=oracle(moment)))
    legacy = [('M009','2025-11-18T13:13:33Z'),('M020','2025-11-19T09:23:10Z')]
    for mid,t in legacy:
        sat=next(s for s in scene['satellites'] if s['id']=='GPM-CORE_39574')
        loc=next(m for m in scene['missions'] if m['id']==mid)['target_location']
        result['historical'].append(dict(task_id=mid,time=t,satellite=sat,location=loc,
            relative=reference(sat,loc)(t),absolute=reference(sat,loc,legacy_absolute=True)(t)))
    old_s2=Path('/home/meteor/eos-course-runtime/epoch-acceptance/s2-20s20m-grid-v2-lazy-20261016/independent-e3-20261016')
    config=json.loads((old_s2/'scheduling/config.json').read_bytes())
    payload=Path(config['scenario_path']).read_bytes(); old=json.loads(payload)
    result['exposure_history']=[]
    for i,(mid,sid,t) in enumerate((('M001','SKYSAT-C2_41773','2025-11-18T15:06:44Z'),
                                   ('M007','SCD_1_22490','2025-11-19T04:46:29Z')),1):
        sat=next(s for s in old['satellites'] if s['id']==sid)
        loc=next(m for m in old['missions'] if m['id']==mid)['target_location']
        plan=(old_s2/f'continuous_duration_probes/{i}_public_verified_plan.json').read_bytes()
        result['exposure_history'].append(dict(task_id=mid,time=t,satellite=sat,location=loc,
            source_sha256=hashlib.sha256(payload).hexdigest(),plan_sha256=hashlib.sha256(plan).hexdigest(),
            point=reference(sat,loc)(t)))
    assert original.read_bytes()==raw
    output.parent.mkdir(parents=True,exist_ok=True)
    encoded=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode()
    with output.open('xb') as stream:stream.write(encoded)
    print(json.dumps(dict(output=str(output),sha256=hashlib.sha256(encoded).hexdigest(),
        windows=[c['windows'] for c in result['cases']]),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--orekit-data',required=True,type=Path)
    a=p.parse_args();freeze(a.output,a.orekit_data)
