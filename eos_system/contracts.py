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
    execution_mode: Literal["formal", "planning_preview"] = "formal"
    source_id: str = Field(default="runtime", min_length=1, max_length=80)
    scenario_id: str = Field(min_length=1, max_length=200)
    algorithm_id: str = Field(min_length=1, max_length=100)
    output_profile_id: str = Field(default="download", min_length=1, max_length=80)
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
    output_kind: Literal["download", "directory"] = "download"
    output_root: str | None = None
    algorithm_version: str
    algorithm_code_sha: str | None = None
    # 来源可未知；新物理候选必须有外部验收，不用当前代码回填历史。
    scenario_provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ReplayRequest(StrictModel):
    """网页只选择已登记的展示配置，不提交服务器文件路径。"""

    replay_config_id: str = Field(min_length=1, max_length=100)


class DirectoryRegistration(StrictModel):
    """位置登记由服务端校验；普通实验请求只携带登记 ID。"""

    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=2048)


def validate_algorithm_params(algorithm_id: str, params: dict[str, Any]) -> None:
    """兼容旧调用方；参数规则只保留在算法注册表一处。"""
    from .algorithm_registry import get_algorithm

    get_algorithm(algorithm_id).parse_params(params)


def list_algorithms() -> list[dict]:
    from .algorithm_registry import list_algorithms as registered

    return registered()
