# 独立 PR 草稿（未创建）

建议标题：`fix(scheduling): preserve and verify assignment source window identity`

分支 fix/source-window-i2；基线0a1a941（CAABS Core PR #17）。服务所有算法，不依赖I1修复，不修改Registry或CAABS搜索。

## 问题与改动

Assignment原有来源ID在公共输出时丢失。Verifier选首个时间包含窗口，导致合法窄窗口任务被宽窗口规则错误拒绝；CLI还忽略伪造ID。

JSON/CSV保留来源编号，两个Verifier共用可信Scenario解析：显式编号唯一定位并核对归属、时间、轨道、对齐、姿态和资源；历史无编号仅在完整语义下唯一匹配时兼容。通信来源同样验证并重建。公共规划模型补齐来源中心、圈号和通信引用检查。

独立审核P2修正：公共ConstraintModel复用UTC解析器，在局部副本上归一带时区Assignment及已有计划的比较时间，支持等价非零时区，保留微秒和冲突规则。来源解析拒绝显式零、负数、非有限及非整数微秒步长；Loader仅对真正缺失/None的全局配置保留原1秒缺省，禁止把0或布尔值吞成1。新增15项独立回归，不修改旧测试夹具或认证时限。

Assignment签名、Worker/Controller信封、API请求、SQLite模式和冻结场景不改。旧结果不回写；历史歧义明确拒绝。新增解析源码纳入部署身份保护。窗口身份、规划可行及实际连续认证分别判断，正式门禁保留。

## 验证与审核

- P2-1 RESOLVED；P2-2 RESOLVED，待人工复审。aware反例由未捕获TypeError/退出1变为可行/退出0；显式零步长由CLI接受变为两个入口在认证前统一拒绝。修复前的新增15项保留12个失败方法，修复后15/15通过。
- 最终同字节WSL本地源码副本：默认完整套件480项，472 PASS、8个原有Orekit opt-in SKIP、0 FAIL/ERROR，退出0。复制源码逐文件SHA校验，场景只读引用；未运行的opt-in不计为通过。
- I2原31项及新增P2 15项，包含公共ConstraintModel、两个Verifier、JSON/SQLite/正式导出往返和多算法；实际工作树Core48项、Adaptive3项、连续流水线17项、认证身份40项均通过，曝光边界14 PASS/1 SKIP，各组退出0。git diff --check及新文件空白检查通过。
- 原Windows挂载路径首轮429 PASS / 28 FAIL / 8 SKIP的日志保留。其中2项Adaptive规划兼容回归已修正；其他时序/启动限制未改成PASS，不把本地副本通过等同于原路径全绿。
- 远端main实际仍为5e37ba720a9222a70d834d84e96c740601a3d236（已合并I1）；本轮独立临时文件组合Registry17、I2/P2 46、Core48、Adaptive3，共114/114通过，不执行Git merge或修改当前基线。正式整理到新main后仍需重新完整验收，COURSE_SETUP和公共接入文档须保留双方记录。本地origin/main未刷新。

契约及跨模块影响见 [来源契约](../assignment_source_window_contract_v1.md)。修复前后反例、完整命令、测试结果和环境限制见 [I2报告](caabs_i2_source_window_fix_20261018.md)。所有正向生命周期证书注入均为UNIT_TEST_INJECTION_ONLY，不是实际物理验收。

请李泽同确认公共身份范围、历史兼容、CSV增列和部署身份；何明涛关注Worker来源往返，其他算法负责人确认实际ID输出。I1和I2集成后须重新验收实际组合版本。本草稿不代表审核签署；未提交、推送或创建PR。
