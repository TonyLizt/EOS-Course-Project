# 实验与算法 Run 管理（2026-10-18）

当前分支从回退后的 92f34d2 继续，复用旧实现中可审查的数据层，不恢复外层 iframe 工作区。

## 数据与事务

一个 Experiment 对应多个 Algorithm Run；实验拥有冻结的公共输入快照，各算法继续拥有原 Run ID、版本、专属参数、状态、事件、计划、指标及 Replay。Controller/WorkerIPC/核验协议不变。

SQLite schema v4 新增 experiments、experiment_runs。每个 Run 只有一个父实验；活跃成员由 `(experiment_id,algorithm_id) WHERE removed_at IS NULL` 唯一索引限制。实验状态从成员状态汇总，不引入新的 Worker 状态机。

`POST /api/experiments` 接收 1–9 个 RunRequest。先全部验证注册算法、参数、源场景 SHA 和来源，再验证公共条件一致，在一个写事务中创建父实验和所有 Run；重复算法、空间不足或任何无效项都不会留下半个实验。Idempotency-Key 绑定规范化配置而非随机 Run ID，网络重试不会重复创建。

## 初始模型和对照

completion_first 与 adaptive_repair 是现有构造/修复调度器，此处作为初始排程模型，不是轨道模型或新的 ML 模型。SA 使用所选模型的初始解，GA/ACO 保留其为候选最佳解；其他已有算法主要独立建解，此事实在 UI 中明示，不改核心策略伪造模型影响。

`POST /api/experiments/{id}/control` 只接受 schedule_model。复用原活动算法、专属参数与公共条件，重新核对当前场景、代码和来源，生成独立 Experiment/Run ID。创建事务内再次校验原成员，防止并发移除造成非单变量对照。EXPERIMENT_CONTROL_CREATED 事件在新 Run 中记录 source_experiment_id、changed_field、from/to；不修改原记录，重试幂等。

比较只允许当前实验内结果，或相同场景 SHA、代码/约束、种子、预算、目标、来源、输出、算法集合和专属参数下，仅模型不同的两个非 legacy 实验。已知指标 schema 不一致时拒绝；不能用失败或计划失效的记录显示成功指标。三种 UI 排序不改变这些边界，也不修改历史。

## HTTP 增量

| 接口 | 行为 |
|---|---|
| POST /api/experiments | `{runs:[RunRequest,...]}` 原子提交 |
| GET /api/experiments | 分页实验摘要，不为列表加载完整计划 |
| GET /api/experiments/{id} | 公共条件、算法 Run、对照来源 |
| POST /api/experiments/{id}/control | `{schedule_model:...}` 快速对照 |
| GET /api/experiments/{id}/peers | 合法模型对照候选 |
| GET /api/experiments/{id}/compare/{other} | 验证后返回两个实验，否则 409 |
| POST /api/experiments/{id}/algorithms | `{algorithm_id,algorithm_params}` 新增成员 |
| DELETE /api/experiments/{id}/algorithms/{aid} | 安全移除及取消，保留历史 |
| GET /api/runs/{rid}/experiment | 当前活动算法所属实验 |

添加算法重新核对冻结条件，拒绝混入新版本场景或代码；并发重复添加整体回滚。移除仅设置 removed_at，并在同一事务调用原取消协议：QUEUED 转 CANCELLED，RUNNING/VERIFYING 记录取消请求，由 Controller 回收；终态结果、文件和 Replay 不删除。重新添加产生新 Run。

原 `/api/runs` 保留兼容；公共配置不返回场景绝对路径。原 Schedule/Replay/Gantt API 仍是唯一数据源。Cesium Run 路由仍打开原 cesium_viewer.html，只增加 experiment_id 上下文。

## 迁移与恢复

v1/v2/v3 升级前在线备份为 `.pre-v4.bak`；已有同名备份时另建唯一名称 `.pre-v4.*.bak`，不覆盖旧备份。事务仅增加表/索引并设 user_version=4；原 v1/v2 的逐步迁移与 pre-v3 备份保留。已有 v4 可直接使用，对照来源使用现有事件表，无额外 schema 迁移。

历史 Run 没有批次证据时按单次 legacy 承接，不凭相近时间猜测合并，也不自动作为公平模型对照。被移除的成员不因重启重新导入。升级前应等任务结束并停止旧服务；回退到只支持 v3 的旧代码不能直接打开 v4，需使用备份或明确迁移，禁止仅修改版本号冒充兼容。

## 定向验证

27 项 Python 检查通过：实验原子性/幂等、模型对照及独立 ID、并发成员重验、冻结场景拒绝、移除/取消/重加、备份不覆盖、v1/v2/v3 保留迁移、旧算法/预览门禁与 CLI 保护。完整 UI、真实小场景及剩余限制见下一提交的统一交互交接。本轮不修改正式运行库、不自动启动 8765、不 Push/PR。
