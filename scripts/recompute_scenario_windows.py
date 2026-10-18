#!/usr/bin/env python3
"""Recompute a frozen legacy scenario into an unpublished E2 candidate bundle.

Only observation_windows and communication_windows are replaced. The JSON is
the source of truth; calculator objects are disposable projections, not default
Satellite constructors or Scenario.export_to_json round trips. A provenance
sidecar is the final completion marker. E3/E4 acceptance remains external.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.time_parsing import EPOCH_PARSER_VERSION, parse_orbit_epoch
from scripts.build_scenario_manifest import Validator, ARRAY_FIELDS, registry_id, unique_pairs, reject_constant

PHYSICS_VERSION = "epoch_fixed_v1"
DYNAMIC_FIELDS = frozenset({"observation_windows", "communication_windows"})
MAX_INPUT_BYTES = 64 * 1024 * 1024


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def static_data(scene):
    """Keep ALL unknown fields; only two contracted top-level fields may change."""
    return {key: value for key, value in scene.items() if key not in DYNAMIC_FIELDS}


def field_differences(before, after, path="$", limit=20):
    differences = []
    if type(before) is not type(after):
        return [f"{path}: {before!r} -> {after!r}"]
    if isinstance(before, dict):
        for key in sorted(before.keys() | after.keys()):
            if key not in before or key not in after:
                differences.append(f"{path}.{key}: added or removed")
            else:
                differences.extend(field_differences(before[key], after[key], f"{path}.{key}", limit))
            if len(differences) >= limit:
                break
    elif isinstance(before, list):
        if len(before) != len(after):
            differences.append(f"{path}.length: {len(before)} -> {len(after)}")
        for index, (old, new) in enumerate(zip(before, after)):
            differences.extend(field_differences(old, new, f"{path}[{index}]", limit))
            if len(differences) >= limit:
                break
    elif before != after:
        differences.append(f"{path}: {before!r} -> {after!r}")
    return differences[:limit]


def assert_same(before, after, label):
    if digest(before) != digest(after):
        raise ValueError(f"FAIL {label}: " + "; ".join(field_differences(before, after)))


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: expected finite JSON number")
    if positive and value <= 0:
        raise ValueError(f"{name}: expected positive number")
    return float(value)


def _location(location, name):
    lat = _number(location.latitude, name + ".latitude")
    lon = _number(location.longitude, name + ".longitude")
    _number(location.altitude_km, name + ".altitude_km")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError(f"{name}: latitude/longitude out of range")
    location.altitude = location.altitude_km


def visibility_settings(scene):
    # Legacy exports omit overrides: use the unchanged generator defaults.
    settings = scene["metadata"].get("extra", {}).get("visibility_settings", {})
    if not isinstance(settings, dict) or set(settings) - {"min_elevation_deg", "coarse_step_min"}:
        raise ValueError("unsupported metadata.extra.visibility_settings")
    return dict(min_elevation_deg=_number(settings.get("min_elevation_deg", 5.0), "min_elevation_deg"),
                coarse_step_min=_number(settings.get("coarse_step_min", 60.0), "coarse_step_min", positive=True))


def _namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    return value


def _plain(value):
    if isinstance(value, SimpleNamespace):
        return {key: _plain(item) for key, item in vars(value).items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def calculator_inputs(scene):
    """Project only legacy API aliases; retain every supplied static attribute.

    This API reads orbit elements, attitude limits and target positions. It does
    not consume FOV/resources. Unsupported sensor identity is rejected, not
    renamed. No constructor may reset a supplied capability to its defaults.
    """
    meta = scene["metadata"]
    start = parse_orbit_epoch(meta["creation_time"], field_name="metadata.creation_time")
    duration = _number(meta["duration"], "metadata.duration", positive=True)
    step = _number(meta["time_step"], "metadata.time_step", positive=True)
    end = start + timedelta(seconds=duration)
    if "end_time" in meta and parse_orbit_epoch(meta["end_time"], field_name="metadata.end_time") != end:
        raise ValueError("metadata.end_time conflicts with creation_time + duration")
    satellites = []
    aliases = {"semi_major_axis": "semi_major_axis_km", "inclination": "inclination_deg",
               "argument_of_perigee": "argument_of_perigee_deg",
               "right_ascension_of_ascending_node": "right_ascension_of_ascending_node_deg",
               "mean_anomaly": "mean_anomaly_deg"}
    for raw in scene["satellites"]:
        sat = _namespace(raw)
        sensors = raw["observation_capability"]["sensors"]
        if len(sensors) != 1 or sensors[0]["sensor_id"] != f"{sat.id}_sensor":
            raise ValueError(f"satellite {sat.id}: unsupported custom/multiple sensors; "
                             "legacy API hardcodes sensor ID; public API proposal required")
        # Require the exported static capability blocks rather than invent defaults.
        if not isinstance(raw["satellite_specs"], dict) or not raw["orbital_type"]:
            raise ValueError(f"satellite {sat.id}: missing static capabilities")
        for field in ("resolution", "sensor_mode", "field_of_view_deg", "observation_swath_width_km",
                      "data_rate_Mbps", "power_consumption_W", "min_elevation_angle_deg"):
            sensors[0][field]
        op = sat.orbital_params
        parse_orbit_epoch(op.epoch, satellite_id=sat.id)
        op.initial_representation_Epoch = op.epoch
        for alias, field in aliases.items():
            setattr(op, alias, _number(getattr(op, field), f"{sat.id}.{field}"))
        _number(op.eccentricity, f"{sat.id}.eccentricity")
        if op.semi_major_axis <= 0 or not 0 <= op.eccentricity < 1:
            raise ValueError(f"{sat.id}: expected elliptic orbit with positive semi-major axis")
        for axis in ("pitch", "yaw", "roll"):
            field = f"max_{axis}_angle"
            value = _number(getattr(sat.maneuverability_capability, field + "_deg"), f"{sat.id}.{field}")
            setattr(sat.maneuverability_capability, field, value)
        satellites.append(sat)
    missions = []
    for raw in scene["missions"]:
        mission = _namespace(raw)
        _location(mission.target_location, f"mission {mission.id}.target_location")
        missions.append(mission)
    stations = []
    for raw in scene.get("ground_stations", []):
        station = _namespace(raw)
        _location(station.location, f"station {station.id}.location")
        stations.append(station)
    return dict(scenario_name=scene["scenario_id"], start_time=start, end_time=end,
                satellites=satellites, missions=missions, ground_stations=stations,
                mission_info=None, step_seconds=step, ensure_each_mission_has_window=False,
                **visibility_settings(scene),
                progress=False)


def validate_structure(scene):
    """Reuse the existing manifest validator without reading/writing a manifest."""
    validator = Validator(Path("candidate.json"))
    for key, value in scene.items():
        if key in ARRAY_FIELDS and isinstance(value, list):
            validator.first(key, "array", None)
            for item in value:
                validator.first(key, "item", item)
        else:
            validator.first(key, "value", value)
    validator.prepare()
    for key in DYNAMIC_FIELDS:
        for item in scene.get(key, []):
            validator.second(key, "item", item)
    validator.finish()
    if validator.level == "FAIL":
        raise ValueError("FAIL structure: " + json.dumps(validator.issues, ensure_ascii=False))
    return {"status": validator.level, "checks": validator.issues,
            "mission_count": len(scene["missions"]), "missions_with_windows": validator.row["missions_with_windows"],
            "observation_segments": validator.row["observation_segment_count"],
            "communication_segments": validator.row["communication_window_count"]}


def serialize_windows(observations, communications):
    def time_window(window, *, observation=False):
        if isinstance(window.orbit_number, bool) or not isinstance(window.orbit_number, int) or window.orbit_number < 1:
            raise ValueError("missing/invalid recomputed orbit_number")
        if observation and (window.agile_data is None or window.non_agile_data is None):
            raise ValueError("recomputed observation must include agile and representative attitudes")
        result = {"start_time": parse_orbit_epoch(window.start_time).isoformat(),
                  "end_time": parse_orbit_epoch(window.end_time).isoformat(),
                  "orbit_number": window.orbit_number}
        if window.agile_data is not None:
            result["agile_data"] = {f"{axis}_angles": getattr(window.agile_data, f"{axis}_angles")
                                    for axis in ("pitch", "yaw", "roll")}
        if window.non_agile_data is not None:
            quaternions = getattr(window.agile_data, "boundary_quaternions_xyzw", None)
            if quaternions is not None:
                result["agile_data"]["boundary_quaternions_xyzw"] = quaternions
            result["non_agile_data"] = {f"{axis}_angle": getattr(window.non_agile_data, f"{axis}_angle")
                                        for axis in ("pitch", "yaw", "roll")}
        return result
    return {
        "observation_windows": [{"satellite_id": w.satellite_id, "sensor_id": w.sensor_id,
                                  "mission_id": w.mission_id,
                                  "time_windows": [time_window(t, observation=True) for t in w.time_window]} for w in observations],
        "communication_windows": [{"satellite_id": w.satellite_id, "ground_station_id": w.ground_station_id,
                                    "time_windows": [time_window(t) for t in w.time_window]} for w in communications],
    }


def recompute_data(scene, *, calculator=None, data_path=None):
    frozen = deepcopy(scene)
    # Validate static schema independently of possibly corrupt legacy windows.
    static = static_data(frozen)
    validate_structure(dict(static, observation_windows=[], communication_windows=[]))
    inputs = calculator_inputs(frozen)
    before_objects = _plain(inputs["satellites"] + inputs["missions"] + inputs["ground_stations"])
    if calculator is None:
        from utils.visibility import calculate_windows_orekit
        calculator = calculate_windows_orekit
    observations, communications, updated_missions = calculator(**inputs, data_path=data_path)
    after_objects = _plain(inputs["satellites"] + inputs["missions"] + inputs["ground_stations"])
    assert_same(before_objects, after_objects, "calculator mutated static objects")
    assert_same(_plain(inputs["missions"]), _plain(updated_missions), "calculator replaced missions")
    if not inputs["ground_stations"] and communications:
        raise ValueError("communication windows returned without ground stations")
    candidate = deepcopy(frozen)
    candidate.update(serialize_windows(observations, communications))
    assert_same(static, static_data(candidate), "static fields changed")
    validation = validate_structure(candidate)
    return candidate, validation


def build_info():
    files = ("scripts/recompute_scenario_windows.py", "utils/time_parsing.py", "utils/visibility.py",
             "utils/continuous_exposure.py",
             "scripts/build_scenario_manifest.py", "core/models.py")
    info = {"source_files_sha256": {name: file_sha256(ROOT / name) for name in files},
            "python_version": sys.version.split()[0], "base_git_sha": None, "recompute_tool_git_sha": None,
            "code_identity_kind": "working_tree_files_plus_base_commit"}
    try:
        info["base_git_sha"] = subprocess.check_output(
            ["git", "--no-optional-locks", "rev-parse", "HEAD"], cwd=ROOT,
            stderr=subprocess.DEVNULL, text=True, timeout=10).strip()
        # A base HEAD is not the running tool's commit when files are untracked
        # or modified. In that case only the actual source hashes identify it.
        tracked = subprocess.run(["git", "--no-optional-locks", "ls-files", "--error-unmatch", "--", *files],
                                 cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if tracked.returncode == 0:
            unchanged = subprocess.run(["git", "--no-optional-locks", "diff", "--quiet", "HEAD", "--", *files],
                                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if unchanged.returncode == 0:
                info["recompute_tool_git_sha"] = info["base_git_sha"]
                info["code_identity_kind"] = "git_commit_plus_source_file_hashes"
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def _protected(path, *, writing):
    lexical = Path(os.path.abspath(Path(path).expanduser()))
    if writing and lexical.is_symlink():
        raise ValueError(f"output already exists: {path}")
    roots = [ROOT / "input", ROOT / "output"]
    if writing:
        roots += [ROOT / "experiments" / "scenarios", ROOT / ".git"]
    for candidate in (lexical, lexical.resolve()):
        if any(candidate == root or root in candidate.parents for root in roots):
            raise ValueError(f"protected path: {path}")
    return lexical.resolve()


def sidecar_path(out):
    return out.parent / "provenance" / (out.name + ".provenance.json")


def _stage(path, payload):
    descriptor, name = tempfile.mkstemp(prefix=".epoch-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _publish_no_replace(temporary, target):
    # Atomic directory entry creation, unlike replace()/POSIX rename() which
    # overwrite. Both names are on the destination filesystem. No unsafe fallback.
    os.link(temporary, target)


def recompute_file(scenario, out, *, calculator=None, data_path=None,
                   expected_source_sha256=None, max_input_bytes=MAX_INPUT_BYTES):
    source = _protected(scenario, writing=False)
    target = _protected(out, writing=True)
    if source == target or os.path.lexists(target):
        raise ValueError("output must be new and different from input")
    if PHYSICS_VERSION not in target.name or target.suffix.lower() != ".json":
        raise ValueError("output name must contain epoch_fixed_v1 and end in .json")
    if source.parent == target.parent:
        raise ValueError("use an independent output directory for epoch_fixed_v1 candidates")
    sidecar = _protected(sidecar_path(target), writing=True)
    if os.path.lexists(sidecar):
        raise ValueError("provenance output already exists")
    # Bounded in-memory implementation. Increasing the limit is explicit; this
    # is not a streaming large-scenario reconstruction implementation.
    with source.open("rb") as stream:
        original = stream.read(max_input_bytes + 1)
    if len(original) > max_input_bytes:
        raise ValueError("input exceeds memory safety limit; raise --max-input-mib explicitly")
    source_sha = hashlib.sha256(original).hexdigest()
    if expected_source_sha256 is not None and source_sha != expected_source_sha256:
        raise ValueError("source SHA-256 differs from frozen input hash")
    scene = json.loads(original, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    # Normalize dict subclasses only; all JSON values and ordering of arrays stay intact.
    scene = json.loads(canonical_bytes(scene))
    info_before = build_info()
    data_file = None
    data_sha = None
    window_boundary_version = None
    if calculator is None:
        from utils.visibility import _find_orekit_data_zip, VISIBILITY_ALGORITHM_VERSION
        data_file = _find_orekit_data_zip(data_path)
        data_sha = file_sha256(data_file)
        window_boundary_version = VISIBILITY_ALGORITHM_VERSION
    candidate, validation = recompute_data(scene, calculator=calculator, data_path=data_path)
    payload = canonical_bytes(candidate) + b"\n"
    result_sha = hashlib.sha256(payload).hexdigest()
    if file_sha256(source) != source_sha:
        raise ValueError("source changed during recomputation")
    if build_info() != info_before:
        raise ValueError("recompute source code changed during calculation")
    propagation_version = None
    if calculator is None:
        if file_sha256(data_file) != data_sha:
            raise ValueError("Orekit data changed during calculation")
        try:
            propagation_version = "orekit-keplerian/orekit_jpype-" + importlib.metadata.version("orekit_jpype")
        except importlib.metadata.PackageNotFoundError:
            pass
    from utils.continuous_exposure import window_generation_record
    generation = (window_generation_record(scene["metadata"]["time_step"], **visibility_settings(scene))
                  if calculator is None else None)
    provenance = dict(info_before, scenario_physics_version=PHYSICS_VERSION,
                      epoch_parser_version=EPOCH_PARSER_VERSION, propagation_version=propagation_version,
                      window_boundary_version=window_boundary_version,
                      window_generation=generation,
                      continuous_certification={"status": "NOT_RUN", "reason": "window precision is not continuity proof"},
                      orekit_data_sha256=data_sha, parent_scenario_sha256=source_sha,
                      source_scenario_id=scene["scenario_id"], scenario_sha256=result_sha,
                      static_data_sha256=digest(static_data(candidate)),
                      legacy_static_sha256=digest(static_data(scene)),
                      provenance_status="verified", provenance_scope="recompute_lineage_only",
                      source_completion_evidence="caller_declared_frozen_and_hash_rechecked",
                      historical_generator_version=None,
                      source_path=str(source), scenario_path=str(target),
                      registry_id=registry_id({"satellite_count": len(scene["satellites"]),
                                               "mission_count": len(scene["missions"]),
                                               "duration_days": scene["metadata"]["duration"] / 86400,
                                               "sha256": result_sha}),
                      registry_id_status="proposed_not_registered", completion_status="complete",
                      publication_status="candidate_only",
                      formal_release_eligible=False, structure_validation=validation,
                      physical_validation={"status": "NOT_RUN", "reason": "requires independent E3 acceptance"},
                      scheduling_validation={"status": "NOT_RUN"},
                      calculator_kind="orekit" if calculator is None else "injected_test_calculator",
                      ground_station_status="configured" if scene.get("ground_stations") else "no_ground_station_configured",
                      calculation_settings={"ensure_each_mission_has_window": False,
                                            "time_step": scene["metadata"]["time_step"],
                                            **visibility_settings(scene)})
    target.parent.mkdir(parents=True, exist_ok=True)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    staged = []
    linked = []
    try:
        scene_temp = _stage(target, payload)
        staged.append(scene_temp)
        if file_sha256(scene_temp) != result_sha:
            raise ValueError("staged scenario hash mismatch")
        if file_sha256(source) != source_sha:
            raise ValueError("source changed before publication")
        _publish_no_replace(scene_temp, target)
        linked.append((scene_temp, target))
        if file_sha256(target) != result_sha:
            raise ValueError("published scenario hash mismatch")
        provenance["completed_at"] = datetime.now(timezone.utc).isoformat()
        evidence_temp = _stage(sidecar, canonical_bytes(provenance) + b"\n")
        staged.append(evidence_temp)
        # Publish evidence last: a scene without this matching marker is incomplete.
        _publish_no_replace(evidence_temp, sidecar)
        linked.append((evidence_temp, sidecar))
    except BaseException:
        for temporary, published in reversed(linked):
            if published.exists() and os.path.samefile(temporary, published):
                published.unlink()
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path, help="completed, frozen legacy JSON (read only)")
    parser.add_argument("--out", required=True, type=Path, help="new epoch_fixed_v1.json in an independent directory")
    parser.add_argument("--preserve-static-data", required=True, action="store_true", help="require exact static JSON invariance")
    parser.add_argument("--no-resample", required=True, action="store_true", help="keep zero-window tasks and their coordinates")
    parser.add_argument("--expected-source-sha256", help="optional externally frozen input SHA-256")
    parser.add_argument("--orekit-data", type=Path, help="existing orekit-data.zip; never downloaded")
    parser.add_argument("--max-input-mib", type=int, default=64, help="in-memory input size limit (default: 64 MiB)")
    args = parser.parse_args(argv)
    if args.max_input_mib <= 0:
        parser.error("--max-input-mib must be positive")
    try:
        evidence = recompute_file(args.scenario, args.out, data_path=str(args.orekit_data) if args.orekit_data else None,
                                  expected_source_sha256=args.expected_source_sha256,
                                  max_input_bytes=args.max_input_mib * 1024 * 1024)
    except (ValueError, KeyError, AttributeError, TypeError, OSError, ImportError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
