# EOS-Course-Project：地球观测卫星任务调度课程系统

本仓库是**操作系统原理课程设计**项目。我们在 [EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench) 的场景、约束、算法基线和可视化代码之上，构建可以由浏览器操作的调度实验系统。项目重点是把一次实验从配置、独立进程执行、进程间通信、结果核验，到持久化和回放连接起来，并让不同组员实现的算法在同一输入与约束下比较。

本项目不是 EOS-Bench 官方仓库。上游研究平台、论文和数据的出处见[来源与致谢](#来源与致谢)；课程系统的新增实现主要位于 `eos_system/`。

## 背景与目标

地球观测卫星需要在有限的可见窗口中安排拍摄和下传任务，同时满足卫星姿态切换、传感器、存储、电量和地面站等约束。EOS-Bench 提供场景与统一调度内核。课程第二阶段进一步关注操作系统层面的真实进程、IPC、排队、同步、取消、故障恢复，以及可复现的算法实验。

本组计划完成三种机制不同的传统算法和一种机器学习算法。新算法会通过同一注册、运行和核验边界进入系统；本仓库当前可选的 `completion_first`、`adaptive_repair` 属于已有基线，**不计作这四种新算法的交付**。

## 当前能力（v0.2.1 框架 + W1/W2 功能分支）

- 浏览器选择**已登记的数据源、场景、算法和输出方案**，提交、取消并查看实验状态与正式结果。
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

首次查看一个场景时，服务会使用仓库的 `utils/orekit-data.zip` 生成 CZML，并缓存到 WSL 运行目录的 `visualizations/scenes/`；相同场景哈希的后续实验复用缓存。可视化轨道使用较稀的采样，仅影响画面文件，不改变调度输入和正式计划。旧的 `main_draw.py` CLI 仍可独立使用。

成功实验的“Cesium 回放”现在还会请求 `GET /api/runs/{run_id}/visualization/replay`。服务只从已入库的正式计划和哈希相符的只读场景派生显示数据，不重跑算法，也不会将回放结果写回调度结果。页面使用 NASA Landsat 8 模型作为数据集卫星的**通用示意外观**，不会把 ALOS-2、AQUA 或 CARTOSAT-2C 改名为 Landsat 8；资产来源与验证见 [`docs/replay/landsat8-validation.md`](docs/replay/landsat8-validation.md)。

当前本体姿态是以 ECEF 轨道位置和任务目标计算的几何指向示意，固定载荷始终使用同一相机—本体变换。它不是 Orekit 姿态或卫星动力学验证；若派生数据不可用，Cesium 保留原有点/标签显示。

每颗星在转向和拍摄阶段会显示独立视锥：转向为琥珀色，拍摄为绿色，并在原 `sat_end_time` 隐藏。视场使用配置中明示的“方形完整角”显示假设，中心和边界射线共用固定载荷姿态，通过 Cesium WGS84 椭球求交生成中心点与地面覆盖。部分视场越过地平线时不画完整覆盖，无交点时不沿用旧几何。这些覆盖仅用于回放，不修正任务成功或指标。详细验证见 [commit 4 交接记录](docs/phase2/satellite_replay_commit_4.md)；卫星选择与同钟固定载荷第二视图尚待 commit 5。

## 开发与验证

```bash
cd /mnt/d/Code/EOS-Course-Project
~/eos-course-runtime/.venv/bin/python -m unittest discover -s tests -v
# 以下脚本要求另一个终端已启动 python -m eos_system
~/eos-course-runtime/.venv/bin/python scripts/smoke_system.py
PYTHONHASHSEED=0 MPLBACKEND=Agg ~/eos-course-runtime/.venv/bin/python -m scripts.check_cli_parity
~/eos-course-runtime/.venv/bin/python -m scripts.check_plan_rejection
# 安装可选轨道依赖后，传入任一成功实验的 run_id
~/eos-course-runtime/.venv/bin/python scripts/check_visualization.py <run_id>
```

组员开发前先读 [协作规范](docs/phase2/team_collaboration.md) 和 [算法接入说明](docs/phase2/algorithm_integration.md)；[当前数据库设计与 ER 图](docs/phase2/database_current_v02.md)记录落地模式。接口和数据库目标审核稿分别在 [接口设计](docs/phase2/interface_design_target.md)、[数据库目标设计](docs/phase2/database_design_target.md)。这些审核稿包含尚未完成的目标，当前字段以源码、`/docs` 和 [交接说明](docs/phase2/framework_handoff.md) 为准。每次版本变化及实测证据记在 [COURSE_SETUP.md](COURSE_SETUP.md)。

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
