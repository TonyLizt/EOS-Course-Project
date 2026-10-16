"""Read-only E3/E4 audit of a checkout and frozen candidate evidence.

No scene recomputation, promotion, registry, database or cache cleanup occurs.
Reports use a new external directory. A FAIL is an audit finding, not a repair.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.time_parsing import parse_orbit_epoch as utc
from scripts.recompute_scenario_windows import static_data, digest
from eos_system.provenance import capture_provenance
from eos_system.visualization import orbit_cache_file, orbit_cache_path, propagation_identity
from eos_system.config import Settings


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def snapshot(path):
    path = Path(path)
    st = path.stat()
    return dict(sha256=sha(path), size=st.st_size, mtime_ns=st.st_mtime_ns)


def pure_time_checks():
    # Only compile the real serializer function; never bootstrap a JVM here.
    module = ast.parse((ROOT / "draw/orekit_to_czml.py").read_text(encoding="utf-8"))
    function = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "build_czml")
    namespace = dict(json=json, os=os, datetime=datetime, timezone=timezone)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / "draw/orekit_to_czml.py"), "exec"), namespace)
    export = namespace["build_czml"]
    start = utc("2025-11-18T12:00:00Z")
    results = []
    cases = [
        ("fractional_epoch", start.replace(microsecond=123456), start.replace(microsecond=123456) + timedelta(seconds=60)),
        ("mixed_aware_naive", start.replace(tzinfo=None), (start + timedelta(seconds=60)).astimezone(timezone(timedelta(hours=8)))),
        ("invalid_sample_time", "invalid", "invalid"),
    ]
    with tempfile.TemporaryDirectory(prefix="eos-audit-time-") as directory:
        for name, first, last in cases:
            samples = {"s1": [
                dict(time=first, lon_deg=1, lat_deg=2, alt_m=600000),
                dict(time=last, lon_deg=2, lat_deg=3, alt_m=600000)]}
            before = deepcopy(samples)
            target = Path(directory) / (name + ".czml")
            row = dict(check=name, status="FAIL")
            try:
                export(samples, [], {}, str(target))
                doc = json.loads(target.read_bytes())
                actual = utc(doc[0]["clock"]["currentTime"])
                expected = utc(first)
                row.update(encoded_start=actual.isoformat(), expected_start=expected.isoformat(),
                           time_error_s=(actual - expected).total_seconds())
                row["status"] = "PASS" if name != "invalid_sample_time" and actual == expected else "FAIL"
            except Exception as exc:
                row.update(exception_type=type(exc).__name__, reason=str(exc))
                row["status"] = "PASS" if name == "invalid_sample_time" and isinstance(exc, ValueError) else "FAIL"
            row["input_unchanged"] = samples == before
            results.append(row)
    return results


def cache_checks():
    with tempfile.TemporaryDirectory(prefix="eos-audit-cache-") as directory:
        root = Path(directory)
        scene = root / "scene.json"
        scene.write_bytes(b"{}")
        settings = Settings(runtime_dir=root, scenario_dir=root / "scenes")
        source_sha = sha(scene)
        old = root / "visualizations/scenes" / (source_sha + "-v1-s300.czml")
        old.parent.mkdir(parents=True)
        old.write_bytes(b"historical-v1")
        with patch("eos_system.visualization.propagation_identity", return_value="audit-version-0000000000000001"):
            target = orbit_cache_file(settings, source_sha)
            def generate(argv, **unused):
                Path(argv[argv.index("--output") + 1]).write_bytes(b"new-cache")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch("eos_system.visualization.subprocess.run", side_effect=generate):
                actual = orbit_cache_path(settings, scene, source_sha)
        with patch("eos_system.visualization.propagation_identity", return_value="audit-version-0000000000000002"):
            changed = orbit_cache_file(settings, source_sha)
        assert actual == target and target != changed and old.read_bytes() == b"historical-v1"
        return dict(status="PASS", version=2, old_cache_preserved=True,
                    propagation_change_isolates_cache=True, includes_source_sha_and_step=True,
                    actual_propagation_identity=propagation_identity())


def evidence_checks(evidence_root, frozen):
    bundle = evidence_root / "s2-20s20m-grid-v2-lazy-20261016/independent-e3-20261016/batch_registration_review.json"
    frozen[str(bundle)] = snapshot(bundle)
    batch = json.loads(bundle.read_bytes())
    rows = []
    source_names = ("utils/visibility.py", "utils/time_parsing.py", "scripts/recompute_scenario_windows.py", "core/models.py")
    for item in batch["rows"]:
        path = Path(item["candidate"])
        side = path.parent / "provenance" / (path.name + ".provenance.json")
        provenance = json.loads(side.read_bytes())
        parent = Path(provenance["source_path"])
        report = Path(item["authoritative_physics_report"]) if "authoritative_physics_report" in item else path.parent.parent / "independent-e3-20261016/physics_refined_report.json"
        for f in (path, side, parent, report, Path(item["report"])):
            frozen[str(f)] = snapshot(f)
        scene = json.loads(path.read_bytes())
        legacy = json.loads(parent.read_bytes())
        assert sha(path) == provenance["scenario_sha256"] == item["candidate_sha256"]
        assert sha(parent) == provenance["parent_scenario_sha256"]
        assert static_data(scene) == static_data(legacy)
        assert digest(static_data(scene)) == provenance["static_data_sha256"] == item["static_sha256"]
        assert provenance["completion_status"] == "complete"
        gate = "UNEXPECTED_ACCEPTANCE"
        try:
            capture_provenance(path, sha(path))
        except ValueError as exc:
            gate = "PASS_REJECTED_CANDIDATE"
            gate_reason = str(exc)
        versions = {}
        for name in source_names:
            file = ROOT / name
            expected = provenance["source_files_sha256"].get(name)
            raw = file.read_bytes()
            versions[name] = dict(current_bytes_sha256=sha(file), accepted_bytes_sha256=expected,
                                 byte_match=sha(file) == expected,
                                 lf_normalized_matches=hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == expected)
        rows.append(dict(case=item["case"], candidate_sha256=sha(path), static_sha256=item["static_sha256"],
                         segments=item["segments"], prior_boundary_error_upper_s=item["boundary_error_upper_s"],
                         prior_physics="PASS", prior_scheduling="PASS", current_release_gate=gate,
                         gate_reason=gate_reason if gate.startswith("PASS") else "",
                         original_publication_status=provenance["publication_status"],
                         source_comparison=versions))
    return rows


def provenance_contract_probe():
    # Synthetic declarations only. No actual candidate or database is modified.
    with tempfile.TemporaryDirectory(prefix="eos-audit-provenance-") as directory:
        scene = Path(directory) / "probe_epoch_fixed_v1.json"
        scene.write_bytes(b"{}")
        side = scene.parent / "provenance" / (scene.name + ".provenance.json")
        side.parent.mkdir()
        declaration = dict(scenario_sha256=sha(scene), completion_status="complete",
                           publication_status="released", formal_release_eligible=True,
                           physical_validation=dict(status="PASS"),
                           parent_scenario_sha256="a" * 64, scenario_physics_version="epoch_fixed_v1",
                           epoch_parser_version="epoch_parser_v1", propagation_version="probe-test-only")
        side.write_text(json.dumps(declaration), encoding="utf-8")
        captured = capture_provenance(scene, sha(scene))
        return dict(status="WARN", synthetic_declaration_accepted=True,
                    omitted_fields=["window_boundary_version", "static_data_sha256", "scheduling_validation", "bound independent report SHA"],
                    returned_fields=sorted(captured),
                    interpretation="Current minimum contract trusts a local PASS declaration. Stronger release evidence needs owner-approved contract, not a unilateral schema change.")


def orekit_checks(data, fixture_scene, output):
    from utils import visibility as visibility
    visibility.ensure_orekit(str(data))
    from draw import orekit_to_czml as draw
    from org.orekit.orbits import KeplerianOrbit, PositionAngleType
    from org.orekit.propagation.analytical import KeplerianPropagator
    from org.orekit.attitudes import TargetPointing
    from org.orekit.bodies import GeodeticPoint, OneAxisEllipsoid
    from org.orekit.frames import FramesFactory, TopocentricFrame
    from org.orekit.utils import Constants, IERSConventions
    from org.hipparchus.geometry.euclidean.threed import RotationOrder, RotationConvention
    from orekit_jpype.pyhelpers import datetime_to_absolutedate
    from replay.runtime import _orbit_samples, _position_at
    inertial = FramesFactory.getEME2000()
    itrf = FramesFactory.getITRF(IERSConventions.IERS_2010, True)
    earth = OneAxisEllipsoid(Constants.WGS84_EARTH_EQUATORIAL_RADIUS, Constants.WGS84_EARTH_FLATTENING, itrf)
    epoch = datetime(2025, 11, 18, 12, tzinfo=timezone.utc)
    sats = {s["id"]: s for s in fixture_scene["satellites"]}
    selected = ["ALOS-2_39766", "GPM-CORE_39574", "SCD_1_22490"]
    def raw_orbit(op):
        assert op["epoch"] == "18 Nov 2025 12:00:00.000"
        return KeplerianOrbit(op["semi_major_axis_km"] * 1000, op["eccentricity"],
                             math.radians(op["inclination_deg"]), math.radians(op["argument_of_perigee_deg"]),
                             math.radians(op["right_ascension_of_ascending_node_deg"]), math.radians(op["mean_anomaly_deg"]),
                             PositionAngleType.MEAN, inertial, datetime_to_absolutedate(epoch), Constants.WGS84_EARTH_MU)
    def xyz(v):
        return [float(v.getX()), float(v.getY()), float(v.getZ())]
    fixed = []
    for sid in selected:
        op = sats[sid]["orbital_params"]
        raw = KeplerianPropagator(raw_orbit(op))
        main = KeplerianPropagator(visibility._build_keplerian_orbit(visibility._CONTEXT,
            op["semi_major_axis_km"]*1000, op["eccentricity"], op["inclination_deg"],
            op["right_ascension_of_ascending_node_deg"], op["argument_of_perigee_deg"], op["mean_anomaly_deg"], utc(op["epoch"])))
        for seconds in (0, 43200, 86400):
            when = epoch + timedelta(seconds=seconds)
            date = datetime_to_absolutedate(when)
            assert float(date.durationFrom(datetime_to_absolutedate(when.astimezone(timezone(timedelta(hours=8)))))) == 0
            for label, frame in (("EME2000", inertial), ("ITRF", itrf)):
                one, two = raw.propagate(date).getPVCoordinates(frame), main.propagate(date).getPVCoordinates(frame)
                pe, ve = math.dist(xyz(one.getPosition()), xyz(two.getPosition())), math.dist(xyz(one.getVelocity()), xyz(two.getVelocity()))
                assert pe <= 1e-6 and ve <= 1e-9
                fixed.append(dict(satellite=sid, utc=when.isoformat(), frame=label, position_error_m=pe, velocity_error_m_s=ve))
    forms = [
        ("z", "2025-11-18T12:00:00Z", 600),
        ("utc_offset", "2025-11-18T12:00:00+00:00", 600),
        ("plus8", "2025-11-18T20:00:00+08:00", 600),
        ("naive", "2025-11-18T12:00:00", 600),
        ("fractional", "2025-11-18T20:00:00.123456+08:00", 600),
        ("non_multiple_end", "2025-11-18T12:00:00Z", 650)]
    exports = []
    base = {key: value for key, value in fixture_scene.items() if key not in ("observation_windows", "communication_windows")}
    for name, creation, duration in forms:
        scene = deepcopy(base)
        scene["satellites"] = [sats[sid] for sid in selected]
        scene["metadata"] = dict(scene["metadata"], creation_time=creation, duration=duration, time_step=1.0)
        source, target = output / (name + ".json"), output / (name + ".czml")
        save(source, scene)
        draw.demo(str(source), str(target), str(data), orbit_step_s=300)
        packets = json.loads(target.read_bytes())
        encoded_start, encoded_end = map(utc, packets[0]["clock"]["interval"].split("/"))
        expected_start = utc(creation)
        max_error = 0.0
        for packet in packets[1:]:
            if packet.get("id") not in selected:
                continue
            prop = KeplerianPropagator(raw_orbit(sats[packet["id"]]["orbital_params"]))
            points = packet["position"]["cartographicDegrees"]
            for k in range(0, len(points), 4):
                offset, lon, lat, alt = points[k:k+4]
                date = datetime_to_absolutedate(utc(packet["position"]["epoch"]) + timedelta(seconds=offset))
                point = earth.transform(GeodeticPoint(math.radians(lat), math.radians(lon), alt))
                truth = prop.propagate(date).getPVCoordinates(itrf).getPosition()
                max_error = max(max_error, math.dist(xyz(point), xyz(truth)))
        good = encoded_start == expected_start and encoded_end == expected_start + timedelta(seconds=duration) and max_error <= 1e-6
        exports.append(dict(case=name, status="PASS" if good else "FAIL", encoded_start=encoded_start.isoformat(),
                            encoded_end=encoded_end.isoformat(), expected_start=expected_start.isoformat(),
                            expected_end=(expected_start+timedelta(seconds=duration)).isoformat(),
                            max_czml_knot_position_error_m=max_error))
    equivalent = all((output / (name + ".czml")).read_bytes() == (output / "z.czml").read_bytes()
                     for name in ("utc_offset", "plus8", "naive"))
    assert equivalent
    interpolation = []
    packets = json.loads((output / "z.czml").read_bytes())
    for packet in packets:
        sid = packet.get("id")
        if sid not in selected:
            continue
        samples = _orbit_samples(packet)
        prop = KeplerianPropagator(raw_orbit(sats[sid]["orbital_params"]))
        for seconds in (75, 150, 225):
            when = epoch + timedelta(seconds=seconds)
            actual = _position_at(samples, when)
            expected = xyz(prop.propagate(datetime_to_absolutedate(when)).getPVCoordinates(itrf).getPosition())
            interpolation.append(dict(satellite=sid, offset_s=seconds, error_m=math.dist(actual, expected)))
    boundary_cases = [
        ("M009", 39.840578, 46.276756, "2025-11-18T13:11:00Z"),
        ("M020", 39.83204, 109.990869, "2025-11-19T09:21:00Z")]
    op = sats["GPM-CORE_39574"]["orbital_params"]
    windows = []
    for mid, lat, lon, begin in boundary_cases:
        start = utc(begin)
        kw = dict(a_m=op["semi_major_axis_km"]*1000, e=op["eccentricity"], i_deg=op["inclination_deg"],
                  raan_deg=op["right_ascension_of_ascending_node_deg"], argp_deg=op["argument_of_perigee_deg"],
                  m_deg=op["mean_anomaly_deg"], epoch_dt=epoch, start_dt=start, end_dt=start+timedelta(seconds=600),
                  step_s=1, target_lat_deg=lat, target_lon_deg=lon, target_alt_m=0,
                  max_yaw_deg=45, max_pitch_deg=45, max_roll_deg=45, min_elevation_deg=5, coarse_step_min=60)
        main_windows, _, angles = visibility.compute_visibility_and_attitude(**kw)
        geo = GeodeticPoint(math.radians(lat), math.radians(lon), 0)
        topo = TopocentricFrame(earth, geo, "AUDIT_" + mid)
        prop = KeplerianPropagator(raw_orbit(op), TargetPointing(inertial, geo, earth))
        def visible(when):
            date = datetime_to_absolutedate(when)
            state = prop.propagate(date)
            el = float(topo.getElevation(state.getPVCoordinates(inertial).getPosition(), inertial, date))
            rot = state.getAttitude().getRotation().getAngles(RotationOrder.ZYX, RotationConvention.FRAME_TRANSFORM)
            return el > math.radians(5) and all(abs(math.degrees(float(x))) <= 45 for x in rot)
        reference = [start + timedelta(seconds=k) for k in range(600) if visible(start+timedelta(seconds=k))]
        assert reference and main_windows
        grid = reference[0]
        lo, hi = grid-timedelta(seconds=1), grid
        assert not visible(lo) and visible(hi)
        while (hi-lo).total_seconds() > 0.000001:
            at = lo + (hi-lo)/2
            if visible(at):
                hi = at
            else:
                lo = at
        actual = main_windows[0][0]
        error_upper = (actual-lo).total_seconds()
        windows.append(dict(mission=mid, status="PASS" if error_upper < 1 else "FAIL",
                            main_start=actual.isoformat(), independent_first_grid=grid.isoformat(),
                            reference_entry_lower=lo.isoformat(), reference_entry_upper=hi.isoformat(),
                            boundary_error_upper_s=error_upper, start_trim_s=(actual-grid).total_seconds(),
                            main_attitude_samples=len(angles), reference_visible_samples=len(reference)))
    return dict(fixed_pv=dict(status="PASS", rows=fixed), equivalent_utc_inputs="PASS",
                public_exports=exports, backend_linear_interpolation=dict(status="WARN", rows=interpolation),
                boundary_regressions=windows, browser_cesium="NOT_RUN")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--orekit-data", type=Path)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    if output.is_relative_to(ROOT):
        parser.error("reports must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    frozen = {}
    source_files = [ROOT/name for name in ("draw/orekit_to_czml.py", "utils/visibility.py",
        "utils/time_parsing.py", "scripts/recompute_scenario_windows.py", "eos_system/provenance.py",
        "eos_system/visualization.py", "replay/runtime.py", "eos_system/runner.py")]
    source_before = {str(path): snapshot(path) for path in source_files}
    result = dict(scope="Read-only current-main E3/E4 review; no complete generation, promotion or database access",
                  source_sha256={str(p.relative_to(ROOT)): sha(p) for p in source_files},
                  pure_time=pure_time_checks(), cache=cache_checks(),
                  candidates=evidence_checks(args.evidence_root, frozen),
                  provenance_contract=provenance_contract_probe())
    if args.orekit_data:
        data = args.orekit_data.resolve()
        frozen[str(data)] = snapshot(data)
        assert sha(data) == "1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985"
        source = args.evidence_root/"s1-20s20m-1d-20261016/candidate/Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1.json"
        frozen[str(source)] = snapshot(source)
        assert sha(source) == "5e7a7702d60d194f403c30b157089243135b4287bef48b4114af5c83899addda"
        result["orekit"] = orekit_checks(data, json.loads(source.read_bytes()), output)
    else:
        result["orekit"] = dict(status="NOT_RUN")
    assert all(snapshot(path) == value for path, value in frozen.items()), "input evidence changed"
    assert all(snapshot(path) == value for path, value in source_before.items()), "source changed"
    result.update(status="FAIL" if any(row["status"] == "FAIL" for row in result["pure_time"])
                  or any(row["status"] == "FAIL" for row in result["orekit"].get("public_exports", []))
                  or any(row["status"] == "FAIL" for row in result["orekit"].get("boundary_regressions", [])) else "WARN",
                  inputs_unchanged=True, sources_unchanged=True, frozen_files=frozen,
                  wall_s=time.perf_counter()-started, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  completed_at=datetime.now(timezone.utc).isoformat())
    save(output/"audit_results.json", result)
    save(output/"evidence_index.json", {str(p.relative_to(output)): snapshot(p) for p in sorted(output.rglob("*")) if p.is_file()})
    print(json.dumps({key:value for key,value in result.items() if key not in ("frozen_files", "candidates", "source_sha256", "orekit")}, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
