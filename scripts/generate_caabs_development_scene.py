#!/usr/bin/env python3
"""Small REAL Orekit development geometry, never a released or private dataset.

Targets are deterministic WGS84 subpoints along one actual input orbit. They
are chosen before window scanning, with unchanged ten-second requirements.
No Legacy bytes, parent SHA, certificate or successful run status is invented.
"""
from __future__ import annotations
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def generate(output, satellites, satellite_id, data_path, *, tasks_per_target=1):
    if type(tasks_per_target) is not int or not 1 <= tasks_per_target <= 8:
        raise ValueError("tasks_per_target must be an integer in [1,8]")
    from core.models import (Satellite, SatelliteSpecs, OrbitalParameters, OrbitalType, ObservationCapability,
        ObservationSensor, SensorResolution, SensorMode, ManeuverabilityCapability, ManeuverabilityType,
        Mission, TargetLocation, ObservationRequirement, MissionInfo)
    from core.scenario import Scenario, ScenarioMetadata
    from utils.time_parsing import parse_orbit_epoch
    from utils import visibility as v
    from utils.certification_identity import source_identity
    from scripts.recompute_scenario_windows import _stage, _publish_no_replace, validate_structure
    from org.orekit.attitudes import NadirPointing
    from org.orekit.propagation.analytical import KeplerianPropagator
    from orekit_jpype.pyhelpers import datetime_to_absolutedate
    output = Path(output).absolute()
    if ".." in output.parts or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("unsafe output path")
    repository = Path(__file__).resolve().parents[1]
    if output == repository or repository in output.parents or output in repository.parents:
        raise ValueError("development output must be outside source tree")
    source = Path(satellites).resolve()
    raw = source.read_bytes()
    satellite_sha = hashlib.sha256(raw).hexdigest()
    orbit_data = json.loads(raw)[satellite_id]
    start = parse_orbit_epoch(orbit_data[7])
    input_identity = source_identity()
    sensor = ObservationSensor(satellite_id + "_sensor", SensorResolution.MEDIUM, SensorMode.VISIBLE,
                              45., 50., .1, 50., 0.)
    sat = Satellite(satellite_id, OrbitalType[orbit_data[0]], OrbitalParameters(*orbit_data[1:]),
                    satellite_specs=SatelliteSpecs(), observation_capability=ObservationCapability([sensor]),
                    maneuverability_capability=ManeuverabilityCapability(ManeuverabilityType.AGILE, 1., 45., 45., 45., 10.))
    ctx = v._CONTEXT
    params = v._extract_orbit_params(sat)
    prop = KeplerianPropagator(v._build_keplerian_orbit(ctx, **params))
    nominal = NadirPointing(ctx.inertial, ctx.earth).getAttitude(prop, datetime_to_absolutedate(start), ctx.inertial).getRotation()
    initial = {satellite_id: {"time": start.isoformat(), "inertial_to_body_quaternion_xyzw":
               [float(nominal.getQ1()), float(nominal.getQ2()), float(nominal.getQ3()), float(nominal.getQ0())]}}
    missions = []
    import math
    for index, second in enumerate((80, 180, 280), 1):
        date = datetime_to_absolutedate(start + timedelta(seconds=second))
        position = prop.propagateOrbit(date).getPVCoordinates(ctx.inertial).getPosition()
        geo = ctx.earth.transform(position, ctx.inertial, date)
        for repeat in range(tasks_per_target):
            missions.append(Mission(f"DEV{index:02d}-{repeat:02d}", TargetLocation(math.degrees(geo.getLatitude()),
                            math.degrees(geo.getLongitude()), 0.), index, ObservationRequirement(10.)))
    metadata = ScenarioMetadata("CAABS real orbit development", start, 360., 1.,
        description="REAL_OREKIT_DEVELOPMENT_ONLY: orbit-derived targets, not a random/final dataset",
        extra={"development_generation_contract": "gen02.development.v1", "initial_attitudes": initial,
               "visibility_settings": {"min_elevation_deg": 5., "coarse_step_min": 60.},
               "task_source": "deterministic_orbit_subpoints_at_80_180_280_seconds",
               "generator_version": "gen02-dev-1.0.0", "raw_satellite_sha256": satellite_sha,
               "tasks_per_target": tasks_per_target,
               "stress_repeats_are_independent_dataset_roots": False})
    scene = Scenario("caabs-real-dev", [sat], missions, [], MissionInfo(0, [[-80, 80]], [[-180, 180]]), metadata)
    tasks_before = canonical([m.to_dict() for m in missions])
    calculation_start = time.monotonic()
    scene.calculate_visibility_windows(ensure_each_mission_has_window=False, data_path=data_path,
                                       min_elevation_deg=5., coarse_step_min=60.)
    runtime = time.monotonic() - calculation_start
    if canonical([m.to_dict() for m in scene.missions]) != tasks_before:
        raise ValueError("calculator changed frozen tasks")
    if source.read_bytes() != raw or source_identity() != input_identity:
        raise ValueError("generation inputs/deployment changed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Exclusive new run directory; no old data is removed or replaced.
    provenance_dir = output / "provenance"
    provenance_dir.mkdir()
    import tempfile
    staging = Path(tempfile.mkdtemp(prefix=".generation-", dir=output))
    target = output / "scene.json"
    scene.export_to_json(str(staging / "scene.raw"))
    result = json.loads((staging / "scene.raw").read_bytes())
    validation = validate_structure(result)
    payload = canonical(result)
    scenario_sha = hashlib.sha256(payload).hexdigest()
    evidence = {"schema_version": "gen02.development.v1", "scenario_sha256": scenario_sha,
        "completion_status": "complete", "publication_status": "development_only", "formal_release_eligible": False,
        "calculator_kind": "orekit", "parent_scenario_sha256": None,
        "raw_satellite_sha256": satellite_sha, "raw_satellite_path": str(source),
        "task_semantic_sha256": hashlib.sha256(tasks_before).hexdigest(),
        "generator_version": "gen02-dev-1.0.0", "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "window_boundary_version": "visibility_exit_refined_v3",
        "window_generation": result["metadata"]["extra"]["window_generation"],
        "source_files_sha256": input_identity, "orekit_data_sha256": hashlib.sha256(Path(data_path).read_bytes()).hexdigest(),
        "physical_validation": {"status": "NOT_CERTIFIED", "scope": "REAL_GRID_PREDICATE_ONLY"},
        "continuous_certification": {"status": "NOT_RUN", "reason": "NO_CONTINUITY_CERTIFICATE"},
        "calculation_settings": {"time_step": 1., "min_elevation_deg": 5., "ensure_each_mission_has_window": False},
        "validation": validation, "window_runtime_s": runtime}
    temporary = _stage(target, payload)
    _publish_no_replace(temporary, target)
    sidecar = provenance_dir / "scene.json.provenance.json"
    temporary = _stage(sidecar, canonical(evidence))
    _publish_no_replace(temporary, sidecar)
    if hashlib.sha256(target.read_bytes()).hexdigest() != scenario_sha:
        raise ValueError("published hash changed")
    from schedulers.scenario_loader import load_scheduling_problem_from_json
    from utils.continuous_exposure import planning_window
    problem = load_scheduling_problem_from_json(target)
    windows = [w for task in problem.tasks.values() for w in task.windows]
    return {"scenario": str(target), "scenario_sha256": scenario_sha,
            "raw_satellite_sha256": satellite_sha, "tasks": len(problem.tasks), "windows": len(windows),
            "planning_windows": sum(planning_window(w).status.value == "PLANNING_FEASIBLE" for w in windows),
            "window_runtime_s": runtime, "formal_release_eligible": False}


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--satellites", type=Path, default=root / "input/10_satellites.json")
    parser.add_argument("--satellite-id", default="ALOS-2_39766")
    parser.add_argument("--orekit-data", type=Path, required=True)
    parser.add_argument("--tasks-per-target", type=int, default=1, choices=range(1, 9),
                        help="Optional co-located real tasks for cancellation stress, not independent dataset roots")
    args = parser.parse_args(argv)
    from utils.visibility import ensure_orekit
    ensure_orekit(str(args.orekit_data))  # Main thread, before importing Java classes.
    print(json.dumps(generate(args.output, args.satellites, args.satellite_id, str(args.orekit_data),
                              tasks_per_target=args.tasks_per_target), indent=2))


if __name__ == "__main__":
    main()
