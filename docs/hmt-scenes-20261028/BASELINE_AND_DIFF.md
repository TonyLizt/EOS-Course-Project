# BASELINE_AND_DIFF — 场景前基线与真实增量

## 1. 两种基线必须区分

- Git BASE_SHA：`6f041617f1fba3aa448a8ae5c02e273298c6c912`，原工作树HEAD、reflog及生成前源身份相互核对；不是按origin/main猜测。
- 分支：`feat/hmt-scenes-10-30-20261028`。选用用户明确允许的专用个人分支；已有算法/IPC分支有不同历史，原工作树有大量既有WIP，故使用独立worktree。
- 场景开发前实际生产部署SHA：`0853deda4e121778a456ebc8ec33a9e1a03b49e4da5f946b0574636e8dbc1405`。
- 该运行基线中216份文件相对Git BASE新增/变化，属于Stage22/24等既有功能。逐文件旧GitblobSHA/场景前文件SHA在 PRE_EXISTING_RUNTIME_DIFF.json；完整要求在 PRE_SCENE_RUNTIME_REQUIREMENT.json。
- 这些既有改动**不提交到本次场景分支、不作为本轮贡献**。ZIP单列 baseline_runtime，供接收方复核依赖；不能把运行快照冒称为某个已存在commit。最终COMMIT_SHA、远端校验及完整实际diff见交付收据；ZIP版本本文件在提交后追加准确SHA。

## 2. 原来已有的系统

原成熟前端 eos_system/web/index.html、app.js、experiment-ui.js；原后端 eos_system.api:create_app；Controller/Worker、算法Registry、实验实体和runs关联、原SQLite、Gantt及Cesium接口均已存在。Stage22的99项只读入口、Stage24的多Worker/物理初始化/协议观察器修复在场景开发前已经存在，均不计入本次新功能。

沿用 schedulers/scenario_loader.py、schedulers/constraint_model.py、eos_system/dataset_registry.py、eos_system/config.py 的原始入口；不引入第二套场景格式、第二套物理几何算法、简化前端或替代数据库。

## 3. 本次场景与来源

| ID | 卫星/任务/窗口 | 多星任务/冲突边 | 中立下界/乐观上界 | 场景SHA256 |
|---|---|---|---|---|
| R10-show-01 | 10/48/72 | 24/120 | 35/48 | cf83a343d5a2f9c6767e1fbc9c844c0523e7bdaaed15277f342da670e30993f0 |
| R30-main-01 | 30/144/216 | 72/360 | 107/144 | f916edf91e47a2471c0bf509f7672d901295ca2a2d181426698b7cb3773db306 |
| C30-main-01 | 30/144/216 | 72/360 | 72/144 | 25ce3f1a33752b9f6c7b219f825100ee1790c4b3fbf43f0dec3564f83fd0f649 |
| R30-main-02 | 30/144/216 | 72/0 | 106/144 | 87419a32c85c303d2e2003f0efd3d3712c624c6a2011e9ad9dcafd2a9bf11c4a |


来源F50文件SHA：`5374c99aead5d8c7dc1b8c85d6d6a0fccaef75a85b3b9096d1f9601bbe215d23`，175214385字节。50条真实轨道和100个城市目标位于 source_header.json，完整原175MB文件不随包分发；原路径仅作来源记录。10/30星按原索引等距子集选取，未伪造轨道。50星展示附件同源，ZIP单列。

固定任务数48/144/240是展示规模要求。采用受控重复请求及公开卫星eligibility，重复城市不等于独立目标；“独占”指请求限定可执行星，不宣称其它卫星几何上不可见。R类5s曝光、共享priority3/独占9；C类混合5/10/20s曝光及相应优先级。每簇共享—独占机会竞争与异构逐轨道storage/power上限公开记录。power是原CM累加W语义，不能解释为Wh或真实硬件参数。

2025-11-18 12:00–18:00 UTC，公开5s源网格，Orekit重算窗口与四元数端点，完整曝光抽样步长0.05s、tracking1deg/s。没有复制旧EOS窗口假称新版物理通过。生成seed2026102701；选取规则/阶段性修订及失败均保留。R30-main-02是允许的开发迭代，其时间冲突边为0，原时间冲突门槛未达到，保留为资源对照，不包装成冲突机制成功。

中立下界是另一策略得到的合法计划见证，不保证这些60秒Solver能达到；上界仅是一任务最多执行一次的乐观上界，差距不保证可兑现。

## 4. 真实代码增量与逐项影响

| 路径 | 修改前 → 修改后 | 原因 / 兼容性 |
|---|---|---|
| data/scenarios/hmt-web-10-30-v1/*/scenario.json及侧车 | 不存在 → 四份原Bundle字节副本 | 原Loader无需改代码；source_snapshot含轨道/任务/来源与控制资源 |
| 同目录dataset_plan.json、MANIFEST.json | 不存在 → 可移植目录标识和逐文件SHA | 使用既有Canonical识别入口，不回写eos-v1；无全局index |
| scripts/hmt_scene_handoff/cli.py | 不存在 → 离线SHA/Loader、显式注册、显式未来生成入口 | 原服务无导入副作用；旧根目录复用避免UNIQUE冲突；运行身份不符fail closed |
| artifacts/generators/*.py | 不存在 → 六份真实生成时版本原件 | 文件名即SHA；历史硬编码只保留审计；便携入口只替换四个顶层路径，不改函数体 |
| artifacts/source_header、source_identity、designs、recipes | 不存在 → 真实轨道/目标/种子/生成身份 | 原始175MB和旧窗口无需附送；原绝对路径仅来源记录 |
| artifacts/runtime_requirement、environment_record | 不存在 → 执行依赖和版本要求 | 明确Git基线缺少既有科学修复；不自动安装依赖、不冒充兼容 |
| serve_original.py与runtime_hook | 不存在 → 接收方可显式启动原factory的便携入口 | 不自动启动；main保护；spawn仅安装既有观察器；不改UI |
| tests/test_hmt_scene_handoff.py | 不存在 → 十项离线回归 | SHA篡改、越界、原生成AST不变、缺运行依赖拒绝、原注册语义 |
| docs/hmt-scenes-20261028 | 不存在 → 本说明/导入文档/原始成绩与验收摘要 | 保留负结果；本次无生产后端接口/前端修改，无删除文件 |

完整Git新增/修改/删除清单由 `git diff --name-status 6f041617f1fba3aa448a8ae5c02e273298c6c912 HEAD` 自动生成随交付保存。本次仅新增批准范围文件，修改既有生产科学文件数0、删除数0。ZIP baseline_runtime 另标为前置依赖，不属于此Git差异。

## 5. 所有14项真实结果

| 场景 | 算法 | 完成 | Score | TP | RT秒 | 原生Score | 公共增量 |
|---|---|---:|---:|---:|---:|---:|---:|
| C30-main-01 | fcfs | 70/144 | 47.789927 | 334.0 | 59.503 | 47.789927 | 0.000000 |
| C30-main-01 | edf | 70/144 | 47.789927 | 334.0 | 59.502 | 47.789927 | 0.000000 |
| C30-main-01 | rabas | 66/144 | 47.901294 | 414.0 | 59.504 | 47.901294 | 0.000000 |
| C30-main-01 | caabs | 59/144 | 44.386489 | 426.0 | 59.505 | 44.386489 | 0.000000 |
| R10-show-01 | rabas | 31/48 | 62.720052 | 171.0 | 41.903 | 56.271798 | 6.448254 |
| R30-main-01 | fcfs | 101/144 | 66.724666 | 495.0 | 59.515 | 66.724666 | 0.000000 |
| R30-main-01 | edf | 101/144 | 66.724666 | 495.0 | 59.508 | 66.724666 | 0.000000 |
| R30-main-01 | rabas | 93/144 | 62.041442 | 483.0 | 59.519 | 58.020464 | 4.020978 |
| R30-main-01 | caabs | 106/144 | 71.155511 | 570.0 | 59.510 | 71.155511 | 0.000000 |
| R30-main-02 | fcfs | 119/144 | 79.692853 | 663.0 | 43.522 | 61.501624 | 18.191229 |
| R30-main-02 | edf | 119/144 | 79.692853 | 663.0 | 43.415 | 61.501624 | 18.191229 |
| R30-main-02 | rabas | 119/144 | 79.692853 | 663.0 | 59.505 | 79.683835 | 0.009018 |
| R30-main-02 | caabs | 119/144 | 79.692853 | 663.0 | 48.093 | 71.954138 | 7.738715 |
| R50-show-01 | fcfs | 167/240 | 66.090509 | 801.0 | 59.544 | 66.090509 | 0.000000 |


R30-main-01 CAABS106/144、TP570、71.155511；FCFS/EDF101/144、TP495、66.724666；RABAS93/144、TP483、62.041442。CAABS相对已测最强OS为+4.430845。按all_scores及阶段诊断，CAABS原生阶段已106项，FCFS/EDF原生已101项，三者公共Score增量均0；RABAS原生87项、58.020464，经公共阶段至93项、62.041442。不能把公共收益记为新自主机制。

C30中CAABS负结果、RABAS只略高0.111367、R30-main-02四算法完全持平，均保留。R10只有RABAS、R50只有FCFS单项，不能推断该规模多算法优劣。RABAS预期明显优势本轮未证实。

## 6. 本次没有改什么

此Git提交没有修改算法核心、Score、60s/29.5s/140000硬预算、物理合同、1deg/s阈值、模型、旧场景和99项归档。本次也未修改原工作树的上述既有WIP。不能错误地据此说Git BASE与现运行科学实现相同；它们的既有差异由独立清单公开。

真实14项运行科学设置为 objective-score-v2 / score-search-v2-hard-budget-r1，Score=70*TCR+20*TP/TotalPriority+10*(1-TM)；最后一项是TM，不是RT。completion_first指原生初始化策略，不把它重命名为独立TCR-only目标。原网页普通创建可能默认objective-v1；要复现表格请使用包内原protocol和原Score-v2 API字段，不凭GUI标签推定等价。

## 7. 如何继续与边界

按 IMPORT_AND_VERIFY.md 准备环境、验证文件/原Loader、显式登记新根目录，继续使用原Web实验创建→管理→比较。重要入口是原 RunRequest/RunConfig、AlgorithmRegistry、SourceWindowIndex和ConstraintModel；不要直接编辑数据库或冒造来源窗。不得为了接收方适配去改scenario.json。

生成器可在全新目录显式调用，但本次交接未再调用generate/Builder/Solver/Verifier，不宣称重新生成跨环境字节确定性已验证；原件与原SHA才是交接对象。

## 8. 限制与验证口径

这些是相关Discovery机制开发例，容量/任务派生共享F50轨道和目标家族，非独立封存泛化测试。没有OFF消融不能量化因果。14项是4 Worker网页条件下的3组四算法+2单项，不是单Worker正式科研矩阵。所有物理成功仅有限工程采样；NOT_CERTIFIED连续认证从未取得。结构WARN缺distribution_type按事实保留。

模型权重、候选物理缓存及在线数据库不分发。LAVIS已有真实加载/固定24维预测证据，但本批无LAVIS正式Controller运行；不宣传其成绩。无预计算缓存时走真实在线物理检查，可能显著降低搜索覆盖或超时，不能保证相同60秒成绩。共享预处理、prepare、Verifier及墙钟成本见原报告，不把Solver RT冒称端到端60秒。

本次Git只承载场景增量。ZIP依赖快照允许独立读取和后续显式本地部署，但本次没有启动接收方服务或新性能请求，因此新便携启动器仅经离线代码检查，实际未来部署须核验模型/来源/物理环境。原发送方8910维持运行，不能成为唯一加载依赖。
