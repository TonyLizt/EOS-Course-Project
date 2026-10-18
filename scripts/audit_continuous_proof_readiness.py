"""Read-only, fail-closed audit of actual proof prerequisites; no certificate.

Point values, supplied JSON bounds and the conditional interval kernel do not
establish a validated Orekit dependency graph or a commanded slew trajectory.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def audit(scene_path, data_path):
    from utils.visibility import ensure_orekit
    from utils.certification_identity import trusted_context
    from utils.continuous_exposure import PlanExposureAuditor
    ensure_orekit(str(data_path))
    raw=Path(scene_path).read_bytes();scene=json.loads(raw)
    context=trusted_context(str(data_path))
    auditor=PlanExposureAuditor(scene,data_path=data_path,min_elevation_deg=5.)
    provider_available=[]
    for sat in scene['satellites']:
        for mission in scene['missions']:
            _,provider=auditor.evaluator(sat,mission)
            provider_available.append(provider is not None)
    # This is an audit of the actual reviewed implementation, not a user-facing
    # runtime policy switch. A future provider requires a new scientific review.
    blockers=[
        'NO_VALIDATED_KEPLER_FLOAT_AND_INPUT_ERROR_ENCLOSURES',
        'NO_VALIDATED_ITRF_EOP_TIME_TRANSFORM_ENCLOSURES',
        'NO_VALIDATED_POINTING_NORMALIZATION_EULER_CHART_ENCLOSURES',
        'NO_COMMAND_SLEW_TRAJECTORY_AND_EXECUTION_ERROR_CONTRACT',
    ]
    if not provider_available or not all(provider_available):
        blockers.insert(0,'NO_PRODUCTION_INTERVAL_PROVIDER')
    return dict(status='INCONCLUSIVE',formal_certification='BLOCKED',
        scenario_sha256=hashlib.sha256(raw).hexdigest(),identity=context.identity(),
        actual_pair_count=len(provider_available),interval_provider_available=all(provider_available) and bool(provider_available),
        blockers=blockers,
        authority='READINESS_DIAGNOSTIC_ONLY_NOT_CERTIFICATE',
        numeric_bounds='NOT_ESTIMATED_FROM_SAMPLES',
        acceptance='Conditional rational kernel results and JSON declarations grant no formal authority')


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',required=True,type=Path)
    parser.add_argument('--orekit-data',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=audit(args.scenario,args.orekit_data)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
