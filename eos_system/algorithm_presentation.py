"""User-facing algorithm metadata, outside the execution source fingerprint."""

from .algorithm_registry import AlgorithmParams, AlgorithmSpec, list_algorithms, get_algorithm

# Presentation-only metadata, shared by every page. Defaults/types remain owned
# by the existing Pydantic models; do not replace nullable defaults with guesses.
_PARAMETER_HELP = {
    'candidate_strategy': ('LAVIS候选策略', 'configured保持原候选；expanded增加源网格上的观测位置，原权重不变，属于扩展候选分布验证。'),
    'search_mode': ('LAVIS搜索方式', 'greedy保留原模型路径；multistart复用原权重尝试多条模型续排路径，不重新训练。'),
    'max_branches': ('LAVIS替代分支上限', '每个分支仍由模型打分续排，全部分支共用本次算法预算。'),
    'model_id': ('冻结模型', '选择管理员登记的训练模型ID；不接受任意文件路径。'),
    'max_candidates_per_task': ('每任务候选上限', '限制每项任务保留的离散候选数；默认配置由对应算法决定。'),
    'alns_iterations': ('破坏重建轮数', '自适应修复的破坏与重建迭代上限。'),
    'max_iterations': ('最大迭代次数', '模拟退火的搜索迭代上限，仍受求解时间预算限制。'),
    'initial_temperature': ('初始温度', '模拟退火初始温度，影响接受较差邻域解的概率。'),
    'cooling_rate': ('降温系数', '每次降温时温度乘以该系数。'),
    'neighbor_attempts': ('邻域尝试次数', '构建邻域时允许的候选尝试上限。'),
    'restarts': ('重启次数', '允许重新开始搜索的次数。'),
    'population_size': ('种群规模', '遗传算法每代保留的个体数量。'),
    'generations': ('最大代数', '遗传算法进化代数上限。'),
    'crossover_rate': ('交叉概率', '遗传算法进行交叉操作的概率。'),
    'mutation_rate': ('变异概率', '遗传算法进行变异操作的概率。'),
    'ants': ('蚂蚁数量', '每轮构建候选计划的蚂蚁数量。'),
    'iterations': ('最大迭代轮数', '蚁群算法更新信息素的轮数上限。'),
    'alpha': ('信息素权重', '候选选择时信息素的幂指数。'),
    'beta': ('启发因子权重', '候选选择时启发因子的幂指数。'),
    'evaporation': ('信息素挥发率', '每轮信息素更新时挥发的比例。'),
    'verbose': ('求解器日志', '是否输出 CBC 求解器的详细运行日志；不会改变求解器可用性。'),
    'beam_width': ('束宽度', 'CAABS 每层保留的部分计划数量上限。'),
    'branch_limit': ('分支上限', 'CAABS 每个部分计划生成的子分支数量上限。'),
    'max_windows_per_task': ('每任务窗口上限', '限制任务候选生成时考察的观测窗口数量。'),
    'conflict_prefilter': ('冲突预筛', '在公共可行性核验前预筛明显冲突；不能替代最终公共核验。'),
    'max_bundle_size': ('任务包大小上限', '每个报价最多包含的任务数量；1 为单任务竞价消融，2/3 为多任务包。'),
    'bid_candidates_per_satellite': ('每星候选扩展数', '每颗卫星逐步建包时，每步最多比较的可行任务数量。'),
    'max_rounds': ('竞价轮数上限', '0 表示按任务数自动设置，最多 1000 轮。'),
    'max_positions_per_window': ('每窗口放置数', '1 仅用当前放置模式；2 同时尝试公共构造器的 earliest/center。'),
    'max_checks_per_round': ('每轮约束检查上限', '限制搜索阶段检查量；中标后的全局核验另计。'),
    'transition_cost_weight': ('转向成本权重', '综合报价中归一化真实转向成本的惩罚权重。'),
    'resource_cost_weight': ('资源成本权重', '综合报价中存储、功率和占用等资源成本的惩罚权重。'),
    'opportunity_cost_weight': ('机会成本权重', '惩罚建包后丢失的独占任务机会；设为 0 关闭该估计。'),
    'reauction_mode': ('重新竞价方式', '当前仅支持 all_affected：每次中标后所有卫星全量重新报价。'),
}


def parameter_schema(model: type[AlgorithmParams]) -> dict:
    """Annotate the public schema without changing validation or runtime defaults."""
    schema = model.model_json_schema()
    for key, prop in schema.get('properties', {}).items():
        if key in _PARAMETER_HELP:
            prop['title'], help_text = _PARAMETER_HELP[key]
            # An algorithm's existing specific description takes precedence.
            prop['description'] = prop.get('description') or help_text
    return schema


def algorithm_info(spec: AlgorithmSpec) -> dict:
    info = spec.public_info()
    decorated = parameter_schema(spec.params_model)
    # 仅补展示文字，保留注册表实时给出的受控模型选项，不重建覆盖Schema。
    for key, prop in info['parameters'].get('properties', {}).items():
        for field in ('title', 'description'):
            if field in decorated['properties'][key]: prop[field] = decorated['properties'][key][field]
    return info


def list_presented_algorithms() -> list[dict]:
    return [algorithm_info(get_algorithm(item["algorithm_id"])) for item in list_algorithms()]

