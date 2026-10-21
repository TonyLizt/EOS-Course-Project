"""第二阶段算法注册表。

统一的是元数据、参数校验与结果边界；算法内部可采用任意搜索或学习方法。
旧 EOS-Bench 算法通过适配器接入，因而不改变旧 CLI 的工厂调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isfinite
from importlib.util import find_spec
from typing import Callable

from pydantic import Field, ValidationError

from algorithms.conflict_beam import CAABSParams, ConflictBeamScheduler, VERSION as CAABS_VERSION
from algorithms.auction_bundle import RABASParams, ResourceAwareBundleAuctionScheduler, VERSION as RABAS_VERSION
from algorithms.lavis.protocol import LavisParams
from algorithms.lavis.solver import build as build_lavis
from algorithms.ppo.protocol import PPOParams, VERSION as PPO_VERSION
from algorithms.ppo.solver import build as build_ppo
from algorithms.deadline_insertion import DARTISParams, DARTISScheduler, VERSION as DARTIS_VERSION
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


class CandidateParams(AlgorithmParams):
    max_candidates_per_task: int | None = Field(default=None, ge=1, le=512)


class SAParams(AlgorithmParams):
    max_iterations: int | None = Field(default=None, ge=1, le=100000)
    initial_temperature: float | None = Field(default=None, gt=0, le=1000000)
    cooling_rate: float | None = Field(default=None, gt=0, le=1)
    neighbor_attempts: int | None = Field(default=None, ge=1, le=1000)
    restarts: int | None = Field(default=None, ge=1, le=20)


class GAParams(CandidateParams):
    population_size: int | None = Field(default=None, ge=4, le=500)
    generations: int | None = Field(default=None, ge=1, le=10000)
    crossover_rate: float | None = Field(default=None, ge=0, le=1)
    mutation_rate: float | None = Field(default=None, ge=0, le=1)


class ACOParams(CandidateParams):
    ants: int | None = Field(default=None, ge=1, le=500)
    iterations: int | None = Field(default=None, ge=1, le=10000)
    alpha: float | None = Field(default=None, gt=0, le=20)
    beta: float | None = Field(default=None, gt=0, le=20)
    evaporation: float | None = Field(default=None, gt=0, lt=1)


class MIPParams(CandidateParams):
    verbose: bool = False


def availability(algorithm_id: str) -> tuple[str, str]:
    if algorithm_id == 'lavis':
        if find_spec('sklearn') is None:
            return 'unavailable', '请在WSL运行环境安装requirements-ml.txt。'
        from algorithms.lavis.model import list_models
        if not list_models():
            return 'unavailable', '尚无兼容的冻结LAVIS模型；请先完成离线训练并登记。'
    if algorithm_id == 'mip':
        if find_spec('pulp') is None:
            return 'unavailable', '缺少 PuLP / CBC 求解器依赖。'
        import pulp
        if not pulp.PULP_CBC_CMD(msg=False).available():
            return 'unavailable', '未找到可用的 CBC 求解器。'
    if algorithm_id == 'ppo':
        if find_spec('torch') is None:
            return 'unavailable', '缺少 PyTorch；请在 Worker 的 WSL Python 环境安装。'
        from algorithms.ppo.model import list_models
        if not list_models():
            return 'unavailable', '尚无兼容的已训练 PPO 模型；请运行 python -m algorithms.ppo.training 训练并登记新模型ID。'
    return 'ready', ''


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
    strategy: str = ""
    objectives: str = ""
    limitations: str = ""

    def parse_params(self, raw: dict) -> AlgorithmParams:
        if not isinstance(raw, dict):
            raise ValueError("算法参数必须是 JSON 对象")
        try:
            return self.params_model.model_validate(raw)
        except ValidationError as exc:
            details = "; ".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in exc.errors())
            raise ValueError(f"算法参数无效：{details}") from exc

    def public_info(self) -> dict:
        schema = self.params_model.model_json_schema()
        if self.algorithm_id == 'lavis':
            from algorithms.lavis.model import list_models
            models = list_models()
            if models:
                schema['properties']['model_id']['enum'] = [item['model_id'] for item in models]
                schema['properties']['model_id']['default'] = models[0]['model_id']
        if self.algorithm_id == 'ppo' and find_spec('torch') is not None:
            from algorithms.ppo.model import list_models
            models = list_models()
            if models:
                schema['properties']['model_id']['enum'] = [item['model_id'] for item in models]
                schema['properties']['model_id']['default'] = models[0]['model_id']
        if self.algorithm_id in {'ppo', 'lavis'} and self.version.endswith('+objective-v1'):
            schema['properties']['model_id']['description'] = '选择原冻结训练模型ID；R1适配器按公共请求目标搜索，训练目标和请求目标分别记录。原场景/放置/物理域限制仍有效。'
        return {
            "algorithm_id": self.algorithm_id,
            "name": self.name,
            "category": self.category,
            "owner": self.owner,
            "version": self.version,
            "description": self.description,
            "strategy": self.strategy,
            "objectives": self.objectives,
            "limitations": self.limitations,
            "availability": availability(self.algorithm_id)[0],
            "availability_message": availability(self.algorithm_id)[1],
            "uses_initial_schedule": self.algorithm_id in {'sa', 'ga', 'aco'},
            "parameters": schema,
        }


class LegacySearchAdapter:
    """仅旧算法需要初始计划；新算法实现 Solver 即可从空计划开始。"""

    def __init__(self, algorithm):
        self.algorithm = algorithm
        self.algorithm_id = ''

    def solve(self, problem: SchedulingProblem, constraints: ConstraintModel, context: SolveContext) -> Schedule:
        if self.algorithm_id in COMPARISON_ALGORITHMS:
            model = create_algorithm(context.schedule_model, cfg_overrides={
                'seed': context.seed, 'time_budget_s': context.time_budget_s / 3})
            initial = model.search(problem, constraints, constraints.build_initial_schedule())
            # Some implementations rebuild solutions, rather than consuming the
            # seed. Keep that behavior explicit; never substitute their output.
            return self.algorithm.search(problem, constraints, initial)
        return SchedulingEngine(problem, constraints, self.algorithm).run()


def _build_legacy(algorithm_id: str, context: SolveContext) -> Solver:
    overrides = context.params.model_dump(exclude_none=True)
    overrides["seed"] = context.seed
    if algorithm_id == "adaptive_repair":
        overrides["time_budget_s"] = context.time_budget_s
    if algorithm_id == 'mip':
        overrides['time_limit_sec'] = max(1, int(context.time_budget_s))
    algorithm = create_algorithm(algorithm_id, objective_weights=context.objective_weights, cfg_overrides=overrides)
    adapter = LegacySearchAdapter(algorithm)
    adapter.algorithm_id = algorithm_id
    return adapter


# 显式注册可审查的本仓库算法；组员新增算法时只在这里增加一项元数据。
_SPECS: dict[str, AlgorithmSpec] = {
    "ppo": AlgorithmSpec(
        algorithm_id="ppo", name="PPO 强化学习", category="learning",
        owner="EOS-Bench / 项目现有实现", version=PPO_VERSION, params_model=PPOParams,
        build=build_ppo, description="使用已登记训练策略及公共候选/约束逐任务解码。",
        strategy="现有Actor-Critic、固定特征与动作协议、动态可行掩码、执行前复查与时间顺序重放。",
        objectives="v1仅收益目标：收益权重大于0，其余权重为0，与训练奖励一致。",
        limitations="仅earliest、默认约束、无地面站；执行模式及场景物理域须与训练清单一致。训练模型仍须独立核验，不保证性能。",
    ),
    "lavis": AlgorithmSpec(
        algorithm_id="lavis", name="LAVIS · 学习型分配价值引导插入调度", category="learning",
        owner="李泽同（刘懋兴、何明涛配合）", version="0.1.0", params_model=LavisParams,
        build=build_lavis, description="监督学习预测完整候选分配的后续完成价值，逐轮可行插入。",
        strategy="24维共享特征、训练后的直方图梯度提升回归、原始预测分数排序；不在线运行教师续排。",
        objectives="v1仅支持完成率目标：完成率权重大于0，其余目标权重为0。",
        limitations="v1仅earliest、默认约束、无地面站；使用受控模型ID，有限候选池，不保证优于传统算法或全局最优。",
    ),
    "completion_first": AlgorithmSpec(
        algorithm_id="completion_first", name="完成率优先（现有基线）", category="baseline",
        owner="EOS-Bench", version="baseline-1", params_model=CompletionParams,
        build=lambda context: _build_legacy("completion_first", context),
        description="EOS-Bench 已有启发式算法，供成对实验对照。",
        strategy="生成离散候选；按可行候选数量选择任务；默认随机打乱候选并接受首个可行安排。",
        objectives="优先增加已安排任务数；不保证最早开始、最近距离或全局最优。",
        limitations="每任务最多 256 个候选。earliest 是候选放置设置，不保证最终选择最早候选；目标权重不改变该算法的固定策略。",
    ),
    "adaptive_repair": AlgorithmSpec(
        algorithm_id="adaptive_repair", name="自适应修复（现有算法）", category="baseline",
        owner="课程项目第一阶段", version="baseline-1", params_model=AdaptiveRepairParams,
        build=lambda context: _build_legacy("adaptive_repair", context),
        description="第一阶段已有算法，四种第二阶段新算法另行登记。",
        strategy="动态稀缺度选择、受限冲突链修复与破坏重建；所有接受的安排通过共享约束模型。",
        objectives="按完成任务数、总任务优先级、较早观测的顺序进行字典序比较。",
        limitations="候选数量和局部修复深度有限，不保证全局最优；遵守时间预算，目标权重不替代其固定字典序目标。",
    ),
    "caabs": AlgorithmSpec(
        algorithm_id="caabs", name="冲突感知 Beam Search（CAABS）", category="traditional",
        owner="刘懋兴", version=CAABS_VERSION, params_model=CAABSParams,
        build=lambda context: ConflictBeamScheduler(),
        description="完成数优先的有界多路径搜索；返回候选计划，仍须公共核验。",
        strategy="预算内贪心初解、受检机会排序、多路径 Beam 搜索、独立检查/可行分支预算与精确键缓存。",
        objectives="完成任务数优先，再按共享 ObjectiveModel 得分与规范键确定次序。",
        limitations="Beam 宽度与候选上限限制覆盖；candidate_check_limit 限尝试数，branch_limit 限可行子节点数；不保证全局最优，候选仍须来源与连续曝光核验。",
    ),
    "dartis": AlgorithmSpec(
        algorithm_id="dartis", name="DARTIS · 截止期感知动态可行插入", category="traditional",
        owner="何明涛", version=DARTIS_VERSION, params_model=DARTISParams,
        build=lambda context: DARTISScheduler(),
        description="离线单计划构造；按观测机会 LLF/EDF 紧迫度选择并动态重评估。",
        strategy="跨卫星及窗口探查可行插入；每次接受后全量重算未安排任务机会。",
        objectives="优先增加完成任务数；LLF/EDF 仅决定搜索顺序，正式指标由 Controller 重算。",
        limitations="窗口和位置有界，松弛度仅针对受检候选近似；大于 1024 网格的敏捷窗口暂跳过，仍须公共认证。",
    ),
    "rabas": AlgorithmSpec(
        algorithm_id="rabas", name="RABAS · 资源感知任务包竞价调度", category="traditional",
        owner="梁兆榮", version=RABAS_VERSION, params_model=RABASParams,
        build=lambda context: ResourceAwareBundleAuctionScheduler(),
        description="单 Worker 内中心化多卫星任务包竞价；不是分布式 CBBA。",
        strategy="每星有界建包、可选多起点，动态机会/资源/转向报价；按候选量及剩余预算收窄搜索，全量核验中标后重新竞价。",
        objectives="最终计划只接受完成数增加；默认按包大小、公共效用减成本竞价，可选未来机会优先排序；Bid 非正式 TP。",
        limitations="有界窗口、放置、任务包和竞价轮数；不保证全局最优，不使用初始模型解，仍须 Controller 独立认证。",
    ),
}


COMPARISON_ALGORITHMS = ('mip', 'profit_first', 'timeliness_first', 'balance_first',
                         'pressure_repair', 'sa', 'ga', 'aco', 'ppo', 'caabs', 'rabas',
                         'lavis', 'dartis')

_DEFINITIONS = [
    ('mip', '混合整数规划 MIP', 'exact', MIPParams, '离散候选与冲突约束构建 MILP，由 CBC 求解。', '候选集上的加权目标优化，含实现中的主目标增强。', '候选集有限；独立建模，不使用初始模型解。'),
    ('profit_first', '收益优先启发式', 'heuristic', CandidateParams, '按收益及可行候选排序构建计划。', '优先总收益，以结束时间等打破平局。', '固定贪心策略，自行重建解，不使用初始模型解。'),
    ('timeliness_first', '时效优先启发式', 'heuristic', CandidateParams, '按任务最早候选时间排序安排可行观测。', '优先较早观测机会。', '不保证全局最早完成；自行重建解，不使用初始模型解。'),
    ('balance_first', '负载均衡启发式', 'heuristic', CandidateParams, '根据卫星负载选择可行安排。', '改善卫星负载均衡。', '固定贪心策略，自行重建解，不使用初始模型解。'),
    ('pressure_repair', '冲突压力修复', 'heuristic', CandidateParams, '冲突压力构造与受限单任务重插入。', '增加可行任务安排。', '有限修复预算，自行重建解，不使用初始模型解。'),
    ('sa', '模拟退火 SA', 'metaheuristic', SAParams, '从所选初始模型解出发，温度与邻域搜索优化。', '共享 ObjectiveModel 的加权目标。', '随机启发式，受迭代次数和 Worker 硬预算限制。'),
    ('ga', '遗传算法 GA', 'metaheuristic', GAParams, '候选编码、交叉、变异与可行解码，保留初始模型解为 incumbent。', '共享 ObjectiveModel 的加权目标。', '初始模型不替代独立种群生成；不保证最优。'),
    ('aco', '蚁群优化 ACO', 'metaheuristic', ACOParams, '信息素与启发因子构造，保留初始模型解为 incumbent。', '共享 ObjectiveModel 的加权目标。', '初始模型不替代蚁群构造；受候选和迭代限制。'),
]
for _id, _name, _category, _params, _strategy, _objectives, _limits in _DEFINITIONS:
    _SPECS[_id] = AlgorithmSpec(_id, _name, _category, 'EOS-Bench / 项目现有实现',
        'console-1', _params, lambda context, aid=_id: _build_legacy(aid, context),
        description=_strategy, strategy=_strategy, objectives=_objectives, limitations=_limits)


# R1 adapters are outside both frozen model source trees. Native specs remain
# available to replay historical RunConfigs with their original solver version.
_NATIVE_SPECS = dict(_SPECS)
from algorithms.objective_adapters import build as build_objective_adapter
for _aid in COMPARISON_ALGORITHMS:
    _native = _NATIVE_SPECS[_aid]
    _SPECS[_aid] = replace(_native, version=_native.version + '+objective-v1',
        build=lambda context, aid=_aid, native=_native: build_objective_adapter(aid, context, native.build, native.version),
        objectives='R1：接受公共ObjectiveModel的任意合法权重；请求目标实际用于候选计划评价和有界搜索。原学习模型的训练目标单独记录。',
        strategy=_native.strategy + ' R1在原提议上增加公共目标感知的有界搜索，搜索计入同一预算。')


def get_native_algorithm(algorithm_id: str) -> AlgorithmSpec:
    return _NATIVE_SPECS[algorithm_id]


def get_algorithm(algorithm_id: str) -> AlgorithmSpec:
    try:
        return _SPECS[algorithm_id]
    except KeyError as exc:
        raise ValueError(f"算法未登记：{algorithm_id}") from exc


def list_algorithms() -> list[dict]:
    return [_SPECS[aid].public_info() for aid in COMPARISON_ALGORITHMS]


def list_schedule_models() -> list[dict]:
    return [{'model_id': aid, 'name': {'completion_first':'完成率优先', 'adaptive_repair':'自适应修复'}[aid], 'description': _SPECS[aid].strategy}
            for aid in ('completion_first', 'adaptive_repair')]


def make_context(seed: int, time_budget_s: float, weights: dict, spec: AlgorithmSpec, params: dict,
                 schedule_model: str = 'completion_first') -> SolveContext:
    """同一注册表负责 HTTP 和 Worker 的参数校验，避免两处规则漂移。"""
    if not isfinite(time_budget_s) or time_budget_s <= 0:
        raise ValueError("算法预算必须是有限正数")
    from algorithms.objective_adapters import validate_weights
    validate_weights(ObjectiveWeights(**weights))
    return SolveContext(
        seed=seed, time_budget_s=time_budget_s,
        objective_weights=ObjectiveWeights(**weights), params=spec.parse_params(params), schedule_model=schedule_model,
    )
