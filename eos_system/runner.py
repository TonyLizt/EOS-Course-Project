"""把旧调度内核包装成可复用的内存计算入口。"""

from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path

from schedulers.constraint_model import ConstraintModel
from schedulers.scenario_loader import SchedulingProblem, load_scheduling_problem_from_json
from schedulers.schedule_output import schedule_to_dict

from .algorithm_registry import SolveContext, Solver, get_algorithm, make_context
from .contracts import RunConfig
from .provenance import verify_provenance


def build_constraint_model(problem, config: RunConfig) -> ConstraintModel:
    """运行和复核必须调用同一个构造函数，防止约束参数漂移。"""
    problem.execution_mode = config.execution_mode
    return ConstraintModel(
        problem=problem,
        placement_mode=config.placement_mode,
        unassigned_penalty=config.constraints.unassigned_penalty,
        downlink_duration_ratio=config.constraints.downlink_duration_ratio,
        agility_profile=config.constraints.agility_profile,
        non_agile_transition_s=config.constraints.non_agile_transition_s,
    )


def prepare(config: RunConfig) -> tuple[Solver, SchedulingProblem, ConstraintModel, SolveContext]:
    """加载只读场景并构造调度器；耗时不计入算法搜索预算。"""
    verify_provenance(config)
    spec = get_algorithm(config.algorithm_id)
    problem = load_scheduling_problem_from_json(Path(config.scenario_path))
    constraint_model = build_constraint_model(problem, config)
    context = make_context(config.seed, config.time_budget_s, config.objective_weights.model_dump(), spec, config.algorithm_params,
                           schedule_model=config.schedule_model)
    solver = spec.build(context)
    internal = getattr(getattr(solver, 'algorithm', None), 'cfg', None)
    if internal is not None:
        for key in ('agility_profile', 'non_agile_transition_s'):
            if hasattr(internal, key):
                setattr(internal, key, getattr(config.constraints, key))
    return solver, problem, constraint_model, context


def run_prepared(solver: Solver, problem: SchedulingProblem, constraints: ConstraintModel, context: SolveContext) -> tuple[dict, float]:
    """仅计时算法搜索，随后将内存计划转换成纯数据候选结果。"""
    started = time.perf_counter()
    schedule = solver.solve(problem, constraints, context)
    runtime = time.perf_counter() - started
    candidate = schedule_to_dict(schedule, problem)
    # Diagnostics are untrusted Worker telemetry, never feasibility evidence.
    # Independent verification rebuilds the plan and deliberately drops these.
    if schedule.metadata:
        candidate["solver_diagnostics"] = deepcopy(schedule.metadata)
    return candidate, runtime


def calculate(config: RunConfig) -> tuple[dict, float]:
    """供命令行对照使用的便捷入口；正式 Worker 分阶段调用。"""
    solver, problem, constraints, context = prepare(config)
    return run_prepared(solver, problem, constraints, context)
