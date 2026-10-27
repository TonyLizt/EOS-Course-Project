# 新机制场景与原工作台验收交付

已取得一组明确的当次开发结果：**R30-main-01 上 CAABS 71.155511，最强OS 66.724666，领先4.430845分；完成106对101，TP570对495。**

RABAS在该场景反而落后；本轮尚未实现RABAS领先2～5分的目标。其余持平、退步结果完整保留。不是普遍性能或独立泛化结论。

本轮上线4个主场景及1个可选迭代对照，共5份；完成3组四算法比较和2项规模技术Smoke，**14/14 Controller SUCCEEDED、SAMPLED_PHYSICAL_PASS、NOT_CERTIFIED**。未更换成熟前后端、未改算法、Score、物理合同、预算或模型，原8910/4 Worker继续运行。没有执行99项旧矩阵。

## 1. 场景产物与准入

| 场景 | 星/任务 | 活动星/目标点 | 可信窗 | 跨星任务 | 时间冲突边 | 中立合法LB / 乐观UB | 正式运行 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C30-main-01 | 30/144 | 24/21 | 216 | 72 | 360 | 72 / 144 | 四算法 |
| R10-show-01 | 10/48 | 8/8 | 72 | 24 | 120 | 35 / 48 | RABAS单项 |
| R30-main-01 | 30/144 | 24/21 | 216 | 72 | 360 | 107 / 144 | 四算法 |
| R30-main-02 | 30/144 | 24/22 | 216 | 72 | 0 | 106 / 144 | 四算法 |
| R50-show-01 | 50/240 | 40/33 | 360 | 120 | 600 | 177 / 240 | FCFS单项 |

五份均用公共Canonical Schema、Loader、来源侧车、公共候选生成、ConstraintModel、characterize及真实PlanExposureAuditor。每个任务都有非零单任务合法候选，每场景生成阶段10段完整曝光有限抽样通过；正式运行另有独立Verifier。source-grid不兼容任务为0，未复用S8窗口。结构实际为 **WARN：未记录distribution_type**，没有伪造分布字段消警告。

R30-main-01以12个共享—独占资格资源簇为主，72项任务两星可选；不同中立顺序得到100～107项合法计划。C30-main-01在同一30星物理库上增加5/10/20秒与价值差异，期望检验成本/价值分支，但当次CAABS落后，不能称CAABS优势场景已达标。R10/R50按10/48、50/240原定规模生成，用于展示可运行性。S50仅FCFS实际系统Smoke，不声称50星四算法或四路满载均已验收。

R30-main-02是明确保留的可选迭代：固定5秒请求槽降低位置歧义，时间重叠边为0、资源竞争仍存在，四算法最终同分。**它未达到最初30条时间冲突边门槛，只作为资源专项/持平对照，不充作主打成功场景。** 上线/可提交表示来源、工程和物理准入，不等于达成预期算法优势。

每场景的design_assessment.json、conflict_graph.json、neutral_legal_plans.json、validation.json、sampled_physics.json、characterization.json、source_snapshot.json及provenance.json均在 `/mnt/f/EOS-Pilot-Work-v1/web-scenes-v25/scenarios`。LB是已构造的合法计划，不是最优；UB使用一任务最多一次的任务数证书，较宽松，不保证LB到UB差距能被优化器兑现。

## 2. 来源及受控合成边界

原文件：`/mnt/f/EOS-Bench/output_s50_cc/re_50_satellites/Scenario_S1_50_satellites_Sats50_M100_T7.0d_cities_01.json`。SHA-256：`5374c99aead5d8c7dc1b8c85d6d6a0fccaef75a85b3b9096d1f9601bbe215d23`。仅提取1MiB头部和流式完整SHA，没有加载原大型窗口。

原文件50颗声明轨道、100个城市目标；10/30星用原始索引等距子集，50星保留原星座。时域2025-11-18 12:00～18:00 UTC。复用OrbitGrid/Orekit重新生成5秒网格，保留原传感器、1deg/s能力与完整曝光0.05秒判定。30星库733段/34.51秒，10星库245段/13.99秒，50星库1227段/51.10秒。旧EOS-Bench窗口没有当作物理通过证据。

**任务数是新请求数，不是独立城市数。** 新场景使用受控重复观测请求，原城市坐标与源卫星轨道有逐项映射。5秒及C场景5/10/20秒是新合成请求，不声称保持原需求时长。每个请求同时保存源时长/优先级和新时长/优先级。任务的单星“独占”是公开请求卫星资格限制，不宣称其它卫星在几何上不可见；共享任务保留真实的两颗星机会。

异构存储及逐轨道累计power_cost_W是公开受控配置，主星6个5秒曝光当量/300W，其余10个当量/500W；没有把W冒充Wh，没有放宽真实跟踪或姿态合同。C长曝光实际消耗更多存储。任务选取、容量及候选先冻结，再运行算法。main02允许依据开发负结果提出新规则，原失败/持平/落后记录不删除。这些都是定向Discovery开发实例，跨档及重复请求高度相关，不是独立最终测试。

## 3. 实验配置与完整结果

当前科学执行版本score-search-v2-hard-budget-r1，objective-score-v2，SCORE_70_20_10，初始模型completion_first，种子2026102701，Solver60秒、原生有效上限29.5秒、公共逐CM检查硬上限140000。参数从已冻结原模板复用，没有削弱FCFS/EDF。每个四算法实验使用原Experiment实体关联4个Run，并在4 Worker环境同时运行；这是交互开发并发比较，不并入Stage22单Worker正式矩阵。

这里“完成率优先”是原工作台的初始模型。**实际目标是70/20/10综合Score，不是纯TCR字典序组；本轮没有执行单独的纯TCR/TP优先补充组。** 该选择在首个Solver运行前已登记于设计修订，保留初始规划草案及差异。RT单独报告，不参与Score：70×TCR+20×TP/总优先级+10×(1−TM)。

### R30-main-01

| 算法 | 完成 | Score | 对最强OS | TCR | TP | TM | BD | RT(s) | 原生Score | 公共增益 | 公共检查 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fcfs | 101 | 66.724666 | +0.000000 | 0.7014 | 495.0 | 0.383089 | 0.788194 | 59.515 | 66.724666 | 0.000000 | 40431 |
| edf | 101 | 66.724666 | +0.000000 | 0.7014 | 495.0 | 0.383089 | 0.788194 | 59.508 | 66.724666 | 0.000000 | 40442 |
| rabas | 93 | 62.041442 | -4.683224 | 0.6458 | 483.0 | 0.434745 | 0.820139 | 59.519 | 58.020464 | 4.020978 | 37515 |
| caabs | 106 | 71.155511 | +4.430845 | 0.7361 | 570.0 | 0.356671 | 0.802315 | 59.510 | 71.155511 | 0.000000 | 37179 |

### C30-main-01

| 算法 | 完成 | Score | 对最强OS | TCR | TP | TM | BD | RT(s) | 原生Score | 公共增益 | 公共检查 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fcfs | 70 | 47.789927 | +0.000000 | 0.4861 | 334.0 | 0.583555 | 0.881111 | 59.503 | 47.789927 | 0.000000 | 34315 |
| edf | 70 | 47.789927 | +0.000000 | 0.4861 | 334.0 | 0.583555 | 0.881111 | 59.502 | 47.789927 | 0.000000 | 33952 |
| rabas | 66 | 47.901294 | +0.111367 | 0.4583 | 414.0 | 0.607859 | 0.875000 | 59.504 | 47.901294 | 0.000000 | 29589 |
| caabs | 59 | 44.386489 | -3.403438 | 0.4097 | 426.0 | 0.653545 | 0.875000 | 59.505 | 44.386489 | 0.000000 | 32701 |

### R30-main-02

| 算法 | 完成 | Score | 对最强OS | TCR | TP | TM | BD | RT(s) | 原生Score | 公共增益 | 公共检查 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fcfs | 119 | 79.692853 | +0.000000 | 0.8264 | 663.0 | 0.350159 | 0.828009 | 43.522 | 61.501624 | 18.191229 | 140000 |
| edf | 119 | 79.692853 | +0.000000 | 0.8264 | 663.0 | 0.350159 | 0.828009 | 43.415 | 61.501624 | 18.191229 | 140000 |
| rabas | 119 | 79.692853 | +0.000000 | 0.8264 | 663.0 | 0.350159 | 0.828009 | 59.505 | 79.683835 | 0.009018 | 135179 |
| caabs | 119 | 79.692853 | +0.000000 | 0.8264 | 663.0 | 0.350159 | 0.828009 | 48.093 | 71.954138 | 7.738715 | 140000 |


S10/RABAS：31/48，Score62.720052，RT41.903482秒；S50/FCFS：167/240，Score66.090509，RT59.543816秒。两项只是规模技术Smoke，没有对应OS/自主四算法组，不能计算优势或跨规模算法排名。

## 4. 优势、负结果与实际计划差异

R30-main-01 的CAABS对最强OS：完成率项 **+2.430556**，收益项 **+1.736111**，时效项 **+0.264178**，合计+4.430845。CAABS完成42项独占资格任务、64项共享任务；FCFS/EDF为32和69。即多完成10个高价值独占请求、少5个共享请求，净增5项、TP+75，TM也降低。

完整任务ID、卫星、开始时刻、仅一方完成及跨星变化见R30_actual_task_difference.json；不是按算法名称推测机制。CAABS原生阶段已经106项/71.155511，公共refinement最终增益0，因而这次优势不是全部来自公共搜索。没有OFF消融，仍不能据此量化future guide或某一个Beam部件的因果收益。

RABAS在R30-main-01为93项/62.041442，比最强OS低4.683224分；仍低于中立合法下界107项，说明当前有限候选/有限预算决策还有搜索空间，不能宣称资源机制已成功转化为该实例的优势。C30场景RABAS少完成4项、TP多80，只得到+0.111367分；CAABS落后。main02所有算法119项/79.692853，不能把更高绝对分或持平包装为RABAS胜利。

## 5. Web接入与验收

原页面 **http://127.0.0.1:8910/**，当前仍是原create_app与成熟工作台，没有创建简化页。通过原数据源API登记 `/mnt/f/EOS-Pilot-Work-v1/web-scenes-v25/scenarios`，source_id=`src-696e02406002`，名称“新机制开发场景 · S10/S30/S50”。新根独立dataset_plan_v1.json供原Registry发现；没有运行全局index，没有改旧Registry/旧场景。

原17场景、19算法、103份Canonical与99项只读历史入口保留。五份新场景均ready且公共请求预校验通过，默认新建表单可正常选择与提交。注意普通新数据源的原生表单默认objective-v1；本轮冻结结果使用objective-score-v2。不要将手动默认协议重跑结果与本轮混成同一条件组；精确配置与命令见验收指南和各compare目录protocol.json。

已在原浏览器实际选择新数据源、看到R30的30星/144任务、打开实验7b86d94d并按综合分排序。截图R30_score_comparison.png和完整AX文本同时保留。原表格有内部滚动，截图不是完整数据导出，所有四项及负结果在CSV/JSON中。用户可从实验管理进入同一实验查看完整四行。甘特、详情、导出仍走原接口；Cesium未构建时不伪称READY。

原8910服务未重启、未替换、实际max_workers仍为4；开始比较前等待用户原有队列空闲，未取消用户任务。当前界面与精确截图步骤见web_acceptance_guide.md。

## 6. 物理、预算、传输和成本

14项全部由真实Controller→Worker→Solver→独立Verifier→SQLite执行。每项检查正式成功、非空计划、完整收据、源/阶段SHA、4MiB严格传输、lossless诊断DAG、真实公共ledger<=140000和RT<=60；CSV/JSON导出仅对本轮新结果操作。原生/公共Score、两阶段耗时、Loader、prepare、核验及请求墙钟见all_run_analysis.json、all_scores.csv。真实Verifier重新传播，生成阶段抽样没有替代运行后核验；连续认证始终NOT_CERTIFIED。

公共阶段可沿用原生未花完的总时间，所以原生很快结束时refinement可超过30.5秒，但总Solver仍不超过60秒；未改已验收的预算分配逻辑。

| 场景 | 静态证据条数 | 建库墙钟(s) | CPU(s) | 镜像校验(s) | 有限采样(s) |
| --- | --- | --- | --- | --- | --- |
| C30-main-01 | 4176 | 20.640 | 14.066 | 0.808 | 0.370 |
| R10-show-01 | 1440 | 6.410 | 4.448 | 0.237 | 0.339 |
| R30-main-01 | 4320 | 20.411 | 14.127 | 0.622 | 0.446 |
| R30-main-02 | 216 | 4.061 | 3.570 | 0.108 | 0.351 |
| R50-show-01 | 7200 | 45.141 | 32.454 | 1.032 | 0.212 |

共享物理证据合计17352条，F盘原件和Linux只读镜像逐文件SHA一致，所有算法接口相同。只缓存静态曝光，动态时序/转向/资源继续实时检查，独立Verifier不信任缓存PASS。

采用已声明的“共享离线准备+在线Solver”开发计时口径。30星窗口库供三个30星场景复用；如需按场景分摊可各计1/3，再将该场景证据成本按4请求均摊；两个规模单项承担各自场景成本。这是报告分摊，不是把成本记为0。bank只保存墙钟/RSS，未单独测量CPU，不伪填CPU。不能宣称含全部预计算、prepare、Verifier的端到端60秒限制已满足。

## 7. LAVIS与历史保护

真实lavis-v4-opportunity已注册，权重SHA `9a2a454f85b41bc948a43ffcc2bbf6d20b7359ec500a81cc8f69841a20ec078d`；源目录仍为 `/mnt/f/EOS-Pilot-Work-v1/lzt-models`。实际FrozenPredictor加载成功，复用真实历史24维特征fixture，805行预测有限、两次输出完全相同，新R10场景API预校验通过。本轮没有新增LAVIS/DARTIS正式运行，不把固定输入推理当成新场景端到端Smoke或性能优势，也没有训练模型。

15160份继承历史工件SHA核验通过，意外变化0。生产算法、前后端、物理、模型及完整部署均未变，完整部署SHA `0853deda4e121778a456ebc8ec33a9e1a03b49e4da5f946b0574636e8dbc1405`。开始时数据库43项Run全部原表行保留；本轮14项之外还有用户自行新增记录，单独计数于database_history_receipt.json，不挪作本轮成绩。最终一致性快照results_after_new_scenes.sqlite3；原99项、S8零计划/失败、R5失败及后续人工实验没有覆盖。

## 8. 文件、版本和复现

场景及权威物理证据：`/mnt/f/EOS-Pilot-Work-v1/web-scenes-v25`。本轮代码/协议/全部运行/报告：`/home/mint/eos-course-runtime/f-pilot-v25-web-scenes`。没有Git写操作。source_header/source_identity、各场景design_frozen、source_snapshot及generation_code_sha都有实际记录；历史生成器字节按对应SHA归档generator_versions，源代码恢复仅在字节SHA完全一致时登记，未回写场景。

唯一额外候选main02首次构造时，工程裁剪helper把已冻结5秒完整曝光误设为至少15秒；在Solver提交前修正helper结构限制，未改变任何请求时间、任务参数或物理阈值，保留失败堆栈及generator_engineering_resume。等待用户队列的第一次预检未提交请求，后续等待空闲后才提交；所有14正式请求均仅一次，没有正式失败重试。

```bash
# 各入口有防覆盖语义。以下仅说明实际流程，不应原路径重复执行。
/home/mint/eos-course-runtime/f-pilot-v4-dev/venv/bin/python -B /home/mint/eos-course-runtime/f-pilot-v25-web-scenes/web_scenes.py init
/home/mint/eos-course-runtime/f-pilot-v4-dev/venv/bin/python -B /home/mint/eos-course-runtime/f-pilot-v25-web-scenes/web_scenes.py bank 30
/home/mint/eos-course-runtime/f-pilot-v4-dev/venv/bin/python -B /home/mint/eos-course-runtime/f-pilot-v25-web-scenes/web_scenes.py build R30-main-01
/home/mint/eos-course-runtime/f-pilot-v4-dev/venv/bin/python -B /home/mint/eos-course-runtime/f-pilot-v25-web-scenes/web_scenes.py evidence R30-main-01
/home/mint/eos-course-runtime/f-pilot-v4-dev/venv/bin/python -B /home/mint/eos-course-runtime/f-pilot-v25-web-scenes/web_scenes.py register R30-main-01
/home/mint/eos-course-runtime/f-pilot-v4-dev/venv/bin/python -B /home/mint/eos-course-runtime/f-pilot-v25-web-scenes/run_comparison.py R30-main-01
# C30采用明确的C任务时长/价值规则；S10/S50固定48/240任务。
# 每个实际阶段使用的代码版本及参数以设计/协议与generator_versions为准。
```

## 9. 全部本轮真实run_id

| 场景 | 算法 | run_id |
| --- | --- | --- |
| C30-main-01 | fcfs | 5ee89a3e-c695-4b15-af28-965e454e6409 |
| C30-main-01 | edf | 8adef3f9-0bf0-4635-a6c4-9fe7ef0b26af |
| C30-main-01 | rabas | 41efa1f4-db62-41b7-895f-2d8d96d56a12 |
| C30-main-01 | caabs | cd863fe1-1d4a-4504-a305-a60602aa6e50 |
| R10-show-01 | rabas | 1432ac85-2614-4d1e-9387-88e3f4181496 |
| R30-main-01 | fcfs | 7ac14fc4-338e-4ba4-a3c2-7bc847b72260 |
| R30-main-01 | edf | 5bd6e943-8e44-40bd-830d-6a610ec5d151 |
| R30-main-01 | rabas | 20c28304-cbbb-4433-ae56-fc8f4190f225 |
| R30-main-01 | caabs | 854c9fe1-a3cf-4f0b-be8c-9fa079dca48d |
| R30-main-02 | fcfs | 5494158a-fa95-4546-b518-6d29e5dfcb07 |
| R30-main-02 | edf | d72b1569-5d91-4610-8d08-0bc9d5ae9004 |
| R30-main-02 | rabas | 7a74d9ac-b4e8-48e4-a695-9215f9e904c2 |
| R30-main-02 | caabs | 00b12d52-b1a2-41ec-b2df-3c636f99d376 |
| R50-show-01 | fcfs | 42da9b47-acc3-44c3-acf0-342e86918507 |

本轮结束，不追加矩阵。建议人工优先验收R30-main-01/实验7b86d94d，完整保留另两个30星负结果和规模Smoke。若下一步必须追求RABAS稳定2～5分优势，应另行审核其搜索成本与资源决策，而不是将本轮负结果删除或冒充独立最终测试。
