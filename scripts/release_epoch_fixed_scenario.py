#!/usr/bin/env python3
"""Validate and release one epoch-corrected scenario without changing it.

The recomputation step deliberately publishes candidate-only data.  This tool
performs the project-side E3/E4 gates needed by the experiment API: exact
static-data lineage, structural validation, full-exposure geometry guardrails,
and repeated feasible completion-first schedules.  Only the small provenance
sidecar is written, and an existing sidecar is never replaced.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithms.factory import create_algorithm
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.engine import SchedulingEngine
from schedulers.scenario_loader import load_scheduling_problem_from_json
from scripts.recompute_scenario_windows import (
    PHYSICS_VERSION,
    _publish_no_replace,
    _stage,
    assert_same,
    build_info,
    canonical_bytes,
    digest,
    file_sha256,
    registry_id,
    sidecar_path,
    static_data,
    validate_structure,
    visibility_settings,
)
from utils.time_parsing import EPOCH_PARSER_VERSION
from utils.visibility import _find_orekit_data_zip


def _verify_schedule(problem, schedule) -> None:
    """Replay every assignment through the shared constraint model."""
    verifier = ConstraintModel(problem)
    accepted = Schedule()
    for assignment in sorted(schedule.assignments, key=lambda item: item.sat_start_time):
        if not verifier.is_feasible_assignment(assignment, accepted):
            raise ValueError(f"constraint verifier rejected {assignment.task_id}")
        accepted.assignments.append(assignment)


def validate_release(legacy: Path, candidate: Path, *, seeds: tuple[int, ...],
                     minimum_tcr: float, orekit_data: str | None = None) -> dict:
    legacy = legacy.expanduser().resolve()
    candidate = candidate.expanduser().resolve()
    if not legacy.is_file() or legacy.is_symlink():
        raise ValueError("legacy source must be a regular file")
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("candidate must be a regular file")
    if PHYSICS_VERSION not in candidate.stem:
        raise ValueError(f"candidate name must contain {PHYSICS_VERSION}")
    evidence_path = sidecar_path(candidate)
    if evidence_path.exists() or evidence_path.is_symlink():
        raise ValueError("release sidecar already exists")
    source = json.loads(legacy.read_bytes())
    corrected = json.loads(candidate.read_bytes())
    assert_same(static_data(source), static_data(corrected), "static lineage changed")
    structure = validate_structure(corrected)
    window_coverage = structure["missions_with_windows"] / structure["mission_count"]
    if window_coverage + 1e-12 < minimum_tcr:
        raise ValueError(
            f"corrected window coverage {window_coverage:.6f} is below {minimum_tcr:.6f}"
        )

    problem = load_scheduling_problem_from_json(candidate)
    isolated = ConstraintModel(problem)
    physically_schedulable = 0
    for task in problem.tasks.values():
        if isolated.build_feasible_assignment_for_task(task, Schedule()) is not None:
            physically_schedulable += 1
    physical_coverage = physically_schedulable / len(problem.tasks) if problem.tasks else 0.0
    if physical_coverage + 1e-12 < minimum_tcr:
        raise ValueError(
            f"only {physically_schedulable}/{len(problem.tasks)} missions have a "
            f"full-exposure geometry-valid assignment; below {minimum_tcr:.6f}"
        )

    scheduling_runs = []
    for seed in seeds:
        constraints = ConstraintModel(problem)
        schedule = SchedulingEngine(
            problem,
            constraints,
            create_algorithm("completion_first", cfg_overrides={"seed": seed}),
        ).run()
        _verify_schedule(problem, schedule)
        completed = len(set(schedule.assigned_task_ids))
        tcr = completed / len(problem.tasks) if problem.tasks else 0.0
        scheduling_runs.append({"seed": seed, "completed": completed, "tcr": tcr})
        if tcr + 1e-12 < minimum_tcr:
            raise ValueError(f"seed {seed} TCR {tcr:.6f} is below {minimum_tcr:.6f}")

    orekit_file = _find_orekit_data_zip(orekit_data)
    try:
        orekit_version = importlib.metadata.version("orekit_jpype")
    except importlib.metadata.PackageNotFoundError:
        orekit_version = "unknown"
    scenario_sha = file_sha256(candidate)
    source_sha = file_sha256(legacy)
    evidence = {
        **build_info(),
        "scenario_physics_version": PHYSICS_VERSION,
        "epoch_parser_version": EPOCH_PARSER_VERSION,
        "propagation_version": f"orekit-keplerian/orekit_jpype-{orekit_version}",
        "orekit_data_sha256": file_sha256(orekit_file),
        "parent_scenario_sha256": source_sha,
        "source_scenario_id": source["scenario_id"],
        "scenario_sha256": scenario_sha,
        "static_data_sha256": digest(static_data(corrected)),
        "legacy_static_sha256": digest(static_data(source)),
        "provenance_status": "verified",
        "provenance_scope": "recompute_lineage_and_project_acceptance",
        "source_path": str(legacy),
        "scenario_path": str(candidate),
        "registry_id": registry_id({
            "satellite_count": len(corrected["satellites"]),
            "mission_count": len(corrected["missions"]),
            "duration_days": corrected["metadata"]["duration"] / 86400,
            "sha256": scenario_sha,
        }),
        "registry_id_status": "released",
        "completion_status": "complete",
        "publication_status": "released",
        "formal_release_eligible": True,
        "structure_validation": structure,
        "physical_validation": {
            "status": "PASS",
            "method": "shared full-exposure 1-second earth-occlusion guard",
            "missions_with_geometry_valid_assignment": physically_schedulable,
            "mission_count": len(problem.tasks),
            "coverage": physical_coverage,
        },
        "scheduling_validation": {
            "status": "PASS",
            "algorithm": "completion_first/baseline-1",
            "minimum_tcr": minimum_tcr,
            "runs": scheduling_runs,
        },
        "calculation_settings": {
            "ensure_each_mission_has_window": False,
            "time_step": corrected["metadata"]["time_step"],
            **visibility_settings(corrected),
        },
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    # Recheck immutable inputs immediately before publishing the trust marker.
    if file_sha256(legacy) != source_sha or file_sha256(candidate) != scenario_sha:
        raise ValueError("source or candidate changed during release validation")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _stage(evidence_path, canonical_bytes(evidence) + b"\n")
    try:
        _publish_no_replace(temporary, evidence_path)
    finally:
        temporary.unlink(missing_ok=True)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", required=True, type=Path)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--seed", type=int, action="append", dest="seeds")
    parser.add_argument("--minimum-tcr", type=float, default=0.92)
    parser.add_argument("--orekit-data", type=Path)
    args = parser.parse_args()
    seeds = tuple(args.seeds or (1, 42, 99))
    if not seeds or not 0.0 <= args.minimum_tcr <= 1.0:
        parser.error("at least one seed and a minimum TCR in [0, 1] are required")
    result = validate_release(
        args.legacy,
        args.scenario,
        seeds=seeds,
        minimum_tcr=args.minimum_tcr,
        orekit_data=str(args.orekit_data) if args.orekit_data else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
