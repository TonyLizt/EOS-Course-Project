"""Controller 的独立计划核验。

本模块复用 EOS-Bench 的约束模型及指标函数，但不信任 Worker 报告的计划状态。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import math
from pathlib import Path

from schedulers.constraint_model import Assignment, Schedule
from schedulers.evaluation_metrics import compute_evaluation_metrics
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.schedule_output import schedule_to_dict
from schedulers.transition_utils import delta_g_between

from .config import sha256_file
from .contracts import RunConfig
from .provenance import verify_provenance
from .runner import build_constraint_model


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _slice_angles(payload, offset: int, count: int):
    """按旧候选生成器相同的时间步切片规则还原来源姿态。"""
    if isinstance(payload, list):
        return payload[offset: offset + count]
    if isinstance(payload, dict):
        return {key: _slice_angles(value, offset, count) for key, value in payload.items()}
    return payload


def verify_candidate(config: RunConfig, candidate: dict, runtime_s: float) -> tuple[dict, dict]:
    """重建每条 assignment，验证可行性并重新计算所有正式指标。"""
    verify_provenance(config)
    path = Path(config.scenario_path)
    if sha256_file(path) != config.scenario_sha256:
        raise ValueError("场景文件与实验配置中的 SHA-256 不一致")
    problem = load_scheduling_problem_from_json(path)
    if candidate.get("scenario_id") != problem.scenario_id:
        raise ValueError("候选计划和输入场景 ID 不一致")
    if candidate.get("start_time") != problem.start_time.isoformat() or candidate.get("end_time") != problem.end_time.isoformat():
        raise ValueError("候选计划的场景时间范围不一致")
    raw_assignments = candidate.get("assignments")
    if not isinstance(raw_assignments, list):
        raise ValueError("候选计划缺少 assignments 列表")
    schedule = Schedule()
    seen_tasks: set[str] = set()
    constraint_model = build_constraint_model(problem, config)
    for item in sorted(raw_assignments, key=lambda row: row["sat_start_time"]):
        task_id = item["task_id"]
        if task_id in seen_tasks or task_id not in problem.tasks:
            raise ValueError(f"重复或不存在的任务：{task_id}")
        seen_tasks.add(task_id)
        task = problem.tasks[task_id]
        start, end = _time(item["sat_start_time"]), _time(item["sat_end_time"])
        windows = [
            window for window in task.windows
            if window.satellite_id == item["satellite_id"]
            and window.sensor_id == item["sensor_id"]
            and window.start_time <= start < end <= window.end_time
        ]
        if not windows:
            raise ValueError(f"任务不在来源窗口内：{task_id}")
        window = windows[0]
        if int(item["orbit_number"]) != window.orbit_number:
            raise ValueError(f"轨道编号与来源窗口不符：{task_id}")
        duration = (end - start).total_seconds()
        if abs(duration - task.required_duration) > 1e-6:
            raise ValueError(f"任务时长与场景定义不符：{task_id}")
        step = float(window.time_step or 1.0)
        offset = (start - window.start_time).total_seconds() / step
        k = round(offset)
        if abs(offset - k) > 1e-6:
            raise ValueError(f"任务起点未对齐来源窗口时间步：{task_id}")
        satellite = problem.satellites[item["satellite_id"]]
        if item["sensor_id"] not in satellite.sensors:
            raise ValueError(f"传感器不存在：{task_id}")
        if satellite.maneuverability_type == "non_agile":
            max_k = math.floor(((window.end_time - window.start_time).total_seconds() - task.required_duration + 1e-9) / step)
            center_k = max(0, min(max_k, round(((window.end_time - window.start_time).total_seconds() - task.required_duration) / (2 * step))))
            if k != center_k:
                raise ValueError(f"非敏捷卫星任务不在窗口中心：{task_id}")
            expected_angles = window.non_agile_data
        else:
            count = max(1, math.ceil(task.required_duration / step - 1e-9))
            expected_angles = _slice_angles(window.agile_data, k, count)
        if item["sat_angles"] != expected_angles:
            raise ValueError(f"姿态数据与来源窗口不符：{task_id}")
        expected_data = constraint_model._estimate_data_volume_GB(item["satellite_id"], item["sensor_id"], start, end)
        expected_power = constraint_model._estimate_power_cost_W(item["satellite_id"], item["sensor_id"])
        if abs(float(item["data_volume_GB"]) - expected_data) > 1e-7 or abs(float(item["power_cost_W"]) - expected_power) > 1e-7:
            raise ValueError(f"资源消耗与传感器规格不符：{task_id}")
        if problem.ground_stations:
            gs_start, gs_end = _time(item.get("gs_start_time")), _time(item.get("gs_end_time"))
            if not gs_start or not gs_end or (gs_end - gs_start).total_seconds() + 1e-6 < task.required_duration * config.constraints.downlink_duration_ratio:
                raise ValueError(f"下传时间不足：{task_id}")
            if not any(cw.satellite_id == item["satellite_id"] and cw.ground_station_id == item.get("ground_station_id")
                       and cw.start_time <= gs_start < gs_end <= cw.end_time for cw in problem.comm_windows):
                raise ValueError(f"下传不在来源通信窗口：{task_id}")
        assignment = Assignment(
            task_id=task_id,
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
    return official, metric_data
