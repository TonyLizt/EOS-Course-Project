# 第二阶段个人算法接入说明（v0.2）

> 2026-10-18：集成 main PR #19 / 22299b4 后 Web 比较列表为原九算法加 CAABS（十种），完成率优先/自适应修复作为初始排程模型独立选择；`get_algorithm` 仍保留两个模型的历史 ID。共用 SolveContext 在原取消回调之后增加有默认值的 schedule_model，保留中立契约和 Registry 同一类型重导出。MIP/PPO 及初始解限制见[九算法历史交接](nine_algorithm_console_handoff.md)，CAABS 保持上游真实实现与参数，I2 来源身份和正式认证门禁不放宽。

本接口只固定**实验边界**：算法 ID、参数、输入场景、预算、候选计划和独立核验。算法可采用构造、修复、搜索、整数规划、监督学习或强化学习等机制；无需继承旧启发式步骤，也无需先得到初始计划。

## 1. 组员要交付什么

1. 在 `algorithms/` 下实现一个类，提供 `solve(problem, constraints, context) -> Schedule`。
2. 从 `algorithms.solver_contracts` 导入共用契约，定义自己的 `AlgorithmParams` 子类（Pydantic），声明可配置参数与类型/范围。
3. 在 `eos_system/algorithm_registry.py` 显式登记唯一 ID、名称、负责人、类别、版本、参数模型和构造函数。
4. 提交机制说明、固定种子小实例、统一约束回放、同场景成对实验及依赖说明。

注册表是组员唯一需要协同修改的系统入口。HTTP 算法列表、参数校验和 Worker 实例化都从此表获取信息；**不修改** Controller、SQLite 表或浏览器硬编码选项。每位负责人从新 `main` 建自己的短期分支，合并前处理注册表冲突并运行闭环。

## 2. 运行对象

| 对象 | 含义 |
|---|---|
| `problem: SchedulingProblem` | 固定场景的任务、卫星、窗口；只读使用。Controller 保存输入 SHA-256，并在核验时重新加载。 |
| `constraints: ConstraintModel` | 与正式核验使用同一配置建立的约束模型。算法可以调用它生成候选、构造初始计划或检查局部可行性，也可以使用自己的内部模型。 |
| `context: SolveContext` | 随机种子、算法搜索预算、目标权重、已校验的专属参数和取消查询函数。 |
| 返回值 `Schedule` | 候选计划。Worker 将其转为 JSON 兼容数据；Controller 对每条 assignment 重建、检查来源窗口/资源/共享约束并重新计算指标。 |

当前分支的 Worker 已将线程安全取消标记接入 `context.is_cancelled()`；运行中取消由 Controller 通过控制 Pipe 发送，`cancel_ack` 不表示算法或进程已退出。算法应主动轮询该回调；不合作算法仍由 Controller 按期限回收。模型准备和场景加载发生在 `SEARCHING` 阶段之前，`solve()` 的时间才计入算法运行秒数。现有 `LegacySearchAdapter` 已通过真实 HTTP → Worker → 核验 → SQLite 基线闭环，但旧算法本身不保证主动响应取消。

共用 `AlgorithmParams`、`SolveContext`、`Solver` 定义在 `algorithms/solver_contracts.py`，不导入 Registry 或工厂。算法实现依赖这一契约层，Registry 再显式导入已审核的算法，避免登记时形成反向导入。`eos_system.algorithm_registry` 继续导出同一组类型，已有 Runner/Worker 调用方无需改导入路径。

## 3. 接入形状

2026-10-18 I2工作树待审核补充：Assignment保留实际 `sat_window_id`，有下传时保留实际 `gs_window_id`。公共输出传递并独立核对来源；历史缺失字段仅在完整语义下唯一确定时兼容。字段已有于dataclass，solve签名和算法策略不改。详见 [来源契约审查稿](assignment_source_window_contract_v1.md)。

```python
from pydantic import Field
from algorithms.solver_contracts import AlgorithmParams
from schedulers.constraint_model import Schedule

class MyParams(AlgorithmParams):
    beam_width: int = Field(default=8, ge=1, le=256)

class MyScheduler:
    def solve(self, problem, constraints, context) -> Schedule:
        # 可从 Schedule() 开始，也可调用 constraints.build_initial_schedule()。
        # 使用 context.seed 控制随机数；具体搜索策略由算法负责人决定。
        schedule = Schedule()
        # ... 在这里实现算法并填充 schedule.assignments ...
        return schedule
```

在 `algorithm_registry.py` 中增加一项 `AlgorithmSpec`，例如 `algorithm_id="algorithm-a"`、`params_model=MyParams`、`build=lambda context: MyScheduler()`。注册表的 `version` 是**该算法实现版本**；修改搜索规则或模型后应更新它。不要把旧算法改名登记为 A/B/C/D。

现有 `completion_first` 和 `adaptive_repair` 通过 `LegacySearchAdapter` 保留旧 `search(problem, constraint_model, initial_schedule)` 协议及旧 CLI。新算法直接实现 `solve`；若算法需要初始计划，可自行调用 `constraints.build_initial_schedule()`。

CAABS 以 `caabs` 登记，版本取算法的 `VERSION`（当前 `0.1.0`），参数模型为 `CAABSParams`，直接构造 `ConflictBeamScheduler`，不走旧 CLI 工厂。登记可查询、参数合法、能返回候选 Schedule 不等于来源窗口消歧或严格连续认证通过；I1 验证和仍未处理的 I2 边界见 [R2-B 报告](algorithms/caabs_i1_registry_fix_20261018.md)。

## 4. 机器学习算法 D

`build(context)` 可以加载训练后固定的模型，再由 `solve()` 推理并返回 `Schedule`。模型文件路径不得由浏览器任意提交；模型 ID、版本、文件哈希与训练来源应在正式接入时一并登记和记录。训练流程、训练/验证/测试来源划分与成本记录属于算法 D 的独立交付；传统算法无需实现训练接口。若 D 采用运行中学习，仍须遵守同一搜索预算和最终计划核验。

## 5. 提交前检查

- 参数缺失、未知字段与越界值应在提交时得到明确错误；`GET /api/algorithms` 中能看到登记信息。
- 固定场景与种子下的行为可重复，或明确记录不可避免的随机来源；不改写母场景。
- 候选计划通过 `eos_system.verification.verify_candidate`；不能直接把算法报告的指标写成正式结果。
- 实际从 HTTP → Worker → Controller → SQLite 跑通至少一个小实例，并与已有基线在相同场景和约束下成对实验。
- 新依赖按用途写入相应 requirements 文件，输出文件进入已登记的运行目录；不将大型模型、虚拟环境、缓存或临时结果提交 Git。
