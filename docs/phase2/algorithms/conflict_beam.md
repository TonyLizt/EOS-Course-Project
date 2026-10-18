# CAABS 当前状态增补 — v0.2.0 候选放置覆盖修复（2026-10-18）

> 以下是针对 Git `ba114dd` 的修复提议，**只有将补丁应用、回归通过并提交新 Git SHA 后，才可以声称 v0.2.0 已实现**。原有 v0.1 / I1 / I2 描述继续保留作为历史资料。
>
> 动机：在独立合成三任务反例中，公共 ConstraintModel 接受 0/55/90 秒的三任务见证计划，而原 CAABS 只返回两任务；旧候选均为 `earliest` / `center` (0/55 秒)。
>
> 最小改动：复用公共 `ConstraintModel.build_feasible_assignment_for_task()` 已支持的 `latest` 放置策略，不复制仰角、来源身份、姿态切片、下传与资源约束。每选定窗口最多从两个变为三个构造调用；最大候选数和 `branch_limit` 不变，仍保留协作取消与时间预算检查。
>
> 限制：这只增加一个确定性晚放置锚点，不保证覆盖全部起点或所有下传组合；窗口数达到候选上限时，晚放置仍可能由于容量限制而未进入前沿。P3 物理模型和严格连续认证另行审核，不能据此认证正式场景。
>
> 验收：新增原始三任务反例回归、候选上限回归，原有四组测试均通过（原基线 103 项，补丁后应超过 103 项）；记录实际输出、测试数量、退出码和提交 SHA。

---

# CAABS v0.1 — Conflict-Aware Anytime Beam Search

> 2026-10-18 R2-B/I1 后续：本工作树已补充 `caabs` Registry 登记及无环共用契约，待人工审核；搜索版本仍为0.1.0。以下核心交付/R1历史记录保留。I2来源窗口、连续认证和正式发布未在I1处理，详见 [I1修复报告](caabs_i1_registry_fix_20261018.md)。

中文：冲突感知限时束搜索。负责人：刘懋兴。
基线：`d0d9325759f078ef13f41cc9eee74c5e7733758a`。
分支：`feat/algorithm-c-caabs`；独立 worktree：`D:\VC\EOS-Course-Project-caabs`。

本轮只实现算法核心、专项测试和文档，未登记 Algorithm Registry，未修改 factory、
Worker、Controller、HTTP、IPC、SQLite、公共物理约束、Loader 或连续曝光认证。
版本常量为 `0.1.0`，参数默认值是实验初值，没有冻结生产配置。

## 入口与主要对象

`ConflictBeamScheduler.solve(problem, constraints, context) -> Schedule` 直接实现当前
Solver 协议。无需旧 search 适配器或初始贪心计划。构造函数只接收可测试的单调 clock，
不会保存 build 阶段的旧 context；取消查询始终使用本次 solve 收到的回调。

| 对象／函数 | 职责 |
|---|---|
| CAABSParams | 继承真实 AlgorithmParams，Pydantic 校验，冻结、拒绝未知字段 |
| BoundedCandidateAdapter | 按卫星和时域选择有限窗口，调用公共单候选构造器 |
| BeamState | 独立 Schedule、固定任务游标、完成数、公共目标分和规范键 |
| canonical_assignment_key / canonical_state_key | 完整、确定性规范表示 |
| clone_schedule / branch_schedule | 深拷贝现有 assignment、候选和 metadata |
| SafeConflictIndex | 当前父状态上的稀疏任务及观测区间索引 |
| _SolveControl | 单调预算、返回余量和协作取消 |
| ConflictBeamScheduler | 固定顺序的多路径扩展、去重、Top-B、独立 incumbent |

直接调用示例（problem／constraints 由现有场景加载和模型构造流程提供）：

```python
from algorithms.conflict_beam import CAABSParams, ConflictBeamScheduler
from algorithms.objectives import ObjectiveWeights
from eos_system.algorithm_registry import SolveContext

context = SolveContext(
    seed=42, time_budget_s=60,
    objective_weights=ObjectiveWeights(w_profit=1),
    params=CAABSParams(),
)
candidate_schedule = ConflictBeamScheduler().solve(problem, constraints, context)
```

## 参数范围

| 参数 | 默认值 | 合法范围 |
|---|---:|---|
| beam_width | 8 | 严格整数 1–256 |
| branch_limit | 8 | 严格整数 1–64，每个父状态尝试的候选上限 |
| max_candidates_per_task | 16 | 严格整数 1–128 |
| max_windows_per_task | 32 | 严格整数 1–256 |
| conflict_prefilter | true | 严格布尔值，供消融 |

布尔值不能冒充整数，未知字段和越界值报 ValidationError。目标权重来自冻结的
context.objective_weights，使用现有 ObjectiveModel 的归一化规则。
v0.1 没有随机步骤：seed 被保留在统一 context 中，同输入与预算足够时结果确定，
无需借助进程哈希种子。受墙钟提前停止时，不保证不同机器返回同一搜索前缀。

## 有界候选与覆盖限制

审计确认 enumerate_task_candidates 的 placement_mode 不控制内部位置枚举，
max_candidates 也不限制其预先创建全部位置／姿态切片的成本；v0.1 不调用它。

适配器先调用公共 planning_window，拒绝证据不足或保守区间不足的窗口。
不构造、不补写、不修改真实 planning_evidence，也不自行计算物理公式。
选定窗口数上限为 min(max_windows_per_task,max_candidates_per_task)。

1. 按卫星分组，以卫星 ID 确定顺序；卫星过多时均匀取子集。
2. 将窗口名额分配给卫星；每星按起止时间、窗口 ID、sensor 排序。
3. 每星的名额在其时间范围均匀选取，随后交替遍历各星窗口。
4. 先为每个选定窗口尝试 earliest，再用剩余候选名额尝试 center。
5. 每次只向公共构造器提供一个来源窗口，randomized=False。
6. 规范键去重，候选顺序保留上述覆盖轮次；搜索仅尝试前 branch_limit 项。

构造模型复制传入 constraints 的所有现有配置，只将放置参数设为 earliest／center。
非敏捷观测仍由公共构造器强制居中，姿态、资源和下传全部由该构造器计算。
_CandidateConstructor 仅增加计数与检查点，实际可行性调用 super()，没有物理规则副本。
最终每次插入都再调用原始传入 constraints，不能用构造检查代替状态相关检查。

每任务最多 2 × 选定窗口数次构造调用，返回候选最多 max_candidates_per_task。
不枚举 latest 或随机位置。单次构造只返回首个可行下传组合，两个放置模式还可能
得到重复观测／不同下传；不保证覆盖全部通信窗口、地面站或可行起点。
某星窗口少时未用配额不会全部回填；无候选的选定窗口不会被穷举替换。
branch_limit 小于候选数时还会损失覆盖；所有这些都是 v0.1 的显式有限搜索策略。
可信 v2 的保守结束点由公共 planning_window 扣减真实扫描步长；不改写来源窗口，
因此公共构造器按原窗口选择的部分位置仍可能被规划检查拒绝。

输入窗口扫描、公共目标评价和排序成本仍随输入规模增长；“有界”指构造调用、
返回候选和分支数量，不是输入大小无关或硬实时保证。

## 多路径流程、评分与独立 incumbent

任务按任务 ID 固定排序，每层处理一个任务。每个父状态：

- 深拷贝生成 skip 分支，游标前移，不能在后续重新处理已跳过任务。
- 对最多 branch_limit 个候选运行安全预筛。
- 必须先调用 constraints.is_feasible_assignment(candidate,parent.schedule)。
- 通过后才深拷贝父 Schedule 并 append 独立候选。
- 计算完成数及公共 ObjectiveModel 分数，更新独立 best_feasible。
- 按搜索键去重，按确定性 rank_key 排序，保留 Top-B。

rank_key 为（完成数降序、公共加权分降序、规范计划键升序）。
这是完成数优先的搜索排序，不等于单一公共加权目标最优化，更不等于正式指标已核验。
没有使用未来收益上界；没有最优性、宽度单调改进或超过 Greedy／SA 的保证。

best_feasible 在子状态产生后、去重和剪枝前保存独立深拷贝。它不引用当前 Beam；
即使在本层完成前停止，也可返回之前已保存的可行子计划。
空计划是启动时、无候选或过早停止时的结构性回退，不宣称“无可行解证明”。

## 状态键与分支隔离

canonical_assignment_key 遍历 Assignment 的所有真实 dataclass 字段，包括：
task_id、satellite_id、sat_window_id、观测 start/end、sensor_id、orbit_number、
data_volume_GB、power_cost_W、完整 sat_angles、ground_station_id、gs_window_id、
下传 start/end。这样保留后续 slew、资源和占用所需的全部输入。

时间统一为 UTC 微秒表示，loader 的 naive 时间按 UTC 解释，不调用本地 timestamp。
浮点使用精确 hex 表示，不用舍入合并。姿态字典键排序、数组保持顺序。
R1.1 起，list 与 tuple 分别使用独立类型标签；每个嵌套层级也保留容器类型。
Schedule 键对 assignment 编码排序，忽略 assignment 列表顺序和非语义 metadata。
BeamState.search_key 再包含 task_index，防止相同计划的不同 skip 游标被合并。

父／子／兄弟状态之间不共享可变 Assignment、姿态或 metadata。候选被插入时也
深拷贝，输入 problem 和原 constraints 不修改。测试诊断钩子 _observe_beam 只供
同步只读观察，不是 Worker 进度通道；测试保存自己的快照。

## Safe Conflict Index 的安全边界

每个父状态只索引已安排任务 ID，以及按卫星分组的固定观测起点和前缀最大结束点。
存储 O(K)，构建约 O(K log K)，重叠查询 O(log K)；K 是父计划长度。
不创建所有 M 个候选的 O(M²) 冲突图，也不缓存任意失败插入为永久冲突边。

仅可静态拒绝同任务或同卫星直接观测重叠。使用半开区间，端点接触不因重叠拒绝。
slew、下传、地面站、累计存储／功率和多个任务的组合约束全部交公共模型。
两两没有冲突不能证明三者累计可行。conflict_prefilter=False 完全关闭预筛。

metadata.caabs.stats 中：

- candidate_builder_calls：公共单候选构造调用次数。
- candidate_constraint_calls：公共构造内部实际进入可行性检查的次数。
- public_constraint_calls：搜索阶段对原始 constraints 的插入检查次数。
- prefilter_rejections：安全索引提前拒绝数。
- accepted_insertions、scored_states、duplicate_states、pruned_states：
  扩展／评分／去重／剪枝计数。
- max_beam_size、max_children、levels_completed：前沿规模与完成层数。

公共检查总数应结合 candidate_constraint_calls 和 public_constraint_calls 阅读，
不能只展示搜索计数而隐去准备成本。schedule_to_dict 不输出 metadata，这些统计仅在
当前内存返回值可用；本轮未改系统结果传输或落库结构。

## Anytime、预算与取消

使用 time.monotonic；测试可注入可控 clock。内部搜索截止为：
started + time_budget_s - min(0.05秒,time_budget_s × 5%)。

在窗口扫描／构造之间、索引构建、扩展、评分前后、规范化、去重和剪枝前后轮询
context.is_cancelled() 与截止时间。候选按任务逐层准备，避免准备所有任务后才有
incumbent。停止后不继续评分或深拷贝整个结果，只附加小型诊断并返回已有快照。

响应粒度仍受单次公共构造（含通信窗口扫描）、公共可行性／目标函数、
单个嵌套对象 deepcopy 和排序内核限制。返回余量是尽力安排，不保证 OS 抢占、
原生长调用或极大输入下严格按时；硬超时和进程回收仍属于 Controller／Worker。

内部 stop_reason 为 completed／budget／cancelled，属于算法诊断，不是系统终态。
取消时尽快返回已有计划，Worker 可抑制其发布。没有流式 best-solution 发布接口；
外部硬终止不会自动保存算法内存 incumbent。不得生成认证回执。

## 正确性验收

测试使用现有 test_adaptive_repair 的合成内存证据约定，标记 CAABS_UNIT_TEST_ONLY。
这些 fixture 仅用于隔离单测，不读写真实场景、不安装生产来源、不冒充物理认证。
C-2、slew、下传和地面站测试都调用真实 ConstraintModel；停止测试只注入时钟、
观察回调或包装真实评分／键函数，没有 mock 可行性结果。

| 编号 | 证据 |
|---|---|
| C-1 | 首层实际保留 T1→S1 和 T1→S2；宽度1完成1项，宽度4完成2项 |
| C-2 | 存储／功率分别限制为2.5，三个任务各消耗1；前两者可行，第三者由公共模型拒绝 |
| C-3 | 同任务多卫星／多窗口候选最终仅执行一次 |
| C-4 | 宽度1、4、8、16，检查真实前沿大小、确定性排名与路径 |
| C-5 | 可控时钟、入口取消、候选准备取消；评分、规范化、去重、剪枝中停止保留 incumbent |
| C-6 | 同一重叠实例启用／关闭预筛，计划相同；搜索公共调用2／3，准备检查均4次；预筛拒绝1／0 |

另外覆盖：空任务／无窗口／缺证据，卫星及时间范围覆盖，earliest／center、
非敏捷中心、v2 保守边界、调用上限，父子／兄弟／incumbent 隔离，所有字段键区分、
顺序和时区规范，真实下传严格边界、地面站占用、敏捷及非敏捷 slew，实际去重、
完成数先于利润、冻结目标权重、固定 seed 和 schedule_to_dict 结构。

测试入口：

```powershell
python -B -m unittest discover -s tests -p "test_algorithm_conflict_beam.py" -v
```

WSL（使用已存在的环境，不创建环境、不下载依赖）：

```bash
cd /mnt/d/VC/EOS-Course-Project-caabs
PYTHONHASHSEED=0 MPLBACKEND=Agg ~/eos-course-runtime/.venv/bin/python -B -m unittest discover -s tests -v
```

### 本轮结果（2026-10-17）

- 第一提交前：专项10项通过，退出0；git diff --check 通过。
- 第二提交前：专项22项通过，退出0；git diff --check 通过。
- 最终专项：Windows Python 3.13.5 与 WSL Python 3.10.12，均42项通过、失败0、跳过0，退出0。
- 扩展测试初次为41项、1项失败：取消 fixture 过早触发，未达到要测的候选准备阶段；
  改为在真实 planning_window 返回后触发回调，未修改公共可行性规则；最终42项通过。
- WSL 原有回归：adaptive_repair 3项通过；transition_model 4项通过；
  continuous_exposure 15项中14项通过、1项可选跳过；均退出0。
### 全量尝试与独立复现

全量未完成，不能报告为通过，也不能把未完成部分的失败／跳过数记作零。

| 检查 | 退出码 | 完成情况 |
|---|---:|---|
| Windows 专项42项 | 0 | 42通过，0失败，0跳过 |
| WSL 专项42项 | 0 | 42通过，0失败，0跳过 |
| WSL adaptive_repair | 0 | 3通过，0失败，0跳过 |
| WSL transition_model | 0 | 4通过，0失败，0跳过 |
| WSL continuous_exposure | 0 | 14通过，0失败，1可选跳过 |
| WSL 全量（内层360秒／外层380秒） | 外层1 | TimeoutExpired，没有完整汇总，计数不可确定 |
| WSL 全量 fail-fast 诊断（180秒） | 内层124，包装器0 | 已观察123条ok、1条skip，没有失败汇总；整体未完成 |
| WSL 单项 HTTP 取消复现（45秒上限） | 0 | 1通过，0失败，0跳过，unittest耗时5.645秒 |

实际全量命令（在上述 worktree，已有 WSL venv 中）：

```bash
MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1 timeout --kill-after=5s 360s \
  ~/eos-course-runtime/.venv/bin/python -B -m unittest discover -s tests -v
# 诊断时将360s改为180s，并增加 -f；日志写入系统临时目录，结束清理。
```

有日志的诊断最后进入
`test_controller_cancel.ControllerCancelTests.test_http_cancel_uses_existing_route_and_temporary_database`，
随后达到180秒上限，结束时出现resource_tracker信号量清理警告。
独立复现命令：

```bash
PYTHONPATH=tests MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1 \
  timeout --kill-after=5s 45s ~/eos-course-runtime/.venv/bin/python -B -m unittest \
  test_controller_cancel.ControllerCancelTests.test_http_cancel_uses_existing_route_and_temporary_database -v
```

独立复现通过，不能认定该测试或公共模块存在必现故障；全量耗时／顺序运行超时原因
尚未确定。项目历史 COURSE_SETUP 也保留同名测试停滞记录，但这不能替代本轮定位。
未修改共享测试、规则或超时协议来放行；检查未发现本次测试残留进程。
没有在本轮确认新的公共物理约束／认证缺陷。后续须在系统验收环境继续完成全量。

最后范围检查：git diff --check、UTF-8中文及基线历史内容保留检查通过；
相对固定基线仅四个指定文件有差异。本轮未生成真实场景或正式认证计划。

对上一轮审计的一处纠正：certify_schedule 中的 model_parameters 来自
CertificationContext.identity()，不能将其认定为缺失字段；未因此修改认证模块。


## 已知限制与后续接入

搜索可行仅表示通过当前公共模型；正式计划仍须 Controller 重新加载场景、
核验每条来源／资源／姿态、重新计算指标，并取得连续曝光认证回执。
生产连续区间证明缺失时仍可能 INCONCLUSIVE；空计划同样不是已认证计划。
本轮不以完成正式认证或超过已有算法作为验收条件。

公共模型当前按轨累加 GB 和 power_cost_W，不是动态存储释放或电池能量仿真。
不在算法中修改单位、slew、严格下传边界、规划来源或认证规则。
有限窗口／位置／首个下传组合与 branch_limit 可能漏解；Beam 剪枝也可能丢失有用路径。
canonical key 包含完整姿态，深拷贝及全目标评分成本可能较大；尚无真实规模性能结论。

后续由集成负责人审查后在 registry 增加唯一 ID、负责人、版本、CAABSParams、
build=lambda context: ConflictBeamScheduler()；不要求 factory 或生命周期协议改造。
登记时还需审查参数基类与算法模块的导入顺序，避免顶层循环导入。
之后再做固定真实场景、同预算多 seed 成对实验，以及 Linux Worker／Controller
独立核验与认证闭环。现有公共认证问题应单独复现和处理，不能通过 CAABS 绕过。

## R1.1：M1 最小修复与复验（2026-10-17）

修复提交：`ce833caee606e3d366026ec0c44b2b4a2719505a`。
算法版本常量仍为 `0.1.0`；本轮是状态键修复，没有新增候选策略、启发式或默认参数。
R1 的原审查结论保留在 [独立审查报告](caabs_r1_independent_review.md)，后续状态见其 R1.1 附录。

`_freeze()` 原来将 list 和 tuple 都编码为 sequence，现在分别编码为 list、tuple。
元素递归顺序、dict 键排序、UTC 微秒、float.hex()、非有限值拒绝及其他标量规则未变。
真实公共姿态解析器对外层 list 与 tuple 有不同语义，不能按内容相同就合并状态。
修复不改变 Assignment、公共 slew、ConstraintModel 或认证规则。

专项由42项增至48项，新增6个测试方法：

- 空/非空 list 与 tuple 的类型区分、各自的元素顺序和同类型内容稳定性。
- dict、list、tuple 内嵌不同容器的区分，以及字典重排不改变键。
- None/bool/int/str、精确浮点及正负零的区分，NaN/正负无穷拒绝。
- 真实公共约束反例：同星前任务0–10秒、后任务30–40秒；0→90度姿态数值相同，后任务外层 list 被拒、tuple 走现有回退而接受，修复后两者键不同。
- 实际搜索去重：只注入候选列表，公共可行性保持真实；同内容 list/tuple 两条路径均保留，另一个完全相同的 list 副本只去重一次。
- C-4 三层饱和测试：每层3候选加skip；重复两轮，检查真实前沿、游标、唯一键、确定排序、剪枝统计及公共模型回放。

原有全部 Assignment 字段区分及 naive/aware UTC、微秒测试继续通过。
合成姿态与规划证据仍仅限单测，不表示正式物理认证通过。

### 修复前后证据

先仅增加测试，在旧 `_freeze()` 上运行 Windows 完整专项：48项中44个方法通过、4个方法失败，
unittest 报 failures=6（其中嵌套测试含3个失败子测试），错误0、跳过0、退出1；
unittest 1.447秒、子进程总计2.501秒。真实公共模型的不同可行性断言先通过，随后才在键相同的断言处失败；
实际去重错误地只保留2个状态而非3个。未切换、重写或修改旧提交历史。
最小修复后下列命令全部退出0，M1标记 **RESOLVED**。

Windows：`D:\Anaconda\python.exe`，Python 3.13.5；WSL Ubuntu-22.04：
`/home/meteor/eos-course-runtime/.venv/bin/python`，Python 3.10.12。
两边均设置 PYTHONHASHSEED=0、MPLBACKEND=Agg，工作目录是各自路径表示的 CAABS worktree。
每条测试子进程上限90秒，均未触发；总计时含 Python 启动，0.000秒仅为 unittest 显示精度。

| 环境 | discover 的 -p 参数 | 项数 | 通过 | 失败 | 跳过 | 退出码 | unittest秒 | 子进程总秒 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Windows | test_algorithm_conflict_beam.py | 48 | 48 | 0 | 0 | 0 | 1.212 | 2.151 |
| Windows | test_transition_model.py | 4 | 4 | 0 | 0 | 0 | 0.000 | 0.417 |
| Windows | test_continuous_exposure.py | 15 | 14 | 0 | 1 | 0 | 0.474 | 0.888 |
| Windows | test_adaptive_repair.py | 3 | 3 | 0 | 0 | 0 | 0.001 | 0.421 |
| WSL | test_algorithm_conflict_beam.py | 48 | 48 | 0 | 0 | 0 | 0.809 | 2.457 |
| WSL | test_transition_model.py | 4 | 4 | 0 | 0 | 0 | 0.000 | 0.997 |
| WSL | test_continuous_exposure.py | 15 | 14 | 0 | 1 | 0 | 0.457 | 1.398 |
| WSL | test_adaptive_repair.py | 3 | 3 | 0 | 0 | 0 | 0.001 | 1.391 |

唯一跳过项均为 opt-in real Orekit exposure cases。公共约束回归由专项真实资源/slew/下传测试、
continuous_exposure 的公共规划门禁测试及原有过渡/调度测试共同覆盖；没有改公共规则来使测试通过。

实际命令（每次单独执行）：

```powershell
Set-Location D:\VC\EOS-Course-Project-caabs
$env:PYTHONHASHSEED = '0'
$env:MPLBACKEND = 'Agg'
D:\Anaconda\python.exe -B -m unittest discover -s tests -p "test_algorithm_conflict_beam.py" -v
D:\Anaconda\python.exe -B -m unittest discover -s tests -p "test_transition_model.py" -v
D:\Anaconda\python.exe -B -m unittest discover -s tests -p "test_continuous_exposure.py" -v
D:\Anaconda\python.exe -B -m unittest discover -s tests -p "test_adaptive_repair.py" -v
```

```bash
cd /mnt/d/VC/EOS-Course-Project-caabs
PYTHONHASHSEED=0 MPLBACKEND=Agg /home/meteor/eos-course-runtime/.venv/bin/python -B -m unittest discover -s tests -p 'test_algorithm_conflict_beam.py' -v
PYTHONHASHSEED=0 MPLBACKEND=Agg /home/meteor/eos-course-runtime/.venv/bin/python -B -m unittest discover -s tests -p 'test_transition_model.py' -v
PYTHONHASHSEED=0 MPLBACKEND=Agg /home/meteor/eos-course-runtime/.venv/bin/python -B -m unittest discover -s tests -p 'test_continuous_exposure.py' -v
PYTHONHASHSEED=0 MPLBACKEND=Agg /home/meteor/eos-course-runtime/.venv/bin/python -B -m unittest discover -s tests -p 'test_adaptive_repair.py' -v
```

| beam_width | 三层实际前沿宽度（两轮一致） |
|---|---|
| 1 | 1, 1, 1 |
| 4 | 4, 4, 4 |
| 8 | 4, 8, 8 |
| 16 | 4, 16, 16 |

原始日志保留于 Windows `%TEMP%\caabs-r11-4eg4_ato` 与 WSL `/tmp/caabs-r11-44gb4hqj`；
临时文件不提交，关键统计及命令已收入本文。代码提交前的 `git diff --check` 和
`git diff --cached --check` 均退出0；文档提交前再次检查暂存范围与空白。

基于R1核心复核与本次M1反例、分支去重和饱和测试，建议将独立核心结论升级为 **CORE REVIEW PASS**。
这不改变 **REGRESSION INCOMPLETE / INTEGRATION NOT VERIFIED**：本轮未重跑全量、未登记 Registry、
未完成正式连续认证。I1未来循环导入、I2公共来源窗口歧义及全量时序/超时仍由独立任务处理。
