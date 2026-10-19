"""冻结v1候选、特征、标签和训练域；不在训练后悄悄改变搜索空间。"""
from __future__ import annotations
from dataclasses import dataclass
from pydantic import Field
from algorithms.solver_contracts import AlgorithmParams

FEATURE_VERSION = 'lavis-features-v1'
CANDIDATE_VERSION = 'configured-placement-v1'
LABEL_VERSION = 'lavis-rollout-label-v1'
POOL_CONFIG = dict(max_source_windows_per_task=16, max_candidates_per_task=32,
                   max_candidates_total=4096, max_source_records=200000,
                   max_downlink_options_per_observation=2)
DOMAIN = dict(placement_mode='earliest', unassigned_penalty=1000.0,
              downlink_duration_ratio=1.0, agility_profile='Standard-Agility',
              non_agile_transition_s=10.0, has_ground_stations=False,
              execution_mode='physical_validation', objective='completion_only')
FEATURE_NAMES = (
 'task_duration_ratio','task_priority_scaled','task_base_candidate_ratio',
 'task_feasible_candidate_ratio','task_feasible_satellite_ratio',
 'window_start_ratio','window_end_ratio','window_slack_ratio',
 'observation_start_ratio','observation_end_ratio','completed_task_ratio',
 'unassigned_task_ratio','satellite_observation_load','satellite_downlink_load',
 'satellite_task_ratio','remaining_interval_pressure','exclusive_interval_pressure',
 'predecessor_gap_ratio','has_predecessor','successor_gap_ratio','has_successor',
 'has_ground_station','downlink_duration_ratio','ground_station_load')

class LavisParams(AlgorithmParams):
    model_id: str = Field('lavis-v1', pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$',
                          description='已登记的冻结模型ID；仅选择ID，不接受文件路径。v1仅支持完成率目标、earliest及默认约束。')

class LavisCancelled(RuntimeError):
    """协作取消必须上报，不能把半轮结果冒充成功。"""

class BudgetExpired(Exception):
    pass

@dataclass
class Control:
    deadline: float = float('inf')
    cancelled: object = lambda: False
    checks: int = 0
    check_limit: int | None = None

    def checkpoint(self):
        import time
        if self.cancelled(): raise LavisCancelled('LAVIS_CANCELLED')
        if time.monotonic() >= self.deadline: raise BudgetExpired()

    def check(self, constraints, candidate, plan, *, static=False):
        self.checkpoint()
        if self.check_limit is not None and self.checks >= self.check_limit: raise BudgetExpired()
        self.checks += 1
        # 池中对象通过空计划完整来源/几何检查后保持只读，动态阶段重查共享资源/转向。
        return (constraints.is_feasible_assignment(candidate,plan) if static
                else constraints.check_discrete_assignment(candidate,plan))

def validate_weights(weights):
    if weights.w_completion <= 0 or any(getattr(weights,k) != 0 for k in ('w_profit','w_timeliness','w_balance')):
        raise ValueError('LAVIS_V1_REQUIRES_COMPLETION_ONLY：完成率权重大于0，其余目标权重为0')
