"""Reproducible G3 *offline preview* probe; never creates a formal result.

The legacy EOS-Bench input is useful for four Solver/discrete-replay rows, but
CAABS needs trusted window generation evidence. Keep the gate diagnosis beside
the rows so an empty CAABS schedule is never ranked as algorithm quality.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import time

from eos_system.algorithm_registry import get_algorithm
from eos_system.contracts import RunConfig
from eos_system.provenance import capture_provenance
from eos_system.runner import build_constraint_model, prepare
from input.scenario_splitter import split_scenario_file
from schedulers.constraint_model import Schedule
from schedulers.evaluation_metrics import compute_evaluation_metrics
from schedulers.preview_exposure import candidate_exposure
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.schedule_output import schedule_to_dict
from schedulers.source_windows import SourceWindowIndex, validate_plan_source
from schedulers.transition_utils import delta_g_between
from utils.continuous_exposure import ExposureStatus, planning_window
from utils.time_parsing import parse_orbit_epoch


VARIANTS = (
    ("DARTIS-LLF", "dartis", {"priority_mode": "llf"}),
    ("DARTIS-EDF", "dartis", {"priority_mode": "edf"}),
    ("Greedy completion_first", "completion_first", {}),
    ("RABAS", "rabas", {}),
    ("CAABS", "caabs", {}),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discrete_replay(config: RunConfig, candidate: dict, runtime_s: float) -> dict:
    """Use the same source, exposure, constraint and metric entry points as Controller."""
    problem = load_scheduling_problem_from_json(config.scenario_path)
    validate_plan_source(candidate, problem, config.scenario_sha256)
    model = build_constraint_model(problem, config)
    sources = SourceWindowIndex(problem)
    schedule = Schedule()
    seen: set[str] = set()
    raw = candidate.get("assignments")
    if not isinstance(raw, list):
        raise ValueError("candidate assignments must be a list")
    for item in sorted(raw, key=lambda row: parse_orbit_epoch(row["sat_start_time"])):
        task_id = item["task_id"]
        if task_id in seen or task_id not in problem.tasks:
            raise ValueError("duplicate or unknown task: " + task_id)
        seen.add(task_id)
        assignment = sources.restore(item, model)
        window = sources.observations[assignment.sat_window_id][0][1]
        decision = candidate_exposure(
            problem, window, assignment.sat_start_time, assignment.sat_end_time,
            problem.tasks[task_id].required_duration,
        )
        if decision.status is not ExposureStatus.PLANNING_FEASIBLE:
            raise ValueError("exposure: " + decision.reason)
        if not model.is_feasible_assignment(assignment, schedule):
            raise ValueError("public constraint rejection: " + task_id)
        schedule.assignments.append(assignment)
    if set(candidate.get("unassigned_tasks", [])) != set(problem.tasks) - seen:
        raise ValueError("unassigned task set mismatch")
    for satellite in problem.satellites.values():
        if satellite.maneuverability_type != "agile":
            continue
        assigned = sorted(schedule.get_assignments_for_satellite(satellite.id),
                          key=lambda row: row.sat_start_time)
        for previous, following in zip(assigned, assigned[1:]):
            if delta_g_between(previous.sat_angles, following.sat_angles) is None:
                raise ValueError("missing agile attitude evidence")
    metrics = asdict(compute_evaluation_metrics(
        problem, schedule, runtime_seconds=runtime_s,
    ))
    return {
        "completed": len(seen),
        "total": len(problem.tasks),
        "tcr": metrics["task_completion_rate"],
        "tp": metrics["task_profit"],
        "tm": metrics["timeliness_metric"],
        "discrete_replay": "PASS",
    }


def run_variant(scene: Path, scene_sha: str, provenance: dict,
                label: str, algorithm_id: str, params: dict,
                seed: int, budget_s: float) -> dict:
    spec = get_algorithm(algorithm_id)
    config = RunConfig(
        run_id="g3-offline-" + algorithm_id + "-" + (params.get("priority_mode") or "default"),
        scenario_id=load_scheduling_problem_from_json(scene).scenario_id,
        scenario_sha256=scene_sha,
        scenario_path=str(scene),
        source_id="g3_offline_probe",
        scenario_provenance=provenance,
        algorithm_id=algorithm_id,
        algorithm_version=spec.version,
        algorithm_params=params,
        seed=seed,
        time_budget_s=budget_s,
        execution_mode="planning_preview",
        schedule_model="completion_first",
        placement_mode="earliest",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    result = {
        "variant": label, "algorithm_id": algorithm_id, "version": spec.version,
        "params": params, "seed": seed, "budget_s": budget_s,
        "solver_return": "ERROR", "planning_preview": "NOT_RUN",
        "formal_continuous_certification": "NOT_RUN",
    }
    try:
        solver, problem, model, context = prepare(config)
        started = time.perf_counter()
        schedule = solver.solve(problem, model, context)
        runtime_s = time.perf_counter() - started
        candidate = schedule_to_dict(schedule, problem)
        result.update(
            solver_return="NORMAL", solver_rt_s=runtime_s,
            candidate_assignments=len(candidate.get("assignments", [])),
        )
        result.update(discrete_replay(config, candidate, runtime_s))
        metadata = schedule.metadata.get(algorithm_id, {})
        if algorithm_id == "dartis":
            stats = metadata.get("stats", {})
            result["candidate_truncation"] = {
                key: stats.get(key) for key in (
                    "windows_truncated", "positions_truncated",
                    "grid_limited_windows",
                )
            }
            result["search_stop_reason"] = metadata.get("stop_reason")
            result["recomputations"] = stats.get("recomputations")
        elif algorithm_id == "caabs":
            stats = metadata.get("stats", {})
            result["candidate_builder_calls"] = stats.get("candidate_builder_calls")
            result["candidate_truncation"] = None
        else:
            result["candidate_truncation"] = None
    except Exception as exc:
        result["failure_reason"] = type(exc).__name__ + ": " + str(exc)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--tasks", type=int, default=30)
    parser.add_argument("--duration", default="24h")
    parser.add_argument("--split-seed", type=int, default=20260927)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--budget-s", type=float, default=5.0)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    before = sha256(source)
    if args.expected_source_sha and before != args.expected_source_sha:
        raise SystemExit("source SHA mismatch: " + before)
    with tempfile.TemporaryDirectory(prefix="dartis-g3-") as tmp:
        with redirect_stdout(sys.stderr):
            scene = Path(split_scenario_file(
                source, search_root=source.parent, out_dir=tmp,
                num_missions=args.tasks, start_offset="0h", duration=args.duration,
                seed=args.split_seed,
            ))
        scene_sha = sha256(scene)
        problem = load_scheduling_problem_from_json(scene)
        decisions = Counter()
        for task in problem.tasks.values():
            for window in task.windows:
                decision = planning_window(window)
                decisions[decision.status.value + "/" + decision.reason] += 1
        provenance = capture_provenance(scene, scene_sha)
        rows = [
            run_variant(scene, scene_sha, provenance, label, aid, params,
                        args.seed, args.budget_s)
            for label, aid, params in VARIANTS
        ]
        trusted = sum(count for key, count in decisions.items()
                      if key.startswith("PLANNING_FEASIBLE/"))
        if trusted == 0:
            for row in rows:
                if row["algorithm_id"] == "caabs":
                    row["comparison_eligible"] = False
                    row["failure_reason"] = "NO_TRUSTED_WINDOWS_FOR_CAABS"
                else:
                    row["comparison_eligible"] = True
        print(json.dumps({
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True,
            ).strip(),
            "source_path": str(source), "source_sha256": before,
            "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
            "split": {"tasks": args.tasks, "start_offset": "0h",
                      "duration": args.duration, "seed": args.split_seed},
            "search_seed": args.seed, "search_budget_s": args.budget_s,
            "derived_sha256": scene_sha,
            "satellites": len(problem.satellites), "tasks": len(problem.tasks),
            "execution_mode": "planning_preview",
            "source_physics_version": provenance.get("scenario_physics_version"),
            "window_decisions": dict(decisions),
            "common_five_way_input": trusted > 0 and trusted == sum(decisions.values()),
            "objective_weights": {
                "w_profit": 1.0, "w_completion": 0.0,
                "w_timeliness": 0.0, "w_balance": 0.0,
            },
            "variants": rows,
            "source_unchanged": sha256(source) == before,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
