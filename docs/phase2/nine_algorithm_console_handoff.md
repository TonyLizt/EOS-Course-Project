# 九算法比较与初始排程模型（2026-10-18）

## 操作与语义

首页原「结果比较」改为「算法比较」。运行调度依次选择场景、初始排程模型、一个或多个比较算法，再按算法分别编辑参数并提交。每项沿用独立 Run ID、Worker、预算、取消、核验及结果存储，不新增批次状态或绕过正式认证。

比较算法固定为当前已有的九项：`mip`、`profit_first`、`timeliness_first`、`balance_first`、`pressure_repair`、`sa`、`ga`、`aco`、`ppo`。`completion_first` 和 `adaptive_repair` 从公共比较列表移至模型选择，仍保留旧 ID 的内部读取/求解兼容，旧历史不删除、不改写；新 HTTP 提交不能将它们当作比较算法。

技术上这两个模型仍是现有构造/修复调度器，不是新的轨道物理模型。适配器先运行所选模型生成 initial_schedule，然后调用所选比较算法的原 search。SA 真正从初始解搜索；GA/ACO 将初始解保留为 incumbent，再独立生成种群/蚁群。MIP、收益/时效/均衡启发式和压力修复主要自行建解，不因选择模型而改变核心策略（MIP 无候选时沿用初始解的旧回退不变）。UI 与算法详情明确此区别，不伪造组合算法效果。

模型阶段计入同一个 Worker 求解时间预算，adaptive_repair 的软预算为总预算三分之一；其余搜索沿用 Controller 硬预算。MIP 时间限制由总预算控制，MIP/ACO 内部机动参数与共享约束配置同步。Controller 仍独立核验最终结果。

## 可用性限制

本机七种算法可运行。MIP 缺 PuLP/CBC，返回 unavailable；PPO 缺 PyTorch，且现有推理尚未接入受信任模型与共享约束配置，始终禁用该 Web 入口。不自动安装依赖、不训练新模型、不加载任意用户路径、不用随机 PPO 代替训练成果。九项均显示，缺依赖/未完成接入者不可勾选，HTTP 提交返回 422。

## 接口与存储

- `/api/algorithms` 的 items 为九算法，新增 models 两项模型元数据；items 增加 availability_message 与 uses_initial_schedule。
- RunRequest / RunConfig 增加 `schedule_model`，仅允许 completion_first / adaptive_repair，默认前者。新比较适配版本 console-1；模型参数固定为现有默认及受控 seed/budget。
- 比较条件增加 schedule_model，不同模型不能混算单指标最佳。旧模型单独运行的历史不再加入九算法比较，但详情及可用可视化继续保留。
- `/api/runs` 列表增加 schedule_model 和 has_plan。仅为既有配置/受验计划的投影，无数据库模式迁移。旧配置未记录模型时显示 legacy_unspecified；旧幂等请求按默认模型规范化。

## Gantt 根因及修复

之前只有 `/visualization/gantt/{run_id}` 和承载绘图的 `/visualization/gantt-page?schedule=...`，没有 `/visualization/gantt`，直接访问会 404。现增加无 ID 的实验选择页，分页展示所有状态；仅有已核验计划的成功 Run 提供原 Gantt 链接。`/visualization/gantt?run_id=...` 也可直接转入指定运行，不猜测或擅自选择最新实验。原核验与失败拒绝逻辑不变。

## 实际验证

- Python 14 项定向测试通过（含已有修复调度器 3 项）：九算法/两模型分离、参数拒绝、所选模型传入适配器、七个真实 search 的小型合成单元场景、模型冒充算法/PPO 提交拒绝、预览存储及启动保护。
- Node 7 项通过：包括不同 schedule_model 必须分组、正式/预览隔离、指标方向和精确时间范围。
- 一次隔离 Chromium 回归：九项显示、模型下拉框、独立参数、单/多项提交、正式门禁拒绝、明示测试 receipt 的历史比较、Gantt 实验选择和跳转，以及原 Hover/键盘/触控/缩放。无页面异常。此测试历史不代表真实物理认证。
- 另一次真实小场景 Chromium：10 星 20 任务、seed 42、5 秒预算、规划预览、自适应修复模型；profit_first (`66ca77f2-0f21-4d53-8d0d-90ce63b257d7`) 与 timeliness_first (`222137c2-4c48-4b49-81c5-3bf671060273`) 均完成 20/20、TCR=1。真实 Worker/Orekit 采样，正式导出仍 409，比较和 Gantt 正常。
- 没有重跑所有算法大型场景、PPO 训练、MIP 求解、GPU 回放或完整 WCAG 审计。七算法小型单元测试不是七算法在大场景性能/物理认证的证明。
