# EOS-Course-Project 第二阶段 W2：Worker/IPC 与 Controller 生命周期协作实施说明

> **版本**：v1.0 · 2026-10-14  
> **状态**：拟实施方案／跨模块协作说明，**不是已完成的功能或测试记录**  
> **方案负责人**：何明涛（Worker、IPC、取消与超时机制）；Controller 集成负责人：李泽同  
> **开发分支**：`feat/hmt-worker-ipc`；W1 已推送：`906fe70`、`70fdefe`；尚未创建 PR  
> **拟入库位置**：`docs/phase2/worker_controller_w2_design.md`  
> **本轮范围**：W2-A 运行中取消；W2-B 超时／异常／单 Worker 回收；W2-C 安全进程组回收与 Controller 停机  
> **不涉及**：算法 A/B/C/D 实现、HTTP 新接口、SQLite 模式迁移、Daemon 主程序、大计划文件载体（W3）

## 1. 依据、效力与职责

### 1.1 上位约束和优先级

本方案依据下列仓库文档制定：

1. `docs/phase2/team_collaboration.md`：成员职责、接口变更通知、文档同步和 PR 审核规范。
2. `docs/phase2/framework_handoff.md`：**当前 v0.2.1 已实现边界**；不将目标稿误认为当前代码。
3. `docs/phase2/interface_design_target.md`：公开状态、IPC 事件种类及取消／核验语义的**目标契约**。
4. `docs/phase2/database_current_v02.md`：当前已实现 SQLite 九表及迁移状态；`eos_system/storage.py` 的实际 `SCHEMA` 为物理模式依据。
5. `docs/phase2/database_design_target.md`：后续目标字段与恢复语义，不能直接当成已落地字段。
6. `docs/phase2/algorithm_integration.md`：新算法 `solve(problem, constraints, context) -> Schedule` 及 `SolveContext.is_cancelled()`。
7. `docs/phase2/worker_ipc_w1.md`：已完成 W1 Worker 端控制 IPC 及协作取消协议。
8. Codex《W2 Controller 生命周期与进程回收设计审计》（2026-10-14）：现有 `controller.py` 风险与拟改造点；**系基于代码阅读的审计报告，不视作 W2 测试通过证据**。

若本方案与已合并公共契约或实际代码有冲突，**停止对应改动并以现行公共契约为准**；需要改变公共契约时，由李泽同确认集成影响后另行更新文档。本方案不擅自扩大 `Controller`、`Daemon` 或数据库职责。

> 仓库曾有早期计划稿使用 Windows 工作树和 `/mnt/c/EOS-Bench`；目前本人的实际唯一开发工作树为 `/home/mint/projects/EOS-Course-Project`，只读数据为 `/mnt/f/EOS-Bench`。**这些是本机部署实例，不应硬编码为全体组员的默认路径**；系统通过 `EOS_RUNTIME_DIR`、已登记数据源和输出方案确定目录。

### 1.2 可以由我们确定、需要通知与不得自行变更

| 层面 | 归属与处理原则 |
|---|---|
| Worker 内部线程／进程与 Pipe 组织、取消标记、受控信号、超时实现、故障测试 | **何明涛制定并实现**，符合 W1 和公共契约即可；不逐项等待李泽同决定技术细节。 |
| 在 `controller.py` 调用已约定的 `cancel`，管理本 attempt 的 deadline 和进程组回收、修复安全停机 | 属于**跨模块集成改动**；本说明给出拟改造方案，**实施前通知李泽同修改范围与预期行为**，在同一分支作最小改动，合并前由其确认集成影响。 |
| 更改 HTTP 路径、状态枚举／响应含义、SQLite 表结构／迁移、`Solver.solve()` 签名、Daemon 权限 | **不在本轮做**。若确有必要，先提出单独的变更申请，取得李泽同确认后处理。 |
| `stop()` 的实例锁、运行状态写入及现有 Controller 单线程串行特性 | 沿用当前所有权；可修复与 Worker 生命周期有关的安全问题，但不能改造成另一套 Controller 或多 Worker 调度框架。 |
| Daemon 重启策略、旧 Controller 崩溃后的 orphan 处理 | 由梁兆榮与李泽同主导联调；本方案仅定义 Worker 身份和回收能力的接入点。 |

## 2. 本阶段冻结的不变量

1. **一次 `(run_id, attempt)` 一个独立 `multiprocessing.spawn` Worker**；暂保持 Controller 的单活动 Worker 处理模型及其队列语义。
2. **双单向 Pipe、JSON 字节、协议版本 1、消息大小上限 4 MiB**；IPC 只传纯数据，不传 `Schedule` Python 对象或 SQLite 连接。
3. Worker → Controller 事件：`started`、`heartbeat`、`candidate_result`、`failed`、`cancel_ack`；Controller → Worker：`start`、`cancel`。Worker 主线程是其事件发送、事件 `seq` 分配和控制读取的唯一所有者；求解线程通过队列交付结果。
4. `cancel_ack` 表示**Worker 已收到并接受取消**；不代表算法结束、Worker 已退出、后代进程已清理，更不代表数据库进入 `CANCELLED`。
5. Worker 自报的候选计划和 runtime 都**不是正式结果**。`set_verifying()`／`finish_success()` 及统一 `verify_candidate()` 仍由 Controller 执行；只有成功事务提交的计划、assignment、metrics 是权威数据。
6. **仅 Controller 写业务 SQLite**；Daemon 不直接修改 `runs`／`plans`／`metrics`，Worker 不打开业务数据库；不引入模式迁移。
7. 保留 `CREATED`、`QUEUED`、`RUNNING`、`VERIFYING`、`SUCCEEDED`、`FAILED`、`CANCELLED`、`TIMED_OUT`，终态不可回退。不在本轮增加 API 状态枚举。
8. `time_budget_s` 仍表示 `solver.solve()` 的算法搜索预算；`RT` 与现有 `EvaluationMetrics.runtime_efficiency` 口径不变，不含加载、序列化、核验和导出。Controller 墙钟防护另计。
9. 队列任务在 `QUEUED` 时可直接取消；运行时取消只提出请求，在必要的退出／回收与状态裁决完成后才进入终态。
10. 数据来源只能走服务端登记路径；原始 `/mnt/f/EOS-Bench` 只读，测试数据库和写入文件使用临时 `EOS_RUNTIME_DIR`，不得触及正式运行目录。

## 3. 我们确定的取消、超时和终态裁决规则

以下为**本方案采用的确定规则**，不新增公共状态，仅细化 Controller 已有状态机行为；实现时需要在 Controller 集成评审中告知李泽同。

### 3.1 运行中取消（W2-A）

1. HTTP `POST /api/runs/{run_id}/cancel` **继续只由原 API／数据库逻辑受理**，写入 `cancel_requested_at`；不让 API 直接持 Pipe。
2. Controller 轮询到本次 `(run_id, attempt)` 有取消请求时，先固定本 attempt 的 `stop_reason=USER_CANCEL` 和单调时钟起点，**仅发送一次** `cancel`；继续接收 Worker 事件，不立即跳出事件循环。
3. 沿用 W1 已兼容的旧 `start` 格式，则本 attempt 第一条完整 `cancel` 的控制序号使用 `seq=1`。消息必须具有：`protocol_version=1`、`run_id`、`attempt`、`seq`、`kind="cancel"`、带时区 `sent_at`、`payload={}`。后续若统一完整 `start`，则分别单调递增控制序号；不能复用同一个 `seq`。
4. Controller 收到 `cancel_ack` 只记录“Worker 接收取消”；**不重置宽限期限**，重复或晚到 ack 不改变状态。若 Pipe 断开、send 失败或 Worker 不配合，立即进入受控回收路径。
5. Controller 给 Worker 有界协作退出宽限。W1 Worker 自身最多等待 2 秒；Controller 的宽限从**首次取消发起的单调时间**计算，需覆盖小量 IPC／调度余量，具体秒数作为内部可配置参数经隔离实测确定，不能将 W1 的 2 秒误作全部回收上限。
6. Worker 退出后，Controller 必须检查直接进程和可验证的后代清理状况，才可写入 `CANCELLED`。无 `cancel_ack` 但进程已安全结束且已有用户取消请求，仍可据事实进入 `CANCELLED`；不以是否收到 ack 作为终态唯一条件。
7. 已取消 attempt 的晚到候选不得进入 `SUCCEEDED`；保留 `set_verifying()` 和 `finish_success()` 的数据库防竞争检查。已经**成功事务提交**的运行再取消，沿用原 API 的 409 语义。

### 3.2 超时与错误分类（W2-B）

| 触发情况 | 对外终态 | 内部诊断代码／处理 |
|---|---|---|
| 算法预算墙钟保护真正到期，且 Worker 已受控回收 | `TIMED_OUT` | `ALGORITHM_TIMEOUT`；记录首次搜索阶段时间、预算、清理耗时 |
| Worker 未按期完成启动或进入搜索阶段 | `FAILED` | `WORKER_STARTUP_TIMEOUT`（不把加载计入算法 RT） |
| 候选传输／退出等待失去响应 | `FAILED` | `IPC_TRANSFER_TIMEOUT` 或 `WORKER_EXIT_TIMEOUT` |
| Worker 异常退出、IPC 无效、求解异常 | `FAILED` | `WORKER_EXIT`／`IPC_PROTOCOL_ERROR`／算法错误代码 |
| Controller 主动停机而中断正在执行的 Worker（并非用户取消） | `FAILED` | `CONTROLLER_SHUTDOWN`；不伪装为用户 `CANCELLED` |
| Worker／必要后代经有限回收仍**已知存活**或身份无法安全证明，无法确保要求的清理完成 | `FAILED` | `WORKER_CLEANUP_INCOMPLETE`，记录受限事实和剩余风险；不得声称清理成功 |
| Worker 候选合法、退出和必要清理均正常、Controller 独立核验通过、提交前无取消／超时裁决 | `SUCCEEDED` | 沿用原正式事务 |

上述诊断码为**内部候选命名**，不是新 HTTP 状态／新增数据库枚举。若现有错误码有相应名称，实施时优先复用；需要新增对外 `error.code` 时先同步接口维护人。对身份尚不可验证但没有证据表明存在后代的正常 Worker，可按直接进程正常退出和既有核验链路处理，并记录回收能力降级；若**确有强制回收需要**但无法安全确认影响范围，则按清理未完成处理。

**取消／超时／候选竞争判定**：Controller 在一个 attempt 的串行裁决逻辑中锁定首个需要终止的理由；锁定超时前必须再查数据库已受理的取消请求。若先已持久化取消请求，则用户取消优先；若超时已经判定并进入受控回收，后来取消不得把已判定的超时覆写为取消。**SQLite 的正式成功提交顺序始终是最终权威**：成功先提交则终态保持 `SUCCEEDED`，取消请求先持久化则禁止后续成功提交。不能仅以不同机器／线程的 `sent_at` 排序作为竞态裁决。

### 3.3 算法预算的分段边界

- `startup_deadline`：在 `process.start()` 前设置单调计时监护，涵盖启动、`setsid()`、初始握手、场景加载直到首次有效 `SEARCHING`。启动调用自身若可能不可抢占，需通过隔离测试识别，不应伪称已有严格的进程创建超时保证。
- `search_started_at`：只在**首次有效** `heartbeat.phase=SEARCHING` 记录一次，后续同类心跳不得重置。
- 当前实现仍有 `time_budget_s + transfer_timeout_s` 的合并墙钟截止；在无法准确辨认求解结束之前，W2-B 先保持这个外部防护口径，明确其**并非严格的算法预算即时强杀**。超过预算的自报算法 runtime 仍不能被当作合格正式计划。
- 如果要精确拆分搜索和传输，需 Worker 在 `solve()` 真正返回时发出可信的内部阶段标志，然后独立设置序列化／IPC 传输期限。**不改 `RT` 计算口径**；该扩展先在 W2-B 通过隔离测试论证，再同步到专题文档。
- 所有墙钟计时使用 `time.monotonic()` 或等效时钟，日志时间可用带时区 ISO 8601；不可仅依靠 Worker 自报秒数来实施硬超时。

### 3.4 `VERIFYING` 及 Controller 停止期间

- Worker 退出后的核验仍由 Controller 同步执行。`VERIFYING` 期间如用户取消已先于成功事务被受理，则沿用既有存储保护，不插入正式成功计划。
- `stop()` 要求**禁止领取新任务 → 通知／回收活跃 Worker → 等待执行线程和附属 IO 任务安全结束 → 释放 `flock`**。
- 关闭开始时仍在 `RUNNING` 且因此被中断的 attempt：回收后写 `FAILED/CONTROLLER_SHUTDOWN`；`QUEUED` 未启动任务保留原有持久排队语义，供下一次安全恢复。
- 若已处于核验／正式提交阶段，不能靠强杀 Controller 后台线程来保证退出。允许正在执行的原子提交／核验按既有数据库保护规则完成，并继续持锁直至线程结束；若有限等待期限到达仍未结束，**`stop()` 必须显式报告未完成并保留锁与必要的执行资源**，不得把失败停机当作完成，更不能先解锁再留线程写库。
- 如果进程被外部 `SIGKILL`，任何 Python 级清理、保存与 `flock` 保持均**不能保证**；这属于 Daemon／重启恢复边界，而非 `stop()` 的正常返回保证。

## 4. W2 的 IPC 与执行架构（最小兼容实现）

### 4.1 attempt 级内部状态（非业务 DB 字段）

由 Controller 管理临时对象，字段建议如下（命名可随代码组织调整）：

```text
run_id / attempt
process_handle / pid / verified_process_identity
control_send_seq / cancel_sent / cancel_ack_received
termination_reason / cancelled_at_monotonic
startup_deadline / search_started_at / search_deadline / transfer_deadline
candidate_received / failed_event / ipc_io_error
reap_result / exit_code / cleanup_diagnostics
```

- 此对象只服务于**本次 attempt**，不得跨不同 run/attempt 复用控制序号、Pipe 或身份标记。
- Controller 是唯一状态、消息受理顺序、数据库写入与终态裁决者。独立 IO 任务只提供字节读写及异常结果，**不调用 storage API**。
- 消息校验顺序：帧大小／JSON → 必需字段及类型 → `protocol_version` → `(run_id, attempt)` → `kind` 与载荷结构 → `seq`（不要求连续，仅接受递增）→ started 的可信身份比对 → 持久化被接受事件。**不得先把未核实 `started` 的 PID／start token 写入数据库。**

### 4.2 防阻塞 IPC 约束

- 现有 `event_recv.poll(0.1)` **不保证**后续 `recv_bytes()` 的整帧读取有硬时间上限；控制 `send_bytes()` 也可能阻塞。仅在外部多写一层 `poll()` 不能视作解决。
- W2 应在 attempt 内采用**一个独占接收、一个独占发送的受管理 IO 通道／任务**，或经严格测试验证的有界非阻塞帧读取实现；使用临时内部队列向 Controller 传递事件和错误。不能多个消费者竞争同一 Pipe。
- IO 队列与可接收消息体积须有界（目前 4 MiB）；不接受无限缓冲。IO 任务在强制回收后要有明确退出检查；如无法保证任务退出，不能提前释放 Controller 实例锁。
- Worker 的 `failed` 事件优先于“退出码等于 0”的正常退出判断；异常消息、EOF、exit code 和清理结果共同形成诊断结论。
- 后续 W3 大结果改为临时文件传递时可复用相同的 attempt 与接收框架，但 W2 不提前实现文件载体。

## 5. Linux Worker 进程组及后代回收规则（W2-C）

### 5.1 核验依据

Worker 在 `setsid()` 成功后，预期 `SID=PGID=PID`；**不能**仅依据 Worker 消息中自报的 PGID 实施 `killpg()`。Controller 需组合核对：

1. 自己 `Process` 对象的 `pid`，Worker 上报 `started.worker_pid`；二者必须一致。
2. 父侧读取的 `os.getpgid(pid)`、`os.getsid(pid)`，成功建组时均等于该 pid，且不能等于 Controller 自己的 SID／PGID。
3. `/proc/<pid>/stat` 的进程启动 tick（解析 `comm` 的括号后再按 Linux 字段解析）及 `/proc/sys/kernel/random/boot_id`；保存本次 attempt 的可核验身份快照。
4. 每次**危险信号调用前**重新核对仍可获得的进程身份、SID、PGID 与组成员；对 `pgid<=0`、当前 Controller 组、已复用 pid 或信息不足的场景禁止组信号。

Worker 可能尚未执行 `setsid()`、组长可能已退出或 PID 被复用；身份校验失败时，只能使用当前本次 `Process` 句柄安全地终止直接 Worker，并记录“后代回收未证实”。

### 5.2 两级回收

1. 先尝试 W1 的 `cancel` 协作退出，有界等待。
2. 若仍未完成：**对已经验证的目标身份**发送 `SIGTERM`，有界等待并核对真实存活状态；必要时再发送 `SIGKILL`，再有界等待。
3. Worker 主进程仍保有可验证的同一 OS 身份时，可在防 PID／PGID 复用检查后对其可信独立进程组操作；组长已退出后，**禁止仅凭历史 PGID 盲目 `killpg`**。如需进一步回收旧组的成员，应扫描 `/proc` 核验每个成员的同组／同 session／启动身份；条件可用时使用 pidfd 或其他经过验证的定向方式，不能把未验证成员当成可信目标。
4. 清理后由 Controller 检查本次 `Process` 退出码、后代进程的**非僵尸存活情况**和无法证明的残留范围。僵尸的回收责任可能落在其实际父进程／subreaper，不将“短暂僵尸不可回收”错误宣称为仍在运行的计算任务。
5. 后代若主动 `setsid()` 或迁出原进程组，原组信号不再具有完整覆盖能力；W2 文档和故障演示须明确此限制，不能宣称任意逃逸后代都能被终止。

**硬性安全禁令**：不对 `killpg(0, ...)`、负值／未知 PGID、Controller 自己进程组、仅从 IPC 取得而未核实的 PID／PGID 发送信号。因无法证明安全而放弃组信号，优于误杀同学的服务或 Controller。

### 5.3 清理结果和 DB 记录

- Controller 将收到 ack、发出的信号、PID／PGID 身份验证结果、退出码、超时次数及残留风险写入已有 `run_attempts`／`run_events` 能表达的位置。
- `run_attempts.exit_code` 是**当前已存在的列**；可以增加小型内部写入方法填充它，但不能绕过 `storage.py` 的事务和状态约束。若当前存储接口不足，先提出方法与测试，再由 Controller／数据库维护者审查；不在 W2 新增表或迁移。
- **已确认存在未清理的活后代时不提交 `SUCCEEDED`**；失败诊断必须明确说明残留。没有后代证据且 Worker 正常退出的正常路径，不因缺少组清理而无条件判失败。
- Controller 发生崩溃后，历史随机 `worker_start_token` 无法证明 PID 身份；W2 **不**根据旧数据库 PID 盲目执行杀进程。继续保留当前 `recover_interrupted()` 把遗留 `RUNNING/VERIFYING` 标为失败的行为，并将“跨 Controller 崩溃的孤儿清理”列为与 Daemon 联调的未完成项。

## 6. Controller 必须修改／应通知李泽同的清单

> **这一节是跨模块交接的核心。** 修改内容由我们提出并在功能分支上实现；在动手编辑 Controller 前，将本节发给李泽同知悉，避免并行改同一函数。涉及公共契约或数据库行为变化时，由其确认集成影响，PR 必须由非作者审核。

| 文件／位置（以仓库实际代码为准） | 当前问题（Codex 审计） | W2 拟修改内容 | 改动性质／通知级别 |
|---|---|---|---|
| `eos_system/controller.py` — `Controller._execute()` | 有 `spawn` 和双 Pipe；发现取消即跳出，未发 W1 cancel | 维护 attempt 状态、给控制 Pipe 发送完整 `cancel`、继续消费 `cancel_ack`／事件、禁止取消候选进入核验；增加有界等待、异常路径与退出结果收集 | **必须提前通知**：属 Controller 核心逻辑，但不改 HTTP／DB schema |
| `eos_system/controller.py` — `_execute()` 的计时与接收 | 重复 `SEARCHING` 可重置起点；`recv_bytes()` 在 `poll()` 后仍可能阻塞 | 首次有效阶段事件确定时限；抽取可监控 IPC IO 和 deadline；保持原算法 `RT` 口径 | **必须通知**：改变内部时序，说明回归测试 |
| `eos_system/controller.py` — `Controller._loop()` | `start_attempt()` 与停机标记存在竞态 | 对“停止领取下一任务”与启动 attempt 进行串行协调；不改变队列／并发公开语义 | **必须通知**：涉及队列同步与状态 |
| `eos_system/controller.py` — `Controller.start()` | 获锁后的恢复／线程启动失败无统一释放路径 | 保证初始化异常时妥善清理资源；正常停止遵守锁的唯一所有权 | **必须通知**：Controller 单实例生命周期 |
| `eos_system/controller.py` — `Controller.stop()` | join 最多 10 秒后不检查线程存活便释放 `flock` | 停止领取、发协作取消、受控回收、等待执行和 IO 线程退出；失败时报告并维持锁／防双写 | **必须通知并重点请其审阅**：影响服务关闭与 Daemon 重启 |
| `eos_system/worker_process.py`（可新建） | 单进程 `terminate()/kill()` 无法覆盖受信任的后代 | 封装 Process 身份读取、PGID/SID 核验、SIGTERM/SIGKILL、结果对象和保守降级；不能直接写数据库 | **本模块自主实现**；接口交给 Controller 调用并告知李泽同 |
| `eos_system/storage.py` — `run_attempts`／事件函数 | 已有 `exit_code` 但未填，事件记录时可能先信任 started payload | **优先仅调整 Controller 调用顺序**；只有确有必要时增加小型事务写入方法，不改表／字段／迁移；新方法先与李泽同确认 | **若需修改此文件，先通知／获得维护者确认** |
| `eos_system/worker_reference.py` | W1 已支持取消；无跨进程后代回收责任 | W2 优先复用现有协议；仅在计时边界或身份验证确有必要时最小补充；保持 W1 测试 | **我们自主维护**；协议字段扩展须通知 |
| `eos_system/config.py`（如需要） | 已有超时配置 | 可增内部可配置取消宽限／回收期限，并带范围检查；不新增任意 HTTP 输入 | 实现前告知配置默认值，不改变算法搜索预算定义 |
| `docs/phase2/worker_controller_w2_design.md`、W1 专题文档 | 目前只记录 W1 | 同步 W2 真实实现、测试、时序及限制；区分设计与验收 | **我们维护** |
| `docs/phase2/interface_design_target.md`、`framework_handoff.md` | 公开文档需要与实际 Controller 行为一致 | **只在行为真正发生变化后**增补“当前实现”说明；不把目标稿直接变成实现承诺，具体改动交李泽同审阅 | **应通知并经李泽同确认** |
| 根目录 `COURSE_SETUP.md` | 所有 PR 需版本记录 | W2-A/B/C 按实际完成情况补日期、变更、测试、限制，不覆盖其他组员的记录 | 依团队规范，提交前检查冲突 |
| `tests/` + 隔离联调脚本 | 无 Controller 发 cancel、组回收、持锁停机测试 | 新增真实 spawn、HTTP/SQLite 临时实例、危险信号安全测试 | 我们自主实现，结果交李泽同联调复核 |

**不应修改**：`api.py` 公开请求格式、SQLite schema／迁移、算法注册签名与算法 A/B/C/D、正式计划核验器的拒绝规则、Daemon 代码及数据登记方案。若实际审计暴露必须改动，暂停该子项而不是暗中扩张改动范围。

## 7. W2-A / W2-B / W2-C 实施与验收门槛

### W2-A — 取消链路接通（优先开始）

**改动**：最小化 `Controller._execute()`，把 W1 已有完整 `cancel` 控制信封、ack 处理和结束时限接上。此阶段不能用直接退出事件循环代替发送取消；不能在 ack 到达时立即记 `CANCELLED`。

**必测**：隔离 HTTP 运行中取消 → DB 受理 → Controller 发 cancel → 真 Worker ack → 无候选正式提交 → Worker 结束 → 终态 `CANCELLED`；启动后立即取消、重复取消、晚到候选、过期 attempt、旧正常成功路径。涉及 IPC 读／写的测试要包含断链与人为阻塞，不可只以 Mock 测试声明抗阻塞通过。

**阶段验收**：测试在隔离临时环境真实执行，通过后才记 `W2-A PASS`；若读／写阻塞仍无界，最多记 `FUNCTIONAL PASS / RELIABILITY PENDING`。

### W2-B — 期限、异常、单进程强制回收

**改动**：建立可信墙钟时限、IO 读写阻塞处理、`SIGTERM → SIGKILL` 有界兜底、异常事件与退出码诊断。保持算法 RT 不变。

**必测**：不合作求解器、算法预算到期、启动／传输／退出超时、IPC EOF 与半帧、Worker 崩溃、取消与候选竞争、无遗留 Worker、正常成功链路不回归。

**阶段验收**：受控生命周期路径有界且测试通过；不能把 `Process.is_alive()==False` 误认为后代也已退出。

### W2-C — Linux 进程组回收与安全停机

**改动**：`worker_process.py`（可选名称）封装组身份和安全回收；修复 `Controller.start()/stop()/_loop()` 的持锁／领取竞态。

**必测**：Worker 派生后代，取消或超时后可信组清理；组长先退出，后代存活；恶意或错误 PGID 不误杀旁观进程；`setsid()` 前取消保守降级；`stop()` 在活动 Worker 和核验中不得提前解锁；多次 stop/start 异常边界。

**阶段验收**：不误杀、无已确认的非僵尸后代遗留、退出和锁释放次序可验证；不满足时报告 `PENDING/BLOCKED`，不把功能性通过等同于可靠性通过。

### W2 最终回归与环境隔离

- `~/eos-course-runtime/.venv/bin/python -m unittest discover -s tests -v`，运行前先确认实际虚拟环境与测试依赖。
- 在独立 `TemporaryDirectory` 中设置全新 `EOS_RUNTIME_DIR`、场景副本、SQLite 和本机测试端口；验证 HTTP → Controller → Worker → 核验 → SQLite，包括取消、超时、异常及正常成功。**不打开本人正式 `~/eos-course-runtime` 中的历史数据库**。
- `python scripts/smoke_system.py`、CLI parity、计划拒绝测试按各自前置条件运行；不能在未确认作用目录和副作用时直接执行。
- `git diff --check`，检查变更清单仅含本功能；不得把虚拟环境、场景、DB/WAL、日志或导出结果加入 Git。
- 阶段性提交仍由何明涛本人执行 `git add/commit/push`；Codex 不执行 Git 改写操作；PR 必须由非作者成员审核并由李泽同确认 Controller 集成影响。

## 8. 交接李泽同的通知正文（可直接发送）

> 我这边 Worker/IPC W1 已完成并推送到 `feat/hmt-worker-ipc`（`906fe70`、`70fdefe`），暂未提 PR；W1 真实 spawn 测试已报告 37 项通过。  
> 
> 接下来 W2 的取消／超时／进程回收方案由我负责细化，严格沿用目前的 HTTP、运行状态枚举、SQLite 九表、`Solver.solve()`、双单向 Pipe 和 W1 协议，不要求你重新设计这些公共接口。  
> 
> 由于 Controller 是你负责的集成模块，**提前通知一下我预计要在自己的功能分支修改的部分**：  
> 1. `Controller._execute()`：把运行中的 `cancel` 真正通过控制 Pipe 发给 Worker，接收 `cancel_ack`，继续处理候选／失败事件并正确裁决取消；修复搜索计时被重复心跳重置以及 IPC 阻塞等问题。  
> 2. `Controller._loop()/start()/stop()`：处理停止领取任务与 `start_attempt()` 的竞态，确保当前 Worker 和执行线程结束后才释放实例锁。  
> 3. 可能新增 `worker_process.py`：由 Worker 模块提供 PID／PGID 身份验证、`SIGTERM→SIGKILL` 和后代清理；Controller 调用并记录结果。  
> 4. 原则上**不动 SQLite 模式、API 和算法签名**。只有实际需要记录退出码时才可能补一个小型 `storage.py` 写入方法；如需修改会先与你对齐。  
> 
> 我们准备采用的状态语义是：`cancel_ack` 仅表示命令被接受，不是终态；用户取消在 Worker 安全停止后进入 `CANCELLED`，算法搜索预算超时且回收完成后进入 `TIMED_OUT`；启动／IPC 故障使用现有 `FAILED` 加诊断码；停止服务而打断运行不伪装为用户取消。成功只由 Controller 核验和事务提交，且成功前必须确认必需的 Worker 清理。  
> 
> 文档会列明具体函数、测试和限制，并按照协作规范更新 `COURSE_SETUP.md` 与受影响的交接说明。**请你主要看是否与你近期正在修改的 Controller 函数冲突，以及这些终态语义是否影响你的现有接口／数据库或 Daemon 联调。** 对于不改变公共契约的 Worker 内部机制，我这边按方案推进；涉及公共接口／数据库变化则先单独与你确认，PR 合并前请你审阅集成影响。

## 9. 尚未交付的边界与后续阶段

1. **W2-A、W2-B、W2-C 分别有本文件第 10、11、12 节的实施与测试记录。** 前述方案段落仍是实施约束，不能替代各阶段的验收报告。
2. W1 已测试的“取消后 Worker 主线程有界退出”不等于“任意不合作线程／逃逸后代均已回收”；W2-C 用独立进程组实测，同时保留已识别的逃逸限制。
3. 崩溃后重新启动 Controller 时，历史随机 `worker_start_token` 不能保证 OS 身份一致；W2 不根据历史 PID 盲目清理旧进程。**如课程最终要求完整的孤儿进程恢复演示，必须与李泽同、梁兆榮共同增加可靠身份记录／回收方案，不能把本版的保守标记失败冒充完成恢复。**
4. W3 才讨论超过 4 MiB 的候选文件载体、相对路径安全、SHA-256 和清理；本方案保留现有消息上限。
5. 模块设计、Controller 行为变更与实际回归证据必须同 PR 审核；W2 不提前开发算法 A 或 D。

---

**变更管理**：如果李泽同反馈现有 Controller 正在并行改同一函数，先锁定合并顺序和代码边界；如涉及公共状态或接口合同，则修改本说明并留下变更记录。只有真实代码和隔离测试达标，才能把上述“拟实施”逐项改写为“已实现”。

## 10. W2-A 实施记录（2026-10-14，待集成审核）

本节记录 W2-A 的实际代码和隔离验证。上文 W2-B/W2-C 仍为设计目标。当前设计文件沿用用户放入仓库时的文件名，未另建重复文件。第 2 节所列 `CREATED` 是目标稿用语；当前 `storage.py` 物理状态枚举不含该值，W2-A 没有新增状态。

### 已实现与函数位置

- `eos_system/controller.py` 的 `Controller._execute()` 保持现有 `spawn`、双单向 Pipe 和旧格式 `start`。读取当前 `(run_id, attempt)` 的数据库取消标记后，仅发送一次 W1 完整格式 `cancel`，其中 `seq=1`、`protocol_version=1`、带时区 `sent_at`、空 `payload`。
- 首次发起取消时记录单调时钟；Controller 协作期限为 W1 的 `CANCEL_GRACE_S`（2 秒）加现有 `Settings.stop_grace_s`（默认 2 秒）。本次测试把后者设为 0.5 秒。发送后继续读取事件；收到 `cancel_ack` 只记事件和 attempt 内确认标记，不改变终态或延长期限。重复 ack 由现有 `record_worker_event()` 序号规则去重；错误 attempt 事件被忽略。
- 取消已被 Controller 确认后收到的候选不进入核验。候选先到时仍由 `set_verifying()` 和 `finish_success()` 的 SQLite 检查裁决。取消后直接 Worker 退出，才写 `CANCELLED`；无 ack 也可在直接进程已退出后写该终态。若直接进程在现有 `join → terminate → kill` 兜底后仍存活，则记 `FAILED/WORKER_CLEANUP_INCOMPLETE`，不虚报取消完成。
- `started.worker_pid` 在事件入库前与 `Process.pid` 比对；首次 `SEARCHING` 后不再重置搜索计时。这两项是本函数内的兼容性修正，没有调整搜索预算起点或算法 runtime 指标。

### 实际验证

在 WSL2 Ubuntu 22.04、Python 3.10.12、`/home/mint/eos-course-runtime/.venv`，使用临时场景和独立 SQLite 运行 `python -m unittest discover -s tests -v`：**51 项通过**，其中新增 `tests/test_controller_cancel.py` 的 14 项。新增测试覆盖真实 spawn 协作取消、合法控制信封、ack 与进程退出分离、重复 ack/取消、启动即取消、无 ack 退出、早退与事件 Pipe 断开、候选及核验竞争、过期 attempt 事件、原注册表 Worker 正常成功路径，以及不绑定外部端口的 ASGI HTTP → Controller → Worker → 临时 SQLite 闭环。假求解器仅为测试桩，不作为调度算法实验结果；临时目录测试没有访问正式数据库或修改 EOS-Bench 母数据。

### 未完成与风险

- W2-A 仍使用同步 `Connection.send_bytes()` 与 `poll()` 后的 `recv_bytes()`；若写入阻塞或接收半帧阻塞，Controller 的单调时钟无法抢占该调用。本轮未完成受管 IO 线程或有界非阻塞帧读取，**不能宣称 IPC 读写具有严格墙钟上限**。这属于 W2-B 的可靠性门槛。
- 当前强制兜底仅操作直接 Worker；没有后代进程组身份验证与清理，也没有修复 `Controller.stop()` 可能提前释放 `flock`。这些属于 W2-C。`run_attempts.exit_code` 仍未写入，启动/搜索/传输完整分段期限也未实现，属于 W2-B。
- 对可验证后代的安全退出尚未实现；W2-A 的 `CANCELLED` 仅证明直接 Worker 已退出，不能宣称任意后代已清理。公共 HTTP、SQLite 物理模式、状态枚举、`Solver.solve()`、协议版本和 4 MiB 限额均未改变。
- 本文件第 6 节要求提前通知李泽同 Controller 修改范围。当前会话没有授权 Codex 代发外部消息；何明涛应在集成审核前按第 8 节通知其确认影响。

**阶段建议：FUNCTIONAL PASS / RELIABILITY PENDING。** 完整 IPC 抗阻塞、后代回收及安全停机不得据本节标记为通过。

## 11. W2-B 实施记录（2026-10-14，待集成审核）

本节以本次工作区代码和实际隔离测试为依据。第 10 节描述的是当时 W2-A 的验收状态；本节补充其后的 W2-B 结果，未将 W2-C 设计写成现有能力。

### 有界 IPC 与职责

- `eos_system/controller_ipc.py` 新增 Controller 独占的 `ControlWriter`、`EventReader`。它们在 Linux Pipe 文件描述符上使用非阻塞 `os.write()` / `os.read()`，由 `_execute()` 同一线程逐轮驱动；没有后台 I/O 线程、第二读取者或并发 SQLite 写入。控制侧仅排队当前 attempt 的旧格式 `start` 和完整格式 `cancel`，单次最多写 1 MiB；事件侧单次最多读 1 MiB，只向状态机交付完整一帧。两侧都检查单调时钟期限及 EOF、半帧、写端断开、非法长度和解码失败。
- 帧格式沿用当前 Linux / CPython 3.10 `multiprocessing.Connection.send_bytes()` 对小于 4 MiB 消息所用的 **4 字节网络序有符号长度头 + JSON 字节**。`worker_reference.py` 抽取共用编解码，Worker 的 `send_bytes()` / `recv_bytes()`、协议版本 1、两条单向 Pipe、消息 JSON 和 `MAX_MESSAGE_BYTES` 均保持原样。该底层帧细节是实现依赖；升级 Python 或移植平台时应重新验证真实 Worker 互通，不能视作新的公共协议承诺。
- `Controller._execute()` 不再在主状态循环中同步 `send_bytes()` 或在 `poll()` 后同步 `recv_bytes()`。合法事件仍先验证身份、版本、关键字段及载荷，再由原有 `record_worker_event()` 去重；错误 attempt 事件不能进入本次状态机。`candidate_result` 只有完整接收后才进入核验路径；4 MiB 以上的帧在读 body 前拒绝。IPC 传输缓冲只保存当前一帧和最多两条控制消息。

### 时钟、竞争与终态

| 阶段 | 单调时钟起点和截止 | 超期处理 |
|---|---|---|
| 启动与准备 | `Process.start()` 调用前设 `startup_timeout_s` 期限；直到首次有效 `SEARCHING`。包含 start 写入、Worker 启动、场景加载与算法准备 | `FAILED/IPC_SEND_TIMEOUT` 或 `FAILED/WORKER_STARTUP_TIMEOUT`；直接进程受控回收 |
| 搜索与结果总保护 | 首次有效 `SEARCHING`；`time_budget_s + transfer_timeout_s`，重复 `SEARCHING` 不重置 | 发一次 W1 cancel，固定协作期限后回收，最终 `TIMED_OUT/ALGORITHM_TIMEOUT` |
| 单帧事件传输 | 本帧首字节到达；每帧 `transfer_timeout_s`，含候选帧 | 未完成为 `FAILED/IPC_TRANSFER_TIMEOUT`；EOF 半帧为 `IPC_TRANSFER_INTERRUPTED` |
| 候选后退出 | 完整候选到达；`stop_grace_s` | 直接 Worker 未退出为 `FAILED/WORKER_EXIT_TIMEOUT`，不得直接提交候选 |
| 用户取消 | 本 attempt 首次读到已持久化的取消；W1 2 秒加 `stop_grace_s` | `cancel_ack` 不延长期限；直接 Worker 结束或回收后裁决 `CANCELLED` |

每轮先读当前 attempt 的数据库取消状态，再判断未锁定的搜索超时。若本轮同时看到两者，用户取消优先；一旦锁定 `USER_CANCEL` 或 `ALGORITHM_TIMEOUT`，晚到的取消、ack、候选或 Worker 自报时间不能更改理由。IPC 故障仍记录诊断事件，但已锁定的取消/超时理由不被其覆盖。候选先到时仍须检查直接进程退出码、用户取消、统一核验及 SQLite 成功事务；`RT` 仍只按 `solve()` 的运行时间统计。

### 回收与诊断

- `_reap_worker()` 只使用本次持有的 `multiprocessing.Process` 句柄：有限 `join` → 若存活 `terminate()` → 最多 `stop_grace_s` 等待 → 若仍存活 `kill()` → 最多 2 秒等待。正常退出也及时 join。`finally` 关闭四个父进程 Pipe 端，并在进程已结束时关闭 Process 句柄；没有调用 `killpg()`。
- `storage.Database.record_attempt_exit()` 仅更新现有 `run_attempts.exit_code` 并写一条小型 Controller `WORKER_REAP` 事件，内容含动作、退出码、存活检查及原因；无需模式迁移，也不向事件表写完整候选。IPC 错误另写 `IPC_ERROR` 诊断。直接进程最终仍存活时使用原状态 `FAILED/WORKER_CLEANUP_INCOMPLETE`，不声称安全回收完成。Worker 不访问 SQLite。
- `FAILED` 中分别使用 `IPC_SEND_TIMEOUT`、`WORKER_STARTUP_TIMEOUT`、`IPC_TRANSFER_TIMEOUT`、`IPC_TRANSFER_INTERRUPTED`、`IPC_MESSAGE_TOO_LARGE`、`IPC_PROTOCOL_ERROR`、`IPC_DISCONNECTED`、`WORKER_EXIT_TIMEOUT` 等错误码；搜索总墙钟到期为 `TIMED_OUT/ALGORITHM_TIMEOUT`。异常退出码不为 0 时，即使先收到候选，也不提交正式结果。

### 实际测试及边界

在 WSL2 Ubuntu 22.04 / Python 3.10.12 的项目虚拟环境，执行 `python -m unittest discover -s tests -v`：**72 项通过**，包括新增 `tests/test_controller_timeouts.py` 的 **21 项**。新测试使用独立临时 EOS_RUNTIME_DIR、场景副本和 SQLite；故障桩在真实 `spawn` 子进程中运行，覆盖正常参考 Worker 成功、搜索超时与不合作算法、重复 `SEARCHING`、启动加载超时、真实受阻 start/cancel 写入、半帧超时与断链、超长帧、畸形 JSON/版本/字段、异常退出、failed 事件、候选后崩溃或不退出、取消/超时先后顺序，以及忽略 SIGTERM 后的 SIGKILL 兜底。每个测试核对终态和直接进程结束；另核对故障运行前后的 `/proc/self/fd` 数量不增加。原 W2-A HTTP/Worker/SQLite 及事务回归也在本次全量测试中通过。测试桩不作为调度实验结果。

### 审核后定向修复

- **已发现并修复的 W2-B 缺陷**：`Controller._execute()` 原先对不同 `seq` 的重复 `candidate_result` 会覆盖候选及重新设置候选后退出期限。现在每个 attempt 首份有效候选仅设置一次该期限；后续不同 `seq` 候选记 `FAILED/IPC_PROTOCOL_ERROR`，不进入核验或正式提交。原有数据库 `seq` 去重先执行，因此相同 `seq` 的重传仍被忽略。取消与搜索超时理由一经锁定的处理保持不变。
- **已发现并修复的 W2-B 缺陷**：`EventReader.read_one()` 读到四字节零长度头时直接抛 `IpcProtocolError`，不再尝试 `os.read(fd, 0)` 后误报传输中断。真实子进程通过 `Connection.send_bytes(b"")` 验证为 `FAILED/IPC_PROTOCOL_ERROR`。
- 新增三个真实 `spawn` 测试：`test_new_sequence_candidate_cannot_extend_exit_deadline`、`test_same_sequence_candidate_remains_deduplicated`、`test_zero_length_send_bytes_is_protocol_error`。持续发送不同 `seq` 候选的故障 Worker 被直接回收，没有正式计划入库；同 `seq` 候选只保留一条事件。本节测试总数已按复测结果更新。上述缺陷与 W2-C 尚未实现的后代进程组清理、持锁停机属于不同边界。

**剩余边界**：`Process.start()` 本身和 Controller 内的场景核验/正式导出调用尚无可抢占硬期限；当前期限保护的是启动调用返回后的状态循环及 Pipe I/O。若直接进程在 `kill()` 后仍无法在 2 秒内结束，会记录回收不完整，不能宣称全链路严格有界。W2-B 只证明直接 Worker 进程的测试回收；其派生后代、PID/PGID/Session 身份核验、`Controller.stop()` 的持锁安全停机及重启后旧进程清扫均属 W2-C。HTTP 路径与响应、八种状态、SQLite 物理模式、算法签名、验证规则和原子提交均未改变；新增的存储方法是 Controller 内部调用。集成前仍须按第 6、8 节与李泽同核对 Controller 和 storage 的并行改动。

**阶段建议：FUNCTIONAL PASS · RELIABILITY PENDING。** 已覆盖本阶段直接 Worker 的正常/故障路径；跨进程后代及安全停机尚无保证。

## 12. W2-C 实施记录（2026-10-14，待集成审核）

本节记录 W2-C 工作区的实际代码和隔离测试。第 10、11 节的“尚待 W2-C”仅描述当时 W2-A/B 的阶段边界，以本节的当前状态为准。

### C1：Linux 身份与信号边界

- 新增 `eos_system/worker_process.py`。`WorkerGroup` 仅从本次 `multiprocessing.Process.pid` 建立身份；记录 Linux boot_id、`/proc/<pid>/stat` 的 starttime、PPID、PGID、SID、进程状态及 pidfd。解析 stat 时从最后一个 `") "` 定位 comm 尾部，支持进程名含括号或空格；不按未经处理的整行 split 固定索引。Worker 原有 `setsid()` 仍在 `started` 事件之前执行；Controller 不采用 IPC 中任意 PGID 作为信号目标。
- 只有本次组长仍存在、starttime/boot_id 与启动时一致、`PGID=SID=Process.pid>0`、与 Controller 自身 PGID/SID 不同，且组长 pidfd 已固定数字 PID 时，才可向其独立进程组发信号；每次发信号前重读 `/proc`。组长在 `setsid()` 前或身份不符时只用 Process 句柄回收直接 Worker，不执行 `killpg`。组长已退出后绝不凭缓存 PGID 调用 `killpg`。
- 组长存活时扫描同 PGID/SID 的成员，并用 pidfd 固定成员身份。审核后补充：本 attempt 已确认独立 session，且组长 pidfd 仍固定其数字 PID 时，即使组长已经退出并被 `join`，也继续扫描同 PGID/SID；新发现的后代须核对 boot_id、starttime、PGID/SID，打开 pidfd 后再复核，之后只通过该 pidfd 发信号。组长退出后绝不向缓存 PGID 调用 `killpg`。缺少组长 pidfd 锚点、扫描失败或超过 128 个成员时标记扫描不完整并保守降级；`WorkerGroup.close()` 关闭全部 pidfd。

### C2：有界回收与结果裁决

- `reap_worker()` 集中执行已有协作期限后的回收：有限等待，必要时对仍可验证的组发 SIGTERM；对已固定的成员发送 SIGTERM；再次有限等待；再以同样身份复核执行 SIGKILL 或 Process 直接回收；最后 join 并检查直接 Worker 与已验证成员是否仍活跃。组长先退出时仅对已固定成员使用 pidfd。没有向 Controller 自己的组发信号。
- `Controller._execute()` 在 Worker 启动后建立 `WorkerGroup`，执行循环中持续收集可验证的同组后代。回收后的 `WORKER_REAP` 小型事件记录动作、退出码、活跃成员数、身份确认/失败、扫描限制、组信号、成员信号及信号错误。直接 Worker、已确认活跃后代或受限扫描仍不能确认清理时，记 `FAILED/WORKER_CLEANUP_INCOMPLETE`，不提交 `SUCCEEDED`。原有用户取消优先于未锁定算法超时的裁决顺序保持不变。
- **可证明的范围**仅是本次 Controller 存活期间仍在已确认 Worker 独立 session 内、且扫描时可逐一固定身份的成员。组长退出后凭本次固定的组长 pidfd 继续发现仍在该 session 的后代；无此锚点时标记 `scan_limited`，不会把无法确认的清理报告为完成。后代自行脱离 session/组、扫描之后才产生且在最后一次扫描之后仍存活、进程消失时 `/proc` 与存在性检查均不可用、以及跨 Controller 重启等情形仍不能保证回收。正常 Worker 无后代证据时继续按原成功核验事务处理。

### C3：Controller 安全停机

- `Controller._loop()` 的停止检查与 `start_attempt()` 由 `_dispatch_lock` 串行。`stop()` 先设置停止标记，等待领取临界区结束，再有限等待执行线程；当前 attempt 的 `_execute()` 在 `start` 已排队时发送一次现有 W1 cancel，尚未排队时不再启动算法，按原宽限回收，最终记 `FAILED/CONTROLLER_STOP`，不伪装成用户取消。核验后、成功事务前还复查停机标记；核验/导出仍由原后台线程执行。
- 只有后台执行线程已退出，`stop()` 才释放 flock。若等待领取锁或线程退出超过期限，`stop()` 抛出明确错误并**保留 flock**；可在后台线程真正结束后再次调用 `stop()` 释放。`start()` 的恢复或线程启动抛异常时关闭已取得的 flock。外部 SIGKILL 结束整个 Controller 进程时，内核会释放锁；Python 停机路径无法阻止该行为。

### 隔离验证与待联调

- `tests/test_worker_process_group.py` 的 **12 项**使用真实 Linux `spawn` 与独立 session，覆盖带括号/空格的 stat 解析、`setsid` 前保守降级、错误 starttime、boot_id 无法读取、伪造 Controller PGID 拒发、真实组 SIGTERM、忽略 SIGTERM 的后代 pidfd SIGKILL、组长先退出后的成员回收及 pidfd 关闭。
- `tests/test_controller_shutdown.py` 的 **7 项**使用临时场景与 SQLite，覆盖运行中停机、与 `start_attempt()` 竞争、核验阻塞时保留 flock、数据库恢复及线程启动异常后的解锁，以及 Controller 中真实后代与崩溃组长的回收。测试通过 `/proc` 核对成员不再活跃，并给测试创建的子进程设置独立 pidfd 清理兜底。两组专题各独立重复三轮均通过；完整 `python -m unittest discover -s tests -v` **91 项通过**，含原有 HTTP/Worker/SQLite 正常成功链路。`git diff --check` 通过；正式运行目录与母场景未用于测试。
- 跨 Controller 崩溃重启仍只保留 `FAILED/CONTROLLER_RESTART` 的原有数据库恢复：历史 `worker_start_token` 或历史 PID 不用于发信号。跨重启孤儿清扫和 Daemon 联调须另议。HTTP、SQLite 物理模式、八种运行状态、`Solver.solve()`、双 Pipe、协议版本 1、4 MiB 限额及核验/正式提交事务不变。李泽同应复核 `_loop/start/stop/_execute` 与其并行 Controller 改动；没有自动发送外部通知。

**阶段建议：PENDING（等待集成审核）。** 已验证本次进程生命周期内的已识别同组后代与持锁停机；扫描竞态、逃逸后代和跨重启清扫仍是明确能力边界，不能表述为无条件进程树回收。

### W2-C 首轮审核后定向修复（2026-10-14）

- 修复组长退出前刚创建的后代未被首次扫描发现的问题。`WorkerGroup.refresh()` 在已确认独立 session 且组长 pidfd 仍持有的条件下，组长退出后继续扫描；只为通过 PGID、SID、boot_id、starttime 复核且成功打开 pidfd 的新成员保留身份。组长退出后仍禁止 `killpg`。若没有组长 pidfd 锚点，`scan_limited` 保守报告风险。
- `_open_pidfd()` 对 `ESRCH` 返回“进程已消失”，对权限、功能缺失和其他错误保留异常；`refresh()` 再核对进程是否确实消失或结束。仍活跃且无法固定的成员进入 `unpinned` 风险集合；后续确认其结束后清除风险。`/proc` 无法读取且存在性无法确认时继续保留风险，不凭历史 PID 发信号。
- 新增真实 `spawn` 测试：`test_crashed_leader_discovers_unseen_child_after_reap` 在组长退出并被 join 后才首次发现后代，测试专用 pidfd 提供独立清理兜底；`test_controller_recovers_child_after_immediate_leader_crash` 验证 Controller 记录异常断链并回收后代；`test_child_exits_between_scan_and_pidfd_open` 让真实子进程在两步之间退出，确认不误报扫描不完整；`test_live_unpinned_child_risk_clears_after_confirmed_exit` 验证权限失败时保留风险、确定退出后清除。前述故障 Worker 与算法均是测试桩。
- WSL2 Ubuntu 22.04 / Python 3.10.12 虚拟环境中，W2-C 专题 23 项连续五轮均通过；完整 `python -m unittest discover -s tests -v` **95 项通过**，包括正常成功、取消、超时、异常退出和持锁停机回归；`git diff --check` 通过。测试进程的直接 Worker 均已退出，测试创建的后代有独立 pidfd 清理兜底，检查时未见活跃测试后代。测试使用独立临时场景和 SQLite，未接触正式运行库或 EOS-Bench 母数据。
- 本次没有修改 Controller 停机、HTTP、SQLite 模式、算法签名或 IPC 契约。pidfd 无法使用、后代脱离 session、跨 Controller 重启及最后一次扫描之后新出现的后代仍是保守边界；不会对不可信 PGID 发组信号。

### W2-C 最终审核：未确认 Session 的成功提交防护（2026-10-14）

- 发现并修复：`WorkerGroup.refresh()` 在从未确认组长独立 session 时可能返回 `scan_limited=False`；此前 Controller 仅以直接进程、已登记成员和该标记判断清理，存在正常退出码与合法候选绕过身份确认的成功提交路径。现在 `confirmed` 还要求组长 pidfd 已固定；Controller 正式成功前同时要求本 attempt 的身份已确认且 `start` 曾获准排队。
- 真实参考 Worker 的顺序是 `setsid()` → `started` → 阻塞等待 `start` → 场景加载与求解。`Controller._execute()` 现收到匹配当前 Process.pid 的 `started` 后，再读取本次进程的 boot_id、starttime、PGID、SID 和 pidfd 状态；确认独立 session 且组长当前仍活跃后才发送原格式 `start`。IPC 自报 PGID 不用于放行或信号。事件到达与放行之间若组长已退出，重新读取会阻止放行；Pipe 本身固定于本次子进程，不根据后来复用的数字 PID 建立新连接。
- 用户在身份确认前取消时，不提前发送 `start` 或无法被等待 `start` 的 Worker 正确处理的 `cancel`；保留单调时钟宽限后通过本次 Process 句柄直接回收。`start` 已排队后的取消仍按原顺序发送一次完整 `cancel`。未确认身份会记录 `WORKER_IDENTITY/WORKER_IDENTITY_UNCONFIRMED` 诊断；直接进程已安全退出的启动期用户取消仍为 `CANCELLED`，但没有把未核实的进程组清理宣称为完成。没有取消理由的合法候选即使退出码为 0，也记 `FAILED/WORKER_IDENTITY_UNCONFIRMED`，不进入统一核验与正式成功事务。

- 原 W2-A/B 的故障测试桩中，需等待 `start` 的桩现在先调用 `setsid()`；阻塞控制写入桩先发送 `started` 再故意不读取 Pipe，以继续真实覆盖非阻塞写期限。这仅是测试桩适配，不改变生产 Worker 或公共协议。
- 新增真实 `spawn` 测试：`test_fast_reference_worker_confirms_session_before_success`、`test_unconfirmed_session_cannot_commit_legal_candidate`（故障桩伪报 PGID、合法候选、退出码 0，且确认没有收到 `start`）、`test_cancel_before_setsid_uses_direct_reap_without_group_signal`。原有组长退出后 pidfd 回收、停机未完成保留 flock、成功/取消/超时回归继续执行。隔离临时场景与 SQLite，不向未确认的组发信号。
- WSL2 Ubuntu 22.04 / Python 3.10.12：W2-C 进程身份与停机专题 **26 项连续三轮通过**；Controller 取消、超时与进程身份专题 **50 项通过**；完整 `python -m unittest discover -s tests -v` **98 项通过**；`git diff --check` 通过。`setsid()` 前取消保持 `CANCELLED` 且无组信号；伪报 PGID 的合法候选及退出码 0 最终为 `FAILED/WORKER_IDENTITY_UNCONFIRMED`，正式 plan 为空；真实快速参考 Worker 为 `SUCCEEDED`，`WORKER_REAP.identity_confirmed=true`。真实子进程均由测试清理，未连接正式实验数据库。
- 仍无法从未确认的启动期 Worker 推断任意已逃逸的后代；该路径仅对本次 Process 句柄执行直接回收并留下明确诊断。已确认 session 的最后一次扫描之后产生的新后代、跨重启孤儿也不在本轮保证范围。HTTP、SQLite 物理模式、状态枚举、Solver 签名、IPC 版本和 4 MiB 限额未变。

### W2-C 最终审核补充：启动与取消竞争（2026-10-14）

- 修复 `Controller._execute()` 的 `start` 入队条件：显式要求 `stop_reason is None`。本轮若已锁定 `USER_CANCEL` 或 `CONTROLLER_STOP` 且 `start` 尚未排队，即使后来收到了 `started` 并确认独立 Session，也不再下发 `start`；因 Worker 第一条控制命令必须是 `start`，此时也不单独发送完整 `cancel`。已排队 `start` 的发送与取消队列保持既有顺序和期限。
- 真实 `spawn` 测试包装原 `worker_main()`：Worker 已执行 `setsid()`，测试桩在发送 `started` 前等待；Controller 先读取已持久化的用户取消，再放行 `started`。子进程记录是否收到 `start`、是否进入算法准备；两者均未发生，最终 `CANCELLED`，直接 Worker 及可信进程组按固定宽限安全回收。另以相同时序测试 `Controller.stop()`，最终 `FAILED/CONTROLLER_STOP` 且释放 flock；原有未完成停机保留 flock 测试继续通过。测试桩仅延迟消息和检测算法入口，不作为调度实验结果。
- 本次仅修改 Controller 的放行条件、上述专题测试和阶段记录；没有改 pidfd、进程组信号、IPC 队列、HTTP、SQLite 模式、Solver 接口或协议版本。主动取消和停机发生在算法开始前时，直接回收可能没有 `cancel_ack`，该 ack 本来只表示收到控制命令，不是终态条件。
- WSL2 Ubuntu 22.04 / Python 3.10.12 隔离环境：W2-C 专题 **28 项连续三轮通过**；完整 `python -m unittest discover -s tests -v` **100 项通过**；`git diff --check` 通过。原有“启动即取消”测试不再把 `cancel_ack` 当作必需事件；阻塞 `start` 写入的取消测试现在确定等到 `start` 入队再触发取消，继续覆盖原有 IPC 写入期限。测试没有使用正式 SQLite 或 EOS-Bench 母数据，结束后未见活跃测试 Worker/后代。

## 13. W1/W2 系统联调与 Controller 交接（2026-10-14，待人工审核）

本节是基于 `30f233a` 的交付验收记录，不改生产运行时代码。新增 `tests/test_http_failure_e2e.py`：测试服务用独立 `EOS_RUNTIME_DIR`、临时场景/SQLite、随机回环端口运行现有 FastAPI 与 Controller；仅在测试 app factory 中将可导入的故障 Worker 入口装配进服务进程，随后由 `spawn` 真正创建 Worker。测试桩不登记为正式算法，也不代表 A/B/C/D 的实验结果。

- `test_real_http_running_cancel_reaps_worker_without_plan`：经真实 TCP HTTP 提交与运行中取消；求解桩已进入 `solve()`，Worker 上报一次 `cancel_ack`，最终 `CANCELLED`，attempt 退出码 0，正式计划/指标为空，`WORKER_REAP` 显示直接 Worker 与已识别成员已退出。
- `test_real_http_search_timeout_reaps_slow_solver`：短预算与不合作求解桩经现有 API 运行，最终 `TIMED_OUT/ALGORITHM_TIMEOUT`，无正式计划，收到超时后的 `cancel_ack`，直接 Worker 有界退出。
- `test_real_http_crash_reaps_trusted_descendant`：故障 Worker 完成独立 Session 握手并在收到 `start` 后创建同 Session 子进程，随后以退出码 23 异常退出；最终 `FAILED/IPC_DISCONNECTED`，无计划。测试核对 `WORKER_REAP` 的已确认身份与零活跃成员，子进程不再活跃；测试端 pidfd 强制清理兜底未触发。

三项均使用真实回环请求、现有 HTTP 路径、Controller、Worker 进程和临时 SQLite；逐项检查 attempt、事件、计划、Worker PID 与服务进程 FD 数量。专题测试两轮各 **3/3 通过**；完整 `python -m unittest discover -s tests -v` **103/103 通过**；`git diff --check` 通过。原有真实成功闭环在隔离服务复跑：只读母场景派生 30 任务临时实例（SHA-256 `192eb635644fcdbc86854912704345494fe36d8cffb828c5000cff9221a9b84e`，种子 20260927），`completion_first` 完成 24/30、TCR=0.800，SQLite 记 `SUCCEEDED`、attempt 1、exit_code 0、一份计划及 24 条 assignment；JSON/CSV、旧 CLI 逐条对照和篡改候选拒绝检查均通过。临时库、场景和服务已清理；未见活跃测试 Worker 或可信后代。后台线程与 flock 生命周期仍以 W2-C 专题真实进程测试为证，不把 HTTP 服务进程退出当作独立的持锁证明。

### 交接李泽同核对的代码边界

1. `controller.py`：`start()/stop()/_loop()` 管理单实例锁、领取与停机；`_execute()` 管理 `spawn`、两条 Pipe、`started` 后内核身份核验再发送旧格式 `start`、一次性完整 `cancel`、事件去重、墙钟期限、候选/取消竞争、核验与正式提交。若后台执行线程未退出，`stop()` 抛错并保留 flock。
2. `controller_ipc.py` 的 `ControlWriter/EventReader` 在 Controller 执行线程中驱动有界非阻塞帧传输；`worker_process.py` 以本次 Process、`/proc` 和 pidfd 保护组/成员信号。组长退出后不向缓存 PGID 发组信号。
3. `storage.py` 仅新增内部 `Database.record_attempt_exit(run_id, attempt, exit_code, diagnostics)`：`_execute()` 回收后调用，写既有 `run_attempts.exit_code` 和小型 `WORKER_REAP` 事件；未改 SQLite 物理模式。
4. `cancel_ack` 仅确认命令收到；用户取消且完成安全退出后为 `CANCELLED`，搜索墙钟预算到期为 `TIMED_OUT/ALGORITHM_TIMEOUT`，内部停机为 `FAILED/CONTROLLER_STOP`。直接 Worker、可信后代或扫描状态无法确认清理时为 `FAILED/WORKER_CLEANUP_INCOMPLETE`；未确认 Session 的候选不得提交成功。
5. 李泽同负责的 `Controller` 生命周期与 `storage.py` 内部写入点是并行分支的主要冲突区。合并前请核对状态优先级、HTTP 409 语义、数据库事务与 Daemon 停机/重启预期。W3 大结果载体、独立 Daemon、正式算法 A/B/C/D、跨重启孤儿回收及逃逸 Session 后代均未在本次交付中实现。
