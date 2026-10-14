# 课程项目运行与版本记录

## 第二阶段回放后端 v0.3（2026-10-14，`feat/replay-backend`，待李泽同审核）

在正式成功实验之后增加独立的回放构建闭环：SQLite `user_version=3` 与 `replay_artifacts`、`POST /api/runs/{run_id}/replay`、回放状态和资源 GET、原甘特图 schedule 身份字段，以及按实验删除派生回放缓存。固定配置 `geometry-illustration-v2` 生成轨道 CZML、姿态示意样本、阶段区间、诊断和配置资源；Controller 校验哈希并发布 READY。旧 `GET /api/runs/{run_id}/visualization/orbit.czml` 保留到梁兆榮完成前端迁移，首次访问仍可能构建旧共享轨道缓存。当前姿态是展示示意，尚未宣称 Orekit TargetPointing 精确姿态；何明涛的正式回放消息型 IPC、梁兆榮的前端、刘懋兴的数据核验仍按交接文档继续。

WSL Ubuntu 22.04 / Python 3.10.12：完整 `unittest discover -s tests -v` **105/105 通过**，包括新增 v2→v3 迁移及 HTTP→独立构建进程→READY→资源 ETag→删除闭环；`git diff --check` 通过。原 Orekit 导出器的单星 10 分钟/3 轨道样本缓存未命中实测约 179 秒，较大场景需单独预算测试。旧本机 SQLite 中 10 条终态测试实验按用户授权在 v3 迁移后删除，现 runs=0；输入场景和正式导出文件未删，迁移验收后的本机 `.pre-v3.bak` 已清理。工作树尚未 commit/推送。接口与任务交接见 [`docs/phase2/replay_backend_handoff.md`](docs/phase2/replay_backend_handoff.md)，当前 ER 图见 [`docs/phase2/database_current_v03.md`](docs/phase2/database_current_v03.md)。

---

## Worker/IPC W1/W2 最终交付联调（2026-10-14，`feat/hmt-worker-ipc`，待何明涛与李泽同审核）

修正 README、框架交接及算法接入说明中过期的“协作取消尚未实现”等描述，保留 W3、Daemon、A/B/C/D 和跨重启回收为未交付范围。新增三个真实 TCP 回环 HTTP → Controller → `spawn` Worker → 临时 SQLite 异常闭环，覆盖运行中取消（`CANCELLED`）、不合作求解超时（`TIMED_OUT/ALGORITHM_TIMEOUT`）和携同 Session 后代的 Worker 异常退出（`FAILED/IPC_DISCONNECTED`、退出码 23）；均无正式计划，直接 Worker 与可信后代无活跃残留。测试桩仅在隔离服务进程中装配，正式算法注册表及运行时代码未改。

WSL2 Ubuntu 22.04 / Python 3.10.12：HTTP 故障专题两轮各 **3/3**、完整 unittest **103/103**、`git diff --check` 通过。隔离成功闭环复跑 `completion_first` 24/30、TCR=0.800，SQLite attempt 1、exit_code 0、一份正式计划；JSON/CSV、旧 CLI 计划对照与篡改候选拒绝均通过。临时场景 SHA-256 为 `192eb635644fcdbc86854912704345494fe36d8cffb828c5000cff9221a9b84e`；母场景只读，临时数据库、服务和测试产物均已清理。Controller 交接及剩余可靠性边界见 W2 专题说明第 13 节。

---

## Worker/IPC W2-C 启动与取消竞争修复（2026-10-14，`feat/hmt-worker-ipc`，待人工复核）

`Controller._execute()` 只有尚未决定取消、超时或停机时才将 `start` 入队。若 `USER_CANCEL` 或 `CONTROLLER_STOP` 先于 `start`，随后到达的 `started` 不再触发算法；也不向等待首条 `start` 的 Worker 单独发送 `cancel`，而是按原有有界回收裁决。真实 `spawn` 测试在 `setsid()` 后延迟 `started`，验证用户取消最终 `CANCELLED`、Controller 停机最终 `FAILED/CONTROLLER_STOP`，两者均没有发送 `start` 或执行算法准备。原有已排队 `start` 的阻塞写测试保持覆盖。W2-C 专题 **28 项连续三轮通过**，完整 unittest **100 项通过**，`git diff --check` 通过。HTTP、SQLite 模式、Solver、IPC 协议及 Linux 身份/信号机制未变；详情见 W2 设计说明。

---

## Worker/IPC W2-C 最终审核定向修复（2026-10-14，`feat/hmt-worker-ipc`，待人工复核）

修复了 Worker 独立 Session 从未确认时，合法候选与退出码 0 可能绕过清理身份检查而提交成功的问题。Controller 现在等本次 Worker 的 `started` 到达，再通过内核 `/proc` 身份及 pidfd 确认独立 Session，才发送旧格式 `start`；正式成功前再次检查本 attempt 的身份确认与 start 放行。未确认身份的候选记明确失败和诊断；启动期用户取消仍按有界直接进程回收裁决，不向 Controller 所在进程组发信号。WSL2 隔离环境中 W2-C 专题 **26 项连续三轮通过**、Controller 取消/超时/进程身份专题 **50 项通过**、完整 unittest **98 项通过**、`git diff --check` 通过。生产 Worker、HTTP、SQLite 模式、算法签名及 IPC 协议未改。剩余边界见现有 W2 设计说明。

---

## Worker/IPC W2-C 首轮审核后定向修复（2026-10-14，`feat/hmt-worker-ipc`，待人工复核）

`WorkerGroup.refresh()` 现在可在本 attempt 已确认独立 session、且组长 pidfd 仍固定身份时，于组长退出后继续发现同组后代；新成员经 PGID、SID、boot_id、starttime 和 pidfd 复核后仅接受逐进程信号，不向已退出组长的缓存 PGID 发 `killpg`。pidfd 获取遇 `ESRCH` 后若确认进程已消失或结束，不误报清理不完整；活跃但无法固定、权限或存在性不明则保留风险，并在后续确认退出后清除。真实 `spawn` 测试增加组长立即崩溃后首次发现后代、Controller 闭环回收、扫描与 pidfd 打开之间子进程退出、以及活跃未固定成员的风险消退。WSL2 隔离环境中 W2-C 专题 **23 项连续五轮通过**、完整 unittest **95 项通过**，`git diff --check` 通过，未见活跃测试后代。本轮未改 Controller 停机、HTTP、SQLite 模式、算法接口及 W1/W2-A/W2-B 协议或超时裁决。最后一次扫描后的新后代、逃逸 session、pidfd 不可用及跨 Controller 重启清扫仍无完整保证。详情见 W2 设计说明的本轮记录。

---

## Worker/IPC W2-C（2026-10-14，`feat/hmt-worker-ipc`，待集成审核）

新增 Linux `/proc` 启动身份、独立 PGID/SID 与 pidfd 核验；只在当前组长身份仍可证明时发送进程组信号，组长退出后用事先固定的 pidfd 回收已识别后代。Controller 停机时停止领取新 attempt、向当前 Worker 请求停止、有限等待执行线程；若线程仍活跃则报错并保留 flock，退出后才解锁。内部停机中断记 `FAILED/CONTROLLER_STOP`；原取消/超时优先级和公共 HTTP、SQLite 模式、状态、算法及 IPC 契约不变。WSL2 Ubuntu 22.04 / Python 3.10.12 独立临时环境的完整 unittest **91 项通过**；W2-C 进程组 12 项、停机 7 项分别独立重复三轮通过，`git diff --check` 通过。已识别同组后代在测试后无活跃残留；逃逸后代、扫描间隙及跨 Controller 重启旧进程仍不能保证回收。详见 [`docs/phase2/W2 WorkerIPC 与 Controller 协作实施说明 v1.0.md`](docs/phase2/W2%20WorkerIPC%20%E4%B8%8E%20Controller%20%E5%8D%8F%E4%BD%9C%E5%AE%9E%E6%96%BD%E8%AF%B4%E6%98%8E%20v1.0.md)。

---

## Worker/IPC W2-B（2026-10-14，`feat/hmt-worker-ipc`，待审核）

Controller 使用单线程非阻塞 Pipe 帧收发，给 start/cancel 写入、启动准备、搜索总墙钟、单帧传输和候选后退出设置单调时钟期限；直接 Worker 依次有界 join、terminate、kill。复用现有 `run_attempts.exit_code` 和小型诊断事件记录退出与 IPC 错误，Worker 不写数据库。人工审核后修复不同 `seq` 重复候选刷新退出期限、零长度帧误分类两项缺陷；同 `seq` 仍去重。WSL2 Ubuntu 22.04 / Python 3.10.12 的独立临时目录中，`python -m unittest discover -s tests -v` **72 项通过**，其中 W2-B 专题 21 项真实 spawn 故障/回收测试；原 W2-A HTTP 闭环、正常成功及 SQLite 事务测试保持通过。HTTP、SQLite 物理模式、状态枚举、算法接口、双 Pipe、协议版本及 4 MiB 限额未变。`Process.start()` 自身无法由现有单线程状态机抢占；后代进程组回收、Controller 安全停机和崩溃后旧进程清扫仍待 W2-C。详见 [`docs/phase2/W2 WorkerIPC 与 Controller 协作实施说明 v1.0.md`](docs/phase2/W2%20WorkerIPC%20%E4%B8%8E%20Controller%20%E5%8D%8F%E4%BD%9C%E5%AE%9E%E6%96%BD%E8%AF%B4%E6%98%8E%20v1.0.md)。

---

## Worker/IPC W2-A（2026-10-14，`feat/hmt-worker-ipc`）

Controller 已接通 W1 的运行中协作取消：本 attempt 一次性发送完整 `cancel`，继续读取并去重 `cancel_ack`，在直接 Worker 退出后裁决 `CANCELLED`；取消候选仍受统一核验和 SQLite 成功事务保护。保留旧 `start`、双单向 Pipe、HTTP、SQLite 模式及算法签名。WSL2 Ubuntu 22.04 / Python 3.10.12 的独立临时目录中，完整单元测试 **51 项通过**（新增 Controller 专题 14 项，含真实 spawn 与 ASGI HTTP → Worker → SQLite 闭环）。同步 Pipe 的严格抗阻塞、完整超时和单 Worker 回收诊断待 W2-B；后代进程组清理与安全停机待 W2-C。因此本阶段建议 **FUNCTIONAL PASS / RELIABILITY PENDING**。详见 [`docs/phase2/W2 WorkerIPC 与 Controller 协作实施说明 v1.0.md`](docs/phase2/W2%20WorkerIPC%20%E4%B8%8E%20Controller%20%E5%8D%8F%E4%BD%9C%E5%AE%9E%E6%96%BD%E8%AF%B4%E6%98%8E%20v1.0.md)。

---

## Worker/IPC W1 补充验收（2026-10-14，`feat/hmt-worker-ipc`）

基于 `906fe70` 增加 5 项真实 Linux `spawn` 子进程测试，覆盖协作取消的跨进程可见性、不合作求解桩的 2 秒有界退出、控制 Pipe EOF、求解异常和事件 Pipe 断链。求解桩在子进程内安装，场景位于临时目录；测试端的 `terminate/kill` 仅作为失败时清理兜底，本次测试未触发。WSL2 Ubuntu 22.04 / Python 3.10.12 虚拟环境中，完整单元测试 **37 项通过**，`git diff --check` 通过。未修改 Worker 业务源码、Controller、HTTP 或 SQLite；完整取消和进程组回收仍待 W2。详见 [`docs/phase2/worker_ipc_w1.md`](docs/phase2/worker_ipc_w1.md)。

---

## Worker/IPC W1（2026-10-14，`feat/hmt-worker-ipc`）

在 v0.2.1 参考 Worker 中增加控制 Pipe 持续监听、协议字段和身份校验，以及接入 `SolveContext.is_cancelled()` 的线程安全取消标记。Worker 主线程独占 IPC 读写和事件序号，求解线程运行算法；收到取消后发送 `cancel_ack`，已取消的算法返回结果不会作为候选上报。保持旧 Controller `start` 消息兼容，未改 HTTP、SQLite 或算法公共签名。WSL2 Ubuntu 22.04 / Python 3.10.12 的虚拟环境中，基线 18 项和修改后 32 项单元测试通过；新增测试使用临时目录和测试桩，未执行服务端集成测试。Controller 发送取消命令、硬超时和进程组回收仍待 W2；大结果文件载体待 W3。详细协议与限制见 [`docs/phase2/worker_ipc_w1.md`](docs/phase2/worker_ipc_w1.md)。

---

## 第二阶段组员协作规范（2026-10-14）

新增 [`docs/phase2/team_collaboration.md`](docs/phase2/team_collaboration.md)，明确每项工作新建分支、经 PR 审核后合入 `main`、代码与对应专题文档及本记录同步提交的流程；列出四人职责、文档映射、PR 检查项和 Windows + WSL2 的协作方式。README 增加入口。本次只改文档，不改变运行行为。

---

## 第二阶段框架 v0.2.1（2026-10-14，Windows + Ubuntu 22.04 / WSL2）

在 `feat/phase2-v0.2` 分支上新增逐条实验清理：网页列表支持翻页，终态实验详情提供永久删除及可选的服务器导出文件清理。HTTP 接口为 `DELETE /api/runs/{run_id}`，可选 `delete_files=true`。数据库按依赖顺序在事务中删除该实验的配置、尝试、事件、计划、assignment、指标和导出记录，再尝试 `VACUUM` 与 WAL 截断；失败会提示，但已删记录不会恢复。正在排队、运行或核验的实验不能直接删除。

文件清理仅针对本实验目录中路径、文件名及原始 SHA-256 均一致的正式 JSON/CSV；被修改的文件会保留。输入场景和多次实验共用的轨道缓存不参与删除。Controller 完成正式结果与目录输出时和删除接口共用进程锁，避免成功入库与导出之间被删除。

实测：Ubuntu 22.04 / Python 3.10.12 完整测试集 18 项通过；JavaScript 语法检查与 `git diff --check` 通过。独立临时 SQLite 验证了非终态 409、终态删除、所有关联表清空及压缩后页数下降。隔离本地服务的网页成功提交 24/30 的实验，终态详情显示删除按钮与文件选项；API 删除后返回 2 个文件已清理、数据库已压缩，列表总数归零。隔离测试服务已停止，`/tmp/eos-delete-qa-v021` 已清理；原有正式运行库没有被删除。

---

## 第二阶段框架 v0.2.0（2026-10-14，Windows + Ubuntu 22.04 / WSL2）

本次与根目录 README 改写一起提交；README 已说明课程项目背景、目标、运行方式和 [EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench) 上游来源。当前实现及组员接入边界见 [`docs/phase2/framework_handoff.md`](docs/phase2/framework_handoff.md)，算法接口见 [`docs/phase2/algorithm_integration.md`](docs/phase2/algorithm_integration.md)，落地数据库 ER 图见 [`docs/phase2/database_current_v02.md`](docs/phase2/database_current_v02.md)。v0.1 的 `feat/phase2-framework` 已由用户合并到 `main`；本版从合并后的 `main` 建立 `feat/phase2-v0.2`。

### 本版变更

| 范围 | 当前实现 |
|---|---|
| 输入与输出 | 浏览器选择并登记数据源、场景和输出方案；Windows 盘符路径转换为 WSL 路径并校验目录；场景保持只读，禁止输入输出目录重叠；每次运行记录所选 ID、解析路径和场景 SHA-256 |
| 正式文件 | JSON/CSV 继续从数据库下载；目录输出按 `run_id` 隔离，原子写入并记录哈希、路径或失败原因；文件失败不撤销已核验的计划 |
| 算法扩展 | 增加 `Solver`、`SolveContext`、`AlgorithmSpec` 和专属参数模型；旧算法走适配器，新算法可独立设计中间状态和搜索机制，最终统一提交 `Schedule` 核验 |
| 可视化回放 | 按 `run_id` 将数据库计划交给原甘特图/Cesium 页面；Orekit 在独立子进程按场景哈希生成 CZML 并缓存，生成物位于 WSL 运行目录；轨道依赖单独安装 |
| 数据库 | `user_version=2`，新增数据源和输出方案登记表、运行选择字段及文件导出字段；v1→v2 事务迁移保留已有实验 |
| 文档与协作 | 新 README、当前 ER 图、算法接入说明、交接说明及目标设计稿状态提示；没有将四种正式新算法或完整 Daemon 误写为已完成 |

### 2026-10-14 实测

Ubuntu 22.04 / Python 3.10.12：16 项单元测试通过，包括 v1 数据库迁移、算法私有参数、场景目录约束、正式目录文件和缓存轨道回放。固定 1 星 30 任务的 HTTP 冒烟实验完成 24 项，TCR=0.800，JSON/CSV 下载通过。另从第二个登记数据源选取 3 星 30 任务场景并指定自定义输出目录，正式实验完成 17 项，TCR=0.567；数据库与目录下 JSON/CSV 记录均为成功。旧 CLI 与新入口对照为相同的 17 条 assignment；资源量篡改计划被拒绝。浏览器检查了数据源切换、实验详情、下载链接、甘特图 17 条计划和已缓存场景的 Cesium 指标/任务列表。1 星 24 小时场景的 CZML 首次生成成功，包含 32 个包；后续按哈希复用缓存。首次生成仍可能耗时较长，Cesium 在线资源需浏览器可访问。

本版仍采用最小参考 Worker；完整 IPC 取消确认、进程组回收、独立 Daemon、三项新传统算法和机器学习算法由组员继续实现。运行位置由 `EOS_RUNTIME_DIR` 与 `EOS_SCENARIO_DIR` 配置，页面还可登记其他目录。Windows 保存代码与使用浏览器，调度、进程、数据库和高频文件运行于 Ubuntu。

---

## 第二阶段框架 v0.1.0（2026-10-13，Windows + Ubuntu 22.04 / WSL2）

本节是当前运行入口；下文第一阶段的 Mac 路径仅保留为历史实验记录。第二阶段框架的模块边界、组员接入方式和已知限制见 [`docs/phase2/framework_handoff.md`](docs/phase2/framework_handoff.md)。

历史交接分支为 `feat/phase2-framework`，已合并到 `main`。本节以下命令与能力记录保持 v0.1 时的状态；当前使用者优先阅读上方 v0.2 记录和根目录 README。

### 本次实现

| 范围 | 变更与验证 |
|---|---|
| 系统包 `eos_system/` | 增加配置、公共契约、调度入口、独立核验、SQLite、Controller、最小参考 Worker、FastAPI 和无外部资源依赖的浏览器页面 |
| 原内核复用 | `schedulers/schedule_output.py` 增加 `schedule_to_dict()`；原 `save_schedule_to_json()` 改用它，原 CLI 的 JSON 格式保持一致。`algorithms/heuristics.py` 把固定实验种子传入候选池，修复跨进程时同种子计划时间不一致的问题 |
| 数据与运行 | 从只读 `/mnt/c/EOS-Bench` 派生 30 任务固定小实例到 `~/eos-course-runtime/scenarios/`；虚拟环境、SQLite/WAL、锁也在这个 WSL 目录 |
| 仓库整理 | 忽略并清理历史误提交的 Python 字节码缓存；这些是生成物，组员从源码运行时会自行生成，不属于交付代码 |
| 验证 | Ubuntu 22.04 / Python 3.10；旧单元测试、事务测试与真实 HTTP→Worker→核验→SQLite→JSON/CSV 闭环，以本次执行记录为准；不把本表当作未运行项目的通过证明 |

### 2026-10-14 验收补记

修复了核验期间取消与成功提交交错时可能残留 `VERIFYING` 的状态问题；增加对应事务测试。将接口和数据库目标设计稿（含 ER 图）放进 `docs/phase2/`，并在文件首页标出与当前实现的边界。Ubuntu 22.04 / Python 3.10.12 上实测：11 项单元测试通过；真实网页提交经独立 Worker、Controller 核验后入库，固定 1 星 30 任务实例完成 24 项，TCR=0.800；HTTP JSON/CSV 导出通过；旧 CLI 与新入口逐条对照 24 条 assignment 一致；篡改资源量被拒绝。演示场景 SHA-256 为 `00274bc1d4bce0ccf427edeac70b9742ad4fd7f21111e4969b9ce1c90c5342c0`。这些是框架验收，不代表尚未实现的三种传统算法、机器学习算法、独立 Daemon 或完整 Worker 故障恢复已经通过。

### Ubuntu 22.04 首次准备

在 Windows PowerShell 输入 `wsl -d Ubuntu-22.04` 后，于 Ubuntu 中执行：

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

Windows 浏览器打开 `http://127.0.0.1:8765/`。页面可登记场景、选择已有算法、提交/查看/取消实验及下载 JSON/CSV。API 文档位于 `http://127.0.0.1:8765/docs`。停止服务在启动终端按 `Ctrl+C`。不要使用 `uvicorn --reload` 或多个 Web worker，因为首版一个服务进程负责唯一 Controller。

在另一个 Ubuntu 终端运行闭环检查：

```bash
cd /mnt/d/Code/EOS-Course-Project
~/eos-course-runtime/.venv/bin/python -m unittest discover -s tests -v
~/eos-course-runtime/.venv/bin/python scripts/smoke_system.py
PYTHONHASHSEED=0 MPLBACKEND=Agg ~/eos-course-runtime/.venv/bin/python -m scripts.check_cli_parity
~/eos-course-runtime/.venv/bin/python -m scripts.check_plan_rejection
```

本节不要求 Java/Orekit：固定预计算场景的调度和基础网页不使用它们。需要 Cesium 轨道生成时再参考下方第一阶段可视化说明。原始母场景不写入或修改；场景派生、数据库与锁集中在 `~/eos-course-runtime`，不向仓库散落运行产物。使用其他机器时通过 `EOS_RUNTIME_DIR` 与 `EOS_SCENARIO_DIR` 环境变量改变运行目录，代码不含固定盘符。

### 下一次迭代接点

- 何明涛：在 `eos_system/worker_reference.py` 的协议和 Controller 的进程边界上实现完整双 Pipe、取消确认、超时、进程组回收和大结果临时文件；替换参考 Worker 后复跑闭环。
- 梁兆榮：在 `/api` 上升级页面、结果比较、Cesium/甘特图，并实现独立 Daemon；当前页面只保证配置、状态、计划表格和导出可用。
- 刘懋兴：提供正式场景清单/哈希、训练来源分组、基线成对实验；当前自动登记只扫描固定场景目录。
- 李泽同：继续完善 Controller 的恢复、算法 A/B/C/D 注册、ML D 训练和系统集成。

---

# 第一阶段：运行 EOS-Bench 与自定义算法（历史记录）

本目录是官方 EOS-Bench 提交 `ee282656e8b2f6fd0d3cf84677b40966e2780ef3` 的独立 Git 工作树；当前开发分支可用 `git branch --show-current` 查看。原始仓库在 `/Users/tonylizt/Projects/EOS-Bench`，数据集在 `/Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data`。准备脚本只读取数据集，所有派生实例、计划和日志均写在本目录的 `output/`。

## 环境

官方 README 建议 Python 3.10+、Java 17，并列出 `orekit-jpype`、`jpype1`、`numpy`、`pandas`、`matplotlib`、`scipy`、`pulp`、`torch`。读取预计算场景并运行本项目的启发式对照，只需 `requirements-course.txt` 中的基础依赖；重新生成轨道场景或使用本地三维可视化还需要 Java/Orekit。MIP 需要 PuLP；PPO 需要 PyTorch。本机系统 `python3` 是 3.9，不适合此仓库；本次使用 Codex 附带的 Python 3.12。

可在有 Python 3.10+ 的环境中这样准备：

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-course.txt
```

本机现有 `.venv` 使用附带的 Python 3.12 创建，已额外安装本地可视化所需的 Orekit 依赖；基础调度与三维展示的操作分别见下文。

## 官方 README 的完整流程与本项目的输入输出

| 阶段 | 官方入口 | 读入 | 写出 | 本次是否执行 |
|---|---|---|---|---|
| 生成场景 | `main_generate.py` | `input/` 中的卫星配置、目标配置，或随机任务参数 | `output/Scenario_*.json`、场景汇总 | 否；已下载预计算场景 |
| 切分母场景 | `input/scenario_splitter.py` | 下载数据集中的 7 天场景 JSON | 较短规划期的场景 JSON | 是；由 `prepare_first_step.py` 调用，写到本项目 `output/` |
| 难度分析 | `Characterisation/analyze_combined_conflict.py` | 场景 JSON | 冲突指标报告和 Excel | 否；官方 README 将其列为可选分析步骤 |
| 调度与评估 | `main_scheduler.py` | `output/` 下所有 `Scenario_*.json`；算法名及参数 | `output/schedules/` 中的计划 JSON、甘特图 PNG、`runlog_batch_*.txt`；PPO 模型写到 `output/models/` | 是；先运行小实例，再做 TCR 对照实验 |
| 三维展示 | `main_draw.py` | 一个场景 JSON、可选的计划 JSON | `draw/orbit.czml`，并启动本地 Cesium 页面 | 是；已用 TCR 首轮实验的新算法计划验证 |

官方 README 给了两种使用方式：终端传参，或编辑脚本末尾的默认配置后直接运行。我们现在用终端传参，输入仍遵循官方 `SchedulingProblem → ConstraintModel → Schedule → 指标和输出` 流程。下载数据集不在代码仓库内；本项目从 `/Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data` 只读获取所需母场景。该数据集不需要搬进 `output/`，也没有被修改。

## 重现这次小实验

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
.venv/bin/python prepare_first_step.py --data-root /Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data --seed 20260927
PYTHONHASHSEED=0 MPLBACKEND=Agg .venv/bin/python main_scheduler.py --algos completion_first pressure_repair --workers_other 1
.venv/bin/python verify_schedules.py output/Scenario_S2_Sats1_M30_T1d_dist0_seed20260927.json output/schedules/scheduler_Scenario_S2_Sats1_M30_T1d_dist0_seed20260927_c2_*.json
.venv/bin/python verify_schedules.py output/Scenario_S3_Sats3_M60_T1d_dist0_seed20260927.json output/schedules/scheduler_Scenario_S3_Sats3_M60_T1d_dist0_seed20260927_c2_*.json
```

`main_scheduler.py` 会递归扫描 `output/` 中所有 `Scenario_*.json`；若以后添加更多实例，上述调度命令会一起运行它们。输出计划与甘特图在 `output/schedules/`，最新运行表为 `runlog_batch_*.txt`。`output/` 和 `.venv/` 被 Git 忽略。

## 数据来源与修复后实测

两个源文件分别为 `output_s1/Sats1_M100_T7d_dist0.json` 和 `output_s3/Sats3_M200_T7d_dist0.json`。SHA-256 分别为 `b61f4de708894f0bc30b6e0614aafc2ac9340880306ed0617fdc50cf492d198a` 和 `7aa6e152163a4484841c45fd2f181ec914db2b622396fe153a187badd05cc272`。切分参数是从起点开始 24 小时、30/60 个任务、种子 20260927；这是从母场景派生的课程小实例，不是论文公布的原始实验集合。

| 实例 | 算法 | TP | TCR | BD | TM | RT（秒） |
|---|---|---:|---:|---:|---:|---:|
| 1 星 / 30 任务 | completion_first | 128 | 0.800 | 1.000 | 0.587 | 0.017 |
| 1 星 / 30 任务 | pressure_repair | 128 | 0.800 | 1.000 | 0.556 | 0.011 |
| 3 星 / 60 任务 | completion_first | 336 | 0.917 | 0.769 | 0.369 | 0.092 |
| 3 星 / 60 任务 | pressure_repair | 336 | 0.917 | 0.695 | 0.304 | 0.051 |

`pressure_repair` 是本项目的初版算法：按窗口稀缺度和重叠压力安排任务，优先选择占用较少其他任务机会的候选位置，再有限次尝试移出一项任务并重插。每次加入任务都调用共享的 `ConstraintModel`。`verify_schedules.py` 检查了四份计划的任务唯一性、窗口包含关系、共享约束模型可行性、TCR，以及敏捷卫星的姿态角转向是否成功解析。两个小实例里它没有提高完成率；TM 与 RT 的差异只是一次运行的结果，不能据此证明稳定优势。下一阶段应在更多实例和多个种子上比较，并做压力排序、修复步骤的消融。

**转向约束修复记录：** 官方提交的姿态提取函数不识别本数据的 `pitch_angles/yaw_angles/roll_angles`，原计划的同星相邻任务因此全部使用 11.66 秒回退值；`ConstraintModel.__init__` 还漏存了转向参数。本分支已同时修复这两个问题，对基线和自定义算法统一生效。修复前的场景、计划与日志保存在 `output_original_fallback/`；修复后的结果在 `output/`，两个文件夹不可混合作为同一模型的实验。两个版本的派生场景 SHA-256 完全一致。当前四份计划分别有 23、23、52、52 个敏捷相邻转向，这些转向角全部成功解析；旧计划在修复后的模型下已有不合规项。`tests/test_transition_model.py` 覆盖字段解析以及敏捷、非敏捷转向参数。

## TCR 优先算法实验

论文对齐的**配置**是 3 颗敏捷卫星、200 个任务、24 小时、Standard-Agility，并分别测试全球随机（`dist0`）和区域聚集（`dist1`）。比较官方 Greedy-TCR、SA-TCR、GA-TCR、ACO-TCR 与本项目的 `adaptive_repair`；MIP-TCR 可在安装 PuLP 后作为限时参考。全部方法在同一个派生 JSON 上使用相同的 `ConstraintModel`、`earliest` 放置模式、下传比率 1、完成率目标及确定的随机种子。TCR/完成数是首要指标，TP、BD、TM、RT 一并记录。Greedy 与新算法有自身的隐含完成率优先规则；SA/GA/ACO/MIP 使用权重 `(TP=0,TCR=1,TM=0,BD=0)`。

`algorithms/adaptive_repair.py` 先跨全部可用窗口分配候选名额，再动态统计当前可行位置数，优先排入位置最稀缺的任务；之后用最多两层的挪位增广链和局部取出重排（ALNS）寻找能增加完成数的安排。其目标按完成数、TP、提前执行时间作字典序比较，并对每一次插入调用共享约束模型。`tests/test_adaptive_repair.py` 覆盖窗口多样性、挪位重插与完整计划可行性。

只读母场景分别为数据集的 `output_s3/Sats3_M200_T7d_dist0.json` 和 `output_s3/Sats3_M200_T7d_dist1.json`。实验入口 `experiments/tcr_study.py` 将派生场景、计划、甘特图、`manifest.json`（源与派生文件 SHA-256）和 `results.csv` 统一写入 `output/experiments/tcr_study/`；每份计划另用 `verify_schedules.py` 回放。先跑论文配置下的首个 24 小时片段：

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
.venv/bin/python -m experiments.tcr_study \
  --data-root /Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data \
  --offsets 0
```

需要扩展到多个时间片时，可使用 `--offsets 0 16 32 48 64 80 96 112 128 144`；`--prepare-only` 只切分场景，`--run-only` 只运行已切分场景，`--algos` 可指定算法；更新某算法已有结果时加 `--rerun --algos adaptive_repair`。`--run-only` 会核对清单中的场景哈希与种子，防止误用不同实例。**这些时间片源自同一份 7 天母场景且部分重叠，不是论文中由独立目标子集生成的十个实例。** 因此论文 Excel 的统计结果只作为配置和趋势参考；严格的性能比较是所有算法在本实验同一份派生实例上的成对对比。运行前确认没有把修复前后的转向模型结果混在一起。MIP 不在默认算法列表中，需另装 PuLP；限时未证最优时不得标为全局最优。

### 首轮成对结果（2026-09-28）

本轮的独立实验记录（文件变更、命令、输入输出、全部指标和限制）见 `experiments/reports/2026-09-28_tcr_pilot.md`。

每格为 **完成任务数 / 200**。同一行的所有算法使用同一份派生场景、相同转向约束和相同完成率目标，均通过计划回放验证。`0h` 与 `48h` 是不重叠的两个时间片，但同分布的时间片仍来自同一母场景，不能视为独立论文重复实验。

| 分布 / 起点 | Greedy-TCR | SA-TCR | GA-TCR | ACO-TCR | adaptive_repair |
|---|---:|---:|---:|---:|---:|
| 全球随机 / 0h | 183 | 187 | 184 | 187 | **187** |
| 区域聚集 / 0h | 150 | 172 | 156 | 171 | **175** |
| 全球随机 / 48h | 188 | 192 | 191 | 192 | **192** |
| 区域聚集 / 48h | 141 | 165 | 148 | 158 | **168** |

全量指标与各次运行时间见 `output/experiments/tcr_study/results.csv`。这些是算法默认迭代参数下的首轮效果，**没有对各算法施加相同计算时间上限**；不能据此声称运行时间或统计显著性占优。MIP 未运行，因为当前精简环境未装 PuLP。

在区域聚集 / 0h 场景，用实验相同的算法种子 `20260928` 做消融：静态稀缺构造 173，启用动态稀缺构造 175，再加增广链仍为 175，完整 ALNS 也为 175。ALNS 对次级 TP/时序质量有改进，但该场景完成数的增量来自动态构造；增广链的重插机制另有单元测试验证。下一轮应在更多独立实例上检查修复模块的收益与随机种子敏感性。

## 本地网页可视化（2026-09-29）

官方的 `main_draw.py` 用 Orekit 把场景中的卫星轨道转换成 CZML，再启动本机 HTTP 服务，通过 `draw/cesium_viewer.html` 展示卫星、地面目标和可选的调度计划。**这是算法结果的三维回放，不会重新运行调度算法，也不是算法内部搜索过程的动画。**

### 本次可视化接入改动

| 文件／本地生成物 | 改动 |
|---|---|
| `draw/orekit_to_czml.py` | 轨道历元同时接受数据集中的 ISO 8601 时间和官方原有的英文月份时间格式；带时区的时间统一转换为 UTC。 |
| `main_draw.py` | HTTP 服务只绑定 `127.0.0.1`，避免把整个项目目录暴露给局域网。 |
| `.gitignore` | 忽略自动生成的 `draw/orbit.czml` 和本机用的 `draw/orekit-data.zip` 链接。 |
| `COURSE_SETUP.md` | 补充依赖、输入配对、启动、输出和停止方法。 |
| 本机 `.venv/`、`draw/orbit.czml`、`draw/orekit-data.zip` | 前者安装可视化依赖；后两者分别是生成的轨道文件和指向仓库已有 `utils/orekit-data.zip` 的符号链接。它们不提交 Git。 |

原始数据集、派生场景 JSON 和调度计划 JSON 均未被这次可视化改动修改。

### 首次准备

从项目根目录执行：

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
.venv/bin/python -m pip install 'orekit-jpype[jdk4py]' 'jpype1==1.5.2'
ln -s ../utils/orekit-data.zip draw/orekit-data.zip
```

`ln -s` 只需在 `draw/orekit-data.zip` 不存在时执行一次；不要覆盖已有文件。仓库内的 `utils/orekit-data.zip` 是 Orekit 所需的数据，不是调度场景。官方建议 Java 17；本机用 Python 3.12、已安装的 `jdk4py` 和 Java 25 实测成功，但其他机器应以官方建议版本为先。页面从 Cesium 在线地址加载脚本与地球资源，浏览器需要能访问相应网络资源。

### 选择输入 JSON

- `--scenario` 必填：选择**一个**场景 JSON。推荐使用 `output/experiments/tcr_study/scenarios/` 中的 24 小时派生场景，不直接用 7 天母场景做课堂演示。
- `--schedule` 可选：选择**同一场景**运行后得到的计划 JSON；省略时只显示卫星和目标，不显示完成率、观测区间等计划信息。
- 两个路径都从本项目根目录算起。可先比较两个 JSON 的 `scenario_id`；应完全一致。计划文件名中的场景部分也应与场景文件名对应，后面的 `adaptive_repair`、`completion_first`、`sa` 等才表示算法。不要把不同分布、时间片或任务集的文件配在一起。
- 若想看仓库自带的官方演示，可配对 `docs/Scenario_S1_Sats20_M500_T0.5d_dist0.json` 与同名前缀的 `docs/scheduler_Scenario_S1_Sats20_M500_T0.5d_dist0_c3_ga_p0_c1_t0_b0.json`（或该目录下其他同场景计划）。这组 20 星、500 任务数据较大，生成轨道会比下方 3 星示例更耗时；不要与 `Scenario_Study_...` 派生场景混用。

例如，查看全球随机分布、0h 时间片的新算法结果：

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
.venv/bin/python main_draw.py \
  --scenario output/experiments/tcr_study/scenarios/Scenario_Study_Sats3_M200_T1d_dist0_h000_seed20260927.json \
  --schedule output/experiments/tcr_study/schedules/scheduler_Scenario_Study_Sats3_M200_T1d_dist0_h000_seed20260927_c2_adaptive_repair_implicit.json \
  --port 8080
```

脚本生成／覆盖 `draw/orbit.czml`，随后自动打开浏览器；也可手动访问终端打印的 `http://localhost:8080/draw/cesium_viewer.html?schedule=...` 地址。页面左侧显示 TP、TCR 等指标，中间播放轨道与目标，右侧列出观测区间；右上角的 **Gantt Chart** 可打开同一计划的甘特图。本机已验证该示例加载 187 个任务、TCR = 0.935、TP = 1045，且页面与 CZML、计划文件均可访问。生成的 CZML 约 25 MB，固定文件名会被下一次展示覆盖；它不改变输入 JSON。若 8080 已被占用，换用 `--port 8081` 等空闲端口。

**停止网页：** 保持启动它的终端运行，演示结束后在该终端按 `Ctrl+C`；服务停止后网页不能继续加载本地文件。若终端已丢失，先用 `lsof -nP -iTCP:8080 -sTCP:LISTEN` 确认对应进程，再停止那个进程，不要盲目结束其他占用端口的程序。
