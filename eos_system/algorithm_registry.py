"""第二阶段算法注册表。

统一的是元数据、参数校验与结果边界；算法内部可采用任意搜索或学习方法。
旧 EOS-Bench 算法通过适配器接入，因而不改变旧 CLI 的工厂调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Callable

from pydantic import Field, ValidationError

from algorithms.conflict_beam import CAABSParams, ConflictBeamScheduler, VERSION as CAABS_VERSION
from algorithms.factory import create_algorithm
from algorithms.objectives import ObjectiveWeights
# Re-export the existing public names for HTTP/Worker and third-party callers.
from algorithms.solver_contracts import AlgorithmParams, SolveContext, Solver
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.engine import SchedulingEngine
from schedulers.scenario_loader import SchedulingProblem


class CompletionParams(AlgorithmParams):
    pass


class AdaptiveRepairParams(AlgorithmParams):
    max_candidates_per_task: int | None = Field(default=None, ge=1, le=512)
    alns_iterations: int | None = Field(default=None, ge=0, le=500)


@dataclass(frozen=True)
class AlgorithmSpec:
    algorithm_id: str
    name: str
    category: str
    owner: str
    version: str
    params_model: type[AlgorithmParams]
    build: Callable[[SolveContext], Solver] = field(repr=False)
    description: str = ""

    def parse_params(self, raw: dict) -> AlgorithmParams:
        if not isinstance(raw, dict):
            raise ValueError("算法参数必须是 JSON 对象")
        try:
            return self.params_model.model_validate(raw)
        except ValidationError as exc:
            details = "; ".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in exc.errors())
            raise ValueError(f"算法参数无效：{details}") from exc

    def public_info(self) -> dict:
        return {
            "algorithm_id": self.algorithm_id,
            "name": self.name,
            "category": self.category,
            "owner": self.owner,
            "version": self.version,
            "description": self.description,
            "parameters": self.params_model.model_json_schema(),
        }


class LegacySearchAdapter:
    """仅旧算法需要初始计划；新算法实现 Solver 即可从空计划开始。"""

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def solve(self, problem: SchedulingProblem, constraints: ConstraintModel, context: SolveContext) -> Schedule:
        return SchedulingEngine(problem, constraints, self.algorithm).run()


def _build_legacy(algorithm_id: str, context: SolveContext) -> Solver:
    overrides = context.params.model_dump(exclude_none=True)
    overrides["seed"] = context.seed
    if algorithm_id == "adaptive_repair":
        overrides["time_budget_s"] = context.time_budget_s
    algorithm = create_algorithm(algorithm_id, objective_weights=context.objective_weights, cfg_overrides=overrides)
    return LegacySearchAdapter(algorithm)


# 显式注册可审查的本仓库算法；组员新增算法时只在这里增加一项元数据。
_SPECS: dict[str, AlgorithmSpec] = {
    "completion_first": AlgorithmSpec(
        algorithm_id="completion_first", name="完成率优先（现有基线）", category="baseline",
        owner="EOS-Bench", version="baseline-1", params_model=CompletionParams,
        build=lambda context: _build_legacy("completion_first", context),
        description="EOS-Bench 已有启发式算法，供成对实验对照。",
    ),
    "adaptive_repair": AlgorithmSpec(
        algorithm_id="adaptive_repair", name="自适应修复（现有算法）", category="baseline",
        owner="课程项目第一阶段", version="baseline-1", params_model=AdaptiveRepairParams,
        build=lambda context: _build_legacy("adaptive_repair", context),
        description="第一阶段已有算法，四种第二阶段新算法另行登记。",
    ),
    "caabs": AlgorithmSpec(
        algorithm_id="caabs", name="冲突感知 Beam Search（CAABS）", category="traditional",
        owner="刘懋兴", version=CAABS_VERSION, params_model=CAABSParams,
        build=lambda context: ConflictBeamScheduler(),
        description="完成数优先的有界多路径搜索；返回候选计划，仍须公共核验。",
    ),
}


def get_algorithm(algorithm_id: str) -> AlgorithmSpec:
    try:
        return _SPECS[algorithm_id]
    except KeyError as exc:
        raise ValueError(f"算法未登记：{algorithm_id}") from exc


def list_algorithms() -> list[dict]:
    return [spec.public_info() for spec in _SPECS.values()]


def make_context(seed: int, time_budget_s: float, weights: dict, spec: AlgorithmSpec, params: dict) -> SolveContext:
    """同一注册表负责 HTTP 和 Worker 的参数校验，避免两处规则漂移。"""
    if not isfinite(time_budget_s) or time_budget_s <= 0:
        raise ValueError("算法预算必须是有限正数")
    return SolveContext(
        seed=seed, time_budget_s=time_budget_s,
        objective_weights=ObjectiveWeights(**weights), params=spec.parse_params(params),
    )
