"""把旧调度内核包装成可复用的内存计算入口。"""

from __future__ import annotations

import time
from pathlib import Path

from algorithms.factory import create_algorithm
from algorithms.objectives import ObjectiveWeights
from schedulers.constraint_model import ConstraintModel
from schedulers.engine import SchedulingEngine
from schedulers.scenario_loader import SchedulingProblem, load_scheduling_problem_from_json
from schedulers.schedule_output import schedule_to_dict

from .contracts import RunConfig, validate_algorithm_params


def build_constraint_model(problem, config: RunConfig) -> ConstraintModel:
    """运行和复核必须调用同一个构造函数，防止约束参数漂移。"""
    return ConstraintModel(
        problem=problem,
        placement_mode=config.placement_mode,
        unassigned_penalty=config.constraints.unassigned_penalty,
        downlink_duration_ratio=config.constraints.downlink_duration_ratio,
        agility_profile=config.constraints.agility_profile,
        non_agile_transition_s=config.constraints.non_agile_transition_s,
    )


def prepare(config: RunConfig) -> tuple[SchedulingEngine, SchedulingProblem]:
    """加载只读场景并构造调度器；耗时不计入算法搜索预算。"""
    validate_algorithm_params(config.algorithm_id, config.algorithm_params)
    problem = load_scheduling_problem_from_json(Path(config.scenario_path))
    constraint_model = build_constraint_model(problem, config)
    params = dict(config.algorithm_params)
    params["seed"] = config.seed
    if config.algorithm_id == "adaptive_repair":
        params["time_budget_s"] = config.time_budget_s
    weights = ObjectiveWeights(**config.objective_weights.model_dump())
    algorithm = create_algorithm(config.algorithm_id, objective_weights=weights, cfg_overrides=params)
    engine = SchedulingEngine(problem, constraint_model, algorithm)
    return engine, problem


def run_prepared(engine: SchedulingEngine, problem: SchedulingProblem) -> tuple[dict, float]:
    """仅计时算法搜索，随后将内存计划转换成纯数据候选结果。"""
    started = time.perf_counter()
    schedule = engine.run()
    runtime = time.perf_counter() - started
    return schedule_to_dict(schedule, problem), runtime


def calculate(config: RunConfig) -> tuple[dict, float]:
    """供命令行对照使用的便捷入口；正式 Worker 分阶段调用。"""
    engine, problem = prepare(config)
    return run_prepared(engine, problem)
