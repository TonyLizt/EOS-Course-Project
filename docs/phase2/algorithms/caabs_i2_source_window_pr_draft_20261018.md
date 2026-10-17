# 独立 PR 草稿（未创建）

建议标题：`fix(scheduling): preserve and verify assignment source window identity`

分支 `fix/source-window-i2`；正式 Rebase 后 main 基线为 `5e37ba720a9222a70d834d84e96c740601a3d236`（含 CAABS Core PR #17、I1 Registry PR #18），已提交 I2 核心 HEAD 为 `0b8dbd4bef5b01bac6538c69a166ee87a62701f6`。R2-C7 仅收口文档，尚未提交。本修复服务所有算法，不修改 Registry 或 CAABS 搜索；本次验收使用已正式整合 I1 的实际源码，不沿用临时组合结论。

## 问题与改动

Assignment原有来源ID在公共输出时丢失。Verifier选首个时间包含窗口，导致合法窄窗口任务被宽窗口规则错误拒绝；CLI还忽略伪造ID。

JSON/CSV保留来源编号，两个Verifier共用可信Scenario解析：显式编号唯一定位并核对归属、时间、轨道、对齐、姿态和资源；历史无编号仅在完整语义下唯一匹配时兼容。通信来源同样验证并重建。公共规划模型补齐来源中心、圈号和通信引用检查。

独立审核P2修正：公共ConstraintModel复用UTC解析器，在局部副本上归一带时区Assignment及已有计划的比较时间，支持等价非零时区，保留微秒和冲突规则。来源解析拒绝显式零、负数、非有限及非整数微秒步长；Loader仅对真正缺失/None的全局配置保留原1秒缺省，禁止把0或布尔值吞成1。新增15项独立回归，不修改旧测试夹具或认证时限。

Assignment签名、Worker/Controller信封、API请求、SQLite模式和冻结场景不改。旧结果不回写；历史歧义明确拒绝。新增解析源码纳入部署身份保护。窗口身份、规划可行及实际连续认证分别判断，正式门禁保留。

## 验证与审核

### 正式集成版本（R2-C6；R2-C7 文档收口）

- **INTEGRATION REVIEW PASS WITH CONDITIONS**。实际 HEAD 的原生 WSL 等字节源码副本完整默认回归497项：**489 PASS、8 SKIP、0 FAIL、0 ERROR，退出码0，150.717秒**。283个复制文件逐文件SHA/大小相等，18个场景输入只读引用并核对身份。I1 Registry17、I2来源31、P2 15、CAABS Core48联合111项均包含在该完整运行中。
- 真实 Orekit 非空小场景下，CAABS、Completion、Adaptive 均通过真实 Worker→Controller→可信 Scenario 来源核验，并进入真实连续认证；均因 `INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE` 被拒绝。没有注入成功证书。SQLite持久化运行诊断，但正式plans/assignments为0，JSON/CSV导出HTTP409；**完整真实非空正式成功入库及导出路径尚未验证**。
- 真实伪造来源、窗口错配、历史歧义及零步长在两个核验入口均被拒绝；真实活跃Worker取消、认证期间取消和搜索预算超时符合现有契约，六次Worker均正常回收。生产认证时限和发布门禁未放宽。
- **8项 Orekit opt-in 未运行**，不计为通过；**原挂载路径28条失败历史未全部归因或解决**，不因原生副本通过而关闭；**外部CSV消费者兼容仍待李泽同确认**。默认单元测试中的正向认证/存储/导出注入不是实际连续认证证据。
- 完整命令、退出码、源码/数据身份、真实运行ID、异常及历史日志见 [C6正式集成验收报告](caabs_i1_i2_integration_validation_20261018.md)。本次文档收口未重跑Python测试，也不将C6结果改写为C7新运行。

### Rebase 前历史验证（保留，不代表当前源码版本）

以下为原基线 `0a1a941` 时的修复与验证记录；其中“本轮”“当前基线”“本地origin/main未刷新”等均指当时状态，正式集成现状以上节为准。

- P2-1 RESOLVED；P2-2 RESOLVED，待人工复审。aware反例由未捕获TypeError/退出1变为可行/退出0；显式零步长由CLI接受变为两个入口在认证前统一拒绝。修复前的新增15项保留12个失败方法，修复后15/15通过。
- 最终同字节WSL本地源码副本：默认完整套件480项，472 PASS、8个原有Orekit opt-in SKIP、0 FAIL/ERROR，退出0。复制源码逐文件SHA校验，场景只读引用；未运行的opt-in不计为通过。
- I2原31项及新增P2 15项，包含公共ConstraintModel、两个Verifier、JSON/SQLite/导出单元往返和多算法；正式成功事务的正向案例使用UNIT_TEST_INJECTION_ONLY，不是实际物理认证闭环。实际工作树Core48项、Adaptive3项、连续流水线17项、认证身份40项均通过，曝光边界14 PASS/1 SKIP，各组退出0。git diff --check及新文件空白检查通过。
- 原Windows挂载路径首轮429 PASS / 28 FAIL / 8 SKIP的日志保留。其中2项Adaptive规划兼容回归已修正；其他时序/启动限制未改成PASS，不把本地副本通过等同于原路径全绿。
- 远端main实际仍为5e37ba720a9222a70d834d84e96c740601a3d236（已合并I1）；本轮独立临时文件组合Registry17、I2/P2 46、Core48、Adaptive3，共114/114通过，不执行Git merge或修改当前基线。正式整理到新main后仍需重新完整验收，COURSE_SETUP和公共接入文档须保留双方记录。本地origin/main未刷新。

契约及跨模块影响见 [来源契约](../assignment_source_window_contract_v1.md)。修复前后反例、完整命令、测试结果和环境限制见 [I2报告](caabs_i2_source_window_fix_20261018.md)。所有正向生命周期证书注入均为UNIT_TEST_INJECTION_ONLY，不是实际物理验收。

## 审核条件与剩余依赖

请李泽同确认公共身份范围、历史兼容、CSV增列和部署身份；何明涛关注原挂载路径进程/时序问题，其他算法负责人确认消费端使用。I1/I2实际集成版本已按C6验收，原报告的临时组合验证不能替代该证据。

具备提交 Draft PR 供人工审核的条件，尚不满足无条件合并 main 的条件：须经非作者审核、公共负责人签收，并明确身份修复合并与物理发布阻断的责任边界。如果合并要求真实非空成功入库/导出闭环，则仍须取得真实连续证明后补验。来源身份一致、离散约束通过、严格连续认证、正式发布资格分别判断。

本草稿不代表审核签署或发布批准；I2核心已提交，C6/C7文档尚未提交。本轮未暂存、提交、推送、Rebase、Merge或创建PR。
