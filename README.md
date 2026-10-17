# EOS-Course-Project：地球观测卫星任务调度课程系统

本仓库是**操作系统原理课程设计**项目。我们在 [EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench) 的场景、约束、算法基线和可视化代码之上，构建可以由浏览器操作的调度实验系统。项目重点是把一次实验从配置、独立进程执行、进程间通信、结果核验，到持久化和回放连接起来，并让不同组员实现的算法在同一输入与约束下比较。

本项目不是 EOS-Bench 官方仓库。上游研究平台、论文和数据的出处见[来源与致谢](#来源与致谢)；课程系统的新增实现主要位于 `eos_system/`。

当前六场景接入、规模预算和验收见[六场景交接](docs/phase2/six_scenario_scale_handoff.md)，历元修正场景的发布与 TCR 证据见[修正场景发布交接](docs/phase2/epoch_fixed_release_handoff.md)；基础框架恢复记录见[修复与集成交接](docs/phase2/restore_integration_handoff.md)。接口/数据库审核稿中的未来功能与当前实现已分别说明。

## 背景与目标

地球观测卫星需要在有限的可见窗口中安排拍摄和下传任务，同时满足卫星姿态切换、传感器、存储、电量和地面站等约束。EOS-Bench 提供场景与统一调度内核。课程第二阶段进一步关注操作系统层面的真实进程、IPC、排队、同步、取消、故障恢复，以及可复现的算法实验。

本组计划完成三种机制不同的传统算法和一种机器学习算法。新算法会通过同一注册、运行和核验边界进入系统；本仓库当前可选的 `completion_first`、`adaptive_repair` 属于已有基线，**不计作这四种新算法的交付**。

## 当前能力（v0.3.4 几何一致性与修正场景发布）

- 浏览器选择**已登记的数据源、场景、算法和输出方案**，提交、取消并查看实验状态与正式结果。
- 启动时递归登记六份已发布的 `epoch_fixed_v1` LFS 场景（小型 4、中型 2），相对仓库定位；只有匹配 SHA、物理 PASS 和 release sidecar 的修正版会替代选择器中的 legacy 版本。未完成候选不会隐藏可用 legacy 场景，`provenance/` 也不会被误列成场景。
- FastAPI 和 Controller 在 WSL2 中运行；Worker 由 `spawn` 创建，通过两条单向 Pipe 交换控制消息和 JSON 事件。Worker 执行 `setsid()` 并报告 `started`，Controller 核验本次进程的 Linux 身份后才发送 `start`；候选由 Controller 独立核验，并在成功事务中写入 SQLite。
- 算法注册表统一元数据、专属参数模型和 Worker 创建入口。现有算法经适配器接入；新算法可从空计划开始，不必沿用旧启发式流程。
- 浏览器下载 JSON/CSV；选择目录输出方案后，成功实验还会在该目录的 `run_id/` 子目录保存正式文件。SQLite、锁和缓存默认位于 WSL Linux 文件系统。
- 结果页复用甘特图和 Cesium 页面。甘特图读取同一 `run_id` 的正式计划；Cesium 轨道按场景 SHA-256 生成并缓存，并可显示 Landsat 8 示意本体、确定性任务姿态与固定载荷指向。轨道生成需要可选的 Java/Orekit 依赖和浏览器可访问 Cesium 在线资源。
- 实验列表可翻页；在详情中可永久删除已结束的实验。删除会清理 SQLite 中该实验的配置、事件、尝试、计划、指标和导出记录，并尝试压缩数据库。

当前分支的 W1/W2 已接通运行中协作取消、IPC 期限与已核验同 Session 后代的安全回收；`cancel_ack` 只确认收到取消，不代表 Worker 或后代已退出。Controller 停机时须等待后台执行线程结束，未结束则保留单实例锁。超过 4 MiB 的大结果文件通道（W3）、独立 Daemon、四种新算法、完整结果比较页面及跨 Controller 重启的孤儿回收仍未交付。能力和限制见 [W2 实施记录](docs/phase2/W2%20WorkerIPC%20%E4%B8%8E%20Controller%20%E5%8D%8F%E4%BD%9C%E5%AE%9E%E6%96%BD%E8%AF%B4%E6%98%8E%20v1.0.md)。

## 运行流程

```text
Windows 浏览器
   │ HTTP：登记目录、提交实验、查看状态和结果
   ▼
WSL2：FastAPI / Controller ─── SQLite（配置、事件、正式计划、指标）
   │  两条单向 Pipe；一次实验对应一次 Worker 尝试
   ▼
独立 Worker ── 场景只读加载 ── 算法求解 ── 候选计划
   │                                   │
   └──────────── Controller 重新核验 ─┘
                         │
              JSON/CSV 下载、目录文件、可视化回放
```

正式计划与指标来自 Controller 核验后的数据库记录。Worker 不写正式数据库；原始母场景保持只读。浏览器提交的是登记 ID，不能把任意磁盘文件路径作为一次实验输入。

## 环境与快速启动

推荐环境：**Windows + WSL2 Ubuntu 22.04 + Python 3.10**。Windows 保存代码、打开浏览器；FastAPI、Controller、Worker、调度内核和 SQLite 都在 Ubuntu 中运行。课程代码示例位置为 Windows `D:\Code\EOS-Course-Project`，在 WSL 中对应 `/mnt/d/Code/EOS-Course-Project`。数据根目录示例为 Windows `C:\EOS-Bench`，对应 `/mnt/c/EOS-Bench`；路径可以通过登记界面更换。

首次准备（在 Ubuntu 终端执行）：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
mkdir -p ~/eos-course-runtime
python3 -m venv ~/eos-course-runtime/.venv
cd /mnt/d/Code/EOS-Course-Project
~/eos-course-runtime/.venv/bin/python -m pip install -r requirements-system.txt
~/eos-course-runtime/.venv/bin/python -m eos_system.prepare_demo --data-root /mnt/c/EOS-Bench
~/eos-course-runtime/.venv/bin/python -m eos_system
```

然后在 Windows 浏览器打开 <http://127.0.0.1:8765/>；接口文档位于 <http://127.0.0.1:8765/docs>。服务只绑定本机地址；当前版本请保持一个服务进程，不使用 `--reload` 或多 Web worker。运行目录可由 `EOS_RUNTIME_DIR` 指定，默认 `~/eos-course-runtime`；默认场景目录可由 `EOS_SCENARIO_DIR` 指定，默认是该目录下的 `scenarios/`。

`prepare_demo` 只读取 `C:\EOS-Bench` 下的母场景，将固定小实例写入运行目录。若尚未取得该数据，可直接在页面登记已有场景 JSON 所在目录；**不需要把大型数据放进 Git 仓库**。

### 选择数据与输出位置

页面的“登记新的数据源或输出目录”接受 Windows 盘符路径或 WSL 绝对路径，服务端会检查目录。数据源直接列出该目录下的 `.json` 场景；实验保存数据源 ID、场景路径和 SHA-256 快照。输出方案包括浏览器下载、WSL 运行目录文件，也可登记另一个已存在的目录。文件输出按 `run_id` 隔离；浏览器下载到 Windows 的具体文件夹由浏览器设置决定。

SQLite、虚拟环境与高频运行文件应放在 WSL Linux 文件系统。选择 Windows 目录保存最终 JSON/CSV 是可以的，但它不会改变数据库的位置。数据源和输出目录不可重叠。

### 删除不需要的实验

在实验列表中选中一条**已结束**的实验，点击“永久删除实验”并确认。排队、运行和核验中的实验要先取消，等进入终态后才能删除。列表支持翻页，因此较早的实验也能找到。删除后，计划与指标无法从系统恢复；SQLite 会尝试立即压缩，若当时被其他连接占用，空闲页仍可供后续实验复用，页面会提示压缩未完成。

默认只删除数据库记录。若勾选“同时删除本实验在服务器输出目录中的正式 JSON/CSV 文件”，系统仅删除与该实验记录的路径和 SHA-256 一致、且未被修改的文件；其他文件会保留并在页面提示。输入场景和可能被多条实验共用的 CZML 缓存不会删除。接口为 `DELETE /api/runs/{run_id}`，可选 `delete_files=true`。

### 可选的 Cesium 轨道回放

甘特图不需要 Java。若要在结果页点击“Cesium 回放”，先在同一虚拟环境中安装轨道依赖：

```bash
cd /mnt/d/Code/EOS-Course-Project
~/eos-course-runtime/.venv/bin/python -m pip install -r requirements-visualization.txt
```

成功实验首次打开 Cesium 页面时，页面先 GET 状态；若为 NOT_REQUESTED，会自动 POST 一次构建并轮询 BUILDING/READY。构建读取已冻结的正式场景和计划，不会重新运行调度算法。自动申请或构建失败后停止自动重试，显示“重试构建回放”供用户确认。Cesium 页面从同一个 manifest 读取五种 READY 资源；选星、播放、拖动和跳转只消费已有样本，不会重复构建。配置 ID 从 `GET /api/replay-configs` 获取，当前默认 `fixed-payload-illustration-v1`。

轨道位置现在使用真实 60 秒 Orekit 节点和局部五阶插值，CZML 与 READY 消费端采用一致的曲线插值规则；旧缓存保留，新构建由既有步长及源码身份隔离。姿态自适应采样和 SLERP 不变。三轨道局部精度及稀疏历史数据限制见[轨道插值验收](docs/phase2/orbit_interpolation_fix_2026-10-17.md)；此修复不会重算正式调度计划。

连续曝光验收可独立运行 `python -B verify_schedules.py SCENE PLAN --continuous --orekit-data ZIP --min-elevation-deg 5 --report NEW_REPORT`，只读取已有计划，不运行求解器。退出码 0/1/2 分别为 PASS/FAIL/INCONCLUSIVE；采样无违规不等于连续性已证明，2 不应放行。依据及四计划结果见[连续曝光修复报告](docs/phase2/continuous_exposure_boundary_fix_2026-10-17.md)。

回放由独立进程只读正式计划及场景生成，服务校验输入/计划/配置/模型与资源哈希后发布，不修改正式 assignment 或 metrics.RT。轨道缓存身份包括历元解析与传播环境，旧 v1 缓存不会冒充修复后的 v2。姿态首选 5 秒，按时域/星数/任务端点余量确定有效步长，目标 100000 样本；本批 10/20/50 星约 10/20/135 秒，保留任务和转向端点。硬上限仍为 200000 样本、每资源 64 MiB。

页面保留甘特图、卫星本体、独立视锥、WGS84 椭球覆盖、选星/追踪、任务点俯视、精确任务跳转和同钟固定载荷视图。卫星 CZML 点不再绘制，标签与轨道线保留。主跟随相机明确使用由卫星位置生成的 ENU 框架，不读取卫星本体姿态；因此本体与固定镜头仍按回放 quaternion 机动，而使用者相机不会随姿态或自动参考框架判定翻转。任务列和 Fixed Payload View 选星会同步主 Viewer 的选中实体；若使用者已开启跟随，跟随对象同步切换，否则不会擅自开启跟随。主地球支持鼠标滚轮、右键拖曳、触屏 pinch，以及 Chromium/Safari 类触控板双指捏合缩放。NASA Landsat 8 仅作为通用外观，原卫星 ID 不改名；安装旋转与方形完整 FOV 是明示的展示假设，几何指向与 SLERP 不等于真实动力学或拍摄成功。非敏捷星只给对地示意。模型来源见[资产说明](docs/replay/landsat8-validation.md)。

Fixed Payload View 以单一序列 renderer 隔离各卫星相机工作；imagery/terrain 完成且连续稳定两帧后才把 framebuffer 原子提交到对应 tile，避免多相机轮巡造成 LOD/旧瓦片频闪。可用 `debug_payload=1` 查看固定载荷专用诊断；细节与 GPU 限制见[频闪修补交接](docs/phase2/fixed_payload_flicker_handoff.md)。

实验保存原场景绝对路径和 SHA-256。若目录之后搬移，回放可在其他已登记数据源中找到同一 `scenario_id`，但只有字节 SHA-256 与正式实验完全一致时才采用；不会用同名的新场景替换历史输入。

**旧 `GET /api/runs/{run_id}/visualization/orbit.czml` 继续保留到组员完成前端迁移复核。**当前课程页面已改读 READY 资源；旧 `visualization/replay` GET 只读取同一 READY 文档，未构建时返回 409。旧配置 `geometry-illustration-v2` 与离线 CLI 暂保留为兼容入口。

### 数据版本与当前限制

保留数据 Manifest 审计、E1 确定性历元解析与 E2 独立重算工具；新实验保存场景来源快照。来源不明的历史数据标为 `legacy_unknown`；E2 待验收候选不得因登记目录自动转成正式实验数据。六个 bundled 场景已按正确轨道历元重算并通过静态谱系、完整曝光地球遮挡和 completion-first 发布门槛：四个小场景三 seed 均为 100% TCR；中型 S1 为 94%～95%，S2 为 98%。中型场景各有两个任务没有足够长的物理窗口，因此不伪造 100% 覆盖。历史 legacy 文件继续供既有 run 按原 ID/SHA 解析。四种新算法、W3、Daemon 和最终比较页面仍待开发。

SQLite 模式为 v3；回放文件位于运行目录的 `replays/`。删除终态实验同步清理本实验派生缓存，BUILDING 时拒绝删除；共享轨道缓存不随单个实验删除。两视图使用随 Cesium 发布的底图，避免依赖个人 Ion token；脚本/底图仍从固定版本 CDN 加载，离线资源包尚未交付。

### 使用内置六场景

确认 Git LFS 的实际 JSON 已下载，安装系统与可视化依赖后启动。在数据源选择“刘懋兴场景 · 小型（4份）”或“中型（2份）”，无需复制文件或手工填本机路径。中型场景建议先用默认 60 秒预算，1 秒可能正常超时。

回放采用流式静态投影，减少重复加载大窗口数组；原调度约束语义保持，提交仍重算源 SHA。数据来源继续为 legacy_unknown，不代表 E3/E4 通过。结果表、复测和限制见[六场景交接](docs/phase2/six_scenario_scale_handoff.md)。

## 开发与验证

```bash
cd /mnt/d/Code/EOS-Course-Project
~/eos-course-runtime/.venv/bin/python -m unittest discover -s tests -v
# 以下脚本要求另一个终端已启动 python -m eos_system
~/eos-course-runtime/.venv/bin/python scripts/smoke_system.py
PYTHONHASHSEED=0 MPLBACKEND=Agg ~/eos-course-runtime/.venv/bin/python -m scripts.check_cli_parity
~/eos-course-runtime/.venv/bin/python -m scripts.check_plan_rejection
# 安装可选轨道依赖后，传入任一成功实验的 run_id
~/eos-course-runtime/.venv/bin/python scripts/check_visualization.py <run_id> --build
node tests/fixed_payload_state.test.cjs
node tests/fixed_payload_geometry.test.cjs
node tests/fixed_payload_view.test.cjs
node tests/replay_acceptance.test.cjs
node tests/satellite_follow.test.cjs
```

可选真实浏览器相机连续性测试位于 `tests/browser/camera-continuity-smoke.*`；它以 60x 连续运行约 31 秒，并覆盖暂停、继续、切星、本体姿态持续变化与主相机方向/距离突变检查。

组员开发前先读 [协作规范](docs/phase2/team_collaboration.md) 和 [算法接入说明](docs/phase2/algorithm_integration.md)；[当前数据库设计与 ER 图](docs/phase2/database_current_v03.md)记录落地模式。接口和数据库目标审核稿分别在 [接口设计](docs/phase2/interface_design_target.md)、[数据库目标设计](docs/phase2/database_design_target.md)。这些审核稿包含尚未完成的目标，当前字段以源码、`/docs` 和 [交接说明](docs/phase2/replay_backend_handoff.md) 为准。每次版本变化及实测证据记在 [COURSE_SETUP.md](COURSE_SETUP.md)。

## 项目分工

| 成员 | 第二阶段主责 |
|---|---|
| 李泽同 | 总体架构、公共接口、FastAPI、Controller、SQLite、系统集成；主导机器学习算法 D |
| 何明涛 | Worker、IPC、取消与超时、传统算法 A；参与算法 D |
| 梁兆榮 | 实验页面、结果比较、Cesium/甘特图、独立 Daemon、传统算法 B |
| 刘懋兴 | 数据准备、哈希与实验协议、基线成对实验、传统算法 C；参与算法 D |

算法 A/B/C/D 的具体机制由负责人设计，最终都须通过同一场景与约束的可行性检查，并提供可重复的成对实验记录。

## 来源与致谢

- **[EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench)**：本项目的上游公开源码与基准平台。我们复用了其场景格式、调度问题/约束模型、基线算法、指标计算和早期 Cesium/甘特图页面，并在课程仓库中保留了相关代码。上游研究论文：[Yin 等，*EOS-Bench: A Comprehensive Benchmark for Earth Observation Satellite Scheduling*](https://arxiv.org/abs/2604.25782)。课程系统的进程、IPC、Controller、数据库及网页实验链路是本项目的第二阶段工作。
- **[Orekit](https://www.orekit.org/)** 与 `orekit-jpype`：可选轨道传播与 CZML 生成依赖；**[CesiumJS](https://cesium.com/platform/cesiumjs/)**：浏览器三维回放；**[FastAPI](https://fastapi.tiangolo.com/)** 与 Uvicorn：HTTP 服务。各依赖的版权和使用条件以其项目发布信息为准。

本仓库的实验结论仅对应所记录的场景、代码版本、配置与数据哈希；派生小实例不等同于 EOS-Bench 论文的完整独立实验集合。

## 连续曝光正式门禁（2026-10-17 P1）

候选规划可行与连续物理认证通过是两个不同状态。规划器与共享约束使用经来源核实的保守窗口规则；Controller 独立认证后，只有 `CONTINUOUS_PASS` 可持久化为正式成功计划。`REJECTED`、`INCONCLUSIVE`、执行异常或超时均不放行，Worker 自报认证字段无效。

历史 `SUCCEEDED` 保留原状态用于追溯，但缺少当前版本认证、来源不匹配或计划 SHA 不符时，Storage 不返回正式计划，API/JSON/CSV/目录导出也会拒绝。列表和详情附带连续认证状态。当前 Orekit 采样模型尚无连续区间证明，四份冻结计划的 80 条任务仍为 `INCONCLUSIVE`，不能正式发布。

正式独立审查需要服务端配置 `EOS_OREKIT_DATA`；没有数据、可信窗口来源或连续性证据都会关闭门禁。普通 `verify_schedules.py` 的离散模式仅供诊断，`PASS_DISCRETE_ONLY` 不代表连续认证。完整契约、测试和风险见 [连续曝光审计报告](docs/phase2/continuous_exposure_boundary_fix_2026-10-17.md) 第 11 节起。
