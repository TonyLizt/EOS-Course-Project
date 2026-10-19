# feat(lavis): 集成学习调度与高冲突数据工具，rebase 到最新 main

## 概要

- 新增LAVIS学习型分配价值调度、受控模型ID/清单/SHA冻结、Worker与Controller核对、实验身份与JSON导出追溯；网页从注册表读取模型选项。
- 提供离线标签、HGB训练、相对排序改进、消融与数据控制工具；提供48个独立合成轨道家族/96场景的生成工具、小型公开规格和历史验证档案，大型数据/标签/权重/数据库不进Git。
- 补充README、COURSE_SETUP、数据与算法交接，以及本次main物理版本迁移说明。

## Rebase与集成

已从PR #24基线rebase到origin/main `7fcc77d`（PR #25）。runner导入冲突同时保留deepcopy与replace；main的开发来源执行模式路由、Nadir相对姿态、相机FOV/跟踪、初始姿态/四元数边界、Controller期限与独立核验均保留。

模型指纹额外绑定共享姿态数学、物理身份、场景loader和core数据模型；新增间接依赖改变时拒绝旧权重、四元数n+1边界及非源网格端点拒绝回归。没有数据库迁移，没有放松物理/来源门禁，没有修改main算法或生命周期实现。

## 验证

- 最终定向92项：91通过、1项因WSL缺Node跳过；开启真实GEN02物理和CAABS集成测试，176.033秒。
- Windows Node 32项通过；实际14个注册Schema渲染/校验通过，失效LAVIS制品明确unavailable。
- git diff --check通过；main的共享物理、Controller、Worker、Daemon文件逐字保留。

## 为什么先提交草稿

**当前不能将本PR当作可直接使用旧v3权重的生产交付。** PR #25修改物理合同后，原lavis-v1/v2/v3与旧96场景的来源证据不再兼容。本机实测旧v3返回LAVIS_INCOMPATIBLE_MODEL、旧F033来源拒绝，目前兼容生产模型0。没有手改manifest/侧车哈希，也没有用规则/随机策略冒充ML。

历史715/900、45.24%→47.34%以及52场景曝光核验数字均已明确标为旧物理版本记录，不能作为当前main验收。后续需新版本场景/来源隔离划分、重打标签、重新训练及独立物理/HTTP/回放验收，然后再决定转为可合并。最终测试始终未使用。

## 交接

- `docs/phase2/algorithms/lavis_main_rebase_handoff.md`：冲突处理、兼容状态、启动注意与下一步数据/模型迁移。
- `experiments/reports/lavis_pr25_rebase_acceptance.json`：本轮实际测试和明确未完成项。
- `docs/phase2/algorithms/lavis.md`、`lavis_conflict_expansion.md`：历史算法与数据结果，顶部已标注适用范围。

更新代码后正常停止旧后端、等待退出再启动，不删除锁。此PR不自动merge main，供李泽同和组员审核。
