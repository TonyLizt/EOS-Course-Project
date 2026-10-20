"""展示评分：只使用已核验指标，绝不改变调度目标或正式指标。"""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

POLICY = 'completion70-profit20-timeliness10-v1'


@lru_cache(maxsize=64)
def _priority_total(path, digest, size, modified):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('评分来源场景 SHA 不匹配')
    values = [float(m['priority']) for m in json.loads(raw)['missions']]
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('收益评分要求非负、有限任务优先级')
    return sum(values)


def calculate_score(metrics, total_priority):
    """绝对归一化：增加/移除对手不会改变分数。TM越小越好，因此用1-TM。"""
    tcr, tp, tm = (float(metrics[k]) for k in ('TCR', 'TP', 'TM'))
    if not all(math.isfinite(v) for v in (tcr, tp, tm, total_priority)):
        raise ValueError('评分指标必须为有限值')
    if not (0 <= tcr <= 1 and 0 <= tm <= 1 and 0 <= tp <= total_priority + 1e-7):
        raise ValueError('评分指标超出有效范围')
    profit_ratio = tp / total_priority if total_priority > 0 else 0.
    return {'value': round(70*tcr + 20*profit_ratio + 10*(1-tm), 6),
            'policy': POLICY, 'weights': {'completion': .7, 'profit': .2, 'timeliness': .1},
            'total_priority': total_priority, 'profit_ratio': profit_ratio,
            'timeliness_score': 1-tm,
            'formula': '70*TCR + 20*(TP/total_priority) + 10*(1-TM)',
            'note': '仅同条件比较；耗时不计分；总优先级为0时收益项计0'}


def score_run(run):
    if run.get('status') != 'SUCCEEDED' or not run.get('metrics'):
        return None
    if not run.get('plan') and not (run.get('temporary') and run.get('has_plan')):
        return None
    try:
        c = run['config']; path = Path(c['scenario_path']); stat = path.stat()
        total = _priority_total(str(path), c['scenario_sha256'], stat.st_size, stat.st_mtime_ns)
        return calculate_score(run['metrics'], total)
    except (KeyError, OSError, ValueError, TypeError):
        # 历史来源不可用时保留原指标，只显示无评分，不填0分冒充有效结果。
        return None
