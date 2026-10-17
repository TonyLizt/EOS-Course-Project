"""Replay exported plans against EOS-Bench's original constraint model."""

from __future__ import annotations

import argparse
import json
import hashlib
from datetime import datetime
from pathlib import Path

from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.transition_utils import delta_g_between
from utils.time_parsing import parse_orbit_epoch
from utils.continuous_exposure import exposure_times, PlanExposureAuditor


def _time(value: str | None) -> datetime | None:
    return parse_orbit_epoch(value).replace(tzinfo=None) if value else None


def verify(scenario_path: Path, plan_path: Path, *, emit: bool = True) -> int:
    problem = load_scheduling_problem_from_json(scenario_path)
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    if data["scenario_id"] != problem.scenario_id:
        raise ValueError(f"Scenario mismatch: {plan_path}")

    constraint_model = ConstraintModel(problem)
    schedule = Schedule()
    for item in sorted(data["assignments"], key=lambda a: a["sat_start_time"]):
        task = problem.tasks[item["task_id"]]
        start = _time(item["sat_start_time"])
        end = _time(item["sat_end_time"])
        exposure_times(start, end, task.required_duration)
        matches = [
            window for window in task.windows
            if window.satellite_id == item["satellite_id"]
            and window.sensor_id == item["sensor_id"]
            and window.start_time <= start < end <= window.end_time
        ]
        if not matches:
            raise ValueError(f"Assignment outside its source window: {item['task_id']}")
        window = matches[0]
        assignment = Assignment(
            task_id=item["task_id"],
            satellite_id=item["satellite_id"],
            sat_start_time=start,
            sat_end_time=end,
            sat_window_id=window.window_id,
            sensor_id=item["sensor_id"],
            orbit_number=int(item["orbit_number"]),
            data_volume_GB=float(item["data_volume_GB"]),
            power_cost_W=float(item["power_cost_W"]),
            sat_angles=item["sat_angles"],
            ground_station_id=item.get("ground_station_id"),
            gs_start_time=_time(item.get("gs_start_time")),
            gs_end_time=_time(item.get("gs_end_time")),
        )
        if not constraint_model.check_discrete_assignment(assignment, schedule):
            raise ValueError(f"Current constraint model rejected {item['task_id']}")
        schedule.assignments.append(assignment)

    parsed_transitions = 0
    for satellite_id, satellite in problem.satellites.items():
        if satellite.maneuverability_type != "agile":
            continue
        assigned = sorted(
            schedule.get_assignments_for_satellite(satellite_id),
            key=lambda assignment: assignment.sat_start_time,
        )
        for previous, following in zip(assigned, assigned[1:]):
            if delta_g_between(previous.sat_angles, following.sat_angles) is None:
                raise ValueError(
                    f"Attitude fallback still used between {previous.task_id} and "
                    f"{following.task_id} in {plan_path}"
                )
            parsed_transitions += 1

    actual = set(schedule.assigned_task_ids)
    expected_unassigned = set(problem.tasks) - actual
    if set(data["unassigned_tasks"]) != expected_unassigned:
        raise ValueError(f"Unassigned-task list mismatch: {plan_path}")
    expected_tcr = len(actual) / len(problem.tasks)
    if "metrics" in data and abs(data["metrics"]["TCR"] - expected_tcr) > 1e-9:
        raise ValueError(f"TCR mismatch: {plan_path}")
    if emit:
        print(
            f"PASS_DISCRETE_ONLY {plan_path.name}: {len(actual)}/{len(problem.tasks)} assignments, "
            f"{parsed_transitions} agile transitions parsed"
        )
    return len(actual)


def verify_continuous(scenario_path, plan_path, *, data_path=None, min_elevation_deg,
                      step_s=0.05, auditor_factory=PlanExposureAuditor,
                      expected_scenario_sha=None, expected_plan_sha=None):
    """Fail-closed independent acceptance gate; never invokes a scheduler or writes inputs."""
    scenario_path,plan_path=Path(scenario_path),Path(plan_path)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    before={"scenario":sha(scenario_path),"plan":sha(plan_path)}
    data_before=sha(Path(data_path)) if data_path and Path(data_path).is_file() else None
    identity=dict(scenario_path=str(scenario_path),plan_path=str(plan_path),
                  scenario_sha256=before["scenario"],plan_sha256=before["plan"])
    if ((expected_scenario_sha is not None and before["scenario"]!=expected_scenario_sha)
            or (expected_plan_sha is not None and before["plan"]!=expected_plan_sha)):
        return dict(identity,status="FAIL",reason="INPUT_SHA_MISMATCH")
    try:
        count=verify(scenario_path,plan_path,emit=False)
    except (KeyError,ValueError,TypeError,OverflowError) as exc:
        return dict(identity,status="FAIL",reason="DISCRETE_CONSTRAINT_REJECTED",detail=str(exc))
    scene=json.loads(scenario_path.read_bytes());plan=json.loads(plan_path.read_bytes())
    auditor=auditor_factory(scene,data_path=data_path,min_elevation_deg=min_elevation_deg,step_s=step_s)
    result=auditor.audit(plan)
    project=Path(__file__).resolve().parent
    result["source_sha256"]={n:sha(project/n) for n in (
        "utils/visibility.py","utils/continuous_exposure.py","utils/time_parsing.py",
        "schedulers/scenario_loader.py","schedulers/constraint_model.py","verify_schedules.py")}
    data_after=sha(Path(data_path)) if data_path and Path(data_path).is_file() else None
    result["orekit_data_unchanged"]=data_before==data_after
    result.update(identity,discrete_status="PASS",discrete_tasks=count,
                  inputs_unchanged=before=={"scenario":sha(scenario_path),"plan":sha(plan_path)})
    if not result["inputs_unchanged"] or not result["orekit_data_unchanged"]:
        result.update(status="FAIL",reason="INPUT_CHANGED_DURING_AUDIT")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("plans", nargs="+", type=Path)
    parser.add_argument("--continuous", action="store_true", help="independent fail-closed exposure audit")
    parser.add_argument("--orekit-data", type=Path)
    parser.add_argument("--min-elevation-deg", type=float,
                        help="explicit production predicate threshold; never inferred from window endpoints")
    parser.add_argument("--scan-step-s", type=float, default=0.05)
    parser.add_argument("--expected-scenario-sha")
    parser.add_argument("--expected-plan-sha")
    parser.add_argument("--report", type=Path, help="exclusive-create NEW JSON report; inputs stay read-only")
    args = parser.parse_args()
    if not args.continuous:
        if args.report:
            parser.error("--report requires --continuous")
        for plan in args.plans:
            verify(args.scenario, plan)
    else:
        if args.min_elevation_deg is None:
            parser.error("--continuous requires explicit --min-elevation-deg")
        reports=[verify_continuous(args.scenario,p,data_path=args.orekit_data,
                 min_elevation_deg=args.min_elevation_deg,step_s=args.scan_step_s,
                 expected_scenario_sha=args.expected_scenario_sha,
                 expected_plan_sha=args.expected_plan_sha) for p in args.plans]
        document=dict(status="FAIL" if any(r["status"]=="FAIL" for r in reports) else
                      ("INCONCLUSIVE" if any(r["status"]=="INCONCLUSIVE" for r in reports) else "PASS"),reports=reports)
        if args.report:
            with args.report.open("x",encoding="utf-8") as stream:
                json.dump(document,stream,ensure_ascii=False,indent=2,allow_nan=False)
        print(json.dumps(document,ensure_ascii=False,indent=2,allow_nan=False))
        raise SystemExit({"PASS":0,"FAIL":1,"INCONCLUSIVE":2}[document["status"]])
