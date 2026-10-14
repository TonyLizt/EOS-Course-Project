"""HTTP、Controller 与参考 Worker 共用的数据契约。"""

from __future__ import annotations

from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConstraintOptions(StrictModel):
    unassigned_penalty: float = Field(default=1000.0, ge=0)
    downlink_duration_ratio: float = Field(default=1.0, gt=0, le=10)
    agility_profile: Literal["Limited-Agility", "Low-Agility", "Standard-Agility", "High-Agility"] = "Standard-Agility"
    non_agile_transition_s: float = Field(default=10.0, ge=0, le=3600)


class ObjectiveOptions(StrictModel):
    w_profit: float = Field(default=1.0, ge=0)
    w_completion: float = Field(default=0.0, ge=0)
    w_timeliness: float = Field(default=0.0, ge=0)
    w_balance: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def check_weights(self) -> "ObjectiveOptions":
        values = (self.w_profit, self.w_completion, self.w_timeliness, self.w_balance)
        if not all(isfinite(value) for value in values) or sum(values) <= 0:
            raise ValueError("目标权重必须是有限非负数，且总和大于零")
        return self


class RunRequest(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=200)
    algorithm_id: str = Field(min_length=1, max_length=100)
    algorithm_params: dict[str, Any] = Field(default_factory=dict)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    placement_mode: Literal["earliest", "center"] = "earliest"
    constraints: ConstraintOptions = Field(default_factory=ConstraintOptions)
    objective_weights: ObjectiveOptions = Field(default_factory=ObjectiveOptions)
    time_budget_s: float = Field(default=60, gt=0, le=600)


class RunConfig(RunRequest):
    run_id: str
    scenario_sha256: str
    scenario_path: str
    algorithm_version: str
    created_at: str


def validate_algorithm_params(algorithm_id: str, params: dict[str, Any]) -> None:
    """首版只开放必要参数；新增算法在此扩展白名单和边界。"""
    allowed = {
        "completion_first": {},
        "adaptive_repair": {"max_candidates_per_task": (int, 1, 512), "alns_iterations": (int, 0, 500)},
    }
    if algorithm_id not in allowed:
        raise ValueError(f"算法未登记：{algorithm_id}")
    spec = allowed[algorithm_id]
    for name, value in params.items():
        if name not in spec:
            raise ValueError(f"算法参数未登记：{name}")
        kind, minimum, maximum = spec[name]
        if type(value) is not kind or not minimum <= value <= maximum:
            raise ValueError(f"算法参数 {name} 超出允许范围")


def list_algorithms() -> list[dict]:
    return [
        {"algorithm_id": "completion_first", "name": "完成率优先（现有基线）", "category": "baseline", "parameters": {}},
        {"algorithm_id": "adaptive_repair", "name": "自适应修复（现有算法）", "category": "baseline", "parameters": {
            "max_candidates_per_task": {"type": "integer", "min": 1, "max": 512},
            "alns_iterations": {"type": "integer", "min": 0, "max": 500},
        }},
    ]
