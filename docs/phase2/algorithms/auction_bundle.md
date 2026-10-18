# RABAS：资源感知任务包竞价调度

日期：2026-10-18；算法 B，负责人：梁兆榮；算法 ID：`rabas`；版本：`1.0.0`。

开发基线为已合并 main `7a1875f`（PR #20）；独立分支 `feat/algorithm-b-rabas`，不依赖未合并的 Daemon。核心提交 `05992a0`，注册/集成提交 `d91b170`。本轮仅本地 Commit，不 Push、不建 PR。原根目录脏工作区不纳入。

设计依据为用户提供的 `L_readme/EOS-Course-Project_v1.1(2).md` 第 4 节及本次完整任务要求。该设计是课程自定义启发式，不宣称为已有论文标准算法、不保证优于基线或全局最优。

## 1. 核心机制与差异

RABAS 在**一个 Worker 内中心化竞价**：每星从当前全局计划投影自身任务，增量构建一条有界局部 Bundle 链；不同卫星及不同长度的真实任务包提交报价，全局只接受一个经过完整公共约束重放的获胜包。中标即更新版本、失效全部旧报价，下一轮重新构建。

- 与普通 Greedy：不是仅给单任务改名计分；默认构造并比较 1/2 任务包，支持 3，包内包含真实 Assignment。
- 与 DARTIS：不以 EDF/LLF 截止期重排序为主体，以各星组合报价和全局中标为主体。
- 与 CAABS：不跨轮次保留多条全局搜索路径；每星只有一条局部逐步扩展链，当前全局 incumbent 只有一份。局部比较备选扩展不等于全局 Beam Search。
- 与 CBBA：没有分布式共识/代理通信，不启动每星独立进程，不称为分布式 CBBA。

## 2. 公共接口与集成范围

实际使用 `algorithms.solver_contracts` 的 `solve(problem, constraints, context) -> Schedule`，不建立第二套 Solver API。注册表直接构造 `ResourceAwareBundleAuctionScheduler`，和 CAABS 同样不走旧 `search()` 工厂；`algorithms/factory.py` 的旧 CLI 契约不改。

复用 Schedule、Assignment、SchedulingProblem、公共候选构造器 `ConstraintModel.build_feasible_assignment_for_task()`、`is_feasible_assignment()`、真实转向助手、ObjectiveModel 和原 EvaluationMetrics。

只增加注册元数据与比较清单，Web 自动展示参数 JSON/schema、说明、可用性和运行入口。当前为原九种 + CAABS + RABAS，共 11 种比较算法（不可用依赖仍禁用）。RABAS 不消耗初始模型解，`uses_initial_schedule=false`；所选模型仍按现有 RunConfig 保存，不能误称模型改变了 RABAS 核心机制。

Controller/Worker、IPC、SQLite、Schedule 输出结构和 TP/TCR/BD/TM/RT/RV 定义均不变。参数显式配置、版本、代码 SHA、场景 SHA 通过原 RunConfig 保存；未显式配置的参数取对应算法版本的默认值。搜索诊断保存在直接 Solver 返回的 `Schedule.metadata['rabas']`；原 serializer 不传该 metadata，**没有为统计新增 IPC 字段或数据库列**，消融脚本在 Solver 边界直接读取。

## 3. 数据结构

`BundleBid` 包含：卫星 ID、全局计划版本、包内实际新增 Assignments、完整星内计划、完整候选全局 Schedule、公共效用增量、转向秒数/归一化成本、资源成本、机会成本、资源快照和最终报价。

`OrbitResources` 按当前模型记录每轨存储 GB、累计功率 W 及剩余额度；无限容量使用 None 表示，不假造容量。冻结 dataclass 容器，候选和最终获胜计划独立复制，不向输入 problem/窗口写入搜索状态。

## 4. 有界增量建包

1. 从当前全局 incumbent 开始。按稳定任务优先级/ID 遍历本星可用任务，每步最多比较 Q 个具有可行候选的任务。
2. 每 `(任务,卫星)` 按整个时间跨度均匀抽取至多 K 个原始窗口，保留真实窗口 ID，不改窗口时间或姿态。
3. 调用公共构造器的所选放置模式和另一 earliest/center 模式，最多 P=2 个位置。非敏捷卫星仍由公共模型限定中心观测，不私自允许转动。
4. 通信候选也有上限：每星均匀保留至多 4 个原始通信窗口；实际公共构造器返回其第一个完整可行组合。
5. `_Constructor` 只负责有界枚举和检查计数，所有可行性决定都委托**原始 constraints 实例**，不克隆掉调用者附加约束。
6. 在 prefix 的完整全局计划上验证新插入；把最优扩展形成真实长度 1 的报价，再在该 prefix 上加入另一个不同任务形成长度 2 的组合报价。支持长度 3，但不全排列枚举所有组合。
7. 每星每层保留最佳报价供全局仲裁，临时扩展不跨轮次作为多路径状态保留。

因此全局任务唯一、其他卫星地面站占用、同星观测/下传互斥、前驱和后继转向、累计资源等都参与增量检查。旧公共约束实际对相关任务逐对检查，RABAS 不替换成仅检查末尾或自制弱模型。

## 5. 报价公式

先按新增任务数降序，再按以下报价降序，最后按卫星/任务/窗口/时刻/通信来源键稳定裁决：

```text
delta_U = ObjectiveModel.score(P + Q) - ObjectiveModel.score(P)
Bid = delta_U - lambda_t * C_transition
              - lambda_r * C_resource
              - lambda_o * C_opportunity
```

相对 v1.1 的局部 U 表达式，这里明确采用**全局公共 ObjectiveModel 的边际差值**，因为 BD 等非可加指标不能由单星孤立评估准确表达。任务数仍为第一层，不改变公共指标。Bid 是内部启发式，不是 TP 或新的正式综合评价指标。

### 转向成本

按时间排序本星观测，调用真实 `constraints._transition_time_s` 求相邻转换总秒数。成本为 `max(0, after-before)/场景时长`，计算插入前后的完整序列，不用任务 ID 或时间间隔替代姿态转换。新旧相关任务是否可行仍由公共检查裁决。

### 资源成本

计算受影响维度利用率平方的增量，并取平均：

- 每轨累计数据量 / max_data_storage_GB；
- 每轨累计 power_cost_W / max_power_W（保持现有模型的 W 求和，**不声称是焦耳能量模型**）；
- 本星观测及下传占用秒数 / 场景时长；
- 包内涉及地面站的占用秒数 / 场景时长。

不存在正容量上限的维度不收费。平方增量使已有高利用率下的新增消耗更贵，报价随当前资源状态变化。ObjectiveModel 不含上述存储/功率/转向成本，故未重复扣减同一成本；时效/均衡得分仍按原定义处理。

### 机会成本

为每星识别**原始窗口仅由该星提供**的任务，按优先级/ID 有界抽查最多 Q 项。对于不在当前包内的受保护任务：若中标前在已搜索窗口/位置内有可行安排，中标后不再存在，则记一次潜在机会损失。

`C_opportunity = 丢失的受保护任务数 / 当前剩余任务数`。

前态可行性只在当前轮缓存，后态对真实候选全局计划重新求公共可行插入。权重设为 0 时跳过此估计，可直接消融。它是**有界机会估计**，不是精确全局机会损失；窗口截断可能遗漏替代位置，且多星均有原始窗口、但当前仅一星可行的动态稀缺不在本版完整建模范围。

## 6. 全局中标、失效与终止

选出报价后，必须校验版本等于当前全局版本；再将完整候选 Schedule 按时间重放到空 Schedule，每条调用原公共约束。全部成功且未取消/超预算，才一次性替换 incumbent、移除包内任务、版本 +1。旧报价清空；下一轮全部卫星重报，不消费陈旧报价。

停止条件：全部安排、无可行报价、轮数上限、搜索检查上限、内部预算或取消。达到搜索预算/检查上限时仅返回**已经完整中标**的 incumbent，不将半轮报价或半个任务包当作成果。内部预算预留 min(0.05s, 5%预算) 返回余量，长原生公共调用仍非硬实时抢占。

取消在初始化、候选、报价、资源/机会估计、全量核验和返回前检查，抛 `RABASCancelled`，即使已有 incumbent 也不伪装成功。生产 Worker 的取消标记/回收/Controller 仲裁不改；外部强制超时仍由原框架决定。

## 7. 参数

| 参数 | 默认 / 范围 | 实际作用 |
|---|---|---|
| max_bundle_size | 2；1–3 | 多任务包上限；1 用于消融 |
| bid_candidates_per_satellite | 8；1–32 | 每星每步最多比较的可行任务数量 Q |
| max_rounds | 0；0–1000 | 0 自动取 min(任务数,1000) |
| max_windows_per_task | 4；1–32 | 每任务每颗卫星的窗口上限 K |
| max_positions_per_window | 2；1–2 | 所选 earliest/center 模式及可选另一模式 |
| max_checks_per_round | 20000；16–100000 | 每轮搜索公共检查上限；中标全量重放另加至多 N 次 |
| transition_cost_weight | 0.1；0–10 | 转向成本权重 |
| resource_cost_weight | 0.1；0–10 | 资源利用压力权重 |
| opportunity_cost_weight | 0.5；0–10 | 机会损失权重，0 关闭 |
| reauction_mode | all_affected | 唯一已实现策略，实际全量重报 |

严格整数拒绝 bool、字符串、小数；权重拒绝 bool、负值、NaN/Inf；未知参数和未实现策略拒绝。冻结参数模型可直接公开 JSON schema，不依赖前端硬编码。

## 8. 伪代码与复杂度

```text
P = empty; version = 0
repeat within rounds / budget:
    bids = []                         # 不带入旧报价
    for satellite:
        prefix = P
        for depth in 1..h:
            best = best bounded feasible extension of prefix
            if none: break
            bid = price full bundle against P and current resources
            bids += best bid of this depth
            prefix = best complete candidate
    if no bids: stop
    winner = completion-first argmax(bids)
    require winner.version == version
    replay winner.full_global_schedule through public constraints
    P = isolated full winner; version += 1
    discard all old bids
return P                             # 取消则异常，不成功返回
```

主体有界扩展约 `O(R S h Q K P F)`，但实际还包括：最多 N 个任务扫描排序、有界独占任务机会探查（额外 Q 因子）、每个候选的公共目标/资源遍历和获胜全局重放；不能把主体粗估当作完整已证明上界。每轮搜索检查有显式上限，预算遍布各循环；全量核验另至多 N 次。生产不保留全部候选树，报价通常仅 S×h 个完整计划；诊断 hook 仅供小型测试，不应在大型运行中收集所有报价对象。

## 9. B-1 至 B-5 机制验证

`tests/test_algorithm_auction_bundle.py` 当前 22 项通过：

- B-1：T1 可 S1/S2，T2 仅 S1，时间冲突；机会成本关闭时 T1→S1 完成1项，开启后 T1→S2/T2→S1 完成2项，真实报价也改变。
- B-2：两星均报价同任务，最终只分配一次。
- B-3：实际生成并全局中标两任务包；检查完整 Assignments、真实转换秒数及资源快照。另验证三任务包、前后邻居转向和累计资源超限。
- B-4：共享地面站使另一星旧报价失效；全量重报后不非法安排。版本逐轮变化，后续报价含最新全局计划。
- B-5：大小1/2与机会成本0/0.5的2×2消融，公开指标由原 compute_evaluation_metrics 计算。
- 另覆盖严格参数、确定性、输入不变、无谱系拒绝、真实公共地球遮挡拒绝、立即/中途中止取消、预算原子返回、轮数和检查上限、空输入。

## 10. 消融实测

环境：项目 Python 3.10 / WSL2；seed=42，预算5s，目标权重 profit=1，其余0（完成任务数仍优先），统一使用公共默认约束（非敏捷转换10s、Standard-Agility、下传比1、earliest）。各配置串行运行，最终记录时已关闭本轮浏览器测试服务；其他宿主负载未控制。每格一次，不代表统计显著性；RT 单位秒，TM 越小越好。

| 输入 | h | λo | 完成 | TP | TCR | BD | TM | RT | 竞价轮数 | 候选包数 | 最大包 | 公共检查数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 合成 B1 |1|0|1/2|10|0.5|0.75|0.5|0.002145|2|3|1|9|
| 合成 B1 |1|0.5|2/2|11|1|1|0|0.002375|2|4|1|14|
| 合成 B1 |2|0|1/2|10|0.5|0.75|0.5|0.001277|2|3|1|11|
| 合成 B1 |2|0.5|2/2|11|1|1|0|0.001720|2|4|1|16|
| 合成 B3 |1|0|3/3|3|1|0.5|0.008333|0.001917|3|6|1|18|
| 合成 B3 |1|0.5|3/3|3|1|0.5|0.008333|0.002668|3|6|1|31|
| 合成 B3 |2|0|3/3|3|1|0.5|0.008333|0.001774|2|6|2|17|
| 合成 B3 |2|0.5|3/3|3|1|0.5|0.008333|0.002813|2|6|2|28|
| S1 预览 |1|0|20/20|117|1|0.630769|0.474938|1.058298|20|1720|1|1936|
| S1 预览 |1|0.5|20/20|117|1|0.630769|0.474938|0.876054|20|1720|1|1936|
| S1 预览 |2|0|20/20|117|1|0.600000|0.448591|0.927536|10|1640|2|1776|
| S1 预览 |2|0.5|20/20|117|1|0.600000|0.448591|0.938629|10|1640|2|1776|

解释：B1 两任务不能同时形成同星包，h=2 不会凭空改善；机会成本改善此反例。B3 的 h=2 真正中标双任务，减少轮数但完成数相同。真实 S1 中机会项没有改变输出，不能宣称对所有场景有效；h=2 的 TM 更低但 BD 更低，不能称为全指标占优。没有跨算法最优性或多种子统计结论。

真实输入为 `small/Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1.json`，SHA-256：`1357bd9802aae6cc2bb21e992e65f432fb3cda24702f1dff4340ec68cc8bccc9`。整个实验只读输入，前后 SHA 一致。全部表格为公共规划可行性/预览实验，**不是正式连续认证成绩**。

## 11. 系统与浏览器验证边界

`tests/test_rabas_integration.py` 4 项通过：

1. 参数 schema、可用性、无初始解依赖、HTTP 非法参数422；新进程导入无循环依赖。
2. 合成三任务经真实 spawn Worker、公共约束、Controller、SQLite 正式生命周期路径，保存参数与版本，重算3项任务指标；Gantt/调度 API 和 Cesium 重定向正确；独立回放构建 READY。
3. 上述正例仅最终 certify_schedule 采用现有 `UNIT_TEST_ONLY` 注入；候选生成/独立来源重建/公共约束/事务未替换。**这不证明真实正式物理认证。**
4. 未改动的真实 S1 场景经真实 Worker/Controller 预览完成20/20，状态 NOT_CERTIFIED；同一输入 formal 请求实际 FAILED / UNTRUSTED_PHYSICAL_SETTINGS，plan/metrics 为 null，正式门禁未放宽。

一次真实 Chromium 小型验收通过：在注册驱动首页展开 RABAS 参数，编辑 h/机会权重，和收益优先一起提交；列表只新增一个实验、内部两算法，RABAS显示3/3指标；Gantt三任务和键盘 Tooltip可用；Cesium自动构建完成，显示2个卫星模型和固定镜头，未出现 pageerror。浏览器同样使用明确标记的合成认证/轨道夹具，**不宣称真实物理端到端成功**。

浏览器末次成功记录：实验 `d89cee95-fab3-4f86-9dd7-295aa54cb30e`，RABAS Run `ddbf9ba7-2bb7-43e5-a484-b2454a86f42f`；另明确断言 Cesium Observation Intervals 为3条，当前行 aria-current 高亮和 URL Run ID 一致。都是临时隔离目录，测试后已清理，不是可从生产控制台查询的历史记录。

最终合并定向命令 `PYTHONPATH=tests python -m unittest test_algorithm_auction_bundle test_rabas_integration test_algorithm_registry_i1 test_nine_algorithms test_console_catalog -v`：**52 项通过，19.036s，0跳过/失败/错误**。未执行默认全套、大型 Benchmark 或中型/50星场景。

## 12. 复现命令

在本分支工作树（或替换为包含提交的项目目录）执行：

```bash
cd /home/asus/projects/eos-course-runtime/.worktrees/algorithm-b-rabas
PY=/home/asus/eos-course-runtime/.venv/bin/python
"$PY" -m unittest discover -s tests -p test_algorithm_auction_bundle.py -v
"$PY" -m unittest discover -s tests -p test_rabas_integration.py -v
PYTHONPATH=tests "$PY" -m unittest test_algorithm_registry_i1 test_nine_algorithms test_console_catalog -v
"$PY" scripts/benchmark_rabas.py
"$PY" scripts/benchmark_rabas.py --scenario experiments/scenarios/small/Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1.json --mode planning_preview --budget 5
```

真实场景若只是 LFS pointer，应先恢复相同 SHA 的原始对象；不改 JSON 来取得认证。运行输出使用 stdout 或显式 `--output` 指定临时文件（拒绝覆盖已有文件），不写业务库。

浏览器夹具可在一个终端运行 `python tests/browser/serve_rabas_fixture.py --coord /tmp/rabas-qa.json`；另一个终端设置 `EOS_RABAS_COORD`、`PLAYWRIGHT_MODULE`、`EOS_BROWSER_EXECUTABLE` 后运行 `node tests/browser/rabas-smoke.cjs`。协调文件不可已存在；服务随机端口、独立 /tmp 数据库，不访问正式8765。脚本结束通知关闭，最长180s自动收尾。

## 13. 剩余限制与验收状态

- **真实正式非空物理认证端到端未完成**：当前现有六个 epoch_fixed_v1 是历史抽样发布，没有符合当前 formal planning 的可信窗口谱系，正式 certifier 还报 UNTRUSTED_PHYSICAL_SETTINGS。不能修改原场景、伪造谱系、跳过地球遮挡或用预览成绩代替。需数据/认证负责人提供同公共物理版本的正式输入后复验。
- 候选只覆盖有界原窗口、earliest/center和至多4通信窗，公共构造器只返回第一个可行通信组合，可能遗漏合法计划。没有自制连续时间放置或私有物理模型来补偿。
- 单条局部贪心建包链可能错过其他组合；最大完成任务数也不保证全局最优。机会估计是受限独占任务损失，并非完整动态稀缺优化。
- 完成搜索时使用稳定 ID 次序且不引入随机源；预算截断位置仍受主机速度影响，不保证不同负载下得到完全相同的部分解。
- 预算仅协作式，有界公共调用本身无法 Python 抢占；检查上限耗尽时可能返回较小但已合法中标计划，明确标注 stop_reason，不伪造完成。
- 没有大型/中型场景性能证明、真实50星浏览器测试或跨算法统计优势结论。
- 旧 registry 测试中“CAABS永远在最后”仅改为按ID查找，旧算法数断言改11；DARTIS/CAABS核心、公共候选/约束/指标/Worker/Controller均未修改。
- 注册表与 Web 提示的最小兼容改动需李泽同确认；后续合并仍按团队独立审核要求，本轮不 Push/PR。
