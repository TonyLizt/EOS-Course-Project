#!/usr/bin/env python3
"""Build reproducible Orekit CZML fixtures for the Cesium interpolation A/B test."""

from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from draw.orekit_to_czml import build_czml, init_orekit, propagate_satellite_groundtrack
from utils.time_parsing import parse_orbit_epoch


DEFAULT_SATELLITES = ("KENT_RIDGE_1_41167", "GPM-CORE_39574", "AQUA_27424")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--orekit-data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration-s", type=int, default=1800)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scene = json.loads(args.scenario.read_text(encoding="utf-8"))
    start = parse_orbit_epoch(scene["metadata"]["creation_time"])
    end = start + timedelta(seconds=args.duration_s)
    selected = [sat for sat in scene["satellites"] if sat["id"] in DEFAULT_SATELLITES]
    if {sat["id"] for sat in selected} != set(DEFAULT_SATELLITES):
        raise ValueError("scenario does not contain all benchmark satellites")

    init_orekit(str(args.orekit_data))
    began = time.perf_counter()
    reference: dict[str, list[dict]] = {}
    trails: dict[str, float] = {}
    for satellite in selected:
        op = satellite["orbital_params"]
        reference[satellite["id"]] = propagate_satellite_groundtrack(
            a_m=float(op["semi_major_axis_km"]) * 1000.0,
            e=float(op["eccentricity"]), i_deg=float(op["inclination_deg"]),
            raan_deg=float(op["right_ascension_of_ascending_node_deg"]),
            argp_deg=float(op["argument_of_perigee_deg"]),
            m_deg=float(op["mean_anomaly_deg"]),
            epoch_dt=parse_orbit_epoch(op["epoch"]), start_dt=start, end_dt=end, step_s=1,
        )
        trails[satellite["id"]] = 0.0
    propagation_s = time.perf_counter() - began

    variants = {
        "reference-1s": (1, "LINEAR", 1),
        "baseline-300s": (300, "LINEAR", 1),
        "candidate-30s": (30, "LAGRANGE", 5),
    }
    metrics = {"scenario": str(args.scenario), "duration_s": args.duration_s,
               "satellites": list(DEFAULT_SATELLITES), "reference_propagation_s": propagation_s,
               "variants": {}}
    for name, (step, algorithm, degree) in variants.items():
        samples = {sat_id: values[::step] for sat_id, values in reference.items()}
        path = args.output_dir / f"{name}.czml"
        began = time.perf_counter()
        build_czml(samples, [], trails, str(path))
        packets = json.loads(path.read_text(encoding="utf-8"))
        for packet in packets[1:]:
            packet["position"]["interpolationAlgorithm"] = algorithm
            packet["position"]["interpolationDegree"] = degree
        path.write_text(json.dumps(packets, separators=(",", ":")), encoding="utf-8")
        metrics["variants"][name] = {
            "step_s": step, "algorithm": algorithm, "degree": degree,
            "samples_per_satellite": len(next(iter(samples.values()))),
            "file_bytes": path.stat().st_size, "write_s": time.perf_counter() - began,
            "path": str(path),
        }
    (args.output_dir / "build-metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
