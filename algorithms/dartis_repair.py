"""DARTIS 有界单任务撤销与续排；只接纳按当前公共目标严格改善且完整重放通过的计划。

参考 2026-10-28 交付快照选择性移植；不引入 Score/v2 协议，不修改物理与指标口径。
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta

from algorithms.candidate_pool import enumerate_task_candidates
from algorithms.objectives import ObjectiveModel
from schedulers.constraint_model import Schedule


class _CheckLimit(Exception):
    pass


def bounded_repair(problem, constraints, context, initial, params, checkpoint,
                   budget_exception, select_windows, grid_steps, assignment_key):
    """Keep only improvements under the requested public objective.

    Candidate sampling, single ejections and two deterministic refill orders are
    bounded independently. A failed or interrupted proposal cannot replace the
    last fully checked incumbent. No reference solution or task identity is used.
    """
    objective = ObjectiveModel(problem, context.objective_weights)
    best = Schedule(list(initial.assignments))
    def quality(plan):
        return (objective.score(plan), len(plan.assignments))
    def better(a,b):return a > b
    best_quality = quality(best)
    stats = dict(checks=0, pool_candidates=0, windows_skipped=0, seeds=0,
                 refill_paths=0, rounds=0, improvements=0, duplicate_seeds=0,
                 stop_reason='completed', changes=[])
    seen = set()

    def check(candidate, plan):
        checkpoint()
        if stats['checks'] >= params.repair_max_checks:
            raise _CheckLimit()
        stats['checks'] += 1
        return constraints.is_feasible_assignment(candidate, plan)

    def replay(assignments):
        plan = Schedule()
        for a in sorted(assignments, key=assignment_key):
            if not check(a, plan):
                return None
            plan.assignments.append(a)
        return plan

    def signature(plan):
        return tuple(assignment_key(a) for a in sorted(plan.assignments, key=assignment_key))

    def remember(plan, removed, mode):
        nonlocal best, best_quality
        value = quality(plan)
        if better(value,best_quality):
            checked = replay(plan.assignments)
            if checked is None:
                return
            before = set(best.assigned_task_ids)
            after = set(checked.assigned_task_ids)
            stats['changes'].append(dict(removed_seed=removed, refill_mode=mode,
                score_before=best_quality[0], score_after=value[0],
                completed_before=len(best.assignments), completed_after=len(checked.assignments),
                added=sorted(after-before), dropped=sorted(before-after)))
            best, best_quality = checked, value
            stats['improvements'] += 1

    try:
        # Build source-derived options once; never invent an attitude or time slice.
        pool = []
        empty = Schedule()
        for tid, task in sorted(problem.tasks.items()):
            checkpoint()
            windows, _ = select_windows(task, params.max_windows_per_task)
            for window in windows:
                steps = grid_steps(problem, task, window)
                if not 0 < steps <= 1024:
                    stats['windows_skipped'] += 1
                    continue
                candidates = enumerate_task_candidates(problem, replace(task, windows=[window]),
                    placement_mode=constraints.placement_mode,
                    downlink_duration_ratio=constraints.downlink_duration_ratio,
                    max_candidates=4096, random_samples_per_window=0, seed=context.seed)
                checkpoint()
                by_start = defaultdict(list)
                for a in candidates:
                    by_start[a.sat_start_time].append(a)
                starts = sorted(by_start)
                if not starts:
                    continue
                proposed = [starts[0], starts[-1]]
                for a in sorted(initial.get_assignments_for_satellite(window.satellite_id),
                                key=assignment_key):
                    for boundary in (a.sat_end_time,
                                     a.sat_start_time-timedelta(seconds=task.required_duration)):
                        i = bisect_left(starts, boundary)
                        for j in (i, i-1):
                            if 0 <= j < len(starts):
                                proposed.append(starts[j])
                # Boundary-near starts occupy half the quota, uniform coverage the rest.
                selected = list(dict.fromkeys(proposed))[:max(2,params.repair_positions_per_window//2)]
                n = len(starts)-1
                for i in range(params.repair_positions_per_window):
                    start = starts[round(n*i/max(1,params.repair_positions_per_window-1))]
                    if start not in selected:
                        selected.append(start)
                    if len(selected) >= params.repair_positions_per_window:
                        break
                for start in sorted(selected):
                    for a in sorted(by_start[start], key=assignment_key)[:16]:
                        if check(a, empty):
                            pool.append(a)
                        if len(pool) >= 4096:
                            break
                    if len(pool) >= 4096:
                        break
                if len(pool) >= 4096:
                    break
            if len(pool) >= 4096:
                break
        stats['pool_candidates'] = len(pool)
        pool.sort(key=assignment_key)
        for _ in range(params.local_repair_rounds):
            checkpoint()
            stats['rounds'] += 1
            origin = Schedule(list(best.assignments))
            origin_quality = best_quality
            missing = set(problem.tasks)-set(origin.assigned_task_ids)

            def blocking_rank(a):
                overlaps = sum(w.satellite_id == a.satellite_id
                    and w.start_time < a.sat_end_time and a.sat_start_time < w.end_time
                    for tid in sorted(missing) for w in problem.tasks[tid].windows)
                return (-overlaps, assignment_key(a))

            removed_options = [None] + sorted(origin.assignments,key=blocking_rank)[:params.repair_ejection_limit]
            for removed in removed_options:
                seed = replay(a for a in origin.assignments if a is not removed)
                if seed is None:
                    continue
                seed_key = signature(seed)
                if seed_key in seen:
                    stats['duplicate_seeds'] += 1
                    continue
                seen.add(seed_key)
                stats['seeds'] += 1
                for mode in ('objective_urgency','chronological'):
                    stats['refill_paths'] += 1
                    plan = Schedule(list(seed.assignments))
                    for _ in problem.tasks:
                        checkpoint()
                        assigned = set(plan.assigned_task_ids)
                        winner = None
                        for a in pool:
                            # An ejection must expose one different first decision;
                            # the removed task may be reinserted after that decision.
                            if (removed is not None and len(plan.assignments)==len(seed.assignments)
                                    and a.task_id==removed.task_id):
                                continue
                            if a.task_id in assigned or not check(a,plan):
                                continue
                            task = problem.tasks[a.task_id]
                            window = next(w for w in task.windows if w.window_id==a.sat_window_id)
                            laxity = (window.end_time-a.sat_start_time).total_seconds()-task.required_duration
                            proposal = Schedule(plan.assignments+[a])
                            candidate_rank = ((-objective.score(proposal), laxity, window.end_time, assignment_key(a))
                                              if mode == 'objective_urgency' else
                                              (a.sat_start_time, -objective.score(proposal), laxity, assignment_key(a)))
                            if winner is None or candidate_rank < winner[0]:
                                winner=(candidate_rank,a)
                        if winner is None:
                            break
                        plan.assignments.append(winner[1])
                        remember(plan, None if removed is None else removed.task_id, mode)
            if best_quality == origin_quality:
                break
    except _CheckLimit:
        stats['stop_reason']='check_limit'
    except budget_exception:
        stats['stop_reason']='budget'
    return best,stats
