# Worker/IPC W1 实现与测试记录（2026-10-14）

本文件记录 `feat/hmt-worker-ipc` 上 W1 已实现的 Worker 内部控制 IPC。基线为 v0.2.1、提交 `09d9055`。当前 Controller 尚未发送运行中的 `cancel` 命令；HTTP 到 Worker 的协作取消闭环尚未实现。

## 进程与线程职责

- Controller 仍通过 `multiprocessing.spawn` 创建一次实验 attempt 对应的 Worker，并持有两条单向 Pipe：控制 Pipe 发往 Worker，事件 Pipe 发往 Controller。
- Worker 主线程是控制 Pipe 的唯一读取者、事件 Pipe 的唯一写入者，也是事件 `seq` 的唯一递增者。主线程接收 `start`，启动执行线程，然后每 50 ms 检查控制消息及线程进度。
- `eos-solve` 执行线程负责场景 SHA-256 检查、`prepare()` 和 `run_prepared()`；它通过线程内队列向主线程交付阶段、候选或异常，不直接接触 Pipe。该线程为 daemon，控制故障或取消宽限到期时不会阻止 Worker 主线程退出。
- `threading.Event` 保存取消状态。Worker 使用 `dataclasses.replace()` 将 `SolveContext.is_cancelled` 接到 `Event.is_set`。`Solver.solve(problem, constraints, context)` 的签名以及 `LegacySearchAdapter` 保持不变。
- 主线程接受取消后立即设置标记并发送 `cancel_ack`。这只表示命令已被 Worker 接受；算法退出、Worker 退出和后代进程回收需另行确认。算法返回时若取消标记已设置，Worker 丢弃候选，不发 `candidate_result`。

## IPC 消息与兼容性

事件和新的控制命令使用协议版本 1 的 JSON 对象，字段为 `protocol_version`、`run_id`、`attempt`、`seq`、`kind`、`sent_at`、`payload`。`attempt` 与 `seq` 是正整数，`sent_at` 为带时区 ISO 8601 字符串，`payload` 为对象。消息仍使用 `Connection.send_bytes/recv_bytes`，上限 4 MiB。

已有 v0.2.1 Controller 的启动消息是 `{kind:"start", run_id, attempt, config}`，没有完整信封。W1 继续接受它。完整格式的启动消息可在 `payload.config` 中传配置。启动消息的外层 `(run_id, attempt)` 与 `RunConfig.run_id` 必须匹配 Worker 本次身份。

W2 发送取消时使用完整格式，例如：

```json
{
  "protocol_version": 1,
  "run_id": "本次运行ID",
  "attempt": 1,
  "seq": 1,
  "kind": "cancel",
  "sent_at": "2026-10-14T12:00:00+08:00",
  "payload": {}
}
```

若 W2 仍发送旧格式 `start`，首次 `cancel.seq` 可用 1；若完整格式 `start.seq=1`，首次 `cancel.seq` 应大于 1。Worker 忽略重复或更旧的控制序号，不要求连续编号。Worker 事件序号从 1 开始严格递增；Controller 原有 `(run_id, attempt, seq)` 去重逻辑未修改。

消息字段、协议版本或身份错误会让 Worker 报 `failed` 并退出；控制 Pipe EOF 也按控制链路错误处理。已接受取消后最多等待 2 秒让算法协作返回，随后 Worker 主线程退出。该宽限不代表 Controller 已回收 Worker 的子进程。候选发送与取消到达的极短竞态仍须由 W2 的 Controller 取消状态检查和正式提交事务裁决。

## 实际测试

在 WSL2 Ubuntu 22.04、Python 3.10.12、`~/eos-course-runtime/.venv` 执行：

```bash
~/eos-course-runtime/.venv/bin/python -m unittest discover -s tests -v
```

基线 18 项通过；W1 修改后 32 项通过，其中 14 项为 `tests/test_worker_ipc.py` 专题测试。测试覆盖旧/完整 `start`、正常退出、实际 `spawn` 运行临时空场景、实际 `spawn` 拒绝错误协议、版本/身份/字段错误、事件序号、重复取消、长时间求解时 `is_cancelled()` 变化、取消后候选抑制、取消引发的求解异常、控制 Pipe EOF、求解异常，以及旧算法适配器调用。空场景和假求解器只是测试桩，未作为调度算法实验结果。测试使用独立临时目录，未连接正式 SQLite 或启动 HTTP 服务。

## 已知限制与 W2/W3 对接

- W2：Controller 在运行中从取消请求发送完整 `cancel` 命令，等待/记录 `cancel_ack`，依据数据库取消状态阻止正式结果提交；取消或超时后按已验证的独立进程组回收 Worker 及后代，记录退出码和回收结果。Worker 只识别本 attempt 的控制命令，Controller 不应把 ack 当成终态。
- W2：当前 Worker 在取消宽限到期后结束主流程，但不保证任意算法及其后代进程均已停止；Controller 必须有单独的硬回收和超时上限。
- W3：大候选计划仍受 4 MiB Pipe 消息上限约束；文件载体、哈希验证和异常清理由后续阶段实现。
- 当前 `started` 中的 `worker_start_token` 仍为随机 UUID；进程组身份验证和 Daemon 恢复规则未在 W1 改动。
- 本次没有运行 HTTP/SQLite/目录输出集成测试，也没有对正式算法做取消响应承诺。既有算法未主动轮询 `context.is_cancelled()` 时，仍需 W2 的强制回收。

本次未改变 HTTP、SQLite 模式、正式运行状态、算法公共签名及 Controller 行为。新控制命令的联调细节应由李泽同确认后进入 W2。

## W1 补充验收（2026-10-14，基于 `906fe70`）

新增 5 项真实 Linux `spawn` 子进程测试。`tests/test_worker_ipc.py` 提供模块顶层可导入的测试入口 `spawn_worker_with_test_solver()`；它在**子进程内**安装有限时长的测试求解桩，再调用原本的 `worker_main()`。取消可见性通过 `multiprocessing.get_context("spawn").Event()` 从子进程回报，未依赖父进程的 monkeypatch。空场景只写在 `tempfile.TemporaryDirectory()`，不接触正式 SQLite 或 EOS-Bench 母数据。

| 新增测试 | 验证结果 |
|---|---|
| `test_real_spawn_cooperative_cancel_observed_without_candidate` | 确认子进程已进入 `solve()`，收到合法 `cancel` 后子进程中的 `is_cancelled()` 变为真；收到一次 `cancel_ack`，无候选，Worker 自行以退出码 0 结束，事件序号递增且 Pipe 最终 EOF。 |
| `test_real_spawn_uncooperative_cancel_has_bounded_worker_exit` | 求解桩有界睡眠 5 秒且不读取取消标记；`cancel_ack` 在 1.5 秒阈值内到达，Worker 在 2 秒取消宽限后自行退出，整体小于 4.5 秒，无候选。测试端未执行强制回收。 |
| `test_real_spawn_control_eof_exits_without_lingering_process` | 运行中关闭控制 Pipe，Worker 报 `failed/ConnectionError`、退出码 0、事件 Pipe EOF。 |
| `test_real_spawn_solver_exception_exits_without_lingering_process` | 子进程求解桩抛出异常，Worker 报 `failed/RuntimeError`、退出码 0、事件 Pipe EOF。 |
| `test_real_spawn_closed_event_pipe_exits_without_lingering_process` | 关闭事件 Pipe 后发送取消，Worker 尝试回报时检测到断链并退出，退出码 0。 |

每项子进程测试在 `finally` 中设置了有界 `join → terminate → kill` 测试兜底；一旦用到外部强制回收，测试会失败并明确报告。当前新增测试均由 Worker 自行退出，无测试结束后的遗留进程。事件 Pipe 如果单独断开而 Worker 长期没有任何下一次事件发送，写端无法立即感知断链；W2 仍需负责墙钟超时和强制回收。

取消与候选竞争的判定保持不变：Worker **已经接受**的取消会先置位，再丢弃随后取得的求解结果；若候选在取消被 Worker 处理之前已经发送，Controller 的运行状态检查与正式提交事务负责裁决。补充检查未发现需要修改 W1 源码的问题。

在 WSL2 Ubuntu 22.04 的 `~/eos-course-runtime/.venv` 执行 `python -m unittest discover -s tests -v`：**37 项全部通过**，其中 Worker IPC 专题 19 项；`git diff --check` 通过。未运行 HTTP 服务端集成检查；现有 Controller 只发送旧 `start` 的正常路径继续由真实 `spawn` 空场景测试覆盖。
