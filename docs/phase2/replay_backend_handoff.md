# 第二阶段结果回放后端交接（李泽同 → 何明涛、梁兆榮、刘懋兴）

- 日期：2026-10-14；分支：feat/replay-backend；状态：本地实现与联调中，尚未 commit/推送/PR。
- 代码目录：Windows D:\Code\EOS-Course-Project；WSL /mnt/d/Code/EOS-Course-Project。
- 前置：使用 Ubuntu 22.04 的 Python 3.10 虚拟环境；回放缓存和 SQLite 放在 WSL Linux 文件系统的 EOS_RUNTIME_DIR。

## 1. 李泽同已经完成的后端范围

1. SQLite 从 user_version=2 增量升级到 3；新增 replay_artifacts、唯一缓存键、attempt 状态和 manifest 元数据。v1/v2 数据先经 SQLite 在线备份再迁移；正式计划与指标仍在原事务边界。
2. 增加 POST 创建/重试、两种 GET 状态、受控资源 GET，并为现有甘特图 schedule URL 附加 plan_sha256；原顶层 assignments/metrics 结构保持。
3. 新增独立回放构建进程和单并发队列。进程只读已提交计划和已登记场景，只写本 replay_id 的临时目录；Controller 校验并原子发布。回放构建耗时独立，不改 metrics.RT。
4. 参考构建可产生五种资源，当前姿态为 geometry_pointing_illustration。它根据轨道和目标构造**展示示意**，并在 manifest/diagnostics 中标明限制；尚不是 Orekit TargetPointing 权威整星姿态。
5. 保留原有终态实验删除接口，并在有 BUILDING 回放时返回 409；其余情况下先删回放记录，再清理本实验派生缓存。正式场景、正式导出文件和多实验共用轨道缓存保持原删除策略。
6. 新的网页实验在 RunConfig 快照中记录算法与共享约束源码 SHA-256；历史实验缺失则以 null + provenance_warning 表示，不能拿当前代码冒充历史出处。

**重要过渡约定：旧 GET /api/runs/{run_id}/visualization/orbit.czml 会保留到梁兆榮完成前端迁移。**它仍可能首次生成场景轨道缓存。新的 replay GET 全部不会启动构建；正式构建只由 POST /replay 发起。梁兆榮迁移并验收后，再另开 PR 清退旧 URL，现阶段不要直接删除或改名。

## 2. 前端消费的接口

已登记展示配置 ID：geometry-illustration-v2。页面只传 ID，不传 WSL 路径或自由几何参数。当前五个接口：

| 方法与路径 | 用法 |
| --- | --- |
| POST /api/runs/{run_id}/replay | JSON `{"replay_config_id":"geometry-illustration-v2"}`；新建/重试 202，已 READY 复用 200 |
| GET /api/runs/{run_id}/replay | 查询当前配置；可带 replay_config_id；未申请返回 NOT_REQUESTED |
| GET /api/runs/{run_id}/replays/{replay_id} | 精确轮询同一回放，配置切换时不串结果 |
| GET /api/runs/{run_id}/replays/{replay_id}/resources/{resource_key} | 仅 READY 可读；五个白名单键；ETag/If-None-Match 支持 304 |
| GET /api/runs/{run_id}/visualization/schedule | 旧计划顶层结构 + plan_sha256/provenance，甘特图仍读取同一正式计划 |

POST/GET 响应包含 run_id、replay_id、replay_status、replay_config_id、build_attempt、status_url、manifest、diagnostics_summary、timings.build_runtime_s、error。状态是 NOT_REQUESTED/BUILDING/READY/FAILED；run 的 SUCCEEDED 不因回放 FAILED 改变。READY 的 manifest.resources 下每项有受控 url、mime、size_bytes、sha256；不要拼服务器文件路径。

资源键：orbit_display（CZML）、attitude_samples（ECEF 米与 body_to_ecef xyzw 的绝对时间样本）、segments（IDLE/SLEWING/OBSERVING 半开区间）、diagnostics、replay_config。前端用同一个 Viewer 时间计算卫星模型、固定镜头、视锥和覆盖；不能把示意射线与地面交点写回正式完成任务数。

错误码要点：run/配置/资源不存在为 404，run 未成功或回放未 READY 为 409，参数错 422，队列满 429，READY 资源缺失/哈希错为 503。FAILED 构建以 HTTP 200 的状态响应表达并提供可重试信息；页面给出“重试”按钮可再次 POST。

## 3. 各组员下一步

### 梁兆榮：页面、Cesium/甘特图、Daemon

- 页面新增回放状态、构建/重试入口和错误诊断。只在用户明确触发时 POST；选星、刷新、暂停、倍速、跳转只读 GET/本地样本，不发起新构建。
- 以 run_id 的正式 schedule 和同 replay_id 的 manifest/五资源为一组，校验场景/计划 SHA 一致。实现 evaluateSatelliteState(t)，主 Viewer 是唯一时钟，固定镜头保持传感器安装旋转不变。
- 先按 geometry_pointing_illustration 显示“示意”标签；没有可靠姿态时禁用精确覆盖/成功结论。完成新接口迁移后，对比旧 orbit.czml GET 展示并书面确认可清退旧 URL。
- Daemon 只监护服务健康，不直接写 replay_artifacts，不替回放构建盲目重试。页面/API 变更记录在前端专题文档和 COURSE_SETUP.md。

### 何明涛：回放进程、IPC 与可靠性

- 当前参考进程以独立 Popen session 运行，通过退出码与临时 manifest 交接；算法 Worker 的双 Pipe/protocol_version=1 不变。
- 在自己的分支补正式 replay_protocol_version=1 消息：replay_start、replay_heartbeat、replay_built、replay_failed、replay_cancel_ack，字段含 replay_id/build_attempt/seq/输入哈希。Controller 仍是 READY 的唯一发布者。
- 复核 Orekit 子进程组超时/取消/Controller 崩溃后的回收，特别是 PID+start_token 与旧 attempt 的误投递。给出杀构建进程、杀 Controller、过期消息和无残留进程证据；变更在 Worker/IPC 专题文档记录。

### 刘懋兴：数据保护与来源核验

- 提供固定小实例及母场景来源、文件大小、scenario_id、SHA-256 清单；回放前后核对场景、正式计划和 metrics 不变。
- 核对原时间语义、轨道 epoch、sat_angles 时间来源、转向函数返回值、视场单值含义和非敏捷星姿态。指出何时只能展示示意，何时可升级为 Orekit TargetPointing。
- 与梁兆榮核对单星两任务、多星并行、空计划、非敏捷星、日期线/地平线和任务端点；提交诊断与显示质量验证记录，不把可视化结果计入成对算法指标。

### 李泽同：剩余集成

- 维护 v3 迁移、API 与 Controller 状态/发布边界；等何明涛的进程协议和梁兆榮的前端接入后联调。
- 可靠 Orekit 整星姿态与固定镜头的转换入口仍需与刘懋兴的数据核验一起完成；在此之前不将示意模式写成精确动力学。机器学习算法 D 的主责另按总计划执行。

## 4. 已验证与尚存限制

- WSL Ubuntu 22.04/Python 3.10.12：新增 v2→v3、HTTP→独立子进程→READY→资源 ETag→删除闭环测试 2/2；原 v0.2/迁移/删除定向回归 7/7。完整测试最终结果见 COURSE_SETUP.md。
- 本机旧结果库：迁移到 v3 后按授权清空 10 条终态测试实验；现 runs=0，输入场景与正式导出文件未删。
- 完整 Orekit 缓存未命中计算较慢：单星、10 分钟、3 个轨道样本的原导出器实测约 179 秒。回放默认 600 秒超时、单构建并发 1；大场景须实测后调整预算或预生成轨道缓存。
- 当前参考姿态以场景目标几何构造，载荷安装取显式登记的单位四元数展示假设，单值视场按完整正方形角解释；manifest 均标明 illustrative/assumption。非敏捷星以对地示意，不能宣称自由敏捷。
- 新资源单次读取上限 64 MiB；若组员生成更大姿态文件，先与李泽同协商分块/流式资源协议，不绕过哈希和目录检查。

## 5. 协作与版本

各成员从最新 main 建自己的分支，修改对应专题文档和 COURSE_SETUP.md，最后发 PR；公共字段先对齐接口文档。本分支尚未提交，李泽同审核后再决定 commit/PR。测试运行库和派生缓存不进入 Git。数据库当前 ER 图见 [database_current_v03.md](database_current_v03.md)，设计细节见 [接口](interface_design_target.md)与[数据库](database_design_target.md)。
