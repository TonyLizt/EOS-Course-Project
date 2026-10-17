# 六场景接入与规模适配交接（v0.3.2）

- 日期：2026-10-16；分支：`feat/six-scenario-scale-adaptation`；基线 main `f0997ed`（PR #11）。
- 已完成代码、真实场景和浏览器验收；李泽同已授权本轮提交、推送和 PR 交接。
- 程序 v0.3.2；SQLite 仍 user_version=3，没有删表或清空历史实验。
- “接入通过”指 Legacy 系统流程可用，**不表示旧窗口通过了 E3/E4 物理验收**。

## 1. 现在怎样使用

启动系统后，网页的数据源自动出现：

| 数据源 | 默认 source_id | 场景 |
|---|---|---|
| 刘懋兴场景 · 小型（4份） | bundled-small | S1/S2，各 10 星和 20 星，20 任务、1 天 |
| 刘懋兴场景 · 中型（2份） | bundled-medium | S1/S2，50 星、100 任务、3 天 |

原文件继续放在 experiments/scenarios/small 与 medium，由 Git LFS 管理。路径相对仓库定位，不复制数据，不写死用户盘符。已有手工登记的同一路径会复用原 ID/名称；重复启动不增加重复项。客户端应查询 /api/data-sources，不假定所有人都使用 bundled-* ID。

1. 选数据源和场景；页面显示星数、任务数、天数、文件大小、来源和预计展示采样。
2. 两个基线均可提交，建议先使用默认 **60 秒算法预算**。1 秒不保证中型场景跑完，超时仍按正式规则落 TIMED_OUT。
3. 成功后下载 JSON/CSV；首次打开 Cesium 会自动构建并等 READY，失败时再手动重试；选星和任务跳转不重复构建。
4. 本批仍是 legacy_unknown/unknown，用于系统与 Legacy 基线验收；正式新物理版本仍待刘懋兴完成 E3/E4。

缺文件、只有 LFS 指针或 SHA 不符时，列表说明原因并禁用该内置场景，提交也重新校验实际 SHA。完成本机 Git LFS 下载后刷新；不要把指针当成 JSON 输入。内置目录与输出目录重叠时不会自动登记，页面提供诊断。

## 2. 实现结构

| 文件 | 职责 |
|---|---|
| experiments/scenario_catalog.json | 六份相对路径、完整 SHA、大小和实际规模；明确来源未知 |
| eos_system/scenario_catalog.py | 幂等登记、目录复用、输入/输出隔离、可用性和提交身份门禁 |
| replay/sampling.py | 与调度无关的确定性展示预算 |
| replay/scene.py | ijson 静态投影，不复制大型窗口/角度数组 |
| scripts/validate_bundled_scenarios.py | 两个基线×六场景、真实 Worker/核验/导出及六次真实回放，隔离数据退出清理 |
| tests/browser/serve_bundled_fixture.py、bundled-system-smoke.cjs | 真实 50 星浏览器验收，退出自动清理 |

### 2.1 列表与来源

列表 SHA 用有界指纹缓存（路径、大小、mtime、ctime），避免切换数据源时反复重读 250 MB。**提交和独立核验重新计算字节 SHA**，列表缓存不是执行信任依据。修改内置文件后须另存为自定义源，不沿用清单身份。

场景文件 ID 与内部 Scenario_S1/S2 分别保留，防止不同规模的内部同名场景混淆。自动登记不补造物理版本、母场景来源或独立训练样本证据。

### 2.2 采样预算

- 首选 5 秒；根据正式时域、星数和 assignment 数计算端点余量，每 assignment 保守预留 4 个观测/转向端点。
- 规则采样加端点的上界目标为 100000；步长向上取 5 秒倍数，最多 300 秒，不依赖机器快慢或文件名。
- 本批 10 星/1 天约 10 秒，20 星/1 天约 20 秒，50 星/3 天约 135 秒；小合成例仍可维持 5 秒。
- 短任务和转向端点强制补齐，活动区间仍左闭右开；不删任务、截断卫星或自动扩大 200000 样本/每资源 64 MiB 硬上限。
- 必留端点本身或时域过大时明确拒绝。规则采样变稀会降低中间时刻的展示精度，本次没有引入位置/姿态误差保证。
- 配置版本 1.1.0，默认 ID 仍 fixed-payload-illustration-v1；实际策略进入配置 SHA、缓存身份和 manifest.sampling_policy。
- 算法、原窗口、约束、正式计划与指标不变；FOV/安装/姿态仍为明示的几何展示假设。

### 2.3 大文件与前端

回放配置、文档和轨道导出共用静态投影。ijson 完整扫描 JSON，仅构造 metadata、satellites、missions、ground_stations 等静态字段，内部未知子字段原值保留。缺依赖时只允许 16 MiB 以下回退；ijson 已由 requirements-system.txt → requirements-course.txt 引入。

调度加载器仍按既有逻辑加载完整输入，没有改约束语义或宣称整个系统都流式化。源 SHA、读取变化检测和最终发布检查保留。

Orekit ZIP 单份临时复制到 Linux 盘，核对原包/副本 SHA 后使用并自动清理，减少 DrvFS 细碎读取。投影/导出入口版本进入传播身份，不复用错误版本缓存。

前端按星索引样本和阶段、二分定位；同一时刻按星缓存，模型/视锥/载荷可复用，最多保留一个时刻。保留原 ID、主时钟与固定安装。

## 3. API 和数据库

没有增加必填请求字段或新业务表：

- GET /api/data-sources 增加 catalog_warnings，原 items 兼容。
- GET /api/scenarios 的内置项附加 catalog_id、availability、expected_sha256、size_bytes、satellite_count、mission_count、duration_s、internal_scenario_id、scenario_physics_version、provenance_status、replay_preview。
- availability 为 ready/missing/lfs_pointer/hash_mismatch；内置 SHA 不符时 POST /api/runs 返回 422。
- GET /api/replay-configs 明示 adaptive_budget_v1、首选 5 秒、目标 100000、硬上限 200000、最大步长 300 秒。前端不能把首选步长当作实际步长。
- 兼容保留旧注册表 attitude_step_s=5，新增 attitude_step_is_preferred=true；它仅表示首选值，不承诺实际恒为 5 秒。
- READY manifest.sampling_policy 和 replay_config 给出实际步长、端点余量及上界。
- 现有 data_sources、replay_config_json 和 manifest 足以保存信息，模式和 ER 关系仍 v3；不回填旧 run 的路径或来源。
- 旧 orbit.czml GET、旧 geometry 配置和离线入口继续兼容，待梁兆榮迁移复核后另行清退。

## 4. 真实六场景验收

Windows + Ubuntu 22.04/WSL2、Python 3.10.12；两个基线使用同一场景 SHA、seed=42、60 秒搜索预算、默认约束、最早可行放置和完成率目标权重。

所有运行通过真实 HTTP → spawn Worker → Controller 独立核验 → SQLite，并验证 JSON/CSV。只给 completion_first 的六个结果构建真实 Orekit 回放；第二基线仅验证调度与导出。

| 场景文件（省略 .json） | completion_first 完成数 | adaptive_repair 完成数 | 回放步长/秒 | 样本数 | 姿态资源/MiB | 构建及资源验收/秒 |
|---|---:|---:|---:|---:|---:|---:|
| Scenario_S1_Sats50_M100_T3.0d_dist1 | 92/100 | 98/100 | 135 | 96300 | 29.57 | 14.31 |
| Scenario_S2_Sats50_M100_T3.0d_dist0 | 98/100 | 98/100 | 135 | 96317 | 29.54 | 18.328 |
| Scenario_S1_Sats10_M20_T1.0d_dist1 | 19/20 | 19/20 | 10 | 86456 | 27.15 | 8.313 |
| Scenario_S1_Sats20_M20_T1.0d_dist1 | 20/20 | 20/20 | 20 | 86465 | 27.18 | 7.979 |
| Scenario_S2_Sats10_M20_T1.0d_dist0 | 20/20 | 20/20 | 10 | 86459 | 27.15 | 8.12 |
| Scenario_S2_Sats20_M20_T1.0d_dist0 | 20/20 | 20/20 | 20 | 86467 | 27.20 | 8.235 |

- 12/12 正式运行 SUCCEEDED、6/6 回放 READY；五资源大小/SHA 匹配，回放前后正式计划和 metrics 相同，源 SHA 前后相同。
- 每个验证 run 通过 DELETE 清理，整个临时运行目录退出删除；未把验证实验写入实际运行库。
- 算法与共享约束源码 SHA：39ca993843e09c74dd7f6199e6d8292f3d8b7d24e0b7d3b73295c978335d070c。
- 构建源码 SHA：4b564572e94b41e64eb059eadc89460856335849c84b01c597fadb263b877236。
- 初次 1 秒诊断的 S1 中型 completion_first 正常超时，随后明确使用 60 秒，不放宽 Controller 规则。
- 这是单种子的系统接入证据，不是论文复现、统计排名、物理验收，也不证明六文件来自独立母场景。

## 5. 回归和浏览器

- 新增针对性测试 11/11；完整 unittest 247 项（245 通过、2 可选 Orekit 默认跳过），138.673 秒。
- 真实等价 epoch CZML 检查 1/1 通过，4.278 秒；Node 四组含 50 星索引、浮点插值与端点检查通过。
- Chrome/CesiumJS 1.136 真实 S2 50 星：4+2 选项、149.5 MiB/来源/135 秒提示、50 模型及 800 条边界射线配置、任务跳转和双视图同钟通过。
- 主/次时间均为 2025-11-18T12:00:11Z，M100 为 OBSERVING，无 page/console/resource error，打开 READY 无额外 POST。
- 浏览器检查含主动等待约 9.278 秒，只代表本次环境，不是性能保证。

### 复测

在安装系统与可视化依赖的 WSL 虚拟环境、仓库根目录执行：

~~~bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python -B scripts/validate_bundled_scenarios.py --budget-s 60 --report <新的报告绝对路径>
~~~

工具禁止覆盖报告或写入输入目录，临时运行数据自动清理。浏览器验证先运行 serve_bundled_fixture.py 并指定新的共享 --coord 文件，再设置 EOS_BROWSER_QA_COORD 运行 bundled-system-smoke.cjs。依赖、浏览器、代理通过 PLAYWRIGHT_MODULE、EOS_BROWSER_EXECUTABLE、EOS_BROWSER_PROXY 传入；个人路径不写入仓库。结束后服务、轨道、回放和协调文件清理。

## 6. 四人接续与限制

- 李泽同：公共登记/来源/预算接口、算法 D、结果比较后端与集成验收。
- 刘懋兴：六场景可用于 Legacy 测试；继续独立来源、E3/E4 正式版本与 ML 来源隔离划分，不把自动登记理解为物理发布。
- 梁兆榮：读场景元数据和 manifest 实际采样，不写死路径或 5 秒；继续最终比较界面、Daemon 和更广交互验收；旧 orbit GET 保留。
- 何明涛：继续 W3/正式 replay IPC 与强故障回收，保持严格预算与独立核验边界。

E2 工具仍有单传感器和默认 64 MiB 重算输入限制，本轮没有改它，也没有生成 epoch_fixed_v1。更大规模需另行制定预算或分块协议。新算法、Daemon 和真实动力学不属于本次交付。

源数据/LFS、算法与约束、E1/E2 原工具只读；实际运行库仅在最终启动时幂等登记两输入目录。最终格式与清理核查同步 COURSE_SETUP.md。本轮由李泽同授权提交、推送，并通过 PR 交接。

### 轨道显示精度与物理验收边界

原始轨道仍每 300 秒传播一次，相邻位置按直线插值，可能显示为折线。10/20/135 秒为回放状态采样，不能恢复原始点之间的真实曲率。后续应统一提高轨道线、卫星、相机和投影的位置精度，并与直接传播结果比较误差。本轮流程与浏览器验收不代表连续轨迹精度或 E3/E4 已通过。E3 核对时间、坐标系、传播和窗口一致性；E4 在需要时重算派生窗口、标记版本并重新实验。
