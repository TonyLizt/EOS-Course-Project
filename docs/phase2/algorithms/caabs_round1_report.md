# CAABS 第一轮性能优化交付报告

日期：2026-10-21。优化分支 `perf/caabs-round1`；工作目录为原仓库下 `output/caabs-round1-worktree`。
起点是已fetch的 `origin/main=f344af9704d5839578b69caed4534a74374cab90`，算法冻结提交 `e50246efb6980e8286e1d8b49b24d90e17d43e1f`。
最终算法源码SHA-256：`768731d2a55ddff65b231316f9fd1288863df5229d4c4484ddc31d5620f1a0d1`。
该值对应Windows CRLF字节；LF规范化SHA（与Git对象一致）为 `46466a861a5260db662b3d2b8c34cc1f8a44382a51c366a50291d1a6c1e03cf2`。

结论：在本轮受测实例、原目标权重和2秒Solver预算下，完成数/TCR、TP和TM的平均表现改善；小、中型平均RT降低，大型通常继续用满预算。BD和RT没有逐实例全面改善，公共约束检查总次数也没有减少。没有比较其他算法，不声称CAABS优于其他算法或达到全局最优。

## 1. 审计与基线

真实入口仍为 `algorithms/conflict_beam.py:ConflictBeamScheduler`，Registry ID仍为 `caabs`，版本从0.2.0升到0.3.0；没有创建第二套算法。
阶段0先完成只读审计、51项旧专项、18组正常基线、单独Profile和内存测量，再修改算法。
完整流程、参数语义、停止条件、硬件/软件环境、seed、哈希及原始指标见[基线报告](caabs_round1_baseline.md)和[原始基线](caabs_round1/baseline.json)。

主要瓶颈是完整计划深复制和完整canonical state key构造，各约占分析运行的四成；目标函数3%–8%，候选构造约0.04–0.06秒。不能相加嵌套Profile累计时间。

## 2. 文件与机制

| 文件 | 修改及边界 |
|---|---|
|`algorithms/conflict_beam.py`|候选检查/可行分支预算分离；合法锚点轮换；受检机会排序；预算内贪心初解；单次solve静态候选缓存；精确增量键；可选整数域增量目标；进度统计|
|`eos_system/algorithm_registry.py`|沿用原注册入口及参数模型，更新机制和预算语义说明|
|`eos_system/algorithm_presentation.py`|补齐CAABS新增参数的展示标题/说明及可行分支含义；不改参数类型、默认值或其他算法行为|
|`tests/test_algorithm_conflict_beam.py`|尾部候选、排序、默认组合、预算、取消、实际分支隔离、证据/约束域缓存失效、完整/增量计算一致性|
|`tests/test_algorithm_registry_i1.py`|将旧五参数断言更新到新契约，增加新字段的边界及严格类型检查|
|`tests/test_gen02_development_source.py`|真实HTTP版本断言改为核对实际VERSION，保留提交/来源/物理/正式导出门禁测试|
|`scripts/benchmark_caabs.py`|串行新进程成对实验，固定提交基线加载，公开白名单，独立重载回放/可选原Controller核验，Profile/内存分开测量|
|`scripts/report_caabs.py`|汇集原始JSON、CSV和均值表，拒绝覆盖既有证据|
|`docs/phase2/algorithms/caabs_round1*`及`conflict_beam.md`|阶段审计、独立消融、参数选择、原始证据和本交付报告|

默认参数为Beam8、可行分支8、候选检查16、候选16、窗口32；预筛选、候选轮换、scarcity排序、贪心incumbent和增量键开启。
`incremental_objective`默认关闭，保留显式实验开关；叠加键缓存后没有稳定额外收益。其整数精确域及公共完整评分回退已测试。
历史 `branch_limit` 实际限制前缀候选检查数，本轮按用户要求改为可行子节点上限；skip另计，前缀被拒时可继续检查到candidate_check_limit。

公共ConstraintModel、曝光/来源规则、Runner计时、指标定义、结果独立核验均未修改。目标仍为完成数优先，其次共享ObjectiveModel；实验保留默认profit权重1，没有为了次级指标改权重。
assignment、姿态和metadata仍安全深复制；精确键使用完整不可变元组，不以哈希代替相等性。去重身份仍含固定顺序游标，greedy只作incumbent，不污染Beam游标。
缓存限定于单次solve，不能跨场景、约束、模式或证据域复用；父计划冲突仍逐次交权威模型。

## 3. 独立消融与参数探索

详见[阶段1](caabs_round1_stage1.md)、[阶段2](caabs_round1_stage2.md)、[阶段3](caabs_round1_stage3.md)。

| 机制（其他条件固定） | 主要实测结果 | 决定 |
|---|---|---|
|检查预算分离|三族100任务平均完成31.67→33.33，但300任务29.33→27.33|保留明确的双预算，避免把扩大检查误当必然提质|
|候选轮换|100任务31.67→33.33，20任务14.33→14.00|与排序/初解组合评估，保留单独退步证据|
|scarcity排序|100任务31.67→36，300任务29.33→37.33|启用；机会是公共构造核验后的有界采样估计|
|预算内贪心|100任务31.67→40，300任务29.33→106|启用；准备和初解均包含在同一预算|
|阶段1组合|100任务47，300任务116；RT未全面减少|继续处理已测出的状态计算瓶颈|
|精确增量键|阶段1小型均值RT0.259→0.148s；大型115.67→122.33任务|启用|
|增量目标|单独小幅改善，叠加键缓存后无稳定额外收益|默认关闭|
|Beam/分支配额|4×4更快，但部分小型TP低于较宽配置；16×8未普遍改善|暂保留原8×8；探索结果不作最终串行性能证明|

每格为对应阶段同一环境的一次探索均值，不是跨阶段的严格RT对照，也不是显著性检验；最终重复矩阵见下一节。
固定工作量615个评分状态下，完整状态键计算615→1；单独tracemalloc运行的Python分配峰值9,497,109→2,158,015字节（诊断变体同时开启键与目标增量，同一计划SHA）。分析器RT不混入普通RT表。

## 4. 最终小、中、大规模对比

Windows Python3.13.5，7族×20/100/300任务×前后版本×2次，共84组，全部串行新子进程。
seed41、PYTHONHASHSEED=0、相同场景SHA、Standard-Agility、相同约束和放置配置、每次2秒、无外部初始排程；算法内部初始化计入预算。
沿用既有uniform、clustered、capacity、hub、downlink、orbit_bands、station_network构造器，不将它们冒充真实dist0/dist1轨道数据。
每族只有一个预设任务来源seed；部分族共享seed/构造逻辑，重复执行不是新增独立场景，不能据此推断总体显著性。

| 任务数 | 完成数 前→后 | TCR 前→后 | TP 前→后 | BD 前→后 | TM 前→后 | RT(s) 前→后 |
|---:|---:|---:|---:|---:|---:|---:|
|20|14.29→15.57|0.7143→0.7786|98.29→108.86|0.9166→0.9466|0.4314→0.3842|0.2278→0.1512|
|100|37.50→53.00|0.3750→0.5300|275.00→402.14|0.9568→0.9725|0.7094→0.5995|1.5319→1.3941|
|300|34.29→136.43|0.1143→0.4548|246.71→987.43|0.9658→0.9730|0.9107→0.6548|1.9369→1.9517|

每项均值各14次运行。84个候选均通过重新生成输入、重建权威ConstraintModel、按时间回放、任务唯一性/未分配集合核验；场景未被修改，均未超2秒。
[原始JSON](caabs_round1/final_synthetic.json)、[CSV含扩展/去重/停止阶段/内存](caabs_round1/final_synthetic.csv)、[自动表](caabs_round1/final_synthetic.md)。这些是合成公共模型压力测试，不是物理认证。

| 任务数 | 公共检查次数均值 前→后 | 候选构造调用均值 前→后 | 已完成Beam层均值 前→后 | 进程生命周期峰值工作集均值(MB) 前→后 |
|---:|---:|---:|---:|---:|
|20|569.9→705.9|192→192|20→20|83.02→79.11|
|100|2737.1→4446.1|1091.2→1360.1|81.3→91.2|89.00→83.37|
|300|3641.2→6008.5|965.8→3964.4|76.7→91.8|101.31→88.08|

更多候选覆盖和贪心初解增加了检查总数；本轮没有实现“检查次数全面下降”。进程峰值包含Python导入和加载，与前面的求解期间tracemalloc峰值含义不同；不包含独立核验JVM。`scored_states`包括root/greedy，不能直接当纯Beam扩展数；`feasible_children`、`skip_states`、`dedup_input_states`单列。`greedy_tasks_completed`表示贪心已处理任务数（含未安排任务），实际完成数以独立指标为准。

## 5. 真实公开场景与独立物理核验

现有WSL Ubuntu22.04 Python3.10.12/Orekit环境，算法源码与冻结SHA一致；沿用原`verify_candidate`（来源重建、权威资源/转向检查、Orekit全曝光0.05秒采样）。核验耗时单列，不计Solver RT。采样通过不等于严格连续区间认证。
只读取公开development目录和train_development/validation白名单；验证划分在算法冻结后评估，没有据其结果再调参；最终冻结测试集未读取。

| 公开输入/分布 | 任务数 | 完成 前→后 | Solver RT(s) 前→后 | 独立物理 |
|---|---:|---:|---:|---|
|开发EOS-G0001 / dist0|20|16→16|0.6676→0.3835|两者PASS|
|开发EOS-G0026 / dist0|40|32→33|1.9531→1.0993|两者PASS|
|开发EOS-G0051 / dist0|40|27→27|1.5325→0.8503|两者PASS|
|开发EOS-G0076 / dist0|80|31→62|1.9743→1.9514|两者PASS|
|验证EOS-G0016 / dist1|20|17→17|0.6012→0.3604|两者PASS|
|验证EOS-G0041 / dist1|40|27→27|1.5689→0.7976|两者PASS|
|验证EOS-G0066 / dist1|40|32→34|1.9517→1.0857|两者PASS|
|验证EOS-G0091 / dist1|80|32→70|1.9520→1.9510|两者PASS|

[开发证据](caabs_round1/real_development.json)、[验证证据](caabs_round1/real_validation.json)，均含每次场景文件SHA、公共及独立物理指标、receipt、实际参数和核验时间；16/16通过。

另复跑仓库既有epoch_fixed_v1矩阵：4个小型实例前后各完成20，平均RT1.2384→0.5581秒；两个100任务dist0/dist1实例分别23→98、19→98，均通过独立物理核验，平均RT1.9562→1.9519秒。
旧500任务实例的前后候选都被独立物理核验拒绝，错误为`PREVIEW_PHYSICS_CHECK_FAILED / NONVISIBLE_EXPOSURE_START`。仅公共模型候选数为36→121，**不作为有效完成数、TP、TCR或质量排名**，没有修改场景或降低门禁使它通过。该矩阵12/14物理通过，不能声称全部真实大场景通过。
[旧场景原始证据](caabs_round1/real_repository.json)及[仅公共回放表](caabs_round1/real_repository.md)；后者标题已说明不是物理成绩，500任务行不能用于物理性能结论。

## 6. 测试结果

| 最终验证 | 结果 | 时间 |
|---|---|---:|
|WSL完整Python回归，开启六组物理/集成开关|758项：748通过、10跳过、0失败/错误|unittest260.239秒，含启动261.468秒|
|Windows CAABS专项|65/65通过，0跳过|1.228秒|
|Windows注册表|17项：16通过、1因缺FastAPI跳过；同HTTP测试在WSL通过|3.029秒|
|Windows真实注册Schema→JavaScript渲染|2/2通过|0.233秒|
|Windows既有Node回归|36/36通过，0跳过|0.337秒|

[结构化测试摘要](caabs_round1/tests.json)、[完整通过日志](caabs_round1/full-tests-linux-pass.log)、[算法专项日志](caabs_round1/final-caabs-tests.log)、[Node日志](caabs_round1/node-tests-approved.log)。
完整回归实际执行真实CAABS Runner/Worker/Controller、取消、崩溃/重启、来源链、HTTP、物理采样及正式导出拒绝测试。
六开关为 `EOS_RUN_CAABS_REAL_E2E / EOS_RUN_GEN02_PHYSICS / EOS_RUN_EXPOSURE_OREKIT_TESTS / EOS_RUN_E3_E4_OREKIT_TESTS / EOS_RUN_OREKIT_TESTS / EOS_RUN_ORBIT_INTERPOLATION_TESTS=1`。
10个跳过为6项需requirements-ml.txt（sklearn）、3项缺PyTorch及1项缺指定只读EOS-Bench源；逐项名称和原因见摘要，未将跳过算作通过，未安装或修改用户既有环境。

验证历史也保留：第一次Windows Node因沙箱禁止spawn而EPERM，注册表临时目录因沙箱权限报错，均在获准环境重跑；Windows注册表最终仅余上述依赖跳过。首次WSL从NTFS worktree运行时出现长时间磁盘I/O及真实集成ERROR，未获得成功全量结果，已核验并中断自有测试会话。
第一次Linux快照完整运行758项中3项失败（新增参数缺展示说明导致2处断言失败、HTTP版本仍写死0.2.0），修复后重新跑全部758项并通过。保留[修复前日志](caabs_round1/full-tests-linux-final.log)，没有隐藏失败或用定向通过代替最终全量。
最终在WSL临时快照执行，清单中的513份文件与优化worktree对应文件逐字节核对一致，算法SHA与性能实验相同；[快照清单](caabs_round1/test_snapshot_manifest.json)。新生成交付报告/最终数据不参与测试执行。发布日志统一为UTF-8并去行尾空白，原始控制台文件仍保留在output/caabs。临时副本只用于测试，追踪代码只修改优化worktree；未修改用户原工作区或既有运行数据库。

## 7. 未改善项、边界和下一轮

- 合成downlink20的BD 0.9868→0.9605，orbit_bands300的BD 0.9700→0.9377；uniform20的TM 0.1853→0.1917。downlink100/300的RT分别0.5373→0.6301、1.8393→1.9508秒。不能把平均改善推广为每个实例均改善。
- 真实100任务旧矩阵平均BD 0.8079→0.3608，同时TCR0.21→0.98；开发80任务BD0.6854→0.6494，验证80任务BD0.6646→0.5445。均衡目标没有全面达成。项目BD空计划也可能为1，必须与完成数一起解读；本轮不修改评分来美化BD。
- 静态机会为有限候选采样，下传仅使用公共构造器首个可行组合；没有穷举全部卫星/窗口/位置。固定任务序列仍存在路径偏置，短预算可能在准备或初解阶段结束。
- 深复制仍是主要剩余开销，尚未证明嵌套姿态可安全共享，故保留隔离；公共约束检查总数增加。后续先Profile当前瓶颈，再独立评估不可变候选载荷、候选键随缓存复用及安全资源索引。
- 下一轮可在完成数/TP不退步的条件下独立研究换星、替代下传和受限重插入，改善BD/TM；另开评分权重消融，不混入本轮机制收益。4×4作为低延迟候选，需扩大真实验证覆盖后再决定是否默认。
- 未找到既有3星200任务研究依赖的两份7天母场景（常规输入、已存在归档目录索引及WSL场景目录均未匹配）。没有重造替代数据冒充3星200任务24小时Standard-Agility基准；该基准未复现。
- 未解决生产严格连续区间证明合同；物理采样PASS不代表formal成功，原阻断与导出规则保留。没有读取最终测试集、创建用户数据库正式成绩、推送分支或发布PR；集成测试仅使用自有临时数据库。

## 8. 复现与交付

阶段1/2/配额参数已指向固定提交，原始JSON内另存当时effective_params与算法源码SHA；最终参数见[final_variants.json](caabs_round1/final_variants.json)。最终变体的current应使用本报告冻结算法及相同公共模块版本，不能将未来分支的current冒充本次实现。依赖和原始输入也须与manifest一致。在优化worktree内运行（输出目录须不存在）：

```powershell
$env:PYTHONHASHSEED='0'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
python -B scripts/benchmark_caabs.py --output output/caabs/final-synthetic --variants docs/phase2/algorithms/caabs_round1/final_variants.json --budget 2 --repeats 2 --families uniform clustered capacity hub downlink orbit_bands station_network
```

真实场景增加`--suite shared --dataset <公开包根目录> --split train_development`或`validation`及`--audit`；既有矩阵用`--suite repository --audit`。WSL使用既有Orekit解释器，并设置`EOS_OREKIT_DATA`。
Windows worktree的`.git`为Windows绝对路径，WSL不能直接加载其历史对象；本轮将固定基线/优化源码导出为只读比较输入，利用脚本ref文件支持加载，逐次源码SHA与Windows冻结结果一致。它们只在忽略的output目录，不注册为新算法。
普通作业的完整候选、原始日志和prof保留在优化worktree的`output/caabs/`；未通过独立物理核验的文件仅为调试候选，不是有效交付计划。

阶段提交：17697f3（只读基线）、e109f4b（候选/排序/初解）、95e3d39（状态增量）、e50246e（默认配置和配额冻结）、5cf7c9f（参数展示与回归契约修复）；最终证据另提交。原工作区未跟踪文件保持不动，未修改前端/PPO/LAVIS/场景或公共约束文件。

## 9. 推荐PR

标题：`perf(caabs): improve budgeted candidate coverage and cache exact beam state keys`

描述：

> CAABS原实现只检查候选前缀、按任务ID搜索，并在每次扩展重复序列化完整计划。此改动分离候选检查与可行子节点预算，加入受检机会排序和预算内贪心incumbent，并缓存完整候选键、增量组合精确状态身份。完成数优先、目标权重、深复制隔离、公共约束与Controller核验保持不变。
>
> 同一2秒预算、7族三规模、前后各两次的合成公共模型测试中，平均完成数20任务14.29→15.57、100任务37.50→53、300任务34.29→136.43；小中型平均RT下降，大型继续用满预算。公开开发/验证16个前后结果均通过独立Orekit采样核验；既有500任务场景前后均被物理核验拒绝，不计质量结论。BD、TM、RT存在逐实例取舍，检查总次数未减少。附逐阶段独立消融、参数/场景/源码SHA和原始CSV/JSON；未读取冻结最终测试集，未改变严格连续认证门禁。
>
> 验证：开启六组物理/集成开关的完整Python回归758项，748通过、10项因依赖或输入缺失跳过、0失败；Windows算法65/65、实际注册Schema渲染2/2、Node36/36通过。详细跳过原因与修复前后日志随报告保存。
