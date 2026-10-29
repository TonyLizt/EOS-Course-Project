"""两种不做收益优化的简单基线，使用现有来源候选和公共约束。

随机基线不是故意丢任务：随机打乱任务与受检放置，接受首个合法安排。
轮询基线在卫星间循环选择首个合法放置，不等同于可抢占的CPU时间片RR。
两者从空计划出发、单次插入、不回溯；不叠加R1全局目标修复。
"""
from __future__ import annotations

import math
import random
import time

from algorithms.basic import BasicParams, BasicScheduler
from algorithms.objective_adapters.protocol import validate_weights
from schedulers.constraint_model import Schedule

VERSION = 'simple-baseline-1'
SIMPLE_BASELINES = ('random_feasible', 'satellite_round_robin')


class SimpleBaselineCancelled(RuntimeError):
    """协作取消必须抛出，不能把取消误报为成功返回。"""


class _BudgetExpired(Exception):
    """仅由当前基线的时间检查产生；返回已接受的完整计划。"""


class SimpleBaselineScheduler:
    """离线、非抢占式的简单构造器；所有状态均局限于本次solve。"""

    def __init__(self, policy: str, *, clock=time.monotonic):
        if policy not in SIMPLE_BASELINES:
            raise ValueError('未知简单基线：'+policy)
        self.policy, self.clock = policy, clock

    def solve(self, problem, constraints, context):
        """按公开策略依次尝试安排，每项任务最多成功一次。"""
        validate_weights(context.objective_weights)
        if not math.isfinite(context.time_budget_s) or context.time_budget_s <= 0:
            raise ValueError('算法预算必须为正的有限数')
        params = BasicParams.model_validate(context.params.model_dump())
        rng = random.Random(context.seed)  # 不污染全局随机数，便于固定种子复验。
        deadline = self.clock()+context.time_budget_s-min(.1, context.time_budget_s*.1)
        plan = Schedule()
        stats = dict(policy=self.policy, seed=context.seed, task_order=[],
                     accepted_order=[], constraint_checks=0, generated_candidates=0,
                     stop_reason='completed', uses_initial_schedule=False,
                     objective_role='evaluation_only_no_objective_search')

        def checkpoint():
            if context.is_cancelled():
                raise SimpleBaselineCancelled('SIMPLE_BASELINE_CANCELLED')
            if self.clock() >= deadline:
                raise _BudgetExpired()

        # 复用六种OS基线的有界来源网格/固定载荷/下传构造器，保持相同资源值。
        generator = BasicScheduler('fcfs', params)
        comm = {}
        cursor = 0
        try:
            for window in problem.comm_windows:
                checkpoint()
                comm.setdefault(window.satellite_id, []).append(window)
            for windows in comm.values():
                windows.sort(key=lambda w:(w.start_time,w.window_id))
            tasks = []
            for task in problem.tasks.values():
                checkpoint()
                if task.windows and math.isfinite(task.required_duration) and task.required_duration > 0:
                    tasks.append(task)
            # 先规范排序，再随机洗牌，防止JSON对象排列隐式改变同种子结果。
            tasks.sort(key=lambda t:t.id)
            satellites = sorted(problem.satellites)
            if self.policy == 'random_feasible':
                rng.shuffle(tasks)
            else:
                tasks.sort(key=lambda t:(min(w.start_time for w in t.windows),t.id))
            for task in tasks:
                checkpoint()
                stats['task_order'].append(task.id)
                candidates = []
                for candidate in generator._candidates(problem,task,constraints,plan,
                        problem.start_time,params,comm,checkpoint):
                    checkpoint()
                    candidates.append(candidate)
                stats['generated_candidates'] += len(candidates)
                if self.policy == 'random_feasible':
                    rng.shuffle(candidates)
                else:
                    # 每次中标后移动游标；当前星不可行时继续轮询其余星。
                    rank = {sid:(i-cursor)%len(satellites) for i,sid in enumerate(satellites)}
                    candidates.sort(key=lambda a:(rank[a.satellite_id],a.sat_start_time,
                        a.sat_end_time,a.sat_window_id,a.gs_start_time or a.sat_end_time,
                        a.ground_station_id or '',a.gs_window_id or 0))
                for candidate in candidates:
                    checkpoint()
                    stats['constraint_checks'] += 1
                    valid = constraints.is_feasible_assignment(candidate,plan)
                    checkpoint()
                    if valid:
                        plan.assignments.append(candidate)
                        stats['accepted_order'].append(task.id)
                        if self.policy == 'satellite_round_robin':
                            cursor = (satellites.index(candidate.satellite_id)+1)%len(satellites)
                        break
        except _BudgetExpired:
            stats['stop_reason'] = 'budget'
        if context.is_cancelled():
            raise SimpleBaselineCancelled('SIMPLE_BASELINE_CANCELLED')
        plan.metadata['simple_baseline'] = stats
        return plan
