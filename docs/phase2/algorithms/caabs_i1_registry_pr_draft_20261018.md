# PR草稿（未创建）

建议标题：`fix(registry): register CAABS through shared Solver contracts`

基线：`0a1a9418659be9d7b9e4dad90484ac2cd087c593`（CAABS Core PR #17已合并）。分支：`fix/caabs-registry-i1`。建议目标：main；本轮未提交或创建PR。

## 问题与改动

公共get_algorithm("caabs")在本基线抛“算法未登记”，而CAABS实现已存在。两种原始导入顺序均成功；循环导入是直接反向eager登记会触发的依赖风险，不是当前基线已发生的异常。

将AlgorithmParams/SolveContext/Solver的原定义移到独立algorithms.solver_contracts，Registry继续重导出原公共名字；CAABS只改该import。Registry显式登记caabs，复用原CAABSParams及VERSION=0.1.0，直接构造ConflictBeamScheduler。旧工厂、旧两算法及适配行为保持不变，不改搜索、规范键或SafeConflictIndex。

## 验证

- 项目WSL共91项：90 PASS、0 FAIL、0 ERROR、1个原有Orekit opt-in SKIP；各命令退出0。
- 新增17项包括独立进程双向导入、Registry独立查询/验证/构造、严格参数负例、类型兼容、非空候选公共约束重放、真实Runner接线及GET /api/algorithms的ASGI响应。
- CAABS Core48/48、旧Adaptive3/3、Transition4/4、选定Registry/Worker4/4通过；公共曝光14/15通过加1跳过。
- Windows Core48/48；新增17中16通过、1因缺FastAPI跳过。原始公共测试的POSIX/依赖错误保留，未修改测试或Worker规避。
- git diff --check及新文件空白检查通过。完整命令、日志、本机证据位置和修复前后表见 [I1报告](caabs_i1_registry_fix_20261018.md)。

## 影响与限制

本PR仅I1。不修改I2来源窗口、公共约束、连续证书、Controller发布门禁、Worker协议、数据库或冻结场景。Registry接入通过不等于完整系统/正式发布通过。没有运行全量默认测试、真实场景benchmark或正式认证。

请李泽同重点审核共用契约层及旧导出兼容、CAABS登记元数据/构造边界；I2在独立修复中验收。本草稿不代表已有审核签署。
