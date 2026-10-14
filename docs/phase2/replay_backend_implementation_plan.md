# 结果回放后端接口与数据库扩展实施计划（已批准，实施对照）

- 日期：2026-10-14
- 状态：李泽同已同意实施；本文件保留原计划目标。已落地的事实以 [回放后端交接](replay_backend_handoff.md) 和 [当前数据库 ER 图](database_current_v03.md) 为准。
- 开发目录：D:\Code\EOS-Course-Project；基线：main，051f286（编制时工作区干净）。
- 依据：用户提供的《第二阶段实施计划说明书》《第二阶段接口设计文档》《第二阶段数据库设计文档》2026-10-14 审核稿；当前仓库代码与 docs/phase2/team_collaboration.md。外来文档中的“已实现/未实现”描述以本次代码核对结果修正。

## 实施状态说明（2026-10-14）

数据库 v3、五个 HTTP 契约、参考独立构建进程、受控资源和删除衔接已实现，完整测试 105/105 通过。实际代码采用 `eos_system/replay_service.py` 与 `eos_system/replay_builder.py`，迁移 SQL 仍集中于 `storage.py`，尚未按原设想拆成 `eos_system/replay/` 目录或独立 SQL 文件。正式消息型回放 IPC、前端迁移、精确 Orekit 整星姿态与跨重启进程组彻底回收由组员后续分支完成；第 7 节 D 的组员联调仍未完成。旧 orbit.czml GET 保留到前端迁移验收。

## 1. 本次目标与完成定义

我负责把“已提交的正式实验结果 → 独立回放构建 → 浏览器受控读取”落实为可运行的后端契约。交付包含回放配置登记、SQLite 增量迁移、五个 HTTP 接口、独立构建任务的状态与发布流程、资源安全读取、删除与恢复衔接，以及对应测试和交接文档。组员拿到稳定的接口、示例响应和固定小实例后，可以并行开发 Cesium、甘特图、Worker 进程支持与数据核对。

完成标准不是只返回占位 JSON：至少用一个固定小实例，从已成功的 run 发起构建，得到可校验的 manifest 和受控资源 URL；重复请求复用同一 replay_id；失败、重试、重启、删除不改变正式计划与指标。几何示意模式必须标注为示意；可靠 Orekit 姿态模式只有在真实导出与坐标校验通过后才宣称可用。

## 2. 已核对的代码基线与必须消除的冲突

| 项目 | 当前 main | 本次处理 |
| --- | --- | --- |
| SQLite | eos_system/storage.py 的 PRAGMA user_version=2；新库直接建 v2，旧 v1 可升级 | 增加 v2→v3 加法迁移；覆盖 v0/v1/v2 开库与数据保留 |
| 实验删除 | DELETE /api/runs/{run_id} 已可删除终态 run，delete_files 只控制正式导出文件 | 保留已有用户能力；增加回放构建冲突处理和回放缓存清理，不照搬草稿“无删除接口”描述 |
| 正式计划 | GET /visualization/schedule 已返回旧页面可读的顶层 assignments/metrics | 保留这个形状，在 provenance 中补 plan_sha256 等身份字段，不让旧 Cesium/甘特图失效 |
| 轨道显示 | 旧 GET /visualization/orbit.czml 会同步生成缓存 | 新 replay GET 全部只读；旧 URL 暂留作兼容入口并标记过渡，待梁兆榮切换后单独移除 |
| 代码出处 | RunConfig 仅保存 algorithm_version，例如 baseline-1；不保存算法 Git SHA | 不能把版本名或当前 HEAD 冒充历史算法 SHA；见第 8 节的兼容决策 |
| 浏览器与运行环境 | Windows 浏览器；FastAPI、Controller、SQLite、Java/Orekit 在 Ubuntu 22.04/WSL2 | 运行库与回放缓存固定在 WSL Linux 文件系统，通过环境配置定位，不写死个人盘符 |

现有算法 Worker 的 IPC、正式结果核验和 metrics 计算不因回放改动。回放只读取成功事务已提交的 plans.plan_json、登记场景与独立 ReplayConfig；不能由页面刷新或选星重新调度。

## 3. 实施边界与模块结构

1. 在 eos_system/contracts.py 增加严格的 ReplayConfig/请求/状态模型，并在单独的回放配置模块登记不可变配置 ID、版本与规范 JSON 哈希。HTTP 只接收配置 ID，不接收任意服务器路径、四元数或模型文件名。
2. 在 eos_system/storage.py 的现有迁移机制上增加 replay_artifacts 表和封装方法。API、Controller 不拼散落的回放 SQL；构建进程和 Daemon 不连接 SQLite。
3. 在 eos_system/replay/ 下分开配置、模型、仓储适配、构建调度、manifest 校验与资源定位。eos_system/api.py 只解析请求、调用服务、映射 HTTP 响应，避免把 Orekit 运算写进路由。
4. 构建任务独立于算法 Worker 的协议与队列，默认并发 1；采用 replay_id/build_attempt/seq 检查过期消息。何明涛提供的进程组回收能力可在明确接口后接入，不改变原算法 protocol_version=1。
5. 先实现可复核的小实例几何示意构建链路，产物含 orbit_display、attitude_samples、segments、diagnostics、replay_config；姿态数据缺失时不能伪造 READY。目标指向示意与 Orekit TargetPointing 的质量标签必须不同。
6. 回放根目录由 EOS_RUNTIME_DIR 派生或独立环境配置指定，启动时检查真实路径不与登记数据源、原 output/Scenario_*.json 等保护输入重叠。大样本存文件，SQLite 只保存状态、快照、哈希与 manifest 元数据。

## 4. HTTP 契约与兼容策略

| 接口 | 后端承诺 |
| --- | --- |
| POST /api/runs/{run_id}/replay | 仅成功 run + 已登记 ReplayConfig；新建/重试返回 202，命中 READY 返回 200；队列满 429；不重跑算法 |
| GET /api/runs/{run_id}/replay?replay_config_id=... | 纯查询。无记录返回 NOT_REQUESTED，其他返回 BUILDING/READY/FAILED；默认配置由服务端登记 |
| GET /api/runs/{run_id}/replays/{replay_id} | 按精确 ID 查询，检查 replay_id 属于该 run，供切换配置后的稳定轮询 |
| GET /api/runs/{run_id}/replays/{replay_id}/resources/{resource_key} | 仅 READY 且资源键在 manifest 白名单中可读；校验目录边界、文件哈希与 MIME；支持 ETag/304 |
| GET /api/runs/{run_id}/visualization/schedule | 复用现有路由与顶层计划结构，增加 plan_sha256、scenario_id、scenario_sha256 的出处；仍从正式库读取 |

新回放接口统一返回 run_id、replay_id、replay_status、replay_config_id、build_attempt、status_url、manifest、error。NOT_REQUESTED 不插数据库假行；FAILED 是正常状态响应，不用 HTTP 500 表示。run/配置不存在为 404，run 未成功为 409，参数无效为 422。资源键错误或跨 run 为 404，未 READY 为 409，已清理为 410，READY 文件丢失或哈希不符为带明确错误码的 503。

旧 schedule 页面消费顶层 assignments/metrics，因此只做附加字段，不改变原结构；正式 JSON/CSV 导出继续由正式库重建，不把回放字段写入计划、metrics 或导出。旧 orbit.czml URL 的副作用作为兼容例外在文档中写明；新回放 GET 没有这种副作用。

## 5. 数据库 v3 与文件发布

新增 replay_artifacts：replay_id 主键；run_id 外键指向 plans(run_id) 且限制删除；scenario/plan/config 的身份与 SHA-256；算法/构建来源和各版本；唯一 cache_key；BUILDING/READY/FAILED；build_attempt、PID+start_token、last_seq；相对产物目录、manifest/哈希、诊断、耗时、错误与时间戳。建 run_id+created_at 和 status+updated_at 索引。NOT_REQUESTED 不入表。

迁移前记录 PRAGMA user_version 并用 SQLite 在线备份保留可恢复副本；迁移只增表和索引，单事务把 user_version 从 2 提到 3。新库按 v3 建立，v1 先经现有 v2 路径再到 v3；版本比代码新时拒绝启动。测试验证外键、唯一 cache_key、CHECK、旧 run/plan/metric 不变，并记录备份位置与回滚步骤。

cache_key 使用 run_id、scenario_sha256、plan_sha256、ReplayConfig 哈希以及构建/传播/姿态/几何版本的规范 JSON SHA-256。相同键 BUILDING 返回原 ID，READY 校验资源后复用，FAILED 原行 attempt+1 重试；并发由唯一约束和短写事务兜底。构建进程只写 <replay_id>/.build-<attempt>/；Controller 校验 manifest、资源哈希、时间端点、场景与计划身份后在同一文件系统原子改名，再以条件更新发布 READY。数据库事务不覆盖 Orekit 运算。过期 attempt 或 seq 不得发布。

Controller 启动先恢复原正式业务，再处理回放：旧 BUILDING 核验 PID+start_token、回收后标 FAILED；READY 校验目录和 manifest，缺损标 FAILED；未发布临时目录按归属清理。回放失败不回退 runs.status=SUCCEEDED，也不更改 plans、assignments、metrics 或 metrics.RT。build_runtime_s 单独保存。

## 6. 与现有删除功能的结合

终态 run 若有 BUILDING 回放，DELETE 返回 409 并提示先等待或取消回放；不在删除事务中强杀不受控进程。其余回放记录在同一写事务里先于 plans/runs 删除，外键 RESTRICT 保证遗漏时不能静默删正式记录。事务成功后只清理该 replay_id 下的可再生缓存；正式导出文件仍服从既有 delete_files 参数。文件清理失败返回告警并由受控孤立缓存扫描收尾，绝不清理登记场景或共享文件。资源读取与删除共用发布/清理协调，避免读到半删目录。

## 7. 分阶段执行与验收门槛

| 阶段 | 实施内容 | 阶段完成证据 |
| --- | --- | --- |
| A 契约冻结 | 从最新 main 建 feat/replay-backend 分支；补当前实现差异、错误码、ReplayConfig 样例、manifest 样例、组员消费示例 | 三份设计文档更新为“当前 v2 + 目标 v3”；梁兆榮和何明涛能据样例开始各自开发 |
| B 数据与只读接口 | v3 迁移、配置登记、仓储层、schedule 兼容补充、三个查询/资源 GET 的权限与状态处理 | v1/v2 数据保留；GET 不启动构建；旧 viewer 仍读取同一正式计划 |
| C 构建闭环 | POST、独立队列/进程、manifest 校验、原子发布、幂等/失败重试/重启恢复、一个固定小实例真实产物 | POST→READY→受控资源读取可复现；失败不影响正式 run；重复 POST 同 ID |
| D 删除与联调 | 回放缓存清理、与现有 DELETE 事务衔接；和梁兆榮/何明涛/刘懋兴分别完成前端、进程、数据联调 | 旧实验功能回归通过，接口示例和实际响应一致，保护输入 SHA 不变 |

阶段内代码写清晰中文注释：解释事务边界、幂等键、文件发布窗口、路径校验、过期消息判定与质量降级；普通字段不堆重复注释。每阶段在工作树中检查差异和测试，不提前 commit。阶段成果给李泽同审核后，再按其决定提交一次或分阶段提交；PR 最终以 main 为目标并请未编写者审核。

## 8. 必须在实施时同步修正的设计稿细节

1. 附件数据库稿称“首版无任意 run 删除接口”，当前 main 已有 DELETE。正式方案以已实现功能为准，数据库稿和接口稿补上第 6 节的回放删除策略。
2. algorithm_code_sha 在旧 run 中无法从 algorithm_version=baseline-1 推导。计划在新 run 创建时记录可验证的代码版本/工作树状态；历史 run 的 SHA 缺失以 null 和 provenance_warning 明示。replay_artifacts 的 algorithm_code_sha 对历史数据允许 NULL，不能伪造为当前 HEAD；需同步修改数据库约束、manifest 和接口示例。构建代码 SHA 单独记录实际构建 checkout。
3. 附件说回放 GET 完全只读；当前旧 orbit.czml GET 可写缓存。新端点按只读实现，旧端点保持兼容并在交接时明确，前端迁移完成后再另 PR 清退。
4. 附件建议 001_initial.sql/002_replay_artifacts.sql，而当前仓库以 storage.py 内嵌 SQL 维护 v2。先做真实 v2→v3 迁移并整理为独立、可检查的迁移 SQL；不重放初始建表。
5. 展示配置中的视场解释、姿态转换、采样频率、资源上限和超时需固定小实例实测后写入配置版本；未实测的值不在代码或文档里宣称为权威。非敏捷星不能静默改成敏捷指向。

## 9. 验证矩阵与组员交接

- 数据：空库、v1、v2 升级；重复开库；断电/异常模拟；唯一键、外键、CHECK；旧正式结果查询与导出字节/语义保持。
- API：未成功 run、缺场景、未知配置、并发同键 POST、READY 复用、FAILED 重试、不同配置隔离、精确 replay_id、GET 无副作用、ETag/304 与错误码。
- 文件与进程：路径穿越/符号链接/跨 run、哈希不符、半成品不可读、旧 attempt 消息、构建超时/崩溃、Controller 重启、READY 文件丢失、删除时读取与构建冲突。
- 回放内容：单星两任务、多星并行、首任务、空计划、时间端点、缺轨道/姿态、非敏捷、经纬度边界；标注示意质量，前后场景与正式计划 SHA 一致。
- 环境：在 Ubuntu 22.04/WSL2 的独立 EOS_RUNTIME_DIR 小实例上运行单元测试和 HTTP 闭环；Windows 浏览器仅访问 HTTP。测试运行库、缓存和临时目录结束后清理，不进入 Git。

交给梁兆榮：OpenAPI、ReplayConfig ID、五个端点样例、manifest v2、资源键、状态轮询与 ETag、schedule 兼容说明；由他负责界面、Cesium 与甘特图消费。交给何明涛：replay_protocol_version=1 消息字段、超时/取消/进程组回收接口和故障注入用例；算法 Worker 契约保持独立。交给刘懋兴：固定场景/计划保护清单、SHA-256、时间与姿态来源校核、示意与可靠模式的验证记录。

同一改动同步更新 docs/phase2/interface_design_target.md、docs/phase2/database_design_target.md（含 ER 图）、新建回放专题说明与 API 样例，并在 COURSE_SETUP.md 顶部记录版本、变更、实测和限制。README 增加用户可见的回放入口与依赖说明。数据库文件、母场景、大模型、构建缓存和临时文件不提交。

## 10. 本次审核关注点

请审核本计划的两个实际兼容决策：保留旧 orbit.czml GET 到前端迁移完成；历史 run 的算法代码 SHA 为空并明确警告。其余内容按上述阶段推进，开始编码前将具体配置版本、构建超时和缓存容量在小实例上测定并写入专题文档。
