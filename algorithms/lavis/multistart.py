"""原权重多分支续排：模型仍决定每步排序，按实际可行完成数保留结果。"""
import time
from schedulers.constraint_model import Schedule
from .protocol import Control, BudgetExpired, validate_weights
from .candidates import build_pool, feasible, key
from .features import extract
import math


def solve_multistart(solver, problem, constraints, context):
    validate_weights(context.objective_weights)
    started = time.monotonic()
    reserve = max(.1, .05 * context.time_budget_s)
    if context.time_budget_s <= reserve:
        raise ValueError('LAVIS_BUDGET_TOO_SMALL')
    control = Control(deadline=started + context.time_budget_s - reserve,
                      cancelled=context.is_cancelled)
    best = Schedule(); stats = {'branches_completed': 0, 'budget_exit': False}

    def ranking(plan, pool):
        current = feasible(pool, plan, constraints, control)
        if not current:
            return []
        rows = extract(problem, plan, pool, current, control)
        scores = []
        for offset in range(0, len(rows), 256):
            control.checkpoint()
            scores.extend(map(float, solver.predictor.predict(rows[offset:offset+256])))
        if len(scores) != len(current) or not all(math.isfinite(v) for v in scores):
            raise ValueError('LAVIS_NONFINITE_OR_MISSING_PREDICTION')
        return sorted(zip(current, scores), key=lambda item: (-item[1], key(item[0])))

    def quality(plan):
        # 主目标始终为完成数；相同完成数再比较收益和开始时间。
        return (len(plan.assignments), sum(problem.tasks[a.task_id].priority for a in plan.assignments),
                -sum((a.sat_start_time-problem.start_time).total_seconds() for a in plan.assignments))

    def remember(plan):
        nonlocal best
        if quality(plan) > quality(best):
            best = Schedule(list(plan.assignments))

    def complete(plan, pool):
        for _ in problem.tasks:
            ranked = ranking(plan, pool)
            if not ranked:
                break
            candidate = ranked[0][0]
            if not control.check(constraints, candidate, plan, static=True):
                raise ValueError('LAVIS_FEASIBILITY_CHANGED')
            plan.assignments.append(candidate)
            remember(plan)
        return plan

    try:
        pool, pool_stats = build_pool(problem, constraints, control)
        stats['pool'] = pool_stats
        # 先完成原模型路径作为 incumbent；不是用传统算法替换机器学习。
        original = complete(Schedule(), pool)
        stats['initial_completed'] = len(original.assignments)
        if context.params.candidate_strategy == 'expanded':
            # 先保留旧候选模型路径，再增广机会；新位置仍逐项通过共享约束。
            pool, expanded_stats = build_pool(problem, constraints, control, strategy='expanded')
            stats['expanded_pool'] = expanded_stats
            complete(Schedule(list(best.assignments)), pool)
            original = complete(Schedule(), pool)
        # 较早决策先试第二候选，再试第三候选；每条分支重新用模型续排。
        attempts = 0
        for alternate in (1, 2):
            for index in range(len(original.assignments)):
                control.checkpoint()
                if attempts >= context.params.max_branches:
                    break
                prefix = Schedule(list(original.assignments[:index]))
                ranked = ranking(prefix, pool)
                if len(ranked) <= alternate:
                    continue
                attempts += 1
                candidate = ranked[alternate][0]
                if not control.check(constraints, candidate, prefix, static=True):
                    continue
                prefix.assignments.append(candidate); remember(prefix)
                complete(prefix, pool)
                stats['branches_completed'] += 1
            if attempts >= context.params.max_branches:
                break
    except BudgetExpired:
        stats['budget_exit'] = True
    # 协作取消会继续抛出，不把缓存计划冒充取消后的成功。
    if control.cancelled():
        control.checkpoint()
    best.metadata = {'lavis': {'search_mode': 'multistart', 'stats': stats,
                             'checks': control.checks, 'weights_reused': True}}
    return best
