# CAABS v0.1 — R1 独立代码审查与全量回归诊断

审查日期：2026-10-17（Asia/Shanghai）。本轮只读源码与诊断；没有修改算法、专项测试、公共模块、Registry 或既有文档，没有 commit、push、PR、reset、rebase 或 main 切换。仅新增本报告。

## 1. 审查结论

| 验收标签 | R1 结论 |
|---|---|
| **CORE REVIEW PASS** | **暂不无条件授予**。标准候选域下核心搜索、分支隔离、公共约束调用通过独立复核；但通用状态键存在确认的容器语义碰撞，需修复或明确收窄契约后再授予无保留 PASS。 |
| **REGRESSION INCOMPLETE** | **是**。当前与固定基线的完整 discover 均触发本轮240秒上限，且都观察到既有系统测试失败；不能以分组结果替代原始全量通过。 |
| **INTEGRATION NOT VERIFIED** | **是**。未登记 Registry、未跑正式算法系统闭环。未来 eager import 循环及来源窗口歧义有独立反例。 |

建议进入**带本报告和待修复项的 Draft 代码审查**，不建议直接合并或进入正式 Registry 登记。若流程要求提交审查前必须 CORE REVIEW PASS，应先完成 M1 的最小修复及反例测试。
本技术复核不替代未编写改动的组员正式 PR 审核。

## 2. Git、范围及基线可比性

- 当前 worktree：`D:\VC\EOS-Course-Project-caabs`。
- 分支：`feat/algorithm-c-caabs`。
- HEAD：`158b41402627d896fb810fbeebe2146d390e6db1`。
- 固定基线：`d0d9325759f078ef13f41cc9eee74c5e7733758a`。
- 开始时 git status --short 为空；指定 diff --check 退出0。
- 基线至 HEAD 恰有四个文件：COURSE_SETUP.md（修改）、algorithms/conflict_beam.py、tests/test_algorithm_conflict_beam.py、docs/phase2/algorithms/conflict_beam.md（新增）。
- 结束时 HEAD 不变；本报告是新增未跟踪文件，不计入上述三个提交。

| 完整 SHA | 提交 |
|---|---|
| fb173ee7da96bc981639e9c9cd3fbde7205945af | feat(caabs): add bounded candidate and beam state foundations |
| fece663efa155c165647f6d6474e2b3abb90b036 | feat(caabs): implement conflict-aware anytime beam search |
| 158b41402627d896fb810fbeebe2146d390e6db1 | test(caabs): cover beam correctness and document limitations |

必要的基线对照使用本轮新建的 detached worktree：
`D:\VC\EOS-Course-Project-caabs-r1-baseline-20261017`，HEAD 为固定基线。
未更新 main 或现有分支。为比较输入而将当前六份既有 LFS 输入逐字节复制到此临时 worktree，
没有下载或改写原输入。临时基线中六份 LFS 文件显示为物化后的工作区差异，**不宣称该临时 worktree 的 Git 状态完全干净**。
对240个基线跟踪路径逐文件 SHA-256 比较，当前与临时基线唯一字节差异是 COURSE_SETUP.md；
公共源码、既有测试和实际输入均相同。CAABS 三个新增文件只在当前分支存在。
这是同依赖、同参数、同公共测试的对照，不是用不同依赖环境回避失败。

两边均使用 `/home/meteor/eos-course-runtime/.venv/bin/python`，同一 WSL Ubuntu-22.04、
PYTHONHASHSEED=0、MPLBACKEND=Agg；没有安装或升级包。
| 环境项 | 实测值 |
|---|---|
| Python | 3.10.12 (main, Aug 31 2026, 10:18:17) [GCC 11.4.0] |
| anyio | 4.15.1 |
| httpx | not-installed |
| starlette | 1.7.0 |
| fastapi | 0.143.3 |
| pydantic | 2.14.1 |
| numpy | 2.2.6 |
| matplotlib | 3.10.9 |


## 3. 实际源码逐函数审查

实际入口仍是 `ConflictBeamScheduler.solve(self, problem: SchedulingProblem, constraints: ConstraintModel, context: SolveContext) -> Schedule`。
`CAABSParams` 继承当前 `AlgorithmParams`；`context.params`、`context.time_budget_s`、`context.is_cancelled()` 沿用真实契约。
算法仅返回 Schedule，不返回 Worker 状态或认证收据。

| 位置 | 复核结果 |
|---|---|
| conflict_beam.py:28–40，_noop / CAABSParams | 专属模型确为 AlgorithmParams 子类；strict整数/布尔、上下界、extra=forbid、frozen 配置相容。 |
| :43–80，_freeze / canonical_assignment_key / canonical_state_key | 遍历 Assignment 的全部真实 dataclass 字段；UTC微秒、None、bool/int、finite float.hex、字典排序正确；list与tuple合并有 M1 反例。 |
| :83–100，clone_schedule / branch_schedule | 每条既有 assignment、候选、metadata 深拷贝；不向父列表 append。单次 deepcopy 不可中断。 |
| :103–118，BeamState.search_key / rank_key | 搜索键包含游标；排序为完成数优先、公共目标分、完整计划键。frozen 不等于 Schedule 深层不可变。 |
| :121–126，_spread | limit=1取首项，超过配额均匀取索引；索引不会越界。它提供有限覆盖，不提供完整性。 |
| :129–148，_CandidateConstructor | 仅复制当前公共构造参数、加计数和检查点；实际检查调用 super()，未复制物理公式。 |
| :151–225，Adapter 初始化、_windows / _window_key / build | 按卫星分组、时域取样、轮询各星窗口；先 earliest 后 center；可信规划证据只读；存在设计性欠配额与重复构造。 |
| :229–270，SafeConflictIndex.from_schedule / rejects | 任务互斥与半开观测区间重叠是安全必要条件；prefix-max-end查询正确；无全候选二次图。 |
| :273–297，_SearchStopped / _SolveControl | 单调时钟，预留 min(0.05s,5%)；取消优先查询；停止是协作式。 |
| :300–355，构造、观察钩子、solve 内 state / remember | 构造不保存旧 context；评分与键成功后才完成状态；incumbent 深拷贝完成后才替换，旧值不被中断复制污染。 |
| :357–395，初始状态与 skip / assign 扩展 | 初始游标0；第i层两个分支都设游标i；每次 assign 先在原始 constraints、未插入的父计划上检查。 |
| :397–430，去重、rank、Top-B、退出 | 本层子状态先去重再排序/截断；remember早于剪枝；停止只返回已保存快照并附内部诊断，不写系统状态/回执。 |

### 3.1 搜索不变量及分支隔离

task_ids 固定排序；进入第i层时所有父状态游标为i-1，产生子状态游标i。skip表示永久跳过已处理任务，
不会在下一层重做；assign只处理本层任务。游标虽在同层相同，仍进入搜索键，避免跨层复用时错误合并。
候选的task_id来自公共构造器，本层正常生成路径不会重复同任务。

接受顺序是：预筛 → 原始公共模型检查 → 深拷贝并插入 → 公共目标评分/规范键 → 独立 incumbent →
去重 → 确定排序 → Top-B。未发现标准 JSON 候选域下跳过公共检查的插入、父子共享可变姿态或不正确覆盖已有 incumbent。
元数据与嵌套姿态的隔离既有测试可信；临时穷举进一步比较了20个四任务小问题，在同一有界候选域中，
宽度256、预筛开/关都与独立递归枚举所得最佳 rank 一致。它不是任意规模最优性证明。

特别界定：若第一次 accepted 插入的评分过程中恰好停止，尚未完成 remember，可能返回空快照。
临时反例记录 accepted_insertions=1、stop_phase=scoring、返回0任务。**这是“仅保存完成状态”的实现边界，
不是把已经保存的更好 incumbent 覆盖成更差计划**。现有 C-5 测试证明旧快照保留，并未证明每个刚通过公共检查的候选都立即持久成为 incumbent。
若要提高这一层 Anytime 承诺，需下一次单独设计安全提交点，不应在停止后无限补复制。

### 3.2 候选配额与公共语义

令 C=max_candidates_per_task，W=max_windows_per_task，K=min(C,W)。
选取卫星数≤K；各卫星窗口配额总和≤K，实际所选窗口数≤K；公共单窗口构造调用数≤2K，输出候选数≤C；
每父状态候选尝试≤min(branch_limit,候选数)，另加一个 skip。
未自行推算地面站、下传或姿态等物理字段；sensor、姿态切片、orbit、GB/W、通信组合全部由公共构造器填入。

这里没有调用会物化全部离散起点的 enumerate_task_candidates。实际模式为字面量 earliest/center，
非敏捷居中仍由公共构造器决定。没有改变输入 window 的规划证据或伪造生产证据。
测试中的 CAABS_UNIT_TEST_ONLY 只是既有合成 fixture 约定，不能当正式来源或连续证书。

欠配额不回填、无候选窗口不被穷举替换、branch_limit只看候选前缀、首个可行下传组合、v2边界可能拒绝构造位置，
都属于已说明的**有意设计限制**，不据此宣称漏解 Bug 或完整性保证。
Minor：无地面站的非敏捷单窗口，两模式生成完全相同结果，默认配额下仍调用两次再去重；
无 slack 的敏捷窗口也可重复。例中 builder_calls=2、generated_candidates=1。
最小后续改进是识别由公共语义可确定等价的模式并跳过第二次调用，不改物理规则。

### 3.3 公共模型与静态预筛

conflict_beam.py:388 使用传入的原始 constraints.is_feasible_assignment(candidate,parent.schedule)。
准备阶段的本地构造检查不能替代这一调用。C-2及独立反例使用真实公共模型，无 mock 可行性返回。

SafeConflictIndex 不处理 slew、累计资源、下传或地面站。直接观测重叠和同任务互斥确可静态拒绝；
端点相接仍交公共模型，可能因 slew 被拒绝。多候选两两可行但三者累计超限不会被索引错误放行，
实际插入仍执行完整公共判断。未发现当前合法区间输入下静态误剪枝反例。

### 3.4 最坏单次不可中断操作

窗口扫描与递归规范化有细粒度检查点，但以下操作必须完成或抛异常后才能再次轮询：

- 公共单候选构造：内部通信窗口扫描/排序；其可行性方法还扫描原任务全部来源窗口。单窗口适配不表示内部只处理常数个来源项。
- 公共约束一次调用、ObjectiveModel 初始化和 score；score即使某权重为0也按公共实现求各分量。
- 每条 assignment 的 deepcopy（含整段嵌套姿态）；metadata 的一次 deepcopy。
- Python 排序内部比较、规范键的深层 tuple 哈希及 dict 查重。
- 自定义观察钩子/取消回调本身的执行时间。

因此准备总体成本仍依赖输入窗口/通信窗口数，状态复制和键成本依赖计划长度及姿态大小。
返回余量是 best effort，不能改称硬实时；没有对最坏原生调用耗时的上界证明。

## 4. Findings：确认缺陷、风险、限制与无证据问题

没有确认 Critical 级缺陷。

### M1 — Major（通用状态键确认缺陷；当前生产候选可达性有限）

位置：algorithms/conflict_beam.py:64–65；关联 schedulers/transition_utils.py:81–105。

_freeze 把 list 和 tuple 都变成同一个 sequence 标记。但公共姿态解析器的**最外层**只将 list
解释为采样记录序列，外层 tuple 会得到 None。实际反例：前任务0–10秒、姿态0度，后任务30–40秒、姿态90度：

```python
b_list.sat_angles = [{"roll": 90.0, "pitch": 0.0, "yaw": 0.0}]
b_tuple = replace(b_list, sat_angles=tuple(b_list.sat_angles))
assert canonical_assignment_key(b_list) == canonical_assignment_key(b_tuple)
# 同一真实公共模型、同一父计划：
# b_list: delta_g=90，插入False
# b_tuple: delta_g=None，走公共回退，插入True
```

确认事实是**同键但公共模型语义不同**；不是推测的浮点误差。
标准 JSON loader 不产生 tuple，且固定来源窗口/位置的姿态确定，因此尚未展示当前生产候选生成路径实际生成这对冲突状态。
不能将其夸大成“当前 CAABS 已误接收真实计划”，但通用 canonical key 契约不成立。

最小修复建议：list和tuple分别带类型标签（或明确拒绝不受支持的容器），新增该反例及嵌套容器测试；
不修改公共 slew 公式。本轮未修复。

### I1 — Major 集成风险（条件触发已复现，当前未登记版本无此故障）

位置：conflict_beam.py:19、:32；algorithm_registry.py:22、:55、:106附近。

算法导入 registry 才能取得 AlgorithmParams。若未来 registry eager import 算法类/参数以构建 AlgorithmSpec，
会形成反向依赖。R1只在新进程内模拟向 registry 末尾附加 import，没有编辑真实 registry：
registry-first退出0；algorithm-first退出1，报 partially initialized module / cannot import CAABSParams。

因此“把import放在参数基类定义之后”仍不足以保证直接 import conflict_beam 的入口安全。
建议集成人员建立无环的参数/契约依赖层，或延迟登记及参数模型加载；两种导入顺序都须回归。
这是未来接入阻塞，不是当前 standalone solve 已有循环。

### I2 — Major 公共集成缺陷（既有来源重建歧义，有真实代码反例）

位置：schedulers/schedule_output.py:69–105 不输出 sat_window_id/gs_window_id；
eos_system/verification.py:66–74 选第一个时间/卫星/sensor匹配窗口，:93–97 再检查非敏捷中心；
CAABS相关位置：conflict_beam.py:185–222 的跨窗口覆盖、:388原模型检查。

使用独立合成 JSON fixture、真实 loader、真实公共模型和 verify_candidate，未 mock 来源或物理判断：
同一非敏捷任务时长10秒，来源窗口1为[0,100]，窗口2为[10,20]，目标权重选择更早观测。
CAABS实际选择 window_id=2、开始10秒，原公共模型接受。导出后 verifier 先命中窗口1，
要求其中心45秒，报“非敏捷卫星任务不在窗口中心：M”，尚未进入连续认证。

任何算法都可能触发该公共问题；CAABS主动覆盖较晚/较窄窗口使该条件可达，不能仅称为抽象格式风险。
尚未证明冻结真实六场景存在这种重叠来源，发生率未知。

最小公共修复建议由集成人员评审：导出并严格核验来源窗口ID，或在全部匹配窗口中按轨道、对齐、
中心和姿态来源一致性消歧，同时保持旧格式兼容。涉及 schedule_output.py/verification.py；
不得在CAABS内伪造窗口或复制一套核验规则。本轮未修改。

### Minor 与潜在风险

- 重复公共构造调用已在3.2列出：性能项，不违反条数/调用上限。
- 原 C-4 小反例对8/16宽度未产生饱和前沿；R1临时补充三层、每层三候选加skip，
  独立检查了实际饱和、排序和唯一键，见下表。建议移入下一轮正式测试。
- _observe_beam接收活的BeamState，其“只读”依赖调用约定；当前实现是no-op，现有测试自己复制快照。
  没有证据显示生产调用修改状态；不能把 frozen dataclass 当作深层不可变保障。
- 构造模型复制当前六项公共配置。未来 ConstraintModel 扩展配置时必须同步复核；
  原模型的最终插入检查仍在，当前无配置漂移反例。

没有证据的问题：当前合法区间上的索引误剪枝、父子姿态污染、已保存incumbent被更差状态覆盖、
CAABS测试遗留线程/patch/子进程。没有证据不等于对任意外部突变输入的数学证明。

## 5. C-1 至 C-6 独立复核

主命令无观察器注入，完全使用用户指定环境变量和 unittest 入口：

```bash
cd /mnt/d/VC/EOS-Course-Project-caabs
PYTHONHASHSEED=0 MPLBACKEND=Agg \
~/eos-course-runtime/.venv/bin/python -B -m unittest \
discover -s tests -p "test_algorithm_conflict_beam.py" -v
```

结果：42通过、0失败、0跳过，退出0；unittest计时0.607秒，子进程总耗时2.162秒。
另一次带faulthandler的同专项为42通过，unittest计时0.495秒。
这两次不是从上一轮报告抄录。

| 编号/源码 | 断言效力及边界 |
|---|---|
| C-1，tests:204–216 | 检查首层确有T1→S1和T1→S2两个计划，并比较完成1/2项；真实约束，确实证明多路径保留。 |
| C-2，:218–236 | 分别设置存储/功率2.5，三个候选各消耗1；空计划均接受、前两项接受、第三项拒绝；索引不拒第三项；没有mock约束。 |
| C-3，:238–243 | 单任务多窗口/多卫星最终只一次，并共享模型回放；覆盖实际唯一性。 |
| C-4，:245–259 | 原断言检查1/4/8/16上限、排序和重复运行一致性；R1加饱和前沿测试，补足8/16未满的覆盖。 |
| C-5，:261–282及StopTests:486起 | 可控时钟与回调；包装真实评分/键函数或在准备阶段设置停止；验证已有快照保留，不用短sleep。不能证明单次不可中断操作的硬时限。 |
| C-6，:284–296 | 开/关索引计划相同且都经过真实模型回放，搜索公共调用严格减少；只证明该确定重叠实例，非普适性能优势。 |

隔离/状态键/下传/slew/资源测试使用真实公共模型；准备、去重、时钟等个别测试有明确的候选列表或函数包装注入。
合成 planning_evidence 不构成正式物理证据；所有这些测试都不能证明 Controller 连续认证成功。

R1独立补充：
- 20个四任务小问题的同候选域穷举最优rank对照，预筛开/关共40次搜索均匹配。
- 饱和前沿结果（每层3候选+skip，三层）：
| beam_width | 三层实际宽度 | 剪枝状态数 |
|---|---|---|
| 1 | [1, 1, 1] | 9 |
| 4 | [4, 4, 4] | 24 |
| 8 | [4, 8, 8] | 32 |
| 16 | [4, 16, 16] | 48 |

- list/tuple、首子状态评分停止、来源窗口歧义反例保存在临时 probes.py/probes.json，未写入测试源码。

## 6. 全量清单、执行顺序与诊断方法

完整发现清单：当前388项，基线346项；删除当前清单中的42项 CAABS 测试后，
余下346项ID及顺序与基线**完全一致**。环境版本也一致。完整当前清单见附录A，
基线顺序就是附录删除 test_algorithm_conflict_beam.*；原始两份JSON也保留。

标准 loader 按模块/类/方法名排序；不是按上轮最后一个输出猜测顺序。模块区间如下：
| 模块（discover顺序） | 当前编号 | 数量 |
|---|---|---|
| test_adaptive_repair | 1–3 | 3 |
| test_algorithm_conflict_beam | 4–45 | 42 |
| test_certification_final_p1 | 46–85 | 40 |
| test_continuous_exposure | 86–100 | 15 |
| test_continuous_pipeline | 101–117 | 17 |
| test_controller_cancel | 118–131 | 14 |
| test_controller_shutdown | 132–144 | 13 |
| test_controller_timeouts | 145–165 | 21 |
| test_e3_e4_orekit | 166–168 | 3 |
| test_e3_e4_time_semantics | 169–185 | 17 |
| test_epoch_parsing | 186–208 | 23 |
| test_http_failure_e2e | 209–211 | 3 |
| test_integrated_replay | 212–217 | 6 |
| test_orbit_export_integration | 218–218 | 1 |
| test_orbit_interpolation | 219–225 | 7 |
| test_replay_backend | 226–227 | 2 |
| test_replay_contracts | 228–231 | 4 |
| test_replay_delivery | 232–232 | 1 |
| test_replay_timeline | 233–235 | 3 |
| test_satellite_asset | 236–237 | 2 |
| test_scenario_manifest | 238–284 | 47 |
| test_scenario_scale | 285–295 | 11 |
| test_system_storage | 296–299 | 4 |
| test_system_v02 | 300–306 | 7 |
| test_transition_model | 307–310 | 4 |
| test_window_recompute | 311–354 | 44 |
| test_worker_ipc | 355–373 | 19 |
| test_worker_process_group | 374–388 | 15 |


诊断目录：`/tmp/caabs-r1-0y7jucc6`，保留 monitor.py、sitecustomize.py、inventory.py、
observe.py、probes.py、registry_cycle.py、io_bench.py 以及每次运行的 command.json/output.log/
summary.json/processes.jsonl/stacks.<PID>.log。可通过 WSL 直接读取。
原始临时日志可能被系统日后清理；关键数据、反例和完整测试清单已收入本报告。

完整discover使用标准 `python -B -m unittest discover -s tests -v` 入口，
额外只读诊断注入为sitecustomize启用faulthandler每30秒输出线程栈，
以及外部进程监视器采样/proc状态。没有重排/修改测试。
每次硬上限240秒、连续45秒无测试进度上限；这两次实际均因**总时长**上限退出，
没有触发45秒无测试进度上限。注入可能影响紧张的时序断言，因此不能将任何单次时间差视为算法性能结论。

仅回收由本次 runner 启动并记录PID/starttime身份的后代；没用宽泛pkill，
没删除已有数据库、场景、缓存或未跟踪文件。超时刚结束时 resource_tracker 有短暂延迟退出，
复查原PID/starttime后都已消失，未对复用PID发信号。

### 6.1 有效运行结果

表中全量的通过/失败/跳过是**截至中断看到的条目**，没有完整 unittest 汇总；
不是剩余测试全部未失败的保证。240秒监视器退出码124，实际runner收到TERM为-15。
监视器自身退出0只表示证据写入完成，不等于测试通过。

| 证据目录/运行 | 总耗时(s) | unittest计时(s) | 通过 | 失败 | 跳过 | 退出码 |
|---|---:|---:|---:|---:|---:|---|
| plain_target | 2.162 | 0.607 | 42 | 0 | 0 | 0 |
| target_current | 2.515 | 0.495 | 42 | 0 | 0 | 0 |
| full_current | 240.250 | 未完成 | 130 | 1 | 1 | 124（hard_limit；进程-15） |
| full_baseline | 240.695 | 未完成 | 80 | 3 | 1 | 124（hard_limit；进程-15） |
| caabs_http_v2 | 8.545 | 4.968 | 43 | 0 | 0 | 0 |
| async_http_current_v2 | 15.084 | 11.759 | 2 | 0 | 0 | 0 |
| async_http_baseline_v2 | 17.608 | 14.934 | 1 | 1 | 0 | 1 |
| failures_current_v2 | 27.164 | 23.603 | 1 | 2 | 0 | 1 |
| failures_baseline_v2 | 26.162 | 21.974 | 0 | 3 | 0 | 1 |


作废/清单采集记录（不纳入测试结论）：

| 目录 | 总耗时(s) | 退出码 | 说明 |
|---|---:|---:|---|
| inventory_current | 5.049 | 1 | 可选依赖元数据查询失败，未执行测试 |
| inventory_baseline | 4.535 | 1 | 可选依赖元数据查询失败，未执行测试 |
| inventory_current_v2 | 4.525 | 0 | 清单采集成功，未执行测试 |
| inventory_baseline_v2 | 4.024 | 0 | 清单采集成功，未执行测试 |
| caabs_then_http | 13.576 | 1 | v1观察器spawn重入，作废 |
| prior_async_http_current | 19.109 | 1 | v1观察器spawn重入，作废 |
| prior_async_http_baseline | 21.148 | 1 | v1观察器spawn重入，作废 |
| failure_group_current | 23.689 | 1 | v1观察器spawn重入，作废 |
| failure_group_baseline | 24.172 | 1 | v1观察器spawn重入，作废 |


### 6.2 全量实际观察

当前 full_current：130条ok、1条skip、1条FAIL，240.250秒结束；
最后进入 controller_shutdown 的 test_cancel_before_delayed_started_never_sends_start。
观察到的失败为 test_blocked_verification_keeps_flock_until_thread_finishes。

基线 full_baseline：80条ok、1条skip、3条FAIL，240.695秒结束；
最后进入 test_real_spawn_controller_sends_cancel_and_records_ack。
观察到的失败是 continuous_pipeline 的 positive_unit_injection、
controller_cancel 的 candidate_and_cancel_race 及 normal_success_path。
这说明全量/系统测试失败和超时在 CAABS 提交之前的源代码上也会出现，
但不能据此证明 CAABS 对所有未执行测试绝无影响。

两边本次均越过了 HTTP取消测试；早先“180秒日志最后停在HTTP”只是当时预算截止位置，
不足以定位固定死锁。**本轮没有复现一个永久停在该HTTP测试的死锁。**

### 6.3 faulthandler、进程、线程和I/O证据

基线主进程PID46476在240秒快照为D（disk sleep），wchan=`p9_client_rpc`。
栈位于 certification_identity.py:114/158 的 read_bytes，经 trusted_context → Database.__init__ → fixture.setUp。
其他周期栈还出现 planning_evidence 的Path.stat，以及Database.connect和有限wait_status。
当前PID45749终止快照在 multiprocessing.Event.wait（test_controller_shutdown.py:417），Controller线程等待队列；
不是CAABS solve。子进程快照包含本轮resource_tracker，native线程多为futex等待。

source身份校验assert_code_current每次disk_sources会读取20个源码文件，Context.check还重新读数据文件。
同字节20文件、10轮read+SHA256局部测量：
- /mnt/d工作树：2.440679秒（200次读取）；
- Linux临时目录副本：0.002470秒；
- 该次测量约988倍差异。只是局部I/O测量，不是整套测试加速保证。

因此本轮确认的耗时机制包括：DrvFS/9p读取延迟、重复身份核验、真实spawn及系统等待；
它们叠加后使固定总预算耗尽，并可能击穿4/5秒测试等待。
本轮证据不支持“CAABS导致HTTP必现死锁”的判断。
仍不能把所有FAIL唯一归因于I/O：尚未在原生Linux工作树做整套同参数反事实实验，
观察器也可能扰动短时序，故保留 REGRESSION INCOMPLETE。

### 6.4 分组、共享状态与数据库锁

修正后的观察器有 __main__ 保护。CAABS42项随后运行HTTP取消，43/43通过。
公共历史导出检查后运行HTTP：当前2/2通过，基线1通过1失败；
基线失败为entered.wait(5)未满足，显示该处在未有CAABS时也有时序敏感性。

三个系统案例相同顺序在两根目录运行：
1. blocked_verification_keeps_flock_until_thread_finishes；
2. normal_success_path_still_commits_verified_plan；
3. positive_unit_injection_reaches_real_transaction_and_export。

当前1通过2失败；基线0通过3失败。共同失败点包括4秒entered等待、成功事务未调用/最终为FAILED。
不能把它们记作CAABS专项失败，也不能以其他分组通过覆盖这些真实回归失败。

每个有效v2分组结束观察点：仅MainThread，active_children=[]，active_patches=0，
time.monotonic恢复内建函数，认证invalidated标记为None，EOS测试环境变量已恢复。
没有发现CAABS遗留的Python线程、patch、子进程或环境变量。
这些快照不覆盖所有可能的第三方全局状态。

全量快照记录的数据库fd未持续持有；结束后的定向/proc/locks检查无本轮持有者，原后代身份复查无残留。
这只能支持“未发现持续遗留锁”，不能排除运行中短暂SQLite/WAL争用。
不删除临时以外的库，不以清库或放宽生命周期规则来使测试通过。

### 6.5 诊断有效性与作废记录

初版inventory因可选httpx未安装而元数据查询退出1，未执行测试；v2将其记为not-installed，清单采集成功。
初版observe缺少main保护，spawn时重入runner；对应五组v1日志**全部作废，不参与结论**。
修正只发生在临时诊断脚本，没有改任何仓库测试。
v2与标准-m unittest的运行结果单独列在表中；没有把工具错误归因到CAABS或公共模块。
本轮报告不把分组全部通过等同于原始全量通过；实际上v2分组也存在失败。

## 7. 后续最小修复与公共负责人事项

| 事项 | 建议负责人/下一步 |
|---|---|
| M1类型标签 | 刘懋兴：独立修复任务中区分list/tuple，加入相同键但不同公共可行性的反例；先不扩算法功能。 |
| I1导入依赖 | Registry/公共契约负责人和刘懋兴：设计无环参数/注册依赖，两个导入顺序与参数schema均回归，之后才登记。 |
| I2来源消歧 | 公共输出/verification负责人：评审来源ID携带和旧格式消歧，新增重叠窗口契约测试。 |
| 全量/系统时序 | 系统运行与测试负责人：在Linux原生文件系统做同代码/同输入/同依赖的完整对照，定位身份校验I/O和spawn期限；不能弱化正式认证或伪造SUCCEEDED。 |
| 测试补强 | 将R1饱和前沿、类型键和重叠来源反例纳入相应后续测试；保留系统失败的真实证据。 |

本轮没有确认新的公共卫星物理公式缺陷，没有改公共模型去迎合测试。
正式连续曝光认证未完成；合成规划可行、结构性空计划、正式已认证计划继续严格区分。

## 附录 A：完整当前测试清单及执行顺序

基线清单从以下顺序删除42个 test_algorithm_conflict_beam.* 即得，已逐ID比较一致。

```text
001 test_adaptive_repair.AdaptiveRepairTests.test_candidates_cover_separate_windows
002 test_adaptive_repair.AdaptiveRepairTests.test_chain_reinserts_displaced_task
003 test_adaptive_repair.AdaptiveRepairTests.test_factory_and_search_return_feasible_schedule
004 test_algorithm_conflict_beam.BoundaryTests.test_agile_slew_uses_real_shared_angle_model
005 test_algorithm_conflict_beam.BoundaryTests.test_branch_limit_bounds_real_alternatives
006 test_algorithm_conflict_beam.BoundaryTests.test_completion_count_precedes_public_profit
007 test_algorithm_conflict_beam.BoundaryTests.test_deduplication_removes_actual_duplicate_children
008 test_algorithm_conflict_beam.BoundaryTests.test_downlink_equality_rejected_and_strictly_later_accepted
009 test_algorithm_conflict_beam.BoundaryTests.test_exact_fit_downlink_has_no_strictly_later_solution
010 test_algorithm_conflict_beam.BoundaryTests.test_frozen_objective_weights_decide_equal_completion
011 test_algorithm_conflict_beam.BoundaryTests.test_ground_station_conflict_is_left_to_public_model
012 test_algorithm_conflict_beam.BoundaryTests.test_index_handles_nested_intervals_without_pair_graph
013 test_algorithm_conflict_beam.BoundaryTests.test_inputs_and_original_placement_configuration_unchanged
014 test_algorithm_conflict_beam.BoundaryTests.test_non_agile_slew_not_pruned_statically
015 test_algorithm_conflict_beam.BoundaryTests.test_normalized_utc_and_microsecond_keys
016 test_algorithm_conflict_beam.FoundationTests.test_agile_only_earliest_and_center
017 test_algorithm_conflict_beam.FoundationTests.test_candidate_coverage_balances_satellites_and_horizon
018 test_algorithm_conflict_beam.FoundationTests.test_constructor_call_bound_even_when_all_modes_fail
019 test_algorithm_conflict_beam.FoundationTests.test_key_distinguishes_all_assignment_fields
020 test_algorithm_conflict_beam.FoundationTests.test_key_order_and_metadata_independence
021 test_algorithm_conflict_beam.FoundationTests.test_no_windows_and_zero_duration
022 test_algorithm_conflict_beam.FoundationTests.test_non_agile_center_and_missing_evidence
023 test_algorithm_conflict_beam.FoundationTests.test_parameter_defaults_and_validation
024 test_algorithm_conflict_beam.FoundationTests.test_schedule_branch_deep_isolation
025 test_algorithm_conflict_beam.FoundationTests.test_v2_boundary_uses_shared_planning_semantics
026 test_algorithm_conflict_beam.SearchTests.test_C1_real_alternative_path_survives_and_improves
027 test_algorithm_conflict_beam.SearchTests.test_C2_true_cumulative_storage_and_power
028 test_algorithm_conflict_beam.SearchTests.test_C3_task_unique_with_multiple_satellites
029 test_algorithm_conflict_beam.SearchTests.test_C4_widths_and_stable_ranking
030 test_algorithm_conflict_beam.SearchTests.test_C5_budget_returns_incumbent_with_manual_clock
031 test_algorithm_conflict_beam.SearchTests.test_C5_cancel_uses_current_solve_context_and_keeps_incumbent
032 test_algorithm_conflict_beam.SearchTests.test_C6_prefilter_ablation_reduces_calls_without_changing_plan
033 test_algorithm_conflict_beam.SearchTests.test_empty_no_candidates_and_missing_evidence
034 test_algorithm_conflict_beam.SearchTests.test_every_insert_checks_untouched_parent
035 test_algorithm_conflict_beam.SearchTests.test_incumbent_and_beam_siblings_own_mutable_data
036 test_algorithm_conflict_beam.SearchTests.test_safe_index_only_proven_conflicts
037 test_algorithm_conflict_beam.SearchTests.test_seeded_determinism_and_serialization
038 test_algorithm_conflict_beam.StopTests.test_budget_reserve_stops_before_requested_budget
039 test_algorithm_conflict_beam.StopTests.test_cancellation_inside_preparation_is_polled
040 test_algorithm_conflict_beam.StopTests.test_invalid_budget_rejected_without_lifecycle_state
041 test_algorithm_conflict_beam.StopTests.test_stop_after_pruning_sort_keeps_incumbent
042 test_algorithm_conflict_beam.StopTests.test_stop_during_canonicalization_keeps_prior_snapshot
043 test_algorithm_conflict_beam.StopTests.test_stop_during_deduplication_keeps_incumbent
044 test_algorithm_conflict_beam.StopTests.test_stop_during_scoring_preserves_unpruned_incumbent
045 test_algorithm_conflict_beam.StopTests.test_stop_in_later_preparation_preserves_incumbent
046 test_certification_final_p1.CancellationTests.test_accepted_cancel_beats_certification_timeout
047 test_certification_final_p1.CancellationTests.test_accepted_cancel_beats_error
048 test_certification_final_p1.CancellationTests.test_accepted_cancel_beats_inconclusive
049 test_certification_final_p1.CancellationTests.test_accepted_cancel_beats_rejected
050 test_certification_final_p1.CancellationTests.test_cancel_terminal_rejects_late_success
051 test_certification_final_p1.CancellationTests.test_cancel_transaction_commits_before_failure_transaction
052 test_certification_final_p1.CancellationTests.test_failure_transaction_commits_before_cancel_transaction
053 test_certification_final_p1.CancellationTests.test_no_cancel_normal_failure_retained
054 test_certification_final_p1.CancellationTests.test_stop_and_search_timeout_priorities_preserved
055 test_certification_final_p1.DataIdentityTests.test_complete_context_matching_positive
056 test_certification_final_p1.DataIdentityTests.test_complete_empty_unit_plan_receipt_preserves_lifecycle_contract
057 test_certification_final_p1.DataIdentityTests.test_data_change_during_real_signing_path_rejected
058 test_certification_final_p1.DataIdentityTests.test_data_changed_after_freeze_not_silently_reaccepted
059 test_certification_final_p1.DataIdentityTests.test_detected_data_change_remains_revoked_after_restore
060 test_certification_final_p1.DataIdentityTests.test_legacy_receipt_never_certified
061 test_certification_final_p1.DataIdentityTests.test_malformed_sha_and_missing_schema_fields_rejected
062 test_certification_final_p1.DataIdentityTests.test_missing_orekit_sha_rejected
063 test_certification_final_p1.DataIdentityTests.test_scene_plan_version_and_dataset_combinations_rejected
064 test_certification_final_p1.DataIdentityTests.test_storage_read_source_oserror_hides_plan_not_http500
065 test_certification_final_p1.DataIdentityTests.test_storage_rejects_changed_dataset_receipt_atomically
066 test_certification_final_p1.DataIdentityTests.test_unreadable_data_fails_closed
067 test_certification_final_p1.DataIdentityTests.test_wrong_orekit_sha_rejected
068 test_certification_final_p1.DeadlineTests.test_already_queued_pass_retrieved_after_deadline_rejected
069 test_certification_final_p1.DeadlineTests.test_before_deadline_can_continue
070 test_certification_final_p1.DeadlineTests.test_expired_before_wait_does_not_read_ready_queue
071 test_certification_final_p1.DeadlineTests.test_expired_between_validation_and_success_transaction
072 test_certification_final_p1.DeadlineTests.test_expiry_during_credential_validation_rejected
073 test_certification_final_p1.DeadlineTests.test_expiry_inside_transaction_rolls_back_every_result_table
074 test_certification_final_p1.DeadlineTests.test_late_pass_cannot_replace_timeout_terminal
075 test_certification_final_p1.ProcessIdentityTests.test_context_from_other_generation_rejected
076 test_certification_final_p1.ProcessIdentityTests.test_disk_changed_during_certification_rejected
077 test_certification_final_p1.ProcessIdentityTests.test_initializing_module_compiled_A_disk_B_rejected
078 test_certification_final_p1.ProcessIdentityTests.test_loaded_A_then_disk_B_rejected_and_new_process_required
079 test_certification_final_p1.ProcessIdentityTests.test_module_loaded_A_before_bootstrap_disk_B_rejected
080 test_certification_final_p1.ProcessIdentityTests.test_new_deployment_new_process_old_receipt_invalid
081 test_certification_final_p1.ProcessIdentityTests.test_observed_source_change_stays_revoked_after_restore
082 test_certification_final_p1.ProcessIdentityTests.test_preloaded_transition_with_set_constants_matches_same_source
083 test_certification_final_p1.ProcessIdentityTests.test_process_deployment_and_disk_agree
084 test_certification_final_p1.ProcessIdentityTests.test_real_other_process_cannot_reuse_receipt
085 test_certification_final_p1.ProcessIdentityTests.test_source_unreadable_before_issuing_rejected
086 test_continuous_exposure.ExposureTests.test_all_visible_points_without_certificate_are_inconclusive
087 test_continuous_exposure.ExposureTests.test_bad_duration_times_and_one_us_short_rejected_publicly
088 test_continuous_exposure.ExposureTests.test_cache_is_bounded_and_does_not_alias_nearby_orbits_or_targets
089 test_continuous_exposure.ExposureTests.test_equivalent_utc_and_microseconds
090 test_continuous_exposure.ExposureTests.test_hidden_gap_is_not_falsely_certified
091 test_continuous_exposure.ExposureTests.test_horizon_is_evaluated_and_refined_without_extra_grid_samples
092 test_continuous_exposure.ExposureTests.test_json_cannot_claim_a_continuity_certificate
093 test_continuous_exposure.ExposureTests.test_legal_exposure_and_visible_safe_endpoint_public_pass
094 test_continuous_exposure.ExposureTests.test_missing_physics_and_evaluator_budget_are_not_pass
095 test_continuous_exposure.ExposureTests.test_refined_endpoint_grid_pose_is_not_exported
096 test_continuous_exposure.ExposureTests.test_refinement_rejects_unbracketed_inputs_and_terminates_at_one_us
097 test_continuous_exposure.ExposureTests.test_separate_windows_cannot_be_spanned
098 test_continuous_exposure.ExposureTests.test_steps_subsecond_exits_and_half_open_pose_slicing
099 test_continuous_exposure.ExposureTests.test_two_historical_overruns_rejected_by_public_gate
100 test_continuous_exposure.RealExposureTests.test_frozen_public_verifier_probes_against_rebuilt_orekit
101 test_continuous_pipeline.AdditionalEvidenceTests.test_ordinary_generation_records_precision_separately_from_certification
102 test_continuous_pipeline.AdditionalEvidenceTests.test_stale_completed_sidecar_cannot_fall_back_to_metadata
103 test_continuous_pipeline.FormalPipelineTests.test_controller_exception_never_persists_success
104 test_continuous_pipeline.FormalPipelineTests.test_controller_fail_never_persists_success
105 test_continuous_pipeline.FormalPipelineTests.test_controller_inconclusive_never_persists_success
106 test_continuous_pipeline.FormalPipelineTests.test_controller_timeout_and_late_pass_cannot_commit
107 test_continuous_pipeline.FormalPipelineTests.test_formal_verifier_keeps_missing_provenance_inconclusive
108 test_continuous_pipeline.FormalPipelineTests.test_historical_succeeded_storage_api_and_file_exports_fail_closed
109 test_continuous_pipeline.FormalPipelineTests.test_positive_unit_injection_reaches_real_transaction_and_export
110 test_continuous_pipeline.FormalPipelineTests.test_real_certifier_missing_evidence_is_not_a_pass
111 test_continuous_pipeline.FormalPipelineTests.test_storage_rejects_missing_forged_and_reused_receipt_atomically
112 test_continuous_pipeline.FormalPipelineTests.test_worker_forged_certification_ignored
113 test_continuous_pipeline.PlanningGateTests.test_both_known_old_acceptances_rejected_by_both_new_entries
114 test_continuous_pipeline.PlanningGateTests.test_crossing_discontinuous_windows_rejected
115 test_continuous_pipeline.PlanningGateTests.test_unknown_step_and_forged_or_stale_source_fail_closed
116 test_continuous_pipeline.PlanningGateTests.test_v2_threshold_comes_from_verified_lineage_not_embedded_claim
117 test_continuous_pipeline.PlanningGateTests.test_v3_budget_not_deducted_twice_and_exact_microsecond
118 test_controller_cancel.ControllerCancelTests.test_ack_does_not_finish_run_before_worker_exits
119 test_controller_cancel.ControllerCancelTests.test_cancel_during_real_spawn_candidate_verification_blocks_commit
120 test_controller_cancel.ControllerCancelTests.test_cancel_immediately_after_attempt_starts
121 test_controller_cancel.ControllerCancelTests.test_candidate_and_cancel_race_cannot_commit_success
122 test_controller_cancel.ControllerCancelTests.test_closed_event_pipe_does_not_wait_forever
123 test_controller_cancel.ControllerCancelTests.test_complete_cancel_envelope_and_duplicate_ack
124 test_controller_cancel.ControllerCancelTests.test_early_worker_exit_does_not_wait_forever
125 test_controller_cancel.ControllerCancelTests.test_http_cancel_uses_existing_route_and_temporary_database
126 test_controller_cancel.ControllerCancelTests.test_normal_success_path_still_commits_verified_plan
127 test_controller_cancel.ControllerCancelTests.test_real_spawn_controller_sends_cancel_and_records_ack
128 test_controller_cancel.ControllerCancelTests.test_repeated_cancel_produces_one_ack_and_one_terminal_event
129 test_controller_cancel.ControllerCancelTests.test_stale_attempt_ack_is_ignored
130 test_controller_cancel.ControllerCancelTests.test_unmodified_reference_worker_success_path
131 test_controller_cancel.ControllerCancelTests.test_worker_exit_without_ack_still_finishes_cancel
132 test_controller_shutdown.ControllerShutdownTests.test_blocked_verification_keeps_flock_until_thread_finishes
133 test_controller_shutdown.ControllerShutdownTests.test_cancel_before_delayed_started_never_sends_start
134 test_controller_shutdown.ControllerShutdownTests.test_cancel_before_setsid_uses_direct_reap_without_group_signal
135 test_controller_shutdown.ControllerShutdownTests.test_controller_recovers_child_after_immediate_leader_crash
136 test_controller_shutdown.ControllerShutdownTests.test_crashed_leader_leaves_no_verified_live_descendant
137 test_controller_shutdown.ControllerShutdownTests.test_fast_reference_worker_confirms_session_before_success
138 test_controller_shutdown.ControllerShutdownTests.test_startup_exception_releases_flock
139 test_controller_shutdown.ControllerShutdownTests.test_stop_active_worker_marks_internal_interruption_and_releases_lock
140 test_controller_shutdown.ControllerShutdownTests.test_stop_and_start_attempt_are_serialized
141 test_controller_shutdown.ControllerShutdownTests.test_stop_before_delayed_started_never_sends_start
142 test_controller_shutdown.ControllerShutdownTests.test_stop_cleans_verified_descendant
143 test_controller_shutdown.ControllerShutdownTests.test_thread_start_exception_releases_flock
144 test_controller_shutdown.ControllerShutdownTests.test_unconfirmed_session_cannot_commit_legal_candidate
145 test_controller_timeouts.ControllerTimeoutTests.test_candidate_exit_timeout_reaps_worker
146 test_controller_timeouts.ControllerTimeoutTests.test_candidate_followed_by_crash_cannot_commit
147 test_controller_timeouts.ControllerTimeoutTests.test_crash_cannot_be_mistaken_for_success
148 test_controller_timeouts.ControllerTimeoutTests.test_failed_event_wins_over_zero_exit_code
149 test_controller_timeouts.ControllerTimeoutTests.test_ignored_sigterm_falls_back_to_kill
150 test_controller_timeouts.ControllerTimeoutTests.test_malformed_json_and_invalid_fields_are_protocol_errors
151 test_controller_timeouts.ControllerTimeoutTests.test_new_sequence_candidate_cannot_extend_exit_deadline
152 test_controller_timeouts.ControllerTimeoutTests.test_oversized_frame_rejected_before_body
153 test_controller_timeouts.ControllerTimeoutTests.test_partial_event_frame_closed_early_is_interrupted
154 test_controller_timeouts.ControllerTimeoutTests.test_partial_event_frame_has_transfer_deadline
155 test_controller_timeouts.ControllerTimeoutTests.test_persisted_user_cancel_precedes_search_timeout
156 test_controller_timeouts.ControllerTimeoutTests.test_pipe_descriptors_close_after_worker_failure
157 test_controller_timeouts.ControllerTimeoutTests.test_real_blocked_control_send_has_deadline
158 test_controller_timeouts.ControllerTimeoutTests.test_real_reference_worker_success_records_zero_exit
159 test_controller_timeouts.ControllerTimeoutTests.test_repeated_searching_does_not_extend_wall_deadline
160 test_controller_timeouts.ControllerTimeoutTests.test_same_sequence_candidate_remains_deduplicated
161 test_controller_timeouts.ControllerTimeoutTests.test_search_wall_timeout_reaps_uncooperative_worker
162 test_controller_timeouts.ControllerTimeoutTests.test_startup_prepare_timeout_is_failed_not_algorithm_timeout
163 test_controller_timeouts.ControllerTimeoutTests.test_timeout_reason_does_not_change_after_late_cancel
164 test_controller_timeouts.ControllerTimeoutTests.test_user_cancel_stays_bounded_while_start_send_is_blocked
165 test_controller_timeouts.ControllerTimeoutTests.test_zero_length_send_bytes_is_protocol_error
166 test_e3_e4_orekit.E3E4OrekitTests.test_all_fractional_czml_knots_and_duration_endpoints
167 test_e3_e4_orekit.E3E4OrekitTests.test_fixed_eme2000_itrf_pv_and_aware_utc
168 test_e3_e4_orekit.E3E4OrekitTests.test_gpm_boundaries_all_samples_and_recompute_serialization
169 test_e3_e4_time_semantics.ClosedOrbitSamplingTests.test_all_requested_durations
170 test_e3_e4_time_semantics.ClosedOrbitSamplingTests.test_fractional_start_and_step_include_exact_end_once
171 test_e3_e4_time_semantics.ClosedOrbitSamplingTests.test_invalid_steps_and_reversed_interval_fail
172 test_e3_e4_time_semantics.CzmlPrecisionTests.test_cache_identity_changes_without_version_or_contract_change
173 test_e3_e4_time_semantics.CzmlPrecisionTests.test_demo_keeps_fractional_scene_and_orbit_epoch
174 test_e3_e4_time_semantics.CzmlPrecisionTests.test_empty_samples_rejected
175 test_e3_e4_time_semantics.CzmlPrecisionTests.test_equivalent_utc_forms_preserve_absolute_time
176 test_e3_e4_time_semantics.CzmlPrecisionTests.test_fractional_clock_availability_epoch_and_offsets
177 test_e3_e4_time_semantics.CzmlPrecisionTests.test_invalid_sample_time_rejected_before_writing
178 test_e3_e4_time_semantics.CzmlPrecisionTests.test_mixed_aware_naive_normalized_at_boundary
179 test_e3_e4_time_semantics.CzmlPrecisionTests.test_negative_offset_not_relabelled
180 test_e3_e4_time_semantics.VisibilityGridTests.test_endpoint_attitude_cannot_leak_into_half_open_window
181 test_e3_e4_time_semantics.VisibilityGridTests.test_inner_fragments_and_attitudes_match_half_open_windows
182 test_e3_e4_time_semantics.VisibilityGridTests.test_offset_and_naive_grid_inputs_mean_utc
183 test_e3_e4_time_semantics.VisibilityGridTests.test_short_pass_between_invisible_coarse_points_is_found
184 test_e3_e4_time_semantics.VisibilityGridTests.test_substep_hidden_window_limitation_is_explicit
185 test_e3_e4_time_semantics.VisibilityGridTests.test_zero_window_and_horizon_clip
186 test_epoch_parsing.EpochParsingTests.test_all_english_months
187 test_epoch_parsing.EpochParsingTests.test_datetime_aware
188 test_epoch_parsing.EpochParsingTests.test_datetime_naive
189 test_epoch_parsing.EpochParsingTests.test_empty
190 test_epoch_parsing.EpochParsingTests.test_english_month
191 test_epoch_parsing.EpochParsingTests.test_equivalent_formats
192 test_epoch_parsing.EpochParsingTests.test_error_context
193 test_epoch_parsing.EpochParsingTests.test_fractional_seconds
194 test_epoch_parsing.EpochParsingTests.test_generator_prevalidation_before_pool_without_importing_generator
195 test_epoch_parsing.EpochParsingTests.test_invalid_dates
196 test_epoch_parsing.EpochParsingTests.test_invalid_types_and_numbers
197 test_epoch_parsing.EpochParsingTests.test_iso
198 test_epoch_parsing.EpochParsingTests.test_leap_day
199 test_epoch_parsing.EpochParsingTests.test_legacy_formats
200 test_epoch_parsing.EpochParsingTests.test_naive_string_means_utc
201 test_epoch_parsing.EpochParsingTests.test_negative_offset
202 test_epoch_parsing.EpochParsingTests.test_no_locale_dependency
203 test_epoch_parsing.EpochParsingTests.test_no_wall_clock_dependency
204 test_epoch_parsing.EpochParsingTests.test_numeric_unix_seconds
205 test_epoch_parsing.EpochParsingTests.test_positive_offset
206 test_epoch_parsing.EpochParsingTests.test_unsupported_month
207 test_epoch_parsing.EpochParsingTests.test_visibility_entry_point_without_jvm
208 test_epoch_parsing.EpochParsingTests.test_z
209 test_http_failure_e2e.HttpFailureE2ETests.test_real_http_crash_reaps_trusted_descendant
210 test_http_failure_e2e.HttpFailureE2ETests.test_real_http_running_cancel_reaps_worker_without_plan
211 test_http_failure_e2e.HttpFailureE2ETests.test_real_http_search_timeout_reaps_slow_solver
212 test_integrated_replay.IntegratedReplayTests.test_committed_plan_to_published_samples_and_compatibility
213 test_integrated_replay.IntegratedReplayTests.test_interrupted_build_blocks_deletion_until_recovery
214 test_integrated_replay.IntegratedReplayTests.test_manifest_samples_reject_nan_and_missing_coverage
215 test_integrated_replay.IntegratedReplayTests.test_timeout_failure_retry_and_resource_corruption_leave_run_intact
216 test_integrated_replay.ProvenanceTests.test_candidate_not_promoted_by_directory_registration
217 test_integrated_replay.ProvenanceTests.test_source_snapshot_unknown_or_verified_never_fabricated
218 test_orbit_export_integration.OrbitExportIntegrationTests.test_equivalent_orbit_and_scene_offsets_export_identical_czml
219 test_orbit_interpolation.OrbitInterpolationTests.test_curved_midpoints_and_off_grid_queries
220 test_orbit_interpolation.OrbitInterpolationTests.test_czml_declares_position_interpolation_without_changing_time
221 test_orbit_interpolation.OrbitInterpolationTests.test_exact_knots_and_fractional_endpoint_are_preserved
222 test_orbit_interpolation.OrbitInterpolationTests.test_existing_budgets_not_relaxed
223 test_orbit_interpolation.OrbitInterpolationTests.test_single_and_two_point_legacy_inputs
224 test_orbit_interpolation.OrekitInterpolationTests.test_300s_nodes_and_dense_off_grid_vs_direct_orekit
225 test_orbit_interpolation.OrekitInterpolationTests.test_ready_backend_and_node_consumer_at_5_20_135_seconds
226 test_replay_backend.ReplayBackendTests.test_http_build_reuse_resources_and_delete
227 test_replay_backend.ReplayBackendTests.test_v2_database_adds_replay_table_without_rewriting_runs
228 test_replay_contracts.ReplayContractTests.test_load_is_byte_preserving_and_links_original_ids
229 test_replay_contracts.ReplayContractTests.test_manifest_has_source_hashes_and_no_absolute_paths
230 test_replay_contracts.ReplayContractTests.test_missing_timezone_is_diagnostic_not_repaired
231 test_replay_contracts.ReplayContractTests.test_output_must_not_overlap_any_source
232 test_replay_delivery.ReplayDeliveryTests.test_successful_run_replay_is_repeatable_read_only_and_complete
233 test_replay_timeline.TimelineTests.test_insufficient_gap_is_diagnostic_and_never_moves_observation
234 test_replay_timeline.TimelineTests.test_phase_is_half_open_and_order_independent
235 test_replay_timeline.TimelineTests.test_plural_angles_use_current_legacy_model_and_endpoints_stay_exact
236 test_satellite_asset.SatelliteAssetTests.test_display_mapping_does_not_claim_source_satellite_identity
237 test_satellite_asset.SatelliteAssetTests.test_landsat_glb_matches_manifest_and_has_no_animation
238 test_scenario_manifest.ManifestTests.test_change_between_passes_even_if_same_size
239 test_scenario_manifest.ManifestTests.test_cli_exit_status_and_required_arguments
240 test_scenario_manifest.ManifestTests.test_detect_change_during_read
241 test_scenario_manifest.ManifestTests.test_duplicate_content
242 test_scenario_manifest.ManifestTests.test_duplicate_entity_ids_and_json_keys
243 test_scenario_manifest.ManifestTests.test_empty_directory_is_not_success
244 test_scenario_manifest.ManifestTests.test_endpoint_and_step_override
245 test_scenario_manifest.ManifestTests.test_existing_reports_never_overwritten
246 test_scenario_manifest.ManifestTests.test_explicit_registry_collision_fails_both
247 test_scenario_manifest.ManifestTests.test_failed_file_only_in_validation_report
248 test_scenario_manifest.ManifestTests.test_file_symlink_to_protected_path_not_opened
249 test_scenario_manifest.ManifestTests.test_inconsistent_angle_lengths
250 test_scenario_manifest.ManifestTests.test_invalid_internal_id_and_negative_resource
251 test_scenario_manifest.ManifestTests.test_invalid_intervals
252 test_scenario_manifest.ManifestTests.test_invalid_json
253 test_scenario_manifest.ManifestTests.test_io_failure_mid_read
254 test_scenario_manifest.ManifestTests.test_io_failure_missing_file_and_nonregular
255 test_scenario_manifest.ManifestTests.test_legacy_angle_arrays_and_window_level_fallback
256 test_scenario_manifest.ManifestTests.test_malformed_structures
257 test_scenario_manifest.ManifestTests.test_missing_attitude_fields
258 test_scenario_manifest.ManifestTests.test_missing_metadata_fails
259 test_scenario_manifest.ManifestTests.test_missing_mission_reference
260 test_scenario_manifest.ManifestTests.test_missing_provenance_is_not_invented
261 test_scenario_manifest.ManifestTests.test_missing_satellite_reference
262 test_scenario_manifest.ManifestTests.test_multiple_windows_one_mission_not_multiple_completions
263 test_scenario_manifest.ManifestTests.test_no_windows
264 test_scenario_manifest.ManifestTests.test_nonfinite_values
265 test_scenario_manifest.ManifestTests.test_normal_scene
266 test_scenario_manifest.ManifestTests.test_numeric_and_duration_rules
267 test_scenario_manifest.ManifestTests.test_optional_missing_fields_warn_not_fail
268 test_scenario_manifest.ManifestTests.test_outer_and_inner_counts
269 test_scenario_manifest.ManifestTests.test_output_equals_input_or_overlaps
270 test_scenario_manifest.ManifestTests.test_output_isolation_and_csv_parity
271 test_scenario_manifest.ManifestTests.test_partial_attitude
272 test_scenario_manifest.ManifestTests.test_protected_roots_rejected_before_discovery
273 test_scenario_manifest.ManifestTests.test_readonly_input_and_no_mutation
274 test_scenario_manifest.ManifestTests.test_rename_does_not_change_registry_id
275 test_scenario_manifest.ManifestTests.test_same_filename_different_content
276 test_scenario_manifest.ManifestTests.test_same_internal_id_different_scale
277 test_scenario_manifest.ManifestTests.test_sensor_and_station_references
278 test_scenario_manifest.ManifestTests.test_sha_stability_and_complete_bytes
279 test_scenario_manifest.ManifestTests.test_small_fallback_limit_without_large_fixture
280 test_scenario_manifest.ManifestTests.test_stream_and_fallback_parity_arbitrary_key_order
281 test_scenario_manifest.ManifestTests.test_symlink_protected_directory_and_report
282 test_scenario_manifest.ManifestTests.test_timezone_matches_loader
283 test_scenario_manifest.ManifestTests.test_trailing_json_rejected_both_parsers
284 test_scenario_manifest.ManifestTests.test_unknown_numeric_overflow_and_malformed_attitude
285 test_scenario_scale.CatalogTests.test_catalog_lists_all_six_real_files_without_reading_window_objects
286 test_scenario_scale.CatalogTests.test_http_submission_rechecks_sha_even_after_cached_listing
287 test_scenario_scale.CatalogTests.test_list_explains_missing_pointer_and_corruption
288 test_scenario_scale.CatalogTests.test_overlapping_output_is_never_registered_as_input
289 test_scenario_scale.CatalogTests.test_registration_is_idempotent_and_reuses_manual_root
290 test_scenario_scale.SamplingScaleTests.test_coarser_grid_still_keeps_short_task_and_slew_endpoints
291 test_scenario_scale.SamplingScaleTests.test_real_scale_profiles_fit_budget
292 test_scenario_scale.SamplingScaleTests.test_small_case_keeps_five_seconds_and_impossible_case_refuses
293 test_scenario_scale.SceneProjectionTests.test_missing_ijson_only_allows_bounded_fallback
294 test_scenario_scale.SceneProjectionTests.test_rejects_duplicate_root_fields_and_invalid_root
295 test_scenario_scale.SceneProjectionTests.test_static_fields_are_exact_and_windows_not_materialized
296 test_system_storage.StorageTransactionTests.test_cancel_during_verification_blocks_success
297 test_system_storage.StorageTransactionTests.test_failed_metric_rolls_back_plan_and_assignments
298 test_system_storage.StorageTransactionTests.test_queued_cancel_never_starts_worker
299 test_system_storage.StorageTransactionTests.test_repeated_worker_sequence_is_ignored
300 test_system_v02.CatalogTests.test_scenario_registration_stays_inside_selected_directory
301 test_system_v02.DeleteApiTests.test_changed_export_file_is_preserved
302 test_system_v02.DeleteApiTests.test_only_terminal_run_can_be_deleted_and_database_compacts
303 test_system_v02.MigrationAndExportTests.test_successful_plan_is_saved_under_its_run_id
304 test_system_v02.MigrationAndExportTests.test_v1_database_is_migrated_without_dropping_runs
305 test_system_v02.RegistryTests.test_custom_algorithm_can_define_its_own_nested_parameters
306 test_system_v02.ReplayTests.test_cached_orbit_survives_missing_original_scenario
307 test_transition_model.TransitionModelTests.test_existing_angle_shape_remains_supported
308 test_transition_model.TransitionModelTests.test_non_agile_transition_setting_is_stored
309 test_transition_model.TransitionModelTests.test_plural_angle_fields_use_last_then_first_sample
310 test_transition_model.TransitionModelTests.test_profile_is_stored_and_changes_transition_time
311 test_window_recompute.OrekitEpochIntegrationTests.test_equivalent_epochs_pv_windows_attitudes_and_small_bundle
312 test_window_recompute.RecomputeTests.test_atomic_no_replace_race_preserves_competing_file
313 test_window_recompute.RecomputeTests.test_broken_output_symlink_rejected
314 test_window_recompute.RecomputeTests.test_calculation_exception_no_publication
315 test_window_recompute.RecomputeTests.test_calculator_replaced_missions_rejected
316 test_window_recompute.RecomputeTests.test_calculator_static_mutation_fails_with_field_diff
317 test_window_recompute.RecomputeTests.test_communication_without_station_rejected
318 test_window_recompute.RecomputeTests.test_completion_is_not_physics_or_scheduling_acceptance
319 test_window_recompute.RecomputeTests.test_completion_timestamp_created_after_scenario_hash_verification
320 test_window_recompute.RecomputeTests.test_custom_sensor_is_rejected_without_renaming
321 test_window_recompute.RecomputeTests.test_deterministic_candidate_bytes_and_static_hash
322 test_window_recompute.RecomputeTests.test_duplicate_json_keys_rejected
323 test_window_recompute.RecomputeTests.test_existing_output_never_overwritten
324 test_window_recompute.RecomputeTests.test_existing_scanning_settings_forwarded
325 test_window_recompute.RecomputeTests.test_existing_sidecar_never_overwritten
326 test_window_recompute.RecomputeTests.test_frozen_sha_mismatch_rejected
327 test_window_recompute.RecomputeTests.test_ground_stations_preserved_communication_recomputed
328 test_window_recompute.RecomputeTests.test_hashes_and_source_provenance_computed_from_bytes
329 test_window_recompute.RecomputeTests.test_independent_output_directory_required
330 test_window_recompute.RecomputeTests.test_invalid_epoch_fails_before_calculator
331 test_window_recompute.RecomputeTests.test_invalid_recomputed_reference_rejected
332 test_window_recompute.RecomputeTests.test_missing_attitudes_rejected
333 test_window_recompute.RecomputeTests.test_missing_ground_stations_no_fabricated_communication
334 test_window_recompute.RecomputeTests.test_missing_orbit_number_rejected
335 test_window_recompute.RecomputeTests.test_missing_required_orbit_field_rejected_without_defaults
336 test_window_recompute.RecomputeTests.test_multi_sensor_is_rejected_before_calculation
337 test_window_recompute.RecomputeTests.test_multiple_windows_and_attitudes_replaced
338 test_window_recompute.RecomputeTests.test_no_resampling_or_generator_import
339 test_window_recompute.RecomputeTests.test_out_of_range_coordinates_rejected
340 test_window_recompute.RecomputeTests.test_output_cannot_equal_input
341 test_window_recompute.RecomputeTests.test_output_name_must_distinguish_physics
342 test_window_recompute.RecomputeTests.test_projection_preserves_configs_no_defaults
343 test_window_recompute.RecomputeTests.test_protected_paths_rejected_before_open
344 test_window_recompute.RecomputeTests.test_readonly_input_byte_and_metadata_unchanged
345 test_window_recompute.RecomputeTests.test_second_publish_failure_rolls_back_owned_scene
346 test_window_recompute.RecomputeTests.test_sensor_resources_coordinates_priority_duration_preserved
347 test_window_recompute.RecomputeTests.test_sidecar_staging_failure_removes_published_candidate
348 test_window_recompute.RecomputeTests.test_size_limit
349 test_window_recompute.RecomputeTests.test_source_changed_during_calculation_rejected
350 test_window_recompute.RecomputeTests.test_static_diff_function_includes_unknown_fields
351 test_window_recompute.RecomputeTests.test_static_fields_including_unknown_fields_identical
352 test_window_recompute.RecomputeTests.test_uncommitted_tool_does_not_claim_base_commit_as_tool_version
353 test_window_recompute.RecomputeTests.test_unknown_scanning_override_rejected
354 test_window_recompute.RecomputeTests.test_zero_window_task_preserved_and_denominator_correct
355 test_worker_ipc.WorkerIpcTests.test_cancel_is_visible_during_solve_and_candidate_is_suppressed
356 test_worker_ipc.WorkerIpcTests.test_control_eof_after_start_reports_failure_and_exits
357 test_worker_ipc.WorkerIpcTests.test_full_start_envelope_is_accepted
358 test_worker_ipc.WorkerIpcTests.test_legacy_adapter_still_uses_engine_contract
359 test_worker_ipc.WorkerIpcTests.test_legacy_start_normal_exit_and_event_sequence
360 test_worker_ipc.WorkerIpcTests.test_malformed_json_and_required_fields_are_rejected
361 test_worker_ipc.WorkerIpcTests.test_real_spawn_closed_event_pipe_exits_without_lingering_process
362 test_worker_ipc.WorkerIpcTests.test_real_spawn_control_eof_exits_without_lingering_process
363 test_worker_ipc.WorkerIpcTests.test_real_spawn_cooperative_cancel_observed_without_candidate
364 test_worker_ipc.WorkerIpcTests.test_real_spawn_rejects_bad_start_and_exits
365 test_worker_ipc.WorkerIpcTests.test_real_spawn_runs_empty_test_scenario
366 test_worker_ipc.WorkerIpcTests.test_real_spawn_solver_exception_exits_without_lingering_process
367 test_worker_ipc.WorkerIpcTests.test_real_spawn_uncooperative_cancel_has_bounded_worker_exit
368 test_worker_ipc.WorkerIpcTests.test_repeated_cancel_has_only_one_ack
369 test_worker_ipc.WorkerIpcTests.test_solver_cancel_exception_does_not_become_failure
370 test_worker_ipc.WorkerIpcTests.test_solver_exception_reports_failure
371 test_worker_ipc.WorkerIpcTests.test_wrong_cancel_identity_reports_failure
372 test_worker_ipc.WorkerIpcTests.test_wrong_cancel_version_is_rejected
373 test_worker_ipc.WorkerIpcTests.test_wrong_version_and_identity_are_rejected
374 test_worker_process_group.WorkerIdentityTests.test_before_setsid_has_no_group_signal
375 test_worker_process_group.WorkerIdentityTests.test_cancel_before_setsid_uses_direct_process_fallback
376 test_worker_process_group.WorkerIdentityTests.test_child_exits_between_scan_and_pidfd_open
377 test_worker_process_group.WorkerIdentityTests.test_child_ignores_term_then_receives_verified_kill
378 test_worker_process_group.WorkerIdentityTests.test_controller_group_number_is_never_signalled
379 test_worker_process_group.WorkerIdentityTests.test_crashed_leader_discovers_unseen_child_after_reap
380 test_worker_process_group.WorkerIdentityTests.test_guard_close_releases_pidfd
381 test_worker_process_group.WorkerIdentityTests.test_identity_failure_downgrades_to_direct_reap
382 test_worker_process_group.WorkerIdentityTests.test_leader_exit_still_allows_pinned_child_recovery
383 test_worker_process_group.WorkerIdentityTests.test_live_unpinned_child_risk_clears_after_confirmed_exit
384 test_worker_process_group.WorkerIdentityTests.test_missing_boot_id_downgrades_without_group_signal
385 test_worker_process_group.WorkerIdentityTests.test_real_setsid_is_bound_to_process_identity
386 test_worker_process_group.WorkerIdentityTests.test_reap_real_isolated_worker
387 test_worker_process_group.WorkerIdentityTests.test_stat_parser_accepts_comm_with_parentheses_and_spaces
388 test_worker_process_group.WorkerIdentityTests.test_wrong_starttime_rejects_group_signal
```



## 附录 B：R1.1 M1 修复复验（2026-10-17）

本附录追加于 R1 原报告之后；上文审查时点、结论、388项清单及失败/超时记录均为历史原文，
没有将未修复时的状态改写为通过。本轮只处理 M1 与专项补测，不是 CAABS v0.2。

- 修复前 HEAD：`158b41402627d896fb810fbeebe2146d390e6db1`。
- 修复提交：`ce833caee606e3d366026ec0c44b2b4a2719505a`。
- 分支/worktree：`feat/algorithm-c-caabs` / `D:\VC\EOS-Course-Project-caabs`。
- 实际代码：`algorithms/conflict_beam.py:64–67` 分别编码 list、tuple，递归保留嵌套类型和顺序。
  dict、UTC微秒、float.hex()、非有限值拒绝及其他标量不变，未修改公共结构/物理规则。
- 专项由42增至48项；原R1附录A保留原时点清单，不当作R1.1的全量执行证明。

### M1 证据与测试强度

先加入新测试，在旧代码上运行完整专项：48项，44个测试方法通过、4个方法失败；
unittest 汇总 failures=6（其中嵌套容器测试含3个失败子测试），errors=0、skipped=0、退出1，
unittest 1.447秒、子进程总2.501秒。未切换或修改旧历史。

`test_M1_container_types_with_real_slew_constraints` 先调用真实
`ConstraintModel.is_feasible_assignment`：同星前任务0–10秒、后任务30–40秒，
姿态0→90度；后任务外层list被拒，tuple按现有公共解析回退被接受。
两者除容器类型外字段相同；父计划未污染。旧代码随后在不同键断言处失败；
修复后 assignment key、完整状态键均不同，测试通过。

`test_M1_dedup_keeps_container_semantics` 仅注入候选准备列表，不mock公共可行性：
单任务list/tuple各一份、额外一个相同list副本。旧代码只保留2个状态；
修复后真实Beam保留skip与两类候选共3个状态，唯一键3个，重复副本只去重1次。
另加容器空/非空及嵌套类型、元素顺序、稳定性、dict重排、标量及非有限浮点测试。
原Assignment所有字段区分及naive/aware UTC、微秒测试均继续通过。

### C-4 饱和前沿

三层、每层3候选+skip，使用真实公共模型；宽度1/4/8/16的实际前沿依次为
[1,1,1] / [4,4,4] / [4,8,8] / [4,16,16]。两轮结果一致。
逐层验证游标、唯一搜索键、确定性rank排序、Top-B上限与剪枝统计；返回3任务均通过公共模型回放。
未改排名算法、候选策略或默认参数。

### Windows / WSL 结果

实际命令、两种计时及完整分项见 [算法文档 R1.1](conflict_beam.md) 的 R1.1 节。
Windows Python3.13.5专项48/48（unittest 1.212秒，总2.151秒），WSL现有Python3.10.12专项48/48
（unittest 0.809秒，总2.457秒），均0失败、0跳过、退出0。
两环境各运行70项：69通过、0失败、1个可选Orekit跳过，全部命令退出0。
公共过渡4/4、曝光门禁14通过1跳过、adaptive_repair 3/3。
真实约束、资源和下传测试未被mock通过。没有执行正式连续认证。

日志：Windows `%TEMP%\caabs-r11-4eg4_ato`，WSL `/tmp/caabs-r11-44gb4hqj`。
代码提交前 `git diff --check` 与 `git diff --cached --check` 均退出0。
文档提交包含原R1报告和本附录；不登记算法、不改公共模块、不push、不创建PR、不合并。

| 状态 | R1.1 结论 |
|---|---|
| M1 | **RESOLVED**：原反例先失败后通过，实际搜索去重保留容器语义。 |
| CORE REVIEW PASS | **建议升级**，范围为CAABS独立核心，基于R1核心复核与本次补充验收；不替代组员正式PR审核。 |
| REGRESSION INCOMPLETE | **保留**。本轮没有重跑全量或解决历史系统测试失败/超时。 |
| INTEGRATION NOT VERIFIED | **保留**。I1未来Registry导入、I2公共来源窗口歧义及正式认证均未在本轮处理。 |
