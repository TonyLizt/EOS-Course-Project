"""只影响展示精度的确定性采样预算，与算法搜索和正式指标无关。"""
from __future__ import annotations

import math

MAX_SAMPLES = 200_000
TARGET_SAMPLES = 100_000
PREFERRED_STEP_S = 5.0
MAX_STEP_S = 300.0
STRATEGY = "adaptive_budget_v1"


def sampling_policy(duration_s: float, satellite_count: int, assignment_count: int) -> dict:
    """按星数/时域放宽规则采样；所有任务和转向端点另行强制保留。"""
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("回放时域必须为有限正秒数")
    if satellite_count < 0 or assignment_count < 0:
        raise ValueError("卫星和任务数量不能为负")
    # 每条观测有两个端点，每条可能的转向再预留两个，取保守上界。
    boundary_reserve = 4 * assignment_count
    step = PREFERRED_STEP_S
    if satellite_count:
        per_satellite = (TARGET_SAMPLES - boundary_reserve) // satellite_count
        if per_satellite < 2:
            raise ValueError("REPLAY_BOUNDARY_LIMIT: 必保留端点已超过展示预算")
        required = duration_s / (per_satellite - 1)
        # 向上取 5 秒倍数，结果不依赖机器性能或执行时间，便于复现。
        step = max(step, math.ceil(required / PREFERRED_STEP_S) * PREFERRED_STEP_S)
    if step > MAX_STEP_S:
        raise ValueError("REPLAY_SAMPLE_LIMIT: 300 秒采样仍超预算，请缩短展示时域")
    estimate = satellite_count * (math.ceil(duration_s / step) + 1) + boundary_reserve
    if estimate > TARGET_SAMPLES:
        raise ValueError("REPLAY_SAMPLE_LIMIT: 必保留端点与规则采样超过预算")
    return {
        "strategy": STRATEGY,
        "preferred_attitude_step_s": PREFERRED_STEP_S,
        "attitude_step_s": float(step),
        "max_attitude_step_s": MAX_STEP_S,
        "target_samples": TARGET_SAMPLES,
        "max_samples": MAX_SAMPLES,
        "boundary_reserve": boundary_reserve,
        "estimated_sample_upper_bound": estimate,
        "preserve_task_and_slew_endpoints": True,
    }
