"""Serial paired CAABS study. Synthetic replay is NOT physical certification.

Each job runs in a fresh process. Profile/memory runs are separate diagnostics;
their instrumented RT must never be mixed with ordinary wall-clock results.
No final-test discovery: shared inputs come only from a public split allowlist.
"""
from __future__ import annotations

import argparse
import cProfile
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import pstats
import subprocess
import sys
import time
import tracemalloc
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = "f344af9704d5839578b69caed4534a74374cab90"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def implementation(ref):
    if ref == "current":
        import algorithms.conflict_beam as module
        return module, (ROOT / "algorithms/conflict_beam.py").read_bytes()
    source = subprocess.check_output(
        ["git", "show", f"{ref}:algorithms/conflict_beam.py"], cwd=ROOT)
    module = types.ModuleType("caabs_benchmark_baseline")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{ref}:algorithms/conflict_beam.py", "exec"), module.__dict__)
    return module, source


def problem_for(job):
    from schedulers.scenario_loader import load_scheduling_problem_from_json
    from scripts.rabas_study_fixtures import fixture
    if job["suite"] == "synthetic":
        return fixture(job["n"], job["family"], job["scenario_seed"])
    return load_scheduling_problem_from_json(Path(job["path"]))


def run_job(job, directory):
    from algorithms.objectives import ObjectiveWeights
    from algorithms.solver_contracts import SolveContext
    from schedulers.constraint_model import ConstraintModel, Schedule
    from schedulers.evaluation_metrics import compute_evaluation_metrics
    from schedulers.schedule_output import schedule_to_dict
    from schedulers.source_windows import SourceWindowIndex, validate_plan_source

    row = dict(job)
    module, source = implementation(job["ref"])
    row["implementation_sha256"] = hashlib.sha256(source).hexdigest()
    problem = problem_for(job)
    constraints = ConstraintModel(problem, placement_mode="earliest", agility_profile="Standard-Agility")
    config = None
    if job["suite"] != "synthetic":
        from eos_system.contracts import RunConfig
        from eos_system.provenance import capture_execution_provenance
        from eos_system.runner import build_constraint_model
        path = Path(job["path"])
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance = capture_execution_provenance(path, sha, "physical_validation")
        config = RunConfig(run_id=job["id"], created_at="2026-10-21T00:00:00Z",
            scenario_id=problem.scenario_id, scenario_path=str(path), scenario_sha256=sha,
            scenario_provenance=provenance, algorithm_id="caabs", algorithm_version=module.VERSION,
            time_budget_s=job["budget"], seed=job["seed"], execution_mode="physical_validation",
            objective_weights=job["weights"], algorithm_params=job["params"])
        from eos_system.provenance import verify_provenance
        verify_provenance(config)
        constraints = build_constraint_model(problem, config)
        row["scenario_file_sha256"] = sha
        row["provenance"] = provenance
    before = digest(asdict(problem))
    params = module.CAABSParams(**job["params"])
    context = SolveContext(job["seed"], job["budget"], ObjectiveWeights(**job["weights"]), params)
    row.update(scenario_sha256=before, total=len(problem.tasks), satellites=len(problem.satellites),
        effective_params=params.model_dump(), constraints=dict(placement_mode=constraints.placement_mode,
        agility_profile=constraints.agility_profile, downlink_duration_ratio=constraints.downlink_duration_ratio,
        non_agile_transition_s=constraints.non_agile_transition_s, unassigned_penalty=constraints.unassigned_penalty))
    profiler = cProfile.Profile() if job["instrument"] == "profile" else None
    if job["instrument"] == "memory":
        tracemalloc.start()
    if profiler:
        profiler.enable()
    started = time.perf_counter()
    plan = module.ConflictBeamScheduler().solve(problem, constraints, context)
    runtime = time.perf_counter() - started
    if profiler:
        profiler.disable()
        profiler.dump_stats(str(directory / (job["id"] + ".prof")))
        groups = {}
        names = {"candidate_build": {"build", "_windows", "build_feasible_assignment_for_task"},
                 "public_constraint": {"is_feasible_assignment"}, "schedule_copy": {"clone_schedule", "branch_schedule"},
                 "objective": {"score"}, "state_key": {"canonical_state_key", "canonical_assignment_key"}}
        for category, functions in names.items():
            groups[category] = [{"file": key[0], "function": key[2], "calls": value[1],
                "self_s": value[2], "cumulative_s": value[3]}
                for key, value in pstats.Stats(profiler).stats.items() if key[2] in functions]
        row["profile"] = groups
    if job["instrument"] == "memory":
        row["peak_python_bytes"] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    candidate = schedule_to_dict(plan, problem)
    (directory / (job["id"] + ".plan.json")).write_text(json.dumps(candidate), encoding="utf-8")
    row.update(runtime=runtime, diagnostic_completed=len(plan.assignments), diagnostics=plan.metadata,
        plan_sha256=digest(candidate), input_unchanged=before == digest(asdict(problem)))
    if not row["input_unchanged"]:
        raise AssertionError("solver mutated scenario")
    # Rebuild the problem and authoritative model independently of solver state.
    fresh = problem_for(job)
    if config:
        fresh_constraints = build_constraint_model(fresh, config)
        validate_plan_source(candidate, fresh, config.scenario_sha256)
        sources = SourceWindowIndex(fresh)
        assignments = [sources.restore(item, fresh_constraints) for item in candidate["assignments"]]
    else:
        from copy import deepcopy
        fresh_constraints = ConstraintModel(fresh, placement_mode="earliest", agility_profile="Standard-Agility")
        assignments = deepcopy(plan.assignments)
    replay = Schedule()
    for assignment in sorted(assignments, key=lambda a: a.sat_start_time):
        if not fresh_constraints.is_feasible_assignment(assignment, replay):
            row.update(status="PUBLIC_REJECTED", error=f"replay rejected {assignment.task_id}")
            return row
        replay.assignments.append(assignment)
    if len(set(replay.assigned_task_ids)) != len(replay.assignments):
        raise AssertionError("duplicate task")
    if set(candidate["unassigned_tasks"]) != set(fresh.tasks) - set(replay.assigned_task_ids):
        raise AssertionError("unassigned tasks differ")
    row.update(status="PUBLIC_PASS", completed=len(replay.assignments),
        unassigned=len(fresh.tasks)-len(replay.assignments),
        metrics=asdict(compute_evaluation_metrics(fresh, replay, runtime)),
        controller_status="NOT_APPLICABLE_SYNTHETIC", formal_certification="NOT_CERTIFIED")
    if runtime > job["budget"]:
        row["status"] = "OVER_BUDGET"
    stats = plan.metadata["caabs"]["stats"]
    row["derived"] = dict(states_per_s=stats["scored_states"]/runtime,
        feasible_children_per_s=stats["accepted_insertions"]/runtime,
        public_acceptance=stats["accepted_insertions"]/max(1,stats["public_constraint_calls"]),
        dedup_rate=stats["duplicate_states"]/max(1,stats["scored_states"]+stats["levels_completed"]))
    if config and job.get("audit", False):
        from eos_system.verification import verify_candidate
        verify_started = time.perf_counter()
        try:
            _, official_metrics, receipt = verify_candidate(config, candidate, runtime)
            row.update(controller_status="PASS", official_metrics=official_metrics, receipt=receipt.evidence())
        except Exception as exc:
            row.update(controller_status="REJECTED", controller_error=f"{type(exc).__name__}: {exc}")
        row["verification_runtime"] = time.perf_counter()-verify_started
    elif config:
        row["controller_status"] = "NOT_RUN"
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", type=Path)
    parser.add_argument("--suite", choices=["synthetic", "repository", "shared"], default="synthetic")
    parser.add_argument("--families", nargs="+", default=["uniform", "clustered", "downlink"])
    parser.add_argument("--sizes", type=int, nargs="+", default=[20, 100, 300])
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--split", choices=["train_development", "validation"], default="train_development")
    parser.add_argument("--per-scale", type=int, default=1)
    parser.add_argument("--budget", type=float, default=2.)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--instrument", choices=["none", "profile", "memory"], default="none")
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--job", type=Path)
    args = parser.parse_args()
    if args.job:
        job = json.loads(args.job.read_text(encoding="utf-8"))
        try:
            row = run_job(job, args.output.parent)
        except Exception as exc:
            row = job | {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
            import traceback
            traceback.print_exc()
        args.output.write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
        return
    args.output.mkdir(parents=True, exist_ok=False)
    variants = json.loads(args.variants.read_text(encoding="utf-8")) if args.variants else [dict(name="baseline", ref=BASELINE, params={})]
    weights = json.loads(args.weights.read_text(encoding="utf-8")) if args.weights else dict(w_profit=1.,w_completion=0.,w_timeliness=0.,w_balance=0.)
    scenarios = []
    if args.suite == "synthetic":
        seeds = {"uniform":101, "clustered":211, "capacity":211, "hub":307, "downlink":307, "orbit_bands":409, "station_network":503}
        for family in args.families:
            for n in args.sizes:
                scenarios.append(dict(label=f"{family}-{n}", family=family, n=n, scenario_seed=seeds[family]))
    elif args.suite == "repository":
        for scale in ("small", "medium"):
            paths = sorted((ROOT / "experiments/scenarios" / scale).glob("*epoch_fixed_v1.json"))
            for path in paths:
                scenarios.append(dict(label=path.stem, path=str(path)))
        large = ROOT / "docs/Scenario_S1_Sats20_M500_T0.5d_dist0.json"
        if large.is_file():
            scenarios.append(dict(label=large.stem, path=str(large)))
    else:
        if not args.dataset:
            parser.error("--dataset required for shared suite")
        import csv
        allow = {r["artifact_id"]:r for r in json.loads((args.dataset/"splits"/(args.split+".json")).read_text(encoding="utf-8-sig"))}
        counts = {}
        with (args.dataset/"development/delivery_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["artifact_id"] not in allow or counts.get(row["scale"],0) >= args.per_scale:
                    continue
                path = args.dataset/"development"/row["relative_path"]
                if hashlib.sha256(path.read_bytes()).hexdigest() != allow[row["artifact_id"]]["scenario_sha256"]:
                    raise ValueError("allowlist SHA mismatch")
                scenarios.append(dict(label=row["artifact_id"], scale=row["scale"], path=str(path)))
                counts[row["scale"]] = counts.get(row["scale"],0)+1
    versions = {}
    for name in ("numpy", "pydantic", "psutil", "orekit-jpype"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    manifest = dict(baseline=BASELINE, code_sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        python=sys.version, executable=sys.executable, platform=platform.platform(), processor=platform.processor(),
        versions=versions, hash_seed=os.environ.get("PYTHONHASHSEED"), threads={k:os.environ.get(k) for k in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS")},
        created_at=datetime.now(timezone.utc).isoformat(), weights=weights, variants=variants, scenarios=scenarios,
        budget=args.budget, repeats=args.repeats, instrument=args.instrument, final_test_used=False,
        note="No initial external schedule; greedy initialization, if enabled, is inside solver budget. Fresh subprocesses, serial execution. Profile/memory overhead excluded from ordinary RT tables.")
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2), encoding="utf-8")
    rows=[]
    for scene_index, scene in enumerate(scenarios):
        for repeat in range(args.repeats):
            # Alternate order to reduce systematic warm-up/thermal bias.
            ordered = variants if (repeat+scene_index)%2 == 0 else list(reversed(variants))
            for variant in ordered:
                jid=f"{scene['label']}-{variant['name']}-{repeat}"
                job=scene | variant | dict(id=jid,suite=args.suite,seed=41,repeat=repeat,budget=args.budget,
                    weights=weights,instrument=args.instrument,audit=args.audit)
                jp=args.output/(jid+".job.json"); rp=args.output/(jid+".result.json")
                jp.write_text(json.dumps(job),encoding="utf-8")
                with (args.output/(jid+".log")).open("w",encoding="utf-8") as log:
                    try:
                        subprocess.run([sys.executable,"-B",str(Path(__file__).resolve()),"--job",str(jp),"--output",str(rp)],
                            cwd=ROOT,stdout=log,stderr=log,timeout=max(60,args.budget+45),check=False)
                    except subprocess.TimeoutExpired:
                        pass
                row=json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else job | dict(status="PROCESS_TIMEOUT")
                rows.append(row)
                (args.output/"results.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
                print(jid,row["status"],row.get("completed"),round(row.get("runtime",0),4),flush=True)


if __name__ == "__main__":
    main()
