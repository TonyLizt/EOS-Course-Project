# DARTIS：截止期感知动态可行插入

- 负责人：何明涛；算法 ID：`dartis`；版本：`0.1.0`。
- 阶段：G1-A 核心已由何明涛提交为 `588dbd2`；G1-B/G2 注册和隔离集成基于该提交。本记录所述集成测试只对应本次工作区。
- 设计依据：《EOS-Course-Project 三种传统卫星调度算法设计与分工说明书 v1.1》第 2、3、6、8–10 节。算法是离线构造，不是在线到达或硬实时调度。

## 机制与参数

`DARTISScheduler.solve(problem, constraints, context) -> Schedule` 维护一份合法部分计划。每轮按原始任务窗口与卫星生成受限候选，使用公共 `ConstraintModel.is_feasible_assignment` 验证，取得**受检候选中**最早合法观测开始时刻。LLF 键先比较 `window_end - required_duration - inspected_start`，EDF 键先比较原窗口结束时刻，再由稳定任务、卫星、窗口及时间字段打平。每次插入后丢弃旧机会并对所有剩余任务 full 重算。中间插入与前后转向、任务唯一性、资源、下传都由公共约束决定。

`DARTISParams` 严格校验：`priority_mode=llf|edf`（默认 llf）、`max_windows_per_task=8`、`max_positions_per_window=4`、`recompute_mode=full`、固定稳定平局规则。窗口上限先轮转覆盖卫星；位置受检数及截断累计到 `Schedule.metadata["dartis"]["stats"]`。metadata 不进入现有 `schedule_to_dict` 或 IPC；正式指标由 Controller 重新计算。所选初始模型记录于 RunConfig，但 DARTIS 自空计划构造，不消耗模型解。

内部单调预算预留返回余量；预算届满且未取消时返回最后合法计划。观察到 `context.is_cancelled()` 后抛出 `DARTISCancelled`，不把缓存计划正常返回。单次公共候选生成/约束调用无法即时抢占，外部超时仍由 Controller 裁决。

## 注册与系统边界

`eos_system/algorithm_registry.py` 显式登记 spec、参数模型、版本、构造函数及比较清单；现有 `/api/algorithms` 和 `/api/runs` 自动读取。未修改 Solver 签名、HTTP 路径、Worker IPC、SQLite 模式、公共核验器、前端或 Daemon。Worker 只产出 JSON 候选，Controller 负责独立来源/约束/物理核验与唯一正式事务。

## 实际验证与证据边界

- G1-A 专项 20/20 通过：A-1 至 A-4、动态重算、真实公共转向/资源/地面站检查、预算、取消、参数、标准序列化和输入不变。
- G2 专项隔离测试使用真实 TCP 回环 Uvicorn、`multiprocessing.spawn` Worker、Controller 与临时 SQLite：合成 3 任务候选经过公共来源及离散约束核验后，借**仅在测试服务进程注入**的 `UNIT_TEST_ONLY` 连续认证收据到达正式事务；这验证系统生命周期，**不证明真实场景物理认证**。运行中取消为 CANCELLED、无正式计划，Worker 异常为 FAILED、无正式计划。
- 只读母文件 `/mnt/f/EOS-Bench/output_s1/Sats1_M100_T7d_dist0.json` SHA-256 `b61f4de708894f0bc30b6e0614aafc2ac9340880306ed0617fdc50cf492d198a`；临时派生 1 星、30 任务、24 小时场景，DARTIS 经真实 HTTP/Worker 产出候选，生产预览核验因本环境缺 `orekit_jpype` 返回 `FAILED/PREVIEW_REJECTED/PHYSICS_UNAVAILABLE`，未生成正式计划或指标。母文件前后 SHA 一致。没有放宽物理门禁，也没有把预览当正式成绩。
- G2 专项 `tests/test_dartis_integration.py` **7/7 通过**（注册/严格参数、新进程无循环导入、合成正式事务、测试时钟预算返回、真实运行中取消、异常、只读母场景派生门禁）。合成正式例实际完成 3/3、TCR=1.0、TP=6.0、BD=0.5、TM=0.2777777778、Worker exit_code=0，正式 `plans` 表有一条；RT 是运行时波动值，不作为静态承诺。
- `python -m unittest discover -s tests -v` 实际执行 **589 项，2 失败、10 错误、9 跳过**。本地 `experiments/scenarios` 场景仍是 Git LFS pointer；需要完整 JSON 的现有历元/几何/场景目录测试因无法解析或场景不可用失败。本轮未替换这些文件，不能标记全量回归通过。G1-A 专项 20/20 与 G2 专项 7/7 单独通过；测试产物均在临时目录，不提交数据库或派生场景。

## 已知限制与下一步

当前复用 `enumerate_task_candidates`，其敏捷窗口时间网格会先完整构造。G1-A 对超过 1024 对齐位置的窗口跳过，并限制候选池与每位置下传探查；所以松弛度仅是受检集合上的近似值，可能漏解。惰性公共候选 helper、缓存和规模优化本轮未实施。真实正式非空物理认证仍需可信场景证据与可用 Orekit 运行环境；不能用测试收据替代。跨场景同预算成对实验与 EDF/LLF 消融统计留待后续实验阶段。

## G3 启动前同场景最小离线对照（2026-10-18）

只读母文件 `/mnt/f/EOS-Bench/output_s1/Sats1_M100_T7d_dist0.json`（SHA-256 `b61f4de708894f0bc30b6e0614aafc2ac9340880306ed0617fdc50cf492d198a`）用 `split_scenario_file(num_missions=30, start_offset="0h", duration="24h", seed=20260927)` 派生到 `TemporaryDirectory`，派生 JSON SHA-256 为 `c405f7f23a8c34cd4c76ac3ceac79b90dec75610fb45d671dec59df9115c2da9`；母文件前后 SHA 一致。五种变体共用该文件、`execution_mode=planning_preview`、`placement_mode=earliest`、默认 `ConstraintOptions` / `ObjectiveOptions`、`schedule_model=completion_first`、seed 42、请求算法预算 5 秒。只用现有 `RunConfig → runner.prepare() → runner.run_prepared()` 调用注册 Solver；每份候选以 `validate_plan_source`、`SourceWindowIndex.restore`、`candidate_exposure` 和 `ConstraintModel.is_feasible_assignment` 逐项独立回放，然后对回放计划调用公共 `compute_evaluation_metrics`。离线直调没有 Controller 的硬超时或正式提交事务。

| 变体 | 候选完成数 | 离线 TCR | 离线 TP | 离线 TM | 本次 Solver 秒数 | 来源与公共离散回放 |
|---|---:|---:|---:|---:|---:|---|
| DARTIS-LLF | 24/30 | 0.800 | 128 | 0.608835 | 0.696041 | PASS |
| DARTIS-EDF | 24/30 | 0.800 | 128 | 0.543262 | 0.470161 | PASS |
| Greedy（已登记 `completion_first`） | 24/30 | 0.800 | 128 | 0.620509 | 0.087091 | PASS |
| RABAS | 24/30 | 0.800 | 128 | 0.628293 | 0.548386 | PASS |
| CAABS | 0/30 | 0 | 0 | 1.000000 | 0.000409 | 空计划结构回放 PASS |

**四类结果必须分开：**以上仅是 Solver 候选和来源/公共离散约束回放；本组**没有调用** Orekit `planning_preview` 审计，故 preview 为 NOT_RUN（当前虚拟环境无 `orekit_jpype`）；正式连续认证也为 NOT_RUN。不可把离线指标填作 SQLite 正式成绩。CAABS 的候选构造器要求受信任 `planning_window`：该临时 legacy 派生场景 37/37 个窗口均为 `INCONCLUSIVE/UNTRUSTED_WINDOW_PROVENANCE`，CAABS `candidate_builder_calls=0`。其 0/30 反映输入来源门禁，**不能用于算法质量排名**；要做五算法有效成对比较，需团队提供各算法可共同接受的同版本、可信窗口来源场景。一次运行的 RT 不代表稳定性能。

本轮定向复跑 G1-A、G2、算法清单、Registry I1、RABAS 和 CAABS 专项共 **125 项，124 通过、1 项因小场景 LFS 实体缺失跳过**；无新增代码失败。前次完整回归 589 项的 LFS 环境问题尚未重新全量运行。
