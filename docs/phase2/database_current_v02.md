# 当前数据库设计与 ER 图（v0.2.0）

> 2026-10-18：Run 配置 JSON 增加 schedule_model，列表投影增加模型与 has_plan；没有 SQL 模式迁移，旧历史不改写。详见[九算法存储说明](nine_algorithm_console_handoff.md)。

> 2026-10-17：新增规划预览，无 SQL 模式迁移。现有计划与指标通过配置 execution_mode 和 PREVIEW_VALIDATED 事件区别于正式认证，历史结果不改写。见[预览存储契约](planning_preview_handoff.md)。

本文件描述已落地的 SQLite 物理模式。完整字段和约束以 `eos_system/storage.py` 为准；`database_design_target.md` 是后续目标审核稿。

```mermaid
erDiagram
    DATA_SOURCES ||--o{ RUNS : selects
    OUTPUT_PROFILES ||--o{ RUNS : selects
    RUNS ||--o{ RUN_ATTEMPTS : starts
    RUNS ||--o{ RUN_EVENTS : records
    RUNS ||--o| PLANS : verifies
    PLANS ||--o{ ASSIGNMENTS : contains
    PLANS ||--|| METRICS : evaluates
    RUNS ||--o{ EXPORTS : produces
    DATA_SOURCES { TEXT source_id PK
                   TEXT name
                   TEXT root_path UK }
    OUTPUT_PROFILES { TEXT profile_id PK
                      TEXT name
                      TEXT kind
                      TEXT root_path UK }
    RUNS { TEXT run_id PK
           TEXT source_id
           TEXT scenario_id
           TEXT scenario_sha256
           TEXT algorithm_id
           TEXT output_profile_id
           TEXT config_json
           TEXT status }
    RUN_ATTEMPTS { TEXT run_id PK
                   INTEGER attempt_no PK
                   INTEGER worker_pid
                   TEXT outcome }
    RUN_EVENTS { INTEGER event_id PK
                 TEXT run_id
                 TEXT source
                 TEXT event_type }
    PLANS { TEXT run_id PK
            TEXT plan_json
            TEXT plan_sha256 }
    ASSIGNMENTS { TEXT run_id PK
                  INTEGER ordinal PK
                  TEXT task_id
                  TEXT assignment_json }
    METRICS { TEXT run_id PK
              INTEGER completed_tasks
              INTEGER total_tasks
              REAL TCR }
    EXPORTS { INTEGER export_id PK
              TEXT run_id
              TEXT format
              TEXT status
              TEXT artifact_path }
```

`runs.source_id` 和 `runs.output_profile_id` 保存用户选择；`config_json` 同时保留提交时实际解析的路径、哈希、算法参数和时间预算。目录登记项变化不会改写历史实验配置。登记表没有级联删除关系。正式计划、assignment 和指标只由 Controller 在共享约束核验成功后写入同一事务。导出记录可多次产生，不替代正式结果。

数据库启用 WAL、外键和写事务 `BEGIN IMMEDIATE`。`PRAGMA user_version=2`；首次建库直接建 v2，已有 v1 库由程序启动时在事务中增加登记表、`runs` 的来源/输出 ID 和 `exports` 的文件路径/失败原因，并保留旧实验。独立 Daemon 尚未写入该库。

v0.2.1 的逐条清理不改变表结构。只有终态 `runs` 可删除；关联的 `exports`、`metrics`、`assignments`、`plans`、`run_events`、`run_attempts` 在同一事务内先于 `runs` 删除。提交后执行 `VACUUM` 和 WAL 截断，尽量立即回收空间；失败时空闲页仍可被未来实验重用。该操作不会级联删除数据源、输出方案或其他实验。
