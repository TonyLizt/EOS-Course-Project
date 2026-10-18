"""第二阶段算法注册表。

统一的是元数据、参数校验与结果边界；算法内部可采用任意搜索或学习方法。
旧 EOS-Bench 算法通过适配器接入，因而不改变旧 CLI 的工厂调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from importlib.util import find_spec
from typing import Callable

from pydantic import Field, ValidationError

from algorithms.conflict_beam import CAABSParams, ConflictBeamScheduler, VERSION as CAABS_VERSION
from algorithms.auction_bundle import RABASParams, ResourceAwareBundleAuctionScheduler, VERSION as RABAS_VERSION
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


# Presentation-only metadata, shared by every page. Defaults/types remain owned
# by the existing Pydantic models; do not replace nullable defaults with guesses.
_PARAMETER_HELP = {
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


def availability(algorithm_id: str) -> tuple[str, str]:
    if algorithm_id == 'mip':
        if find_spec('pulp') is None:
            return 'unavailable', '缺少 PuLP / CBC 求解器依赖。'
        import pulp
        if not pulp.PULP_CBC_CMD(msg=False).available():
            return 'unavailable', '未找到可用的 CBC 求解器。'
    if algorithm_id == 'ppo':
        return 'unavailable', ('缺少 PyTorch；' if find_spec('torch') is None else '') + '尚未接入受信任训练模型及共享约束，禁止随机策略冒充训练结果。'
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
            "parameters": parameter_schema(self.params_model),
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
        strategy="有界候选生成、多路径 Beam 搜索与受限可行性预筛选。",
        objectives="完成任务数优先，再按共享 ObjectiveModel 得分与规范键确定次序。",
        limitations="Beam 宽度、分支及候选上限限制覆盖；不保证全局最优，候选仍须来源与连续曝光核验。",
    ),
    "rabas": AlgorithmSpec(
        algorithm_id="rabas", name="RABAS · 资源感知任务包竞价调度", category="traditional",
        owner="梁兆榮", version=RABAS_VERSION, params_model=RABASParams,
        build=lambda context: ResourceAwareBundleAuctionScheduler(),
        description="单 Worker 内中心化多卫星任务包竞价；不是分布式 CBBA。",
        strategy="每星增量构建真实多任务 Bundle，资源/转向/机会成本报价，全局核验中标后全量重新竞价。",
        objectives="新增完成任务数优先，同数量按公共加权效用增量减归一化成本报价，再按稳定 ID 裁决。",
        limitations="有界窗口、放置、任务包和竞价轮数；不保证全局最优，不使用初始模型解，仍须 Controller 独立认证。",
    ),
}


COMPARISON_ALGORITHMS = ('mip', 'profit_first', 'timeliness_first', 'balance_first',
                         'pressure_repair', 'sa', 'ga', 'aco', 'ppo', 'caabs', 'rabas')

_DEFINITIONS = [
    ('mip', '混合整数规划 MIP', 'exact', MIPParams, '离散候选与冲突约束构建 MILP，由 CBC 求解。', '候选集上的加权目标优化，含实现中的主目标增强。', '候选集有限；独立建模，不使用初始模型解。'),
    ('profit_first', '收益优先启发式', 'heuristic', CandidateParams, '按收益及可行候选排序构建计划。', '优先总收益，以结束时间等打破平局。', '固定贪心策略，自行重建解，不使用初始模型解。'),
    ('timeliness_first', '时效优先启发式', 'heuristic', CandidateParams, '按任务最早候选时间排序安排可行观测。', '优先较早观测机会。', '不保证全局最早完成；自行重建解，不使用初始模型解。'),
    ('balance_first', '负载均衡启发式', 'heuristic', CandidateParams, '根据卫星负载选择可行安排。', '改善卫星负载均衡。', '固定贪心策略，自行重建解，不使用初始模型解。'),
    ('pressure_repair', '冲突压力修复', 'heuristic', CandidateParams, '冲突压力构造与受限单任务重插入。', '增加可行任务安排。', '有限修复预算，自行重建解，不使用初始模型解。'),
    ('sa', '模拟退火 SA', 'metaheuristic', SAParams, '从所选初始模型解出发，温度与邻域搜索优化。', '共享 ObjectiveModel 的加权目标。', '随机启发式，受迭代次数和 Worker 硬预算限制。'),
    ('ga', '遗传算法 GA', 'metaheuristic', GAParams, '候选编码、交叉、变异与可行解码，保留初始模型解为 incumbent。', '共享 ObjectiveModel 的加权目标。', '初始模型不替代独立种群生成；不保证最优。'),
    ('aco', '蚁群优化 ACO', 'metaheuristic', ACOParams, '信息素与启发因子构造，保留初始模型解为 incumbent。', '共享 ObjectiveModel 的加权目标。', '初始模型不替代蚁群构造；受候选和迭代限制。'),
    ('ppo', 'PPO 强化学习', 'learning', AlgorithmParams, '训练策略通过动作掩码逐任务选择候选。', '训练和推理配置的奖励目标。', '独立解码，不使用初始模型；可信模型与统一约束尚未接入，当前不可运行。'),
]
for _id, _name, _category, _params, _strategy, _objectives, _limits in _DEFINITIONS:
    _SPECS[_id] = AlgorithmSpec(_id, _name, _category, 'EOS-Bench / 项目现有实现',
        'console-1', _params, lambda context, aid=_id: _build_legacy(aid, context),
        description=_strategy, strategy=_strategy, objectives=_objectives, limitations=_limits)


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
    return SolveContext(
        seed=seed, time_budget_s=time_budget_s,
        objective_weights=ObjectiveWeights(**weights), params=spec.parse_params(params), schedule_model=schedule_model,
    )
