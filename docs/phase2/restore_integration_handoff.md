> 版本说明：本页保留 v0.3.1 交接。六场景登记和 20/50 星采样限制已由 [v0.3.2 六场景交接](six_scenario_scale_handoff.md)更新，其余阶段二任务仍按分工推进。

## v0.3.3 可视化易用性补充（2026-10-16）

- Cesium 页面继续采用“GET 查询、显式 POST 构建”。打开页面不会自动建立回放，因为构建可能启动 Orekit/JVM、占用单构建槽并写入较大的派生资源；失败重试也必须由用户确认。
- 场景原绝对路径失效后，服务可在已登记数据源中按正式 `scenario_id + SHA-256` 重定位。未登记路径、符号链接或同名不同内容不会通过，不修改历史实验配置或计划。
- 主地球 Viewer 支持 Chromium 触控板捏合产生的 `Ctrl+wheel` 以及 Safari 类 gesture；处理器阻止浏览器整页缩放，并保留 Cesium 原生滚轮、右键拖曳和触屏 pinch。
- 当前任务列只同步固定载荷选星和时间，不自动改写主 Viewer 的 `trackedEntity`。因此任务列卫星与 Cesium 顶部追踪卫星可能不同；此跟随镜头状态统一需另项修复。

# 第二阶段修复与集成交接（v0.3.1）

- 日期：2026-10-16；分支：`fix/restore-integrated-phase2`。
- 起点：main `74f2516ce956460108e465f94afdc5b857aa0b25`（PR #8 后）。
- 状态：本地修复、集成与验收已完成；已获李泽同授权进行一次本地提交，本次不推送、不创建 PR。
- 本文是当前实现说明；恢复的 10 月 14–15 日专题文档保留历史语境，接口有差异时以本文、当前代码与运行后的 `/docs` 为准。

## 1. 本次为什么修复

PR #7 的合并提交 `753d267` 与其分支端点使用同一棵树。相对第一父提交 `a43a826`，有 51 个文件被删除；关键删除提交是 `c9480d2`。这影响了此前已集成的 W2 Worker/IPC、SQLite v3、独立回放及固定载荷页面。

本次从最新 main 建修复分支，按文件恢复 `a43a826` 中仍需要的功能，再进行兼容整合。没有回退公共 main，也没有整次撤销 PR #7；PR #7/#8 的数据审计、六份 LFS 场景、E1 历元解析与 E2 重算工具继续保留。

## 2. 修复后可使用的功能

| 模块 | 已实现范围 | 验收边界 |
|---|---|---|
| 实验配置 | 网页登记数据源、选择场景/算法/输出方案，专属 JSON 参数、种子和预算 | 路径由服务端登记；不写死到算法和页面业务中 |
| 算法接入 | 注册表、独立参数模型、SolveContext、统一 Schedule 输出 | 当前可用的两个算法仍是已有基线，不能算作组员的新算法 |
| Controller/Worker | spawn 独立进程、双单向 Pipe、真实 Linux 身份确认、期限、取消与回收 | cancel_ack 只表示收到请求；核验与成功提交仍由 Controller 完成 |
| 数据库 | SQLite v3、正式计划/指标事务、回放状态/attempt、v1/v2 增量迁移 | 启动接受已有 v3；迁移前在线备份；本次未清空实际运行库 |
| 输出与删除 | JSON/CSV 下载，目录输出，终态删除及可选导出文件删除 | 运行中或回放 BUILDING 时拒绝删除；共享输入不删除 |
| 独立回放 | 显式 POST、单构建并发、精确状态轮询、哈希核验、五种受控资源、失败重试 | Builder 不写 SQLite，不重跑算法，不修改正式计划/指标 |
| 结果页面 | 甘特图、卫星示意本体、视锥、WGS84 覆盖、固定载荷第二视图、选星与任务跳转 | 主 Viewer 为唯一时钟，读取同一批 READY 样本 |
| 新数据工作 | 保留 Manifest 审计与 E1/E2，记录提交时来源快照，防止 candidate 自动转正 | 来源不明场景标为 legacy_unknown；合成测试不等于真实 E3/E4 验收 |

Windows 负责代码编辑、Git 协作与浏览器展示；Ubuntu 22.04/WSL2 负责 FastAPI、Controller、Worker、Linux IPC/文件锁、SQLite 和 Orekit。SQLite、锁和派生缓存应放在 WSL Linux 文件系统；场景和导出目录可通过网页登记 Windows 挂载目录。正式计时实验不要同时构建回放或训练模型。

## 3. 统一回放流程

```text
SUCCEEDED 正式实验
  → GET 当前回放状态（无副作用）
  → 用户点击“构建/重试”才 POST
  → BUILDING：独立进程读计划/场景，写私有临时目录
  → 服务端检查身份、覆盖、有限数值、单位四元数和文件 SHA
  → 原子发布目录，条件提交 READY
  → 主 Viewer 与固定载荷视图读取同一批样本
```

默认配置 ID 是 `fixed-payload-illustration-v1`；前端先读 `GET /api/replay-configs`，不要在自己的页面写死旧配置。传感器和原卫星 ID 由场景展开，不再只支持原型中的三颗星。API 文件场景 ID 与 JSON 内部 scenario_id 分别记录。

| 路径 | 当前语义 |
|---|---|
| GET /api/replay-configs | 默认 ID、采样策略与已登记配置 |
| POST /api/runs/{run_id}/replay | 传 replay_config_id；新建/重试 202，READY 校验后复用 200 |
| GET /api/runs/{run_id}/replay | 当前配置状态；可带 replay_config_id |
| GET /api/runs/{run_id}/replays/{replay_id} | 精确查询同一回放 |
| GET /api/runs/{run_id}/replays/{replay_id}/resources/{key} | 仅 READY；受控 URL、大小、SHA、ETag/304 |
| GET /api/runs/{run_id}/visualization/schedule | 正式计划及 plan_sha256，甘特图复用 |
| GET /api/runs/{run_id}/visualization/replay | 兼容读取当前默认配置的 READY 姿态文档；未 READY 返回 409 |

五个资源键为 `orbit_display`、`attitude_samples`、`segments`、`diagnostics`、`replay_config`。
本版本 `attitude_samples` 是 JSON 对象，含 manifest、satellites、missions、assignments、segments、samples 等；不是直接返回样本数组。每条 sample 含绝对 UTC 时间、ECEF 米位置和 `body_to_ecef_quaternion_xyzw`。
`segments` 只存活动的 SLEWING/OBSERVING，未命中活动区间即 IDLE，采用左闭右开区间；原任务结束端点立即停止拍摄显示。

**请梁兆榮注意：旧 GET /api/runs/{run_id}/visualization/orbit.czml 继续保留。**它可能首次生成共享轨道缓存。当前课程 Cesium 页面已迁移到 manifest 资源；待组员完成前端迁移复核后，再另开 PR 决定清退旧 URL。本 PR 不删除它。
旧 `geometry-illustration-v2` 配置仍可由 API 显式申请，经 `replay_legacy.py` 保持旧资源语义；新页面不用它。离线 CLI 的原入口保留。

### 显示真实性与规模边界

- 敏捷星是几何目标指向示意；非敏捷星只提供对地示意，不伪装成自由敏捷。
- 固定安装取展示配置中的 camera_to_body；首版零位移、单位安装旋转，FOV 单值按“方形完整角”的明示假设解释。
- 任务转向阶段仍来自共享的旧约束转向模型；5 秒姿态样本与 SLERP 只用于显示，不替代调度可行性和动力学验证。
- 轨道默认 300 秒采样；姿态默认 5 秒并补齐任务/阶段端点。最多 200000 个姿态样本，每资源最多 64 MiB；超过上限明确失败，不截断伪造成功。大场景先裁定展示预算或另行设计分块协议。
- 模型、固定相机、视锥及覆盖使用同一采样位置和姿态，避免 CZML 插值和前端重算形成两套状态。
- 视锥/地面交点不计入 TCR；无地面交点时不能保留上一帧覆盖。WGS84 椭球显示不含真实遥感影像和地形遮挡。
- 主、次视图都使用 Cesium 随包 NaturalEarthII 底图，移除旧仓库个人 Ion token 依赖；Cesium 脚本和底图仍从固定版本 CDN 加载，完全离线部署尚未打包。

## 4. 缓存、进程和删除边界

缓存身份纳入场景、正式计划、展开后的显示配置、实际源码及模型字节、传播源码/wrapper/Orekit 数据包身份。未提交源码也会影响身份；旧缓存不会冒充新版本。轨道缓存升为 v2，不复用历元解析修复前的 v1 缓存。

回放 Builder 独立 session 运行，复用 W2 的进程身份和后代回收逻辑。停机或超时会阻止发布；父服务校验完整资源，READY 复用时也核验文件。文件损坏落 FAILED，原 run 的 SUCCEEDED 与正式导出保持。

提交/删除共用回放锁；资源读取与缓存删除互斥。发布目录只保留 manifest 和五个资源，含服务器路径的 job.json、日志以及失败临时目录及时清理。默认删除只清数据库及本实验回放缓存；勾选后才删除哈希匹配的正式目录导出。共享轨道缓存保留，不把同一场景的其他实验破坏。

这是当前进程内及已确认 Linux 身份范围的回收，不等于完整 Daemon 或任意孤儿追踪。组长身份已丢失、后代脱离 session、Controller 被 SIGKILL 等更强故障场景仍需后续 W3/Daemon 设计。不得以固定 PID 或扫描到的进程名盲目 kill。

## 5. 数据来源与数据库

数据库物理版本仍是 `PRAGMA user_version=3`，程序版本为 v0.3.1。没有为每个来源字段增加新表；将 `scenario_provenance` 保存进不可变 RunConfig JSON，兼容旧记录默认空对象。当前 ER 图见 [database_current_v03.md](database_current_v03.md)。

来源文件约定：场景旁 `provenance/<场景文件名>.provenance.json`。

- 没有证据的旧场景允许流程演示，明确标记 `legacy_unknown/unknown`；不能把这些结果当作修复物理版本的正式比较。
- E2 的 `candidate_only`、未完成标记、SHA 不符或没有物理 PASS 的场景拒绝提交，网页登记目录不会绕过检查。
- 正式修复场景需匹配场景 SHA、complete 标记、formal_release_eligible=true、physical_validation.status=PASS、父 SHA 和版本字段。此检查读取刘懋兴提供的本地验收证据，不代替独立物理验收或密码学签署。
- Worker 准备和 Controller 独立核验时复查提交时来源快照，提交后替换 sidecar 会失败；JSON/CSV 导出和回放 manifest 保留来源。
- 本次没有重算六份真实场景，也没有替刘懋兴把 E2 候选改成 released。输入只读和 LFS 内容保护仍需保持。

## 6. 文件结构与扩展入口

| 位置 | 用途/负责人 |
|---|---|
| eos_system/algorithm_registry.py | 新算法登记；四人协同改动前先对齐 ID/参数 |
| eos_system/controller*.py、worker*.py | 正式实验 IPC/取消/期限/进程回收；何明涛对接 |
| eos_system/storage.py、contracts.py、api.py | 状态、事务、契约与 HTTP；李泽同维护 |
| eos_system/replay_service.py、replay_builder.py | 回放编排、受控发布与独立构建 |
| replay/ | 共享配置、时间线、坐标/姿态示意与校验，前后端不各造一套任务语义 |
| replay_configs/、assets/satellites/ | 显式展示配置、NASA 模型和来源说明 |
| draw/fixed-payload-*.js、cesium_viewer.html | 消费 READY 样本、几何和双视图；梁兆榮维护 |
| eos_system/provenance.py | 场景来源快照与候选门禁；李泽同/刘懋兴对接 |
| scripts/build_scenario_manifest.py、recompute_scenario_windows.py | 最新数据审计与独立 E2 工具，保持原实现 |
| tests/browser/serve_integrated_fixture.py、integrated-system-smoke.cjs | 自动清理的真实网页验收工具 |

## 7. 本次验收记录

| 检查 | 结果 |
|---|---|
| 完整 Python 回归（最终代码） | 236 项，234 通过、2 项可选 Orekit 默认跳过；127.380 秒 |
| 独立真实 CZML 导出 | 1/1 通过；英文 epoch、UTC、正负时区偏移的等价时间生成相同 CZML；5.585 秒 |
| E2 重算及真实 Orekit | 44/44 通过；含等价 epoch 的 PV、窗口与姿态比较；42.998 秒 |
| Node.js 状态/几何/视图/总验收 | 4 组通过；新增 READY 唯一样本来源、插值及半开端点断言 |
| 真实 Chrome 网页 | 登记输出目录、空场景真实 Worker 提交、JSON/CSV 目录输出、下载、构建、两星模型/视锥/双视图、任务跳转和终态删除通过 |
| 网页关键证据 | 任务开始 00:00:10Z 为 OBSERVING；结束 00:00:15Z 为 IDLE；两个 Viewer 不独立推进；一次 POST 构建、旧 orbit GET 为 0；console/page error 为 0 |
| 统一检查 CLI + 旧接口 | 隔离真实 HTTP 检查通过：2 条种入的正式 assignment、五资源 SHA 匹配、旧 orbit GET 可用；测试后服务和文件清理 |
| 隔离服务清理 | 服务正常 shutdown，临时库、场景、缓存、导出、浏览器临时数据和协调文件已清理 |
| 保护与格式核查 | 历史删除 51/51 文件已存在；6/6 LFS 场景实际 SHA 匹配（250365834 字节）；输入与 E1/E2 无改动；git diff --check、83 个实际改动文件的语法/空白、关键文档本地链接检查通过；不提交测试产物 |

验收用临时场景/数据库/导出目录均隔离于实际运行库。浏览器两任务结果由测试种入，只验证回放；另提交空场景经过真实注册表/Worker/核验/事务链路，不能冒称两任务算法实验或真实物理验收。真实 Orekit 的等价时间 CZML 导出由可选独立测试覆盖。

### 如何复测

在 WSL 的已安装项目依赖环境中：

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
EOS_RUN_OREKIT_TESTS=1 PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -p test_orbit_export_integration.py -v
EOS_RUN_OREKIT_TESTS=1 PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -p test_window_recompute.py -v
node tests/fixed_payload_state.test.cjs
node tests/fixed_payload_geometry.test.cjs
node tests/fixed_payload_view.test.cjs
node tests/replay_acceptance.test.cjs
```

浏览器验收需 Playwright 和可用 Chromium。先在 WSL 运行 fixture 服务：

```bash
PYTHONDONTWRITEBYTECODE=1 python -B tests/browser/serve_integrated_fixture.py --coord <可供浏览器脚本读取的新协调文件绝对路径>
```

再在有浏览器的环境设置 `EOS_BROWSER_QA_COORD` 为同一文件路径，运行 `node tests/browser/integrated-system-smoke.cjs`。可选环境变量 `PLAYWRIGHT_MODULE`、`EOS_BROWSER_EXECUTABLE`、`EOS_BROWSER_PROXY` 分别指定依赖、浏览器和网络代理；服务默认 300 秒自动结束。脚本只连接隔离服务，退出后停止服务并清理。不要把自己的账号、代理或绝对路径写进代码。

线上检查正式实验可运行 `python scripts/check_visualization.py <run_id>`；首次需要构建时显式加 `--build`。旧轨道 GET 检查须另外加 `--check-legacy-orbit`，避免普通查询隐式生成旧链路。

## 8. 组员接下来做什么

| 成员 | 本次接到的基础 | 下一步交付 |
|---|---|---|
| 李泽同 | 公共运行框架、v3 数据库、统一回放、来源快照 | 公共接口审核、集成验收、主导机器学习算法 D，维护实验一致性 |
| 何明涛 | 恢复的 W1/W2、取消/超时/进程组故障测试 | W3 大结果文件通道、独立 replay 消息协议及强故障回收验证；传统算法 A；参与 D |
| 梁兆榮 | 已接通的 READY 页面、甘特图、模型/视锥/固定载荷视图 | 页面交互与可比结果展示、完整前端迁移复核、独立 Daemon/有限恢复；传统算法 B |
| 刘懋兴 | Manifest、epoch_parser_v1、E2 工具与候选门禁 | 真实 E3/E4、场景来源与固定小实例、成对实验及 ML 来源隔离划分；传统算法 C；参与 D |

算法 A/B/C 可自选，但机制须有实质差异；D 必须是机器学习算法。现有 completion_first/adaptive_repair 只作基线。D 的训练/验证/测试按独立母场景来源划分，不能用同一母场景裁片伪造独立样本；六个文件是否独立仍需来源证据。样本不足时先补数据，不能报告未经独立测试的泛化性能。

### 离阶段二完成还缺什么

1. **数据与物理验收**：完成真实场景 E3/E4，固定数据版本、哈希、独立来源与指标口径；确认 E2 的单传感器和默认 64 MiB 输入限制如何覆盖目标数据。
2. **四种新算法**：A/B/C 各机制测试、可行回放和同场景同预算成对实验；D 有可复现训练配置、模型版本、数据划分与推理接入，不把训练计时混成算法 RT。
3. **OS 强故障闭环**：W3 大结果协议、独立 Daemon、Controller 被杀后的有限恢复与重试上限，证明不会错杀、重复入库或永远重试。
4. **前端完整验收**：可比较结果页、最终图表/甘特图交互、真实发布场景的回放验收及旧接口迁移确认。
5. **最终集成与答辩**：固定种子矩阵、故障演示、输入只读证明、每人独立报告、完整启动/交接说明和带证据的验收清单。

建议先合入本修复 PR 形成共同基线，各成员从更新后的 main 新开分支；以后每个 PR 同步专题文档与 COURSE_SETUP.md，并至少由另一成员审核。提交前核对 diff，禁止把旧整仓文件直接覆盖最新 main。李泽同已授权本次本地提交；推送与 PR 另行确认。

## 9. 最终保护核对

- 历史 a43a826 → 当前 main 删除的 51 个路径在本分支均已恢复；部分恢复文件进一步集成，未要求字节等同历史版本。
- 六份 LFS 场景合计 250365834 字节，逐文件实际 SHA-256 与 LFS OID 全部一致；不删除正式数据和 LFS 缓存。
- input、experiments/scenarios、main_generate.py、utils/time_parsing.py、utils/visibility.py、Manifest/E2 工具及其原测试、.gitignore 相对起点没有更改。
- 本次仅执行李泽同已授权的本地提交；不推送、不创建 GitHub PR。
