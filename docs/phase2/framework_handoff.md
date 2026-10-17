> 历史专题记录：当前 v0.3.1 的实现、接口过渡与剩余分工见[修复集成交接](restore_integration_handoff.md)。下文保留当时的版本与验收语境。

# 第二阶段框架交接说明（v0.2.1 框架 + W1/W2 + 卫星回放 commit 1–6 及后续整合）

本文件记录 v0.2.1 框架、`feat/hmt-worker-ipc` 与卫星回放 commit 1–6 及其真实页面后续修正的系统边界，作为四位成员在同一框架上开发的入口。目标设计稿位于同目录的 `interface_design_target.md` 和 `database_design_target.md`；尚未实现的目标不能视为当前接口承诺。卫星回放的 commit 6 交付证据见 [`../replay/final-validation.md`](../replay/final-validation.md)，commit 6 后的兼容、视锥和交互修正见 [`satellite_replay_post_commit_6.md`](satellite_replay_post_commit_6.md)。

## 1. 当前闭环

2026-10-18 I2工作树待审核补充：公共计划输出保留观测/通信来源编号，两个Verifier按可信Scenario独立验证；历史歧义拒绝，不默认取首项。Worker/Controller信封、SQLite模式及认证门禁不改，详见 [来源契约](assignment_source_window_contract_v1.md)。本条不代表已合并或连续认证通过。

浏览器或 HTTP 客户端选择数据源、场景、算法和输出配置，提交实验。FastAPI 将配置写入 SQLite，Controller 启动独立参考 Worker，读取算法返回的计划，经共享约束模型复核后，把状态、计划、指标和事件持久化。结果可从数据库下载 JSON/CSV；若选文件输出，还会在指定目录下以运行 ID 为子目录保存相同内容。甘特图和 Cesium 页面按运行 ID 读取正式结果；轨道 CZML 按场景哈希缓存，卫星本体/固定载荷数据则每次从已提交结果只读派生。

入口：`python -m eos_system`。本地接口文档：`http://127.0.0.1:8765/docs`。默认只监听本机；同一数据库只运行一个 Controller 实例。

## 2. 模块边界

| 模块 | 当前职责 | 后续接入点 |
|---|---|---|
| `eos_system/api.py` | HTTP 参数和路径配置、资源列表、结果及可视化入口 | 前端只经 `/api` 调用；新增接口先更新契约文档 |
| `eos_system/storage.py` | SQLite 事务、迁移、运行/事件/导出记录 | 状态变化保持事务；新增列写显式迁移 |
| `eos_system/controller.py` | 排队、核验 Worker 独立进程身份后放行启动、取消与超时裁决、正式结果入库及安全停机 | 与李泽同核对 Controller 集成影响；独立 Daemon 另行接入 |
| `eos_system/worker_reference.py` | 独立 Worker、双单向 Pipe、协作取消和候选事件 | W3 大结果文件载体与跨重启恢复另行设计；进程身份及后代回收见 `worker_process.py` |
| `eos_system/algorithm_registry.py` | 算法规格、参数校验、`Solver` 协议、旧算法适配 | 四位成员按 `algorithm_integration.md` 注册算法 |
| `eos_system/exporting.py` | 数据库结果的 JSON/CSV 下载及文件输出 | 新导出格式以同一已入库快照为准 |
| `eos_system/visualization.py` | CZML 缓存与生成进程 | 梁兆榮完善 Cesium 和甘特图交互 |
| `replay/` 与 `replay_configs/` | 回放契约、输入完整性、manifest、任务阶段及可版本化显示配置 | 回放仅派生显示数据；不得向调度约束反向写入 |
| `replay/assets.py` | 校验资产 manifest、受控路径及实际 GLB 哈希，将模型资源纳入 cache identity | 资产变更必须得到新 identity；不向浏览器暴露服务器绝对路径 |
| `draw/cesium_viewer.html`、`draw/fixed-payload-state.js` 与 `draw/fixed-payload-geometry.js` | 按绝对时间求本体/载荷姿态，显示 GLB，用 Cesium WGS84 求逐星视锥、中心交点和覆盖 | 回放不可用时保留点/标签回退；正式链路总验收见 commit 6 |
| `draw/fixed-payload-view.js` | 从同一姿态输出相机 pose，固定光学 FOV/纵横比，为选中星驱动无独立时钟的第二 Viewer；活动任务显示地面点、ID 与经纬度 | 只读主时钟；隐藏后不渲染；不向姿态增加镜头自由度 |

## 3. 配置与路径

`data_sources` 表登记可读场景目录；`output_profiles` 表登记下载或文件输出方式。Windows 路径如 `C:\EOS-Bench\output_s1` 在 WSL 中转换为 `/mnt/c/EOS-Bench/output_s1`。目录登记由本机管理员执行；运行时仍检查场景文件属于已登记目录。输出目录必须可写，且不能与任何输入目录互相包含。默认数据源来自 `EOS_SCENARIO_DIR`，默认文件输出根目录来自 `EOS_RUNTIME_DIR/artifacts`。

本地运行文件、数据库和缓存统一放在 `EOS_RUNTIME_DIR`（默认 `~/eos-course-runtime`）；母场景只读，派生场景存入登记的运行目录。文件输出的每次实验有独立 `run_id` 目录。浏览器可同时保留下载方式。

## 4. 算法协作规则

算法作者实现 `solve(problem, constraints, context) -> Schedule`，可自行组织搜索、学习模型或中间状态，不要求共用单计划修复机制。`context` 提供种子、时间预算、取消检查和算法私有参数；算法必须返回可由共享核验器复核的最终计划。算法规格在 `algorithm_registry.py` 注册，记录 ID、版本、作者、类别和参数模型。完整示例与验收要求见 [`algorithm_integration.md`](algorithm_integration.md)。

各成员在自己的分支提交算法或系统模块，避免并行修改同一个注册表；集成时由李泽同统一登记、跑固定种子成对实验和完整 HTTP 闭环。刘懋兴提供场景来源与哈希清单，并参与机器学习算法；何明涛负责 Worker/IPC 和一项传统算法；梁兆榮负责界面、可视化和一项传统算法；李泽同负责整体集成与机器学习算法主导。

## 5. 可复现检查

```bash
python -m unittest discover -s tests -v
python scripts/smoke_system.py
PYTHONHASHSEED=0 MPLBACKEND=Agg python -m scripts.check_cli_parity
python -m scripts.check_plan_rejection
python scripts/check_visualization.py <已成功的运行ID>
```

前三项和可视化检查都依赖已经启动的服务或相应运行记录；纯单元测试独立执行。Cesium 轨道生成另需 `requirements-visualization.txt`，不影响基础调度。所有算法都要补充最小机制测试、可行计划回放及同场景同预算的成对实验；本版只验证参考框架，未声称完成组员的正式算法。

## 6. 当前限制

- 本分支 W1/W2 已实现协作取消、有界 IPC 传输、运行期限、可信同 Session 后代回收及 Controller 持锁停机；`cancel_ack` 只确认收到请求。已核验 Worker 的正常完成不等于任意逃逸后代或跨重启孤儿都能回收；W3 大结果传输和独立 Daemon 留待后续。
- 本地管理接口没有用户认证，服务应保持监听 `127.0.0.1`。
- CZML 首次生成需要 Orekit/JVM；页面依赖 Cesium 在线资源，离线展示需后续打包资源。
- Landsat 8 GLB 只是通用显示外观，不改变源场景的卫星 ID。模型—本体轴校准尚为单位四元数；当前姿态是几何指向示意，不是 Orekit 姿态或动力学验证。
- commit 4 已实现视锥、椭球中心交点、ECEF 覆盖和部分/无交点降级，但仍采用方形全角显示假设，不包含地形遮挡或真实成像验证；见 [`satellite_replay_commit_4.md`](satellite_replay_commit_4.md)。
- commit 5 已实现列表/地球/任务选星和与主时钟同步的固定载荷第二视图。第二 Viewer 显示的是地图/椭球模拟视野，不是真实遥感影像；见 [`satellite_replay_commit_5.md`](satellite_replay_commit_5.md)。
- commit 6 后已补齐正式 schedule UTC 相容、CesiumJS 1.136 模型姿态、任务精确跳转、半透明 3D 方锥、原生选取/追踪、callback/浏览器缓存防护、载荷任务标记和任务点俯视；见 [`satellite_replay_post_commit_6.md`](satellite_replay_post_commit_6.md)。这些仍是显示交互，不改变调度可行性或正式结果。
- 文件输出失败会留下数据库内已成功的计划与导出失败事件，便于重试；不会把有效计划改判为失败。

## 7. 实验数据清理

`DELETE /api/runs/{run_id}` 只接受终态实验，按外键依赖顺序在一笔 SQLite 事务内删除导出、指标、assignment、计划、事件、尝试和运行记录。Controller 完成成功状态与目录文件输出时持有同一进程锁，避免刚成功就被删除导致导出写入悬空。删除后执行 `VACUUM` 和 WAL 截断；若压缩被其他连接占用，删除仍有效，接口返回警告。

默认保留服务器目录文件；显式传 `delete_files=true` 时仅按登记路径、文件名和原始哈希删除本实验的正式 JSON/CSV，不递归删除目录中的其他内容。原始场景与按场景哈希共享的轨道缓存始终保留。浏览器提供确认步骤及列表翻页；此功能是永久删除，组员批量清理前应先导出需要保存的实验。
