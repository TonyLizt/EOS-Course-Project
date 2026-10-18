"""Controller 的独立计划核验。

本模块复用 EOS-Bench 的约束模型及指标函数，但不信任 Worker 报告的计划状态。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import os
from utils.continuous_exposure import (certify_schedule, CertificationReceipt, planning_exposure,
                                       ExposureStatus, ContinuousCertificationError)
from utils.time_parsing import parse_orbit_epoch

from schedulers.constraint_model import Schedule
from schedulers.source_windows import SourceWindowIndex, validate_plan_source
from schedulers.evaluation_metrics import compute_evaluation_metrics
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.schedule_output import schedule_to_dict
from schedulers.transition_utils import delta_g_between

from .config import sha256_file
from .contracts import RunConfig
from .provenance import verify_provenance
from .runner import build_constraint_model
from schedulers.preview_exposure import candidate_exposure
from .planning_preview import audit_preview
import time


def _time(value: str | None) -> datetime | None:
    return parse_orbit_epoch(value).replace(tzinfo=None) if value else None


def verify_candidate(config: RunConfig, candidate: dict, runtime_s: float) -> tuple[dict, dict, CertificationReceipt]:
    """重建每条 assignment，验证可行性并重新计算所有正式指标。"""
    verify_provenance(config)
    path = Path(config.scenario_path)
    if sha256_file(path) != config.scenario_sha256:
        raise ValueError("场景文件与实验配置中的 SHA-256 不一致")
    problem = load_scheduling_problem_from_json(path)
    validate_plan_source(candidate, problem, config.scenario_sha256)
    raw_assignments = candidate.get("assignments")
    if not isinstance(raw_assignments, list):
        raise ValueError("候选计划缺少 assignments 列表")
    schedule = Schedule()
    seen_tasks: set[str] = set()
    constraint_model = build_constraint_model(problem, config)
    sources = SourceWindowIndex(problem)
    for item in sorted(raw_assignments, key=lambda row: _time(row["sat_start_time"])):
        task_id = item["task_id"]
        if task_id in seen_tasks or task_id not in problem.tasks:
            raise ValueError(f"重复或不存在的任务：{task_id}")
        seen_tasks.add(task_id)
        task = problem.tasks[task_id]
        assignment = sources.restore(item, constraint_model)
        start, end = assignment.sat_start_time, assignment.sat_end_time
        window = sources.observations[assignment.sat_window_id][0][1]
        planning = candidate_exposure(problem, window, start, end, task.required_duration)
        if planning.status is not ExposureStatus.PLANNING_FEASIBLE:
            raise ContinuousCertificationError(planning.status, planning.reason)
        if not constraint_model.is_feasible_assignment(assignment, schedule):
            raise ValueError(f"统一约束模型拒绝任务：{task_id}")
        schedule.assignments.append(assignment)
    expected_unassigned = set(problem.tasks) - seen_tasks
    if set(candidate.get("unassigned_tasks", [])) != expected_unassigned:
        raise ValueError("未安排任务集合不一致")
    for satellite in problem.satellites.values():
        if satellite.maneuverability_type != "agile":
            continue
        assigned = sorted(schedule.get_assignments_for_satellite(satellite.id), key=lambda row: row.sat_start_time)
        for previous, following in zip(assigned, assigned[1:]):
            if delta_g_between(previous.sat_angles, following.sat_angles) is None:
                raise ValueError("敏捷卫星姿态数据不足，无法核验转向")
    metrics = compute_evaluation_metrics(problem, schedule, runtime_seconds=runtime_s)
    official = schedule_to_dict(schedule, problem)
    metric_data = asdict(metrics)
    metric_data.update({"completed_tasks": len(seen_tasks), "total_tasks": len(problem.tasks)})
    if config.execution_mode in ('planning_preview', 'physical_validation'):
        from utils.continuous_exposure import _RUNTIME
        runtime = getattr(_RUNTIME, 'value', None)
        receipt = audit_preview(config, official, deadline=runtime[0] if runtime else time.monotonic()+30)
        return official, metric_data, receipt
    receipt = certify_schedule(path, official, run_id=config.run_id,
                               scenario_sha=config.scenario_sha256,
                               data_path=os.environ.get("EOS_OREKIT_DATA"))
    return official, metric_data, receipt
