# LAVIS 与 main PR #25 的 rebase 集成交接

日期：2026-10-19。分支：`feat/lavis-learning-scheduler`。本次由李泽同明确授权提交、rebase、推送并创建PR；不自动merge main。

## 1. 版本和范围

- 原基线：`2d8a808`（PR #24）。远端新基线：`7fcc77d`（PR #25）。
- 将前轮未提交的LAVIS与独立高冲突数据代码保存为`50660f3`，本地恢复分支`backup/lavis-before-pr25-rebase`指向它；rebase后的功能提交为`ab1fc4d`。
- 唯一文本冲突在`eos_system/runner.py`导入区：同时保留main的`deepcopy`（不可信诊断复制）和LAVIS的`replace`（冻结模型上下文注入）。没有整文件选ours/theirs，没有改写组员算法。
- 已自动合并的API继续使用`capture_execution_provenance`，开发限定来源仍只能planning_preview；保留runner诊断遥测、Controller期限、独立曝光核验、来源匹配和工程/正式导出区别。
- LAVIS仍按既定注册、参数、Worker与SQLite config_json接入；模型SHA参与实验身份和导出。没有数据库迁移，没有降低物理门槛。

## 2. 额外修复

main新增的`utils/attitude_frames.py`实际影响姿态和转向。LAVIS模型指纹现在同时绑定它、`utils/certification_identity.py`、`schedulers/scenario_loader.py`和`core/models.py`，避免只修改间接依赖时旧权重被误判为兼容。

新增回归覆盖：单独改变共享姿态模块读取内容会拒绝冻结模型；新候选构造保留n+1个四元数边界，非源网格曝光端点被拒绝。测试不修改真实物理源码、不伪造认证凭据。

## 3. 当前能用与不能用

| 项目 | 当前状态 |
| --- | --- |
| main原算法、来源门禁、姿态与Worker/Controller机制 | 保留；本轮定向回归 |
| LAVIS接口、冻结制品、训练/验证工具和历史档案 | 已集成 |
| 原lavis-v1 / v2 / v3权重 | 与当前代码指纹不兼容，明确拒绝，不改manifest |
| 原96个高冲突场景及旧共享场景 | 原物理证据不能直接复用于新合同；F033实测来源门禁拒绝 |
| 当前本机兼容生产模型 | 0，网页明确禁用LAVIS；不是规则/随机替代 |
| 原45.24%→47.34%、52场景物理通过等数字 | 历史版本结果，不代表本轮main验收 |
| 此次PR | 集成审核草稿；新物理数据与模型刷新未完成 |

不要给旧模型、侧车、规格或报告改SHA强行放行，也不要将旧的PASS贴到新物理模型。旧ZIP/原始数据/模型/数据库均未删除或改写；历史报告保留原值，额外增加current_applicability说明。

## 4. 开始新物理版本训练前还需完成

1. 数据负责人基于当前真实生成合同创建新版本数据根与规格；保留训练/验证/测试父来源隔离，不覆盖旧根，不从测试来源生成训练样本。更新公开划分中的真实场景SHA，不能只替换文件名。
2. 生成端显式传递卫星固定相机FOV、机动类型、跟踪角速度、传感器/任务最低仰角，保存初始姿态和源四元数边界。曝光端点须落在真实源网格；应选择合法曝光长度或细化真实采样，不能插值冒充存储边界。
3. 按main当前来源策略提供匹配的生成器/源码/Orekit/任务/窗口证据。`gen02.development.v1`只允许planning_preview，不能直接作为LAVIS当前physical_validation训练域的正式来源；工程共享来源与开发限定来源必须明确区分。
4. 李泽同更新离线数据版本/白名单接入，重新生成标签，使用新模型ID训练并记录新指纹；保留失败配置和同参数数据对照。不能复用旧标签缓存的协议SHA。
5. 使用当前物理模型重新做固定种子成对比较、独立曝光核验、真实HTTP/Worker/导出/回放验收后，才确认新推荐模型并决定PR是否转为可合并。最终测试继续冻结，由数据负责人在最终模型冻结后独立执行。

本次没有擅自进行新一轮大规模重建/训练；PR审核不能以旧验证数字替代上述工作。

## 5. 运行与协作

- 更新代码后先正常停止原后端并等进程退出，再按项目启动说明启动；不要继续使用加载旧代码的Controller，不删除锁。
- 前端继续从注册接口读取算法可用性和模型选项，不写死路径/ID。无兼容模型时禁用LAVIS是预期行为；旧orbit.czml GET兼容入口仍保留。
- 大型场景、标签、权重、ZIP、SQLite都不进Git。仓库只保存代码、小型公开规格、历史验证与本次集成说明。
- 每位组员从最新main另开分支开发，提交PR后合并；数据/算法/接口变化同步对应文档。此次PR合并仍由李泽同审核决定。

## 6. 本轮验证

完整计数、真实物理opt-in及限制见`experiments/reports/lavis_pr25_rebase_acceptance.json`。本轮目标是集成与门禁正确性，不签发新模型性能或当前全组场景的生产验收。


### 本轮实际结果

- 最终定向92项：91通过、1因WSL缺Node跳过；开启EOS_RUN_GEN02_PHYSICS=1和EOS_RUN_CAABS_REAL_E2E=1，实际执行新姿态、开发来源、P7来源、CAABS真实集成及LAVIS机制回归，176.033秒。没有声称92项全部是生产ML真实实验。
- Windows Node全部32项通过；实际14个算法/种子模型Schema渲染与校验通过，LAVIS旧模型失效时unavailable符合预期。
- 与origin/main逐文件比较：ConstraintModel、loader、visibility、continuous_exposure、attitude_frames、core数据模型、Controller、Worker和Daemon没有本分支差异。
- 原89项/23跳过仅是首轮未启用物理测试的检查，不与最终92项相加。正式连续证明、新物理版本ML训练和全仓库全量测试没有在本轮宣称完成。
