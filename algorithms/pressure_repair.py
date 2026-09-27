"""Conflict-pressure construction with a bounded single-task reinsertion pass."""

from __future__ import annotations

from dataclasses import dataclass

from algorithms.candidate_pool import enumerate_task_candidates
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import SchedulingProblem, TaskWindow


@dataclass
class PressureRepairConfig:
    seed: int = 20260927
    max_candidates_per_task: int = 64
    max_repair_checks: int = 2000


def _overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


class PressureRepairScheduler:
    def __init__(self, cfg: PressureRepairConfig | None = None) -> None:
        self.cfg = cfg or PressureRepairConfig()

    def search(
        self,
        problem: SchedulingProblem,
        constraint_model: ConstraintModel,
        initial_schedule: Schedule,
    ) -> Schedule:
        # Build the same candidate type used by the official heuristics.
        task_ids = sorted(problem.tasks)
        candidates: dict[str, list[Assignment]] = {}
        for index, tid in enumerate(task_ids):
            candidates[tid] = enumerate_task_candidates(
                problem=problem,
                task=problem.tasks[tid],
                placement_mode=constraint_model.placement_mode,
                downlink_duration_ratio=constraint_model.downlink_duration_ratio,
                max_candidates=self.cfg.max_candidates_per_task,
                random_samples_per_window=0,
                seed=self.cfg.seed + index,
            )

        windows: dict[str, list[TaskWindow]] = {
            tid: problem.tasks[tid].windows for tid in task_ids
        }
        pressure: dict[str, float] = {}
        for tid in task_ids:
            own = windows[tid]
            conflicts = sum(
                _overlap(w.start_time, w.end_time, other.start_time, other.end_time)
                for w in own
                for other_tid in task_ids
                if other_tid != tid
                for other in windows[other_tid]
                if w.satellite_id == other.satellite_id
            )
            pressure[tid] = conflicts / max(1, len(own))

        # Scarce, contested tasks are considered first. Candidate cost estimates
        # how many other raw windows would be occupied by the placement.
        def task_key(tid: str):
            return (
                len(windows[tid]) if candidates[tid] else float("inf"),
                -pressure[tid],
                -float(problem.tasks[tid].priority),
                tid,
            )

        def candidate_key(candidate: Assignment):
            conflicts = sum(
                _overlap(
                    candidate.sat_start_time,
                    candidate.sat_end_time,
                    window.start_time,
                    window.end_time,
                )
                for other_tid in task_ids
                if other_tid != candidate.task_id
                for window in windows[other_tid]
                if window.satellite_id == candidate.satellite_id
            )
            return (conflicts, candidate.sat_end_time, candidate.satellite_id)

        for tid in task_ids:
            candidates[tid].sort(key=candidate_key)

        schedule = Schedule()
        for tid in sorted(task_ids, key=task_key):
            for candidate in candidates[tid]:
                if constraint_model.is_feasible_assignment(candidate, schedule):
                    schedule.assignments.append(candidate)
                    break

        # A repair is accepted only if the displaced task can be reinserted:
        # completion count and total positive task profit then both increase.
        checks = 0
        while checks < self.cfg.max_repair_checks:
            changed = False
            assigned = set(schedule.assigned_task_ids)
            for tid in sorted((t for t in task_ids if t not in assigned), key=task_key):
                if float(problem.tasks[tid].priority) < 0:
                    continue
                for candidate in candidates[tid]:
                    checks += 1
                    if constraint_model.is_feasible_assignment(candidate, schedule):
                        schedule.assignments.append(candidate)
                        changed = True
                        break
                    if checks >= self.cfg.max_repair_checks:
                        break
                    blockers = list(schedule.assignments)
                    for blocker in blockers:
                        if checks >= self.cfg.max_repair_checks:
                            break
                        reduced = Schedule(
                            assignments=[a for a in schedule.assignments if a is not blocker]
                        )
                        checks += 1
                        if not constraint_model.is_feasible_assignment(candidate, reduced):
                            continue
                        reduced.assignments.append(candidate)
                        for replacement in candidates[blocker.task_id]:
                            checks += 1
                            if constraint_model.is_feasible_assignment(replacement, reduced):
                                reduced.assignments.append(replacement)
                                schedule = reduced
                                changed = True
                                break
                            if checks >= self.cfg.max_repair_checks:
                                break
                        if changed:
                            break
                    if changed:
                        break
                if changed or checks >= self.cfg.max_repair_checks:
                    break
            if not changed:
                break

        schedule.metadata["repair_checks"] = checks
        return schedule
