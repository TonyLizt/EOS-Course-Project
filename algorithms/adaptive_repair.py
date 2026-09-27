"""Completion-first scheduling with dynamic scarcity and bounded local repair.

The objective is lexicographic: completed tasks, then total task priority,
then earlier observations. Every accepted assignment uses the shared
ConstraintModel; feasibility rules are not duplicated here.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, replace

from algorithms.candidate_pool import enumerate_task_candidates
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import SchedulingProblem, SchedulingTask


@dataclass
class AdaptiveRepairConfig:
    seed: int = 20260927
    max_candidates_per_task: int = 72
    probe_candidates: int = 24
    scan_tasks: int = 48
    dynamic_selection: bool = True
    chain_depth: int = 2
    chain_candidate_limit: int = 24
    max_blockers: int = 5
    max_repair_checks: int = 6000
    alns_iterations: int = 30
    destroy_size: int = 4
    time_budget_s: float = 60.0


class AdaptiveRepairScheduler:
    def __init__(self, cfg: AdaptiveRepairConfig | None = None) -> None:
        self.cfg = cfg or AdaptiveRepairConfig()

    def _diverse_candidates(
        self, problem: SchedulingProblem, task: SchedulingTask,
        cm: ConstraintModel, seed: int,
    ) -> list[Assignment]:
        """Reserve candidate slots for every usable window before filling extras."""
        limit = max(1, self.cfg.max_candidates_per_task)
        windows = sorted(
            (w for w in task.windows if w.duration + 1e-9 >= task.required_duration),
            key=lambda w: (w.start_time, w.satellite_id, w.window_id),
        )
        if len(windows) > limit:
            # Evenly cover the horizon instead of taking only early windows.
            if limit == 1:
                windows = [windows[0]]
            else:
                windows = [windows[round(i * (len(windows) - 1) / (limit - 1))]
                           for i in range(limit)]
        if not windows:
            return []

        per_window = max(1, math.ceil(limit / len(windows)))
        buckets: list[list[Assignment]] = []
        for index, window in enumerate(windows):
            one_window_task = replace(task, windows=[window])
            buckets.append(enumerate_task_candidates(
                problem=problem,
                task=one_window_task,
                placement_mode=cm.placement_mode,
                downlink_duration_ratio=cm.downlink_duration_ratio,
                max_candidates=per_window,
                random_samples_per_window=0,
                seed=seed + index,
            ))

        result: list[Assignment] = []
        for position in range(per_window):
            for bucket in buckets:
                if position < len(bucket):
                    result.append(bucket[position])
                    if len(result) >= limit:
                        return result
        return result

    @staticmethod
    def _quality(problem: SchedulingProblem, schedule: Schedule) -> tuple[int, float, float]:
        assignments = schedule.assignments
        return (
            len(assignments),
            sum(float(problem.tasks[a.task_id].priority) for a in assignments),
            -sum((a.sat_start_time - problem.start_time).total_seconds() for a in assignments),
        )

    @staticmethod
    def _nearby_blockers(
        candidate: Assignment, schedule: Schedule, limit: int,
    ) -> list[Assignment]:
        related = [
            a for a in schedule.assignments
            if a.satellite_id == candidate.satellite_id
            or (candidate.ground_station_id is not None
                and a.ground_station_id == candidate.ground_station_id)
        ]
        related.sort(key=lambda a: (
            max(0.0, (candidate.sat_start_time - a.sat_end_time).total_seconds(),
                (a.sat_start_time - candidate.sat_end_time).total_seconds()),
            a.task_id,
        ))
        return related[:limit]

    def _destroy_blockers(
        self, candidate: Assignment, schedule: Schedule, mode: str,
    ) -> list[Assignment]:
        nearby = self._nearby_blockers(candidate, schedule, len(schedule.assignments))
        if mode == "orbit":
            nearby.sort(key=lambda a: (
                a.satellite_id != candidate.satellite_id
                or a.orbit_number != candidate.orbit_number,
                max(0.0, (candidate.sat_start_time - a.sat_end_time).total_seconds(),
                    (a.sat_start_time - candidate.sat_end_time).total_seconds()),
            ))
        return nearby[:self.cfg.destroy_size]

    def _repair_feasible(
        self, candidate: Assignment, schedule: Schedule,
        cm: ConstraintModel, budget: dict[str, int], deadline: float,
    ) -> bool:
        if budget["checks"] >= budget["limit"] or time.monotonic() >= deadline:
            return False
        budget["checks"] += 1
        return cm.is_feasible_assignment(candidate, schedule)

    def _insert_chain(
        self, tid: str, schedule: Schedule, depth: int,
        protected: frozenset[str], candidates: dict[str, list[Assignment]],
        cm: ConstraintModel, budget: dict[str, int], deadline: float,
    ) -> Schedule | None:
        for candidate in candidates[tid][:self.cfg.chain_candidate_limit]:
            if budget["checks"] >= budget["limit"] or time.monotonic() >= deadline:
                return None
            if self._repair_feasible(candidate, schedule, cm, budget, deadline):
                return Schedule(assignments=schedule.assignments + [candidate])
            if depth <= 0:
                continue
            for blocker in self._nearby_blockers(candidate, schedule, self.cfg.max_blockers):
                if blocker.task_id in protected:
                    continue
                reduced = Schedule(assignments=[a for a in schedule.assignments if a is not blocker])
                if not self._repair_feasible(candidate, reduced, cm, budget, deadline):
                    continue
                placed = Schedule(assignments=reduced.assignments + [candidate])
                repaired = self._insert_chain(
                    blocker.task_id, placed, depth - 1,
                    protected | {tid}, candidates, cm, budget, deadline,
                )
                if repaired is not None:
                    return repaired
        return None

    def search(
        self, problem: SchedulingProblem, constraint_model: ConstraintModel,
        initial_schedule: Schedule,
    ) -> Schedule:
        started = time.monotonic()
        deadline = started + max(0.0, self.cfg.time_budget_s)
        rng = random.Random(self.cfg.seed)
        task_ids = sorted(problem.tasks)
        candidates = {
            tid: self._diverse_candidates(problem, problem.tasks[tid], constraint_model,
                                          self.cfg.seed + 7919 * index)
            for index, tid in enumerate(task_ids)
        }
        window_count = {
            tid: len({(a.satellite_id, a.sat_window_id) for a in candidates[tid]})
            for tid in task_ids
        }

        def scarcity_key(tid: str):
            return (window_count[tid], -float(problem.tasks[tid].priority), tid)

        schedule = Schedule()
        remaining = {tid for tid in task_ids if candidates[tid]}
        construction_checks = 0
        while remaining:
            ordered = sorted(remaining, key=scarcity_key)
            best: tuple | None = None
            if self.cfg.dynamic_selection:
                sampled = ordered[:self.cfg.scan_tasks]
                if len(ordered) > self.cfg.scan_tasks:
                    tail = ordered[self.cfg.scan_tasks:]
                    sampled += rng.sample(tail, min(8, len(tail)))
                for tid in sampled:
                    feasible: list[Assignment] = []
                    for candidate in candidates[tid][:self.cfg.probe_candidates]:
                        construction_checks += 1
                        if constraint_model.is_feasible_assignment(candidate, schedule):
                            feasible.append(candidate)
                    if feasible:
                        pick = min(feasible, key=lambda a: (a.sat_end_time, a.satellite_id))
                        key = (len(feasible), *scarcity_key(tid), pick.sat_end_time)
                        if best is None or key < best[0]:
                            best = (key, tid, pick)
            else:
                for tid in ordered:
                    for candidate in candidates[tid]:
                        construction_checks += 1
                        if constraint_model.is_feasible_assignment(candidate, schedule):
                            best = ((), tid, candidate)
                            break
                    if best is not None:
                        break

            if best is None:
                # A complete pass prevents the probe limit from hiding a task.
                for tid in ordered:
                    for candidate in candidates[tid]:
                        construction_checks += 1
                        if constraint_model.is_feasible_assignment(candidate, schedule):
                            best = ((), tid, candidate)
                            break
                    if best is not None:
                        break
            if best is None:
                break
            schedule.assignments.append(best[2])
            remaining.remove(best[1])

        if self._quality(problem, initial_schedule) > self._quality(problem, schedule):
            schedule = Schedule(assignments=list(initial_schedule.assignments))
        budget = {"checks": 0, "limit": max(1, self.cfg.max_repair_checks // 2)}
        chain_gains = 0
        while time.monotonic() < deadline and budget["checks"] < budget["limit"]:
            changed = False
            assigned = set(schedule.assigned_task_ids)
            for tid in sorted((t for t in task_ids if t not in assigned and candidates[t]),
                              key=scarcity_key):
                repaired = self._insert_chain(
                    tid, schedule, self.cfg.chain_depth, frozenset(),
                    candidates, constraint_model, budget, deadline,
                )
                if repaired is not None and self._quality(problem, repaired) > self._quality(problem, schedule):
                    schedule = repaired
                    chain_gains += 1
                    changed = True
                    break
            if not changed:
                break

        best_schedule = schedule
        current = schedule
        alns_gains = 0
        operator_weights = {"temporal": 1.0, "orbit": 1.0}
        budget["limit"] = self.cfg.max_repair_checks
        for _ in range(self.cfg.alns_iterations):
            if time.monotonic() >= deadline or budget["checks"] >= budget["limit"]:
                break
            assigned = set(current.assigned_task_ids)
            unassigned = [t for t in task_ids if t not in assigned and candidates[t]]
            if not unassigned:
                break
            unassigned.sort(key=scarcity_key)
            tid = rng.choice(unassigned[:min(16, len(unassigned))])
            modes = list(operator_weights)
            mode = rng.choices(modes, weights=[operator_weights[m] for m in modes])[0]
            reward = 0.0
            trials = candidates[tid][:]
            rng.shuffle(trials)
            for candidate in trials[:self.cfg.chain_candidate_limit]:
                removed: list[Assignment] = []
                reduced = Schedule(assignments=list(current.assignments))
                for blocker in self._destroy_blockers(candidate, current, mode):
                    if self._repair_feasible(candidate, reduced, constraint_model, budget, deadline):
                        break
                    reduced.assignments.remove(blocker)
                    removed.append(blocker)
                if not self._repair_feasible(candidate, reduced, constraint_model, budget, deadline):
                    continue
                reduced.assignments.append(candidate)
                for displaced in sorted(removed, key=lambda a: scarcity_key(a.task_id)):
                    repaired = self._insert_chain(
                        displaced.task_id, reduced, 0, frozenset(),
                        candidates, constraint_model, budget, deadline,
                    )
                    if repaired is not None:
                        reduced = repaired
                if len(reduced.assignments) < len(current.assignments):
                    continue
                if self._quality(problem, reduced) > self._quality(problem, best_schedule):
                    best_schedule = reduced
                    alns_gains += 1
                    reward = 3.0
                if (self._quality(problem, reduced) >= self._quality(problem, current)
                        or rng.random() < 0.25):
                    current = reduced
                    reward = max(reward, 1.0)
                break
            operator_weights[mode] = 0.8 * operator_weights[mode] + 0.2 * (1.0 + reward)

        best_schedule.metadata.update({
            "construction_checks": construction_checks,
            "repair_checks": budget["checks"],
            "chain_gains": chain_gains,
            "alns_gains": alns_gains,
            "alns_operator_weights": operator_weights,
            "dynamic_selection": self.cfg.dynamic_selection,
            "time_budget_s": self.cfg.time_budget_s,
        })
        return best_schedule
