#!/usr/bin/env python3
"""Real Orekit + Registry + Spawn + Controller acceptance, isolated and bounded.

No simulated certificates or Worker replacements. Preview completion is never
formal certification. All generated targets/windows and failed run evidence
are retained in a NEW directory outside the repository.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import uuid


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def make_config(scene, algorithm="caabs", *, budget=2., params=None):
    from eos_system.algorithm_registry import get_algorithm
    from eos_system.contracts import RunConfig
    from eos_system.provenance import capture_execution_provenance
    sha = hashlib.sha256(scene.read_bytes()).hexdigest()
    return RunConfig(run_id=str(uuid.uuid4()), scenario_id="scene", scenario_path=str(scene),
        scenario_sha256=sha, algorithm_id=algorithm, algorithm_version=get_algorithm(algorithm).version,
        seed=42, placement_mode="center", time_budget_s=budget, algorithm_params=params or {},
        execution_mode="planning_preview",
        scenario_provenance=capture_execution_provenance(scene, sha, "planning_preview"),
        created_at=datetime.now(timezone.utc).isoformat())


def runner_case(config, output):
    from eos_system.runner import prepare, run_prepared
    from eos_system.verification import verify_candidate
    from utils.continuous_exposure import certify_schedule, ContinuousCertificationError
    before = hashlib.sha256(Path(config.scenario_path).read_bytes()).hexdigest()
    solver, problem, constraints, context = prepare(config)
    candidate, runtime = run_prepared(solver, problem, constraints, context)
    official, metrics, receipt = verify_candidate(config, candidate, runtime)
    assert metrics["completed_tasks"] > 0, "real Runner returned empty plan"
    assert before == hashlib.sha256(Path(config.scenario_path).read_bytes()).hexdigest()
    assert all(type(a["sat_window_id"]) is int for a in official["assignments"])
    try:
        certify_schedule(config.scenario_path, official, run_id=config.run_id,
                         scenario_sha=config.scenario_sha256, data_path=os.environ["EOS_OREKIT_DATA"])
    except ContinuousCertificationError as exc:
        certification = {"status": exc.status.value, "reason": str(exc)}
        assert "NO_CONTINUITY_CERTIFICATE" in str(exc)
    else:
        raise AssertionError("unexpected continuous success: inspect new certificate implementation")
    result = {"config": config.model_dump(), "candidate": candidate, "official": official,
              "metrics": metrics, "runtime_s": runtime, "preview": receipt.evidence(),
              "continuous_certification": certification}
    write(output, result)
    return result


def wait_run(database, run_id, *, action=None, timeout=100.):
    from eos_system.process_state import identity, pinned_signal
    deadline, acted = time.monotonic() + timeout, False
    while time.monotonic() < deadline:
        with database.connect() as connection:
            status = connection.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
            searching = connection.execute("SELECT 1 FROM run_events WHERE run_id=? AND event_type='heartbeat' "
                "AND json_extract(payload_json,'$.phase')='SEARCHING'", (run_id,)).fetchone()
            pid = connection.execute("SELECT worker_pid FROM run_attempts WHERE run_id=?", (run_id,)).fetchone()
        if action and searching and not acted and status == "RUNNING":
            if action == "cancel":
                assert database.request_cancel(run_id)[1]
            elif action == "crash":
                # Current own attempt, pinned identity, never historical PID-only kill.
                saved = identity(pid[0])
                assert saved["pgrp"] == pid[0] and saved["sid"] == pid[0]
                assert pinned_signal(saved, signal.SIGKILL)
            else:
                raise ValueError(action)
            acted = True
        if status in {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"}:
            result = database.get_run(run_id)
            if action:
                assert acted, "search ended before real in-search action"
            return result
        time.sleep(.025)
    raise TimeoutError(f"run {run_id}: {status}")


def controller_cases(root, scene, stress):
    from eos_system.config import Settings
    from eos_system.controller import Controller
    from eos_system.exporting import render_json, render_csv
    from eos_system.planning_preview import preview_schedule
    from eos_system.storage import Database
    runtime = root / "runtime"
    database = Database(runtime / "results.sqlite3")
    settings = Settings(runtime, scene.parent, stop_grace_s=2.)
    database.ensure_defaults(scene.parent, runtime)
    controller = Controller(settings, database)
    controller.start()
    results = {}
    stress_params = dict(beam_width=256, branch_limit=64, max_candidates_per_task=128)
    try:
        cases = [("normal", make_config(scene)),
                 ("completion_first", make_config(scene, "completion_first")),
                 ("short_budget", make_config(stress, budget=.06, params=stress_params)),
                 ("cancel", make_config(stress, budget=15., params=stress_params)),
                 ("crash", make_config(stress, budget=15., params=stress_params))]
        for name, config in cases:
            database.enqueue(config, max_queued=8)
            record = wait_run(database, config.run_id, action=name if name in {"cancel", "crash"} else None)
            write(root / f"controller-{name}.json", record)
            if name == "short_budget" and record["status"] == "TIMED_OUT":
                # Best-effort solver may overrun one uninterruptible constructor;
                # Controller MUST reject it rather than silently increase budget.
                assert record["error"]["code"] == "SEARCH_BUDGET" and record["plan"] is None
                results[name] = {"run_id": config.run_id, "status": record["status"],
                                 "error": record["error"], "attempts": record["attempts"]}
                continue
            if name in {"normal", "completion_first", "short_budget"}:
                assert record["status"] == "SUCCEEDED", record.get("error")
                assert record["result_kind"] == "planning_preview"
                assert record["continuous_certification"]["status"] == "NOT_CERTIFIED"
                write(root / f"preview-{name}.json", preview_schedule(record))
                for exporter in (render_json, render_csv):
                    try:
                        exporter(record)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("formal exporter accepted development preview")
                if name != "short_budget":
                    assert record["metrics"]["completed_tasks"] > 0
            else:
                assert record["status"] == ("CANCELLED" if name == "cancel" else "FAILED"), record
                assert record["plan"] is None
                assert not any(e["event_type"] == "candidate_result" for e in record["events"])
            results[name] = {"run_id": config.run_id, "status": record["status"], "error": record["error"],
                             "metrics": record["metrics"], "attempts": record["attempts"]}
    finally:
        controller.stop()
    # Same SQLite and run root: actual Controller restart after failed Worker.
    restarted = Controller(settings, database)
    restarted.start()
    try:
        config = make_config(scene)
        database.enqueue(config, max_queued=8)
        record = wait_run(database, config.run_id)
        write(root / "controller-restarted.json", record)
        assert record["status"] == "SUCCEEDED" and record["metrics"]["completed_tasks"] > 0, record
        results["restart"] = {"run_id": config.run_id, "status": record["status"]}
    finally:
        restarted.stop()
    assert controller._lock_file is None and restarted._lock_file is None
    assert not list(runtime.glob("worker-*.json")), "active worker journal remains"
    return results


def execute(root, data):
    repository = Path(__file__).resolve().parents[1]
    root = root.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)) or ".." in root.parts:
        raise ValueError("unsafe acceptance directory")
    if root == repository or repository in root.parents or root in repository.parents:
        raise ValueError("acceptance output must be outside repository")
    root.mkdir(parents=True, exist_ok=False)
    os.environ["EOS_OREKIT_DATA"] = str(data.resolve())
    os.environ["EOS_PREINITIALIZE_OREKIT"] = "1"
    from utils.visibility import ensure_orekit
    ensure_orekit(str(data))
    from scripts.generate_caabs_development_scene import generate
    from eos_system.runner import prepare, run_prepared
    from eos_system.verification import verify_candidate
    from eos_system.algorithm_registry import get_algorithm
    from eos_system.scenario_catalog import ScenarioCatalog
    small = generate(root / "small", repository / "input/10_satellites.json", "ALOS-2_39766", str(data))
    stress = generate(root / "stress", repository / "input/10_satellites.json", "ALOS-2_39766", str(data), tasks_per_target=8)
    scene = Path(small["scenario"])
    stress_scene = Path(stress["scenario"])
    summary = {"small": small, "stress": stress, "runner": {}}
    for algorithm in ("caabs", "completion_first"):
        config = make_config(scene, algorithm)
        result = runner_case(config, root / f"runner-{algorithm}.json")
        summary["runner"][algorithm] = {"metrics": result["metrics"], "runtime_s": result["runtime_s"],
            "diagnostics": result["candidate"].get("solver_diagnostics")}
    # Real callback and monotonic elapsed time on genuine stress windows.
    config = make_config(stress_scene, budget=15., params=dict(beam_width=256, branch_limit=64, max_candidates_per_task=128))
    solver, problem, constraints, context = prepare(config)
    cancelled = threading.Event()
    timer = threading.Timer(.15, cancelled.set)
    context = replace(context, is_cancelled=cancelled.is_set)
    timer.start()
    try:
        candidate, runtime = run_prepared(solver, problem, constraints, context)
    finally:
        timer.cancel()
        timer.join()
    assert candidate["solver_diagnostics"]["caabs"]["stop_reason"] == "cancelled"
    official, metrics, receipt = verify_candidate(config, candidate, runtime)
    write(root / "runner-cancel.json", dict(candidate=candidate, runtime_s=runtime, metrics=metrics))
    summary["runner_cancel"] = dict(runtime_s=runtime, diagnostics=candidate["solver_diagnostics"], metrics=metrics)
    catalog = ScenarioCatalog(repository)
    rows = catalog.list_scenarios(scene.parent, "runtime", planning_preview=True)
    assert rows[0]["availability"] == "ready" and rows[0]["execution_modes"] == ["planning_preview"]
    assert catalog.list_scenarios(scene.parent, "runtime")[0]["availability"] == "invalid"
    summary["controller"] = controller_cases(root, scene, stress_scene)
    summary["formal_release"] = "BLOCKED: NO_CONTINUITY_CERTIFICATE; development source only"
    write(root / "acceptance.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main():
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--orekit-data", required=True, type=Path)
    args = parser.parse_args()
    execute(args.output, args.orekit_data)


if __name__ == "__main__":
    main()
