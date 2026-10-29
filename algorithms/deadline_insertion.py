"""截止期动态插入：加入自适应补点、局部撤销续排和可选资源修复。

参考 2026-10-28 交付快照选择性移植；不引入 Score/v2 协议，不修改物理与指标口径。
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
import math
import time
from typing import Callable, Literal

from pydantic import ConfigDict, Field

from algorithms.candidate_pool import enumerate_task_candidates
from algorithms.solver_contracts import AlgorithmParams, SolveContext
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import SchedulingProblem, SchedulingTask, TaskWindow

VERSION = "0.5.0-course.1"
# candidate_pool eagerly builds the grid: reject larger agile grids in G1-A.
_MAX_GRID_STEPS = 1024
_MAX_POOL_ASSIGNMENTS = 4096
_MAX_DOWNLINK_CHECKS = 16


class DARTISParams(AlgorithmParams):
    model_config = ConfigDict(extra="forbid", frozen=True)
    aggregate_resource_repair: bool = Field(False, strict=True, description="有界聚合资源释放/迁移，默认关闭保留0.4路径。")
    resource_migrations: bool = Field(True, strict=True, description="聚合修复允许跨星迁移；关闭作替换消融。")
    conflict_exchange: bool = Field(False, strict=True,
        description="实验性两任务冲突定向撤销重插；默认关闭，保留0.3.0决策路径。")
    exchange_max_checks: int = Field(30000, ge=1, le=60000, strict=True, description='两任务交换阶段的公共约束检查总上限；到限保留已验证的最佳计划。')
    exchange_max_seeds: int = Field(64, ge=1, le=128, strict=True, description='两任务交换最多尝试的撤销种子数。')
    priority_mode: Literal["llf", "edf"] = Field("llf", description="llf 按受检机会的近似松弛度优先，edf 按观测窗口结束时间优先；另一项作为次级排序键。")
    max_windows_per_task: int = Field(8, ge=1, le=64, strict=True)
    max_positions_per_window: int = Field(4, ge=1, le=32, strict=True)
    adaptive_rescue_positions_per_window: int = Field(12, ge=0, le=32, strict=True,
        description="初始位置无解时，从空闲观测间隙有界补查的最大起点数；0 关闭补查。")
    local_repair_rounds: int = Field(2, ge=0, le=4, strict=True,
        description="原插入完成后，执行有界单任务撤销与续排；0 保留 0.2.0 路径。")
    repair_ejection_limit: int = Field(6, ge=1, le=16, strict=True,
        description="每轮最多撤销尝试的已安排任务数，按对剩余任务的窗口阻塞数排序。")
    repair_positions_per_window: int = Field(12, ge=2, le=32, strict=True,
        description="局部修复每个来源窗口的起点上限；边界邻近与均匀栅格各占部分名额。")
    repair_max_checks: int = Field(12000, ge=1, le=100000, strict=True,
        description="局部修复的公共约束检查总上限；到限返回已经完整核验的最佳计划。")
    recompute_mode: Literal["full"] = Field("full", description="仅支持 full：每次成功插入后，基于更新的计划全量重算剩余任务的受检机会。")
    tie_break: Literal["earliest_deadline_then_id"] = Field("earliest_deadline_then_id", description="固定平局规则标识：主紧迫度相同时先比较另一紧迫度量，再按任务、卫星、窗口、开始时刻及下传字段稳定排序；当前不切换排序实现。")


class DARTISCancelled(RuntimeError):
    """Cancellation is not a successful anytime return."""


class _BudgetExpired(Exception):
    pass


@dataclass(frozen=True)
class Opportunity:
    task_id: str
    satellite_id: str
    window_id: int
    deadline: datetime
    inspected_start: datetime
    laxity_s: float
    assignment: Assignment
    plan_version: int
    rescued: bool = False

    def rank(self, mode: str) -> tuple:
        urgency = ((self.laxity_s, self.deadline) if mode == "llf"
                   else (self.deadline, self.laxity_s))
        a = self.assignment
        return (*urgency, self.task_id, self.satellite_id, self.window_id,
                self.inspected_start, a.gs_window_id or 0,
                a.ground_station_id or "", a.gs_start_time or datetime.min)


def _assignment_key(a: Assignment) -> tuple:
    return (a.sat_start_time, a.sat_end_time, a.satellite_id, a.task_id,
            a.sat_window_id, a.gs_start_time or datetime.min,
            a.gs_window_id or 0, a.ground_station_id or "")


def _select_windows(task: SchedulingTask, limit: int) -> tuple[list[TaskWindow], int]:
    """Round-robin satellites so one satellite cannot exhaust the cap."""
    groups: dict[str, list[TaskWindow]] = defaultdict(list)
    for window in task.windows:
        groups[window.satellite_id].append(window)
    for windows in groups.values():
        windows.sort(key=lambda w: (w.start_time, w.end_time, w.window_id))
    selected: list[TaskWindow] = []
    depth = 0
    while len(selected) < limit:
        found = False
        for sid in sorted(groups):
            if depth < len(groups[sid]):
                selected.append(groups[sid][depth])
                found = True
                if len(selected) == limit:
                    break
        if not found:
            break
        depth += 1
    return selected, len(task.windows) - len(selected)


def _grid_steps(problem: SchedulingProblem, task: SchedulingTask, window: TaskWindow) -> int:
    satellite = problem.satellites.get(window.satellite_id)
    if satellite is None:
        return 0
    width = (window.end_time - window.start_time).total_seconds()
    step = float(window.time_step)
    duration = task.required_duration
    if (not all(math.isfinite(x) for x in (width, step, duration))
            or step <= 0 or duration <= 0 or width < duration):
        return 0
    if satellite.maneuverability_type == "non_agile":
        return 1
    quotient = (width - duration + 1e-9) / step
    if quotient > _MAX_GRID_STEPS:
        return _MAX_GRID_STEPS + 1
    return math.floor(quotient) + 1


def _select_starts(starts: list[datetime], plan: Schedule, sid: str,
                   limit: int) -> list[datetime]:
    """Prefer a window start and positions adjacent to occupied intervals."""
    if len(starts) <= limit:
        return starts
    from bisect import bisect_left
    proposed = [starts[0], starts[-1]]
    for a in sorted(plan.get_assignments_for_satellite(sid), key=_assignment_key):
        for boundary in (a.sat_end_time, a.sat_start_time):
            index = bisect_left(starts, boundary)
            if index < len(starts):
                proposed.append(starts[index])
            if index:
                proposed.append(starts[index - 1])
    proposed.append(starts[(len(starts) - 1) // 2])
    chosen = []
    for start in proposed:
        if start not in chosen:
            chosen.append(start)
        if len(chosen) == limit:
            break
    return sorted(chosen)


def _rescue_starts(starts: list[datetime], selected: list[datetime],
                   plan: Schedule, sid: str, duration_s: float, limit: int) -> list[datetime]:
    """Sample free observation gaps after the small boundary probe fails.

    This overlap filter is only a necessary condition. Every proposed source-grid
    assignment still passes the public ConstraintModel before insertion.
    """
    from datetime import timedelta
    if not limit:
        return []
    occupied = sorted(plan.get_assignments_for_satellite(sid), key=_assignment_key)
    duration = timedelta(seconds=duration_s)
    eligible = [start for start in starts if start not in selected and all(
        start + duration <= a.sat_start_time or start >= a.sat_end_time
        for a in occupied)]
    if not eligible:
        return []
    # Separate grid runs at occupied intervals. Sample each run at its ends,
    # middle and quarters; this reaches useful interior slots without a blind
    # global increase of max_positions_per_window.
    step = min(((b - a).total_seconds() for a, b in zip(starts, starts[1:])
                if b > a), default=1.0)
    groups: list[list[datetime]] = []
    for start in eligible:
        if not groups or (start - groups[-1][-1]).total_seconds() > step + 1e-6:
            groups.append([])
        groups[-1].append(start)
    proposed = []
    for group in groups:
        n = len(group) - 1
        for fraction in (0.5, 0.0, 1.0, 0.25, 0.75):
            candidate = group[round(n * fraction)]
            if candidate not in proposed:
                proposed.append(candidate)
    for group in groups:
        for candidate in group:
            if candidate not in proposed:
                proposed.append(candidate)
    return proposed[:limit]


class DARTISScheduler:
    """Single feasible incumbent, rebuilt opportunities after every insertion."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self.clock = clock

    def _observe_round(self, version: int, opportunities: tuple[Opportunity, ...]) -> None:
        """Read-only diagnostic hook; never changes scheduling decisions."""

    def solve(self, problem: SchedulingProblem, constraints: ConstraintModel,
              context: SolveContext) -> Schedule:
        params = DARTISParams.model_validate(context.params.model_dump())
        if not math.isfinite(context.time_budget_s) or context.time_budget_s <= 0:
            raise ValueError("time_budget_s must be finite and positive")
        reserve = min(0.05, context.time_budget_s * 0.05)
        deadline = self.clock() + context.time_budget_s - reserve
        plan = Schedule()
        remaining = set(problem.tasks)
        stats = dict(rounds=0, recomputations=0, constraint_checks=0,
                     positions_inspected=0, windows_inspected=0, windows_truncated=0,
                     positions_truncated=0, grid_limited_windows=0,
                     pool_limit_reached_windows=0, rescue_windows=0,
                     rescue_positions_inspected=0, rescue_successes=0)
        version = 0
        reason = "completed"
        trace = []

        def checkpoint() -> None:
            if context.is_cancelled():
                raise DARTISCancelled("DARTIS cancelled by SolveContext")
            if self.clock() >= deadline:
                raise _BudgetExpired()

        try:
            while remaining:
                checkpoint()
                stats["rounds"] += 1
                stats["recomputations"] += int(version > 0)
                opportunities: list[Opportunity] = []
                for task_id in sorted(remaining):
                    checkpoint()
                    task = problem.tasks[task_id]
                    windows, omitted = _select_windows(task, params.max_windows_per_task)
                    stats["windows_truncated"] += omitted
                    for window in windows:
                        checkpoint()
                        stats["windows_inspected"] += 1
                        steps = _grid_steps(problem, task, window)
                        if not steps:
                            continue
                        if steps > _MAX_GRID_STEPS:
                            stats["grid_limited_windows"] += 1
                            continue
                        # Public generator handles original source IDs, attitude
                        # slices, exposure, resource values and downlink candidates.
                        options = enumerate_task_candidates(
                            problem, replace(task, windows=[window]),
                            max_candidates=_MAX_POOL_ASSIGNMENTS,
                            random_samples_per_window=0, seed=context.seed)
                        checkpoint()
                        if len(options) == _MAX_POOL_ASSIGNMENTS:
                            stats["pool_limit_reached_windows"] += 1
                        by_start: dict[datetime, list[Assignment]] = defaultdict(list)
                        for candidate in options:
                            by_start[candidate.sat_start_time].append(candidate)
                        starts = sorted(by_start)
                        selected = _select_starts(starts, plan, window.satellite_id,
                                                  params.max_positions_per_window)
                        feasible = None
                        used_rescue = False
                        for start in selected:
                            checkpoint()
                            stats["positions_inspected"] += 1
                            for candidate in sorted(by_start[start], key=_assignment_key)[:_MAX_DOWNLINK_CHECKS]:
                                checkpoint()
                                stats["constraint_checks"] += 1
                                valid = constraints.is_feasible_assignment(candidate, plan)
                                checkpoint()
                                if valid:
                                    feasible = candidate
                                    break
                            if feasible is not None:
                                break
                        rescue = []
                        if feasible is None and params.adaptive_rescue_positions_per_window:
                            rescue = _rescue_starts(starts, selected, plan,
                                window.satellite_id, task.required_duration,
                                params.adaptive_rescue_positions_per_window)
                            if rescue:
                                stats["rescue_windows"] += 1
                        for start in rescue:
                            checkpoint()
                            stats["positions_inspected"] += 1
                            stats["rescue_positions_inspected"] += 1
                            for candidate in sorted(by_start[start], key=_assignment_key)[:_MAX_DOWNLINK_CHECKS]:
                                checkpoint()
                                stats["constraint_checks"] += 1
                                if constraints.is_feasible_assignment(candidate, plan):
                                    feasible = candidate
                                    stats["rescue_successes"] += 1
                                    used_rescue = True
                                    break
                            if feasible is not None:
                                break
                        stats["positions_truncated"] += max(0, len(starts) - len(selected) - len(rescue))
                        if feasible is not None:
                            laxity = ((window.end_time - feasible.sat_start_time).total_seconds()
                                      - task.required_duration)
                            opportunities.append(Opportunity(
                                task_id, window.satellite_id, window.window_id,
                                window.end_time, feasible.sat_start_time,
                                laxity, feasible, version, used_rescue))
                self._observe_round(version, tuple(opportunities))
                checkpoint()
                if not opportunities:
                    reason = "no_feasible_opportunity"
                    break
                chosen = min(opportunities, key=lambda x: x.rank(params.priority_mode))
                if chosen.plan_version != version:
                    raise RuntimeError("stale DARTIS opportunity")
                checkpoint()
                stats["constraint_checks"] += 1
                if not constraints.is_feasible_assignment(chosen.assignment, plan):
                    raise RuntimeError("public constraints rejected DARTIS insertion")
                checkpoint()
                plan.assignments.append(deepcopy(chosen.assignment))
                trace.append(dict(task_id=chosen.task_id,satellite_id=chosen.satellite_id,
                    window_id=chosen.window_id,start=chosen.inspected_start.isoformat(),
                    rescued=chosen.rescued,feasible_opportunities=len(opportunities)))
                plan.assignments.sort(key=_assignment_key)
                remaining.remove(chosen.task_id)
                version += 1
        except _BudgetExpired:
            reason = "budget"
        if context.is_cancelled():
            raise DARTISCancelled("DARTIS cancelled before return")
        repair_stats = {"stop_reason":"disabled", "improvements":0}
        if params.local_repair_rounds and reason != "budget" and remaining:
            from algorithms.dartis_repair import bounded_repair
            plan,repair_stats = bounded_repair(problem,constraints,context,plan,params,
                checkpoint,_BudgetExpired,_select_windows,_grid_steps,_assignment_key)
        if context.is_cancelled():
            raise DARTISCancelled("DARTIS cancelled during repair")
        exchange_stats = {"stop_reason":"disabled", "improvements":0}
        if params.conflict_exchange and reason != "budget" and len(plan.assignments)<len(problem.tasks):
            from algorithms.dartis_exchange import exchange
            metadata=plan.metadata
            plan,exchange_stats=exchange(problem,constraints,context,plan,params,checkpoint,
                _BudgetExpired,_assignment_key)
            plan.metadata.update(metadata)
        if context.is_cancelled():
            raise DARTISCancelled("DARTIS cancelled during exchange")
        # 聚合资源修复为可选策略；不改变存储/功率的公共定义，完整重放通过才接纳。
        resource_stats={"stop_reason":"disabled","accepted":0}
        if params.aggregate_resource_repair and reason!="budget" and len(plan.assignments)<len(problem.tasks):
            from algorithms.dartis_resources import improve
            metadata=plan.metadata
            plan,resource_stats=improve(problem,constraints,context,plan,params,checkpoint,
                _BudgetExpired,_assignment_key,_grid_steps)
            plan.metadata.update(metadata)
        if context.is_cancelled():raise DARTISCancelled("DARTIS cancelled during resource repair")
        plan.metadata["dartis"] = {
            "version": VERSION, "priority_mode": params.priority_mode,
            "stop_reason": reason, "approximate_laxity": True, "stats": stats,
            "greedy_trace":trace,"chosen_rescue_insertions":sum(x['rescued'] for x in trace),
            "local_repair":repair_stats,"conflict_exchange":exchange_stats,"aggregate_resource_repair":resource_stats}
        return plan
