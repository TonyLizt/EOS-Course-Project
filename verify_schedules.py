"""Replay exported plans against EOS-Bench's original constraint model."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.transition_utils import delta_g_between


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def verify(scenario_path: Path, plan_path: Path) -> int:
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
        if not constraint_model.is_feasible_assignment(assignment, schedule):
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
    if abs(data["metrics"]["TCR"] - expected_tcr) > 1e-9:
        raise ValueError(f"TCR mismatch: {plan_path}")
    print(
        f"PASS {plan_path.name}: {len(actual)}/{len(problem.tasks)} assignments, "
        f"{parsed_transitions} agile transitions parsed"
    )
    return len(actual)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("plans", nargs="+", type=Path)
    args = parser.parse_args()
    for plan in args.plans:
        verify(args.scenario, plan)
