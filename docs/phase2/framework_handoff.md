# 第二阶段框架 v0.1 交接说明

本文件描述**当前代码实际实现**，用于四人接入。目标接口与 ER 图已随仓库放在 [`interface_design_target.md`](interface_design_target.md)、[`database_design_target.md`](database_design_target.md)；两份是审核稿，尚未实施的字段按文件开头提示处理。启动命令和版本记录见仓库根目录的 `COURSE_SETUP.md`。

## 1. 当前可运行链路

```text
浏览器（配置、状态、计划表格、JSON/CSV）
    → FastAPI / Controller（单服务进程）
    → spawn 最小参考 Worker（独立进程，现有算法）
    → 候选计划 JSON 经 Pipe 返回
    → Controller 按同配置重建并核验计划
    → SQLite 事务写入 plans + assignments + metrics + SUCCEEDED
    → 页面与导出从 SQLite 读取
```

当前只有已有 `completion_first` 和 `adaptive_repair` 两个算法可选，均视为基线，不冒称 A/B/C/D 已完成。参考 Worker 支持真实进程、启动/阶段/候选/失败事件，Controller 可强制终止单个 Worker；它不代替何明涛负责的控制线程、协作取消、进程组后代回收、大结果文件通道和完整故障测试。独立 Daemon、Cesium、交互甘特图、ML D 也尚未接入。

## 2. 代码地图

| 文件 | 职责 | 扩展时注意 |
|---|---|---|
| `eos_system/config.py` | WSL 运行目录、场景登记和 SHA-256 | 正式场景清单由刘懋兴替换/扩充；保留只读和 ID→路径边界 |
| `eos_system/contracts.py` | HTTP/Worker 共用配置与算法白名单 | A/B/C/D 在这里增加参数模式和注册，不透传任意 Python 对象 |
| `eos_system/runner.py` | 复用 `SchedulingProblem`、`ConstraintModel`、`SchedulingEngine` | 算法返回内存计划，保持旧 CLI 可运行 |
| `eos_system/verification.py` | Controller 重建 assignment、检查来源窗口/资源/约束并算指标 | Worker 报告不成为正式计划或指标；变更约束时同步验证 |
| `eos_system/worker_reference.py` | 最小参考进程及 JSON 字节 IPC | 何明涛负责完善，可替换实现但保留消息字段与纯数据协议 |
| `eos_system/controller.py` | 持久排队、状态、启动 Worker、取消/预算、单实例锁 | 替换 Worker 时沿用 run_id/attempt/seq 去重与状态事务 |
| `eos_system/storage.py` | SQLite 七表、事务与查询 | 仅 Controller 正式写入；迁移时提升 `PRAGMA user_version` |
| `eos_system/api.py` | HTTP 与数据库导出 | 前端只调用此层；`scenario_path` 不返回浏览器 |
| `eos_system/web/` | 零构建依赖的临时操作页面 | 梁兆榮可重做 UI，不应绕过 API 直读文件 |
| `eos_system/prepare_demo.py` | 只读母场景→固定小实例 | 只在显式运行时产生文件，不在服务启动时自动切分 |

## 3. 运行配置与文件位置

- 权威代码仓库：Windows `D:\Code\EOS-Course-Project`，WSL `/mnt/d/Code/EOS-Course-Project`。
- 原始母场景：Windows `C:\EOS-Bench`，WSL `/mnt/c/EOS-Bench`，只读。
- 默认运行目录：WSL `~/eos-course-runtime/`；场景在 `scenarios/`，虚拟环境在 `.venv/`，结果库为 `results.sqlite3`，锁为 `controller.lock`。
- 环境变量：`EOS_RUNTIME_DIR` 可以指定整个运行目录，`EOS_SCENARIO_DIR` 可以指定场景登记目录。数据库不要放到 `/mnt/c` 或 `/mnt/d`。
- 浏览器地址：`http://127.0.0.1:8765/`。不启动多 Web worker 或 `--reload`。

## 4. 公共契约

`POST /api/runs` 接受登记的 `scenario_id`、`algorithm_id`、白名单 `algorithm_params`、`seed`、`placement_mode`、约束、权重和 `time_budget_s`；服务器补齐 `run_id`、场景哈希与路径、算法版本和创建时间。查询：`GET /api/scenarios`、`GET /api/algorithms`、`GET /api/runs`、`GET /api/runs/{id}`；取消：`POST /api/runs/{id}/cancel`；导出：`GET /api/runs/{id}/export?format=json|csv`。详细字段以 FastAPI `/docs` 及 `contracts.py` 为当前实现依据。

Worker 事件包：`protocol_version=1`、`run_id`、`attempt`、严格递增的 `seq`、`kind`、`sent_at`、`payload`。现有事件 `started`、`heartbeat`（含 `phase`）、`candidate_result`、`failed`；Controller→Worker 现有 `start`。参考 Worker 还没有实现 `cancel_ack`，当前取消由 Controller 强制终止该进程。`candidate_result` 只含候选计划与算法搜索秒数，不直接触发成功。

数据库中的 `QUEUED` 是排队真相，重启会继续取出；旧 `RUNNING/VERIFYING` 在 Controller 重启时保守标记 `FAILED`，不信任可能迟到的旧进程消息。一个 `run_id` 只能有一个正式计划，成功事务同时写 `plans/assignments/metrics/runs.status`。结果导出只从正式库生成。

## 5. 组员接入顺序

1. **何明涛**：先跑 `scripts/smoke_system.py`，再将 `worker_reference.py` 拆成 Worker 入口、IPC 和运行管理；`controller.py` 可改为使用其稳定的 `start_worker/poll_events/request_cancel/reap_worker` 接口。重点补充后代回收、大计划和取消/超时测试。
2. **刘懋兴**：提供固定场景 ID、路径、哈希与来源分组，先替换 `config.py` 中的目录扫描登记，避免把所有 JSON 当正式实验场景；实验脚本调用 API 或统一 runner，保留输入 SHA。
3. **梁兆榮**：页面只消费 `/api`；升级视觉和比较功能时保持配置与计划来源一致。Daemon 读取 `/api/health`，只监护 Controller，不直接写正式 DB。
4. **李泽同**：维护公共契约、数据库迁移、Controller 状态/事务和 D 算法注册；公共字段变更先同步四人并更新此文档。

## 6. 已知边界与验证

- 参考 Worker 只有小结果 Pipe（上限 4 MiB）；超限进入失败状态。何明涛的正式实现要加隔离目录的原子临时文件与哈希。
- 当前取消终止 Worker 主进程；算法自行启动的后代进程尚无完整清理保证。只开放当前不启动额外进程的两个基线算法。
- Controller 单实例、一个参考 Worker 并行；`Settings.max_workers` 留作后续并发实现，当前请保持 1。
- 运行时环境依赖由 `requirements-system.txt` 说明；Java/Orekit 不在基础网页的启动门槛内。
- 测试：`python -m unittest discover -s tests -v` 检查旧算法、事务与 IPC 去重；服务运行后 `python scripts/smoke_system.py` 检查真实 HTTP、进程、库和两个导出，`PYTHONHASHSEED=0 MPLBACKEND=Agg python -m scripts.check_cli_parity` 与旧 CLI 逐条对照，`python -m scripts.check_plan_rejection` 验证篡改资源量不能过核验。对照脚本使用自动清理的临时目录。每次更换 Worker、场景登记或算法注册后复跑。
