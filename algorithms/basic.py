"""Non-preemptive, opportunity-aware textbook baselines on the shared EOS model.

There is no CPU arrival/deadline field in the datasets: release is the first
window start and deadline is the last window end. At each dispatch event only
tasks with an inspected feasible observation at that time compete. No exposure
is split, and no assignment is accepted without the public constraint model.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import math
import time

from pydantic import Field

from algorithms.objectives import ObjectiveModel, ObjectiveWeights
from algorithms.solver_contracts import AlgorithmParams, SolveContext
from schedulers.assignment_building import observation_at_index
from schedulers.constraint_model import Schedule

VERSION = "basic-1"
BASIC_ALGORITHMS = ("fcfs", "sjf", "priority", "edf", "llf", "hrrn")
BASIC_ALIASES = {"fcfo": "fcfs", "fifo": "fcfs"}


class BasicParams(AlgorithmParams):
    max_candidates_per_task: int = Field(128, ge=1, le=512, strict=True,
        title="每轮每任务候选上限", description="每次派发重新检查的完整观测/下传候选上限；达到上限可能遗漏机会。")
    max_windows_per_task: int = Field(32, ge=1, le=256, strict=True,
        title="每任务窗口上限", description="每轮按时间检查尚未过期的前若干观测窗口。")
    max_positions_per_window: int = Field(8, ge=1, le=64, strict=True,
        title="每窗口放置上限", description="在真实采样网格检查当前时刻、资源释放附近与均匀锚点；非敏捷卫星固定居中。")


class BasicCancelled(RuntimeError):
    pass


class _BudgetExpired(Exception):
    pass


def canonical_basic_name(name: str) -> str:
    name = name.strip().lower()
    return BASIC_ALIASES.get(name, name)


def _key(a):
    return (a.sat_start_time, a.gs_end_time or a.sat_end_time, a.satellite_id,
            a.sensor_id, a.sat_window_id, a.ground_station_id or "",
            a.gs_window_id or 0, a.gs_start_time or a.sat_end_time)


class BasicScheduler:
    def __init__(self, policy: str, params: BasicParams | None = None, *,
                 weights: ObjectiveWeights | None = None, time_budget_s: float = 60., seed: int = 42):
        self.policy = canonical_basic_name(policy)
        if self.policy not in BASIC_ALGORITHMS:
            raise ValueError(f"Unknown basic policy: {policy}")
        self.params = params or BasicParams()
        self.weights = weights or ObjectiveWeights()
        self.time_budget_s, self.seed = time_budget_s, seed

    def search(self, problem, constraint_model, initial_schedule):
        # A fresh baseline must not silently inherit an optimized initial plan.
        return self.solve(problem, constraint_model, SolveContext(
            self.seed, self.time_budget_s, self.weights, self.params))

    def _rank(self, task, release, deadline, ordinal, now):
        duration = float(task.required_duration)
        primary = {
            "fcfs": (release,),
            "sjf": (duration,),
            "priority": (-float(task.priority),),
            "edf": (deadline,),
            "llf": ((deadline - now).total_seconds() - duration,),
            "hrrn": (-(1. + max(0., (now - release).total_seconds()) / duration),),
        }[self.policy]
        return (*primary, release, ordinal)

    def _positions(self, problem, task, window, cm, plan, now, limit):
        step, duration = float(window.time_step), float(task.required_duration)
        slack = window.duration - duration
        if not all(math.isfinite(x) for x in (step, duration, slack)) or step <= 0 or duration <= 0 or slack < 0:
            return []
        last = math.floor((slack + 1e-9) / step)
        first = max(0, math.ceil((now - window.start_time).total_seconds() / step - 1e-9))
        if first > last:
            return []
        if problem.satellites[window.satellite_id].maneuverability_type == "non_agile":
            center = max(0, min(last, round(slack / (2 * step))))
            return [center] if center >= first else []
        if cm.placement_mode == "latest":
            return [last]
        if cm.placement_mode == "center":
            first = max(first, min(last, round(slack / (2 * step))))
        proposed = [first]
        for a in plan.get_assignments_for_satellite(window.satellite_id):
            # Re-evaluate real source angles when estimating slew at this anchor.
            base = max(first, math.ceil((a.sat_end_time - window.start_time).total_seconds() / step - 1e-9))
            if base <= last:
                probe = observation_at_index(problem, task, window, base)
                if probe is not None:
                    transition = cm._transition_time_s(window.satellite_id, a, probe)
                    if math.isfinite(transition):
                        proposed.append(max(first, math.ceil(((a.sat_end_time - window.start_time).total_seconds() + transition) / step - 1e-9)))
            if a.gs_end_time:
                proposed.append(max(first, math.ceil((a.gs_end_time - window.start_time).total_seconds() / step - 1e-9)))
        proposed.extend(round(first + (last-first)*i/max(1, limit-1)) for i in range(limit))
        chosen = list(dict.fromkeys(k for k in proposed if first <= k <= last))[:limit]
        return sorted(chosen)

    def _candidates(self, problem, task, cm, plan, now, params, comm, checkpoint):
        windows = sorted((w for w in task.windows if w.end_time >= now + timedelta(seconds=task.required_duration)
                          and w.satellite_id in problem.satellites),
                         key=lambda w: (w.start_time, w.satellite_id, w.window_id))[:params.max_windows_per_task]
        # Interleave windows so a dense first window cannot exhaust the task cap.
        positions = [(w, self._positions(problem, task, w, cm, plan, now, params.max_positions_per_window)) for w in windows]
        produced = 0
        for depth in range(params.max_positions_per_window):
            for w, indices in positions:
                checkpoint()
                if depth >= len(indices):
                    continue
                a = observation_at_index(problem, task, w, indices[depth])
                if a is None:
                    continue
                if not problem.ground_stations:
                    yield a
                    produced += 1
                else:
                    duration = timedelta(seconds=task.required_duration * cm.downlink_duration_ratio)
                    for cw in comm.get(w.satellite_id, []):
                        checkpoint()
                        # Public constraints require a strictly later downlink.
                        start = max(cw.start_time, a.sat_end_time + timedelta(microseconds=1))
                        ends = [start]
                        ends.extend(b.gs_end_time for b in plan.assignments if b.gs_end_time
                                    and (b.satellite_id == w.satellite_id or b.ground_station_id == cw.ground_station_id))
                        ends.extend(b.sat_end_time for b in plan.get_assignments_for_satellite(w.satellite_id))
                        for gs_start in sorted(set(t for t in ends if t >= start)):
                            checkpoint()
                            if gs_start + duration > cw.end_time:
                                continue
                            yield replace(a, ground_station_id=cw.ground_station_id, gs_window_id=cw.window_id,
                                          gs_start_time=gs_start, gs_end_time=gs_start+duration)
                            produced += 1
                            if produced >= params.max_candidates_per_task:
                                return
                if produced >= params.max_candidates_per_task:
                    return

    def solve(self, problem, constraints, context):
        from algorithms.objective_adapters.protocol import validate_weights
        validate_weights(context.objective_weights)
        params = BasicParams.model_validate(context.params.model_dump())
        started = time.monotonic()
        deadline = started + context.time_budget_s - min(.1, context.time_budget_s*.1)
        stats = dict(policy=self.policy, dispatch_order=[], constraint_checks=0,
                     objective_evaluations=0, budget_exit=False,
                     objective_role="same_task_same_start_placement_tiebreak",
                     release_rule="first_window_start", deadline_rule="last_window_end")

        def checkpoint():
            if context.is_cancelled():
                raise BasicCancelled("BASIC_SCHEDULER_CANCELLED")
            if time.monotonic() >= deadline:
                raise _BudgetExpired()

        plan = Schedule()
        objective = ObjectiveModel(problem, context.objective_weights)
        remaining = {}
        comm = {}
        now = problem.start_time
        try:
            for cw in problem.comm_windows:
                checkpoint()
                comm.setdefault(cw.satellite_id, []).append(cw)
            for rows in comm.values():
                rows.sort(key=lambda w: (w.start_time, w.window_id))
            for ordinal, (tid, task) in enumerate(problem.tasks.items()):
                checkpoint()
                if task.windows and math.isfinite(task.required_duration) and task.required_duration > 0:
                    remaining[tid] = (min(w.start_time for w in task.windows), max(w.end_time for w in task.windows), ordinal)
            while remaining:
                choices = []
                for tid, (release, end, ordinal) in remaining.items():
                    checkpoint()
                    task = problem.tasks[tid]
                    best = None
                    for a in self._candidates(problem, task, constraints, plan, now, params, comm, checkpoint):
                        checkpoint()
                        if best is not None and a.sat_start_time > best.sat_start_time:
                            continue
                        stats["constraint_checks"] += 1
                        if not constraints.is_feasible_assignment(a, plan):
                            continue
                        if best is None or a.sat_start_time < best.sat_start_time:
                            best = a
                        else:
                            # Weights choose placement only; never reorder the policy queue.
                            checkpoint()
                            old = objective.score(Schedule(plan.assignments + [best]))
                            new = objective.score(Schedule(plan.assignments + [a]))
                            stats["objective_evaluations"] += 2
                            if (-new, _key(a)) < (-old, _key(best)):
                                best = a
                    if best is not None:
                        choices.append((best.sat_start_time,
                            self._rank(task, release, end, ordinal, best.sat_start_time), _key(best), best))
                if not choices:
                    break
                checkpoint()
                selected = min(choices, key=lambda row: row[:3])[-1]
                plan.assignments.append(selected)
                now = selected.sat_start_time
                stats["dispatch_order"].append(selected.task_id)
                del remaining[selected.task_id]
        except _BudgetExpired:
            stats["budget_exit"] = True
        if context.is_cancelled():
            raise BasicCancelled("BASIC_SCHEDULER_CANCELLED")
        stats["search_seconds"] = time.monotonic() - started
        plan.metadata["basic_scheduler"] = stats
        return plan
