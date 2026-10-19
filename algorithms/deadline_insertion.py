"""Offline DARTIS: bounded EDF/LLF insertion using shared candidates and constraints."""
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

VERSION = "0.1.0"
# candidate_pool eagerly builds the grid: reject larger agile grids in G1-A.
_MAX_GRID_STEPS = 1024
_MAX_POOL_ASSIGNMENTS = 4096
_MAX_DOWNLINK_CHECKS = 16


class DARTISParams(AlgorithmParams):
    model_config = ConfigDict(extra="forbid", frozen=True)
    priority_mode: Literal["llf", "edf"] = Field("llf", description="llf 按受检机会的近似松弛度优先，edf 按观测窗口结束时间优先；另一项作为次级排序键。")
    max_windows_per_task: int = Field(8, ge=1, le=64, strict=True)
    max_positions_per_window: int = Field(4, ge=1, le=32, strict=True)
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
                     pool_limit_reached_windows=0)
        version = 0
        reason = "completed"

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
                        stats["positions_truncated"] += len(starts) - len(selected)
                        feasible = None
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
                        if feasible is not None:
                            laxity = ((window.end_time - feasible.sat_start_time).total_seconds()
                                      - task.required_duration)
                            opportunities.append(Opportunity(
                                task_id, window.satellite_id, window.window_id,
                                window.end_time, feasible.sat_start_time,
                                laxity, feasible, version))
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
                plan.assignments.sort(key=_assignment_key)
                remaining.remove(chosen.task_id)
                version += 1
        except _BudgetExpired:
            reason = "budget"
        if context.is_cancelled():
            raise DARTISCancelled("DARTIS cancelled before return")
        plan.metadata["dartis"] = {
            "version": VERSION, "priority_mode": params.priority_mode,
            "stop_reason": reason, "approximate_laxity": True, "stats": stats}
        return plan
