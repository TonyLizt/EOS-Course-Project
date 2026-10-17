#!/usr/bin/env python3
"""Parallel wrapper for publishing large epoch-fixed scenario candidates.

Observation geometry is independent per mission.  Each spawned process starts
its own Orekit VM and computes a disjoint mission shard; the parent merges only
dynamic windows and revalidates the complete unchanged static scenario.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.recompute_scenario_windows import (
    MAX_INPUT_BYTES, _protected, _publish_no_replace, _stage, assert_same,
    build_info, canonical_bytes, file_sha256, recompute_data, static_data,
    unique_pairs, reject_constant, validate_structure,
)
from utils.time_parsing import parse_orbit_epoch


def _mission_shard(payload: tuple[dict, str | None]) -> tuple[list, list]:
    scene, data_path = payload
    candidate, _ = recompute_data(scene, data_path=data_path)
    return candidate["observation_windows"], candidate["communication_windows"]


def covered_mission_ids(candidate: dict) -> set[str]:
    """Return missions having at least one segment long enough to execute."""
    required_duration = {
        row["id"]: float(row["observation_requirement"]["duration_s"])
        for row in candidate["missions"]
    }
    return {
        row["mission_id"]
        for row in candidate["observation_windows"]
        if any(
            (parse_orbit_epoch(window["end_time"])
             - parse_orbit_epoch(window["start_time"])).total_seconds()
            + 1e-9 >= required_duration[row["mission_id"]]
            for window in row["time_windows"]
        )
    }


def recompute_parallel(source: Path, target: Path, *, data_path: str | None,
                       workers: int, max_input_bytes: int,
                       minimum_coverage: float = 0.0) -> dict:
    source = _protected(source, writing=False)
    target = _protected(target, writing=True)
    if (os.path.lexists(target) or source == target
            or "epoch_fixed_v1" not in target.name or target.suffix.lower() != ".json"):
        raise ValueError("output must be a new epoch_fixed_v1 JSON")
    if not 0.0 <= minimum_coverage <= 1.0:
        raise ValueError("minimum coverage must be in [0, 1]")
    original = source.read_bytes()
    if len(original) > max_input_bytes:
        raise ValueError("input exceeds --max-input-mib")
    scene = json.loads(original, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    scene = json.loads(canonical_bytes(scene))
    missions = scene.get("missions", [])
    if not missions:
        raise ValueError("scenario contains no missions")
    source_sha256 = file_sha256(source)
    info_before = build_info()
    wrapper_sha256 = file_sha256(Path(__file__))
    # Resolve dependencies in the parent before starting expensive workers.
    # Passing one explicit ZIP path also guarantees every JVM uses identical
    # Orekit auxiliary data.
    import orekit_jpype  # noqa: F401 - dependency preflight
    from utils.visibility import _find_orekit_data_zip
    data_file = _find_orekit_data_zip(data_path)
    data_sha256 = file_sha256(data_file)
    data_path = str(data_file)
    worker_count = max(1, min(int(workers), len(missions)))
    shards = [[] for _ in range(worker_count)]
    for index, mission in enumerate(missions):
        shards[index % worker_count].append(mission)

    base = dict(static_data(scene), observation_windows=[], communication_windows=[])
    inputs = []
    for missions_shard in shards:
        # Do not duplicate the potentially 100+ MiB legacy window arrays into
        # every worker payload; only immutable static inputs are required.
        shard = deepcopy(base)
        shard["missions"] = missions_shard
        shard["observation_windows"] = []
        # Communication geometry is mission-independent.  The benchmark
        # scenarios have no stations; reject rather than duplicate it here.
        if shard.get("ground_stations"):
            raise ValueError("parallel wrapper currently requires no ground stations")
        shard["communication_windows"] = []
        inputs.append((shard, data_path))

    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as pool:
        results = list(pool.map(_mission_shard, inputs))

    candidate = deepcopy(scene)
    candidate["observation_windows"] = [window for observations, _ in results for window in observations]
    candidate["communication_windows"] = []
    assert_same(static_data(scene), static_data(candidate), "static fields changed")
    validation = validate_structure(candidate)
    covered = validation["missions_with_windows"]
    coverage = covered / len(missions)
    if coverage + 1e-12 < minimum_coverage:
        raise ValueError(
            f"only {covered}/{len(missions)} missions have a physically valid "
            f"window; below minimum coverage {minimum_coverage:.6f}"
        )
    covered_ids = covered_mission_ids(candidate)
    missing_mission_ids = [row["id"] for row in missions if row["id"] not in covered_ids]
    payload = canonical_bytes(candidate) + b"\n"
    if file_sha256(source) != source_sha256:
        raise ValueError("source changed during parallel recomputation")
    if file_sha256(data_file) != data_sha256:
        raise ValueError("Orekit data changed during parallel recomputation")
    if build_info() != info_before:
        raise ValueError("recompute source code changed during parallel recomputation")
    if file_sha256(Path(__file__)) != wrapper_sha256:
        raise ValueError("parallel wrapper changed during recomputation")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = _stage(target, payload)
    try:
        _publish_no_replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "source": str(source), "source_sha256": source_sha256,
        "scenario_path": str(target), "scenario_sha256": file_sha256(target),
        "workers": worker_count, "structure_validation": validation,
        "mission_window_coverage": coverage,
        "missing_mission_ids": missing_mission_ids,
        "orekit_data_sha256": data_sha256,
        "orekit_jpype_version": importlib.metadata.version("orekit_jpype"),
        "parallel_wrapper_sha256": wrapper_sha256, "build_info": info_before,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--orekit-data", type=Path)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--max-input-mib", type=int, default=64)
    parser.add_argument("--minimum-coverage", type=float, default=0.0,
                        help="optional early candidate gate; formal release uses --minimum-tcr")
    args = parser.parse_args()
    result = recompute_parallel(
        args.scenario, args.out,
        data_path=str(args.orekit_data) if args.orekit_data else None,
        workers=args.workers, max_input_bytes=args.max_input_mib * 1024 * 1024,
        minimum_coverage=args.minimum_coverage,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
