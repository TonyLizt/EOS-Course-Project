"""Shared Solver types, independent of registry entries and algorithm factories."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict

from algorithms.objectives import ObjectiveWeights
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.scenario_loader import SchedulingProblem


class AlgorithmParams(BaseModel):
    """组员可自行定义嵌套参数；未知字段必须明确报错。"""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class SolveContext:
    """每次求解的受控服务；算法可选择是否构造初始计划。"""

    seed: int
    time_budget_s: float
    objective_weights: ObjectiveWeights
    params: AlgorithmParams
    # 正式 Worker 接入协作取消后可替换此回调；硬超时仍由 Controller 负责。
    is_cancelled: Callable[[], bool] = field(default=lambda: False, repr=False)
    # Initial-plan model is optional; keep the existing positional cancel argument.
    schedule_model: str = 'completion_first'
    # HTTP冻结模型身份；不从算法参数接受任意路径或可变权重。
    model_provenance: dict = field(default_factory=dict)


class Solver(Protocol):
    def solve(self, problem: SchedulingProblem, constraints: ConstraintModel, context: SolveContext) -> Schedule:
        """产出候选计划；正式可行性和指标由 Controller 独立判定。"""
