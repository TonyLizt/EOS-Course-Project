# 独立 Daemon：实现与故障恢复验证

2026-10-18；基线 `7a1875f`（main / PR #20）。初次交付仅本地提交；现按用户后续要求准备推送并创建 PR，等待独立审核，不自行合并。

## 1. 实际架构及职责

```text
Linux / WSL2
  └─ python -m eos_system.daemon run     独立 PID/session；心跳、退避、日志、subreaper
       └─ python -m eos_system          独立 PID/session；FastAPI + Controller
            ├─ resource_tracker        Python 辅助进程
            └─ spawn Worker            独立 PID/session；算法、双单向 Pipe
```

Controller 当前仍在 FastAPI 进程中的调度线程内运行，因此**恢复整个服务进程**，不尝试在线替换 Controller 对象。Daemon 是独立 Linux 进程，Controller 崩溃后仍存活。`start_new_session=True` 使后台 Daemon 脱离启动终端；日志排水辅助线程并不是监护程序的替代品。

Daemon 不导入 Database，不执行算法，不读写业务表，不重试 Run，不向 Worker 发信号。Controller 继续负责 Worker、IPC、核验、队列和业务提交。Daemon 的 Linux subreaper 只 `waitpid` 已退出孤儿，避免 WSL PID1 未回收造成僵尸，不管理仍在运行的 Worker。

没有引入 systemd 或第二套自动恢复器。不要同时配置其他管理器重启同一 Controller；若使用 systemd，应只托管本 Daemon 的前台 `run`。

## 2. 管理命令

本次在独立工作树开发，未覆盖原根目录已有的未提交修改：

```bash
cd /home/asus/projects/eos-course-runtime/.worktrees/controller-daemon
export EOS_RUNTIME_DIR=/home/asus/eos-course-runtime-daemon
export EOS_SCENARIO_DIR=/home/asus/projects/eos-course-runtime/experiments/scenarios
PY=/home/asus/eos-course-runtime/.venv/bin/python

# 先正常停止已有的 8765 服务，或选择不同运行目录和端口。
$PY -m eos_system.daemon start --port 8765
$PY -m eos_system.daemon status
curl -fsS http://127.0.0.1:8765/api/health
tail -n 30 "$EOS_RUNTIME_DIR/daemon.log"
$PY -m eos_system.daemon stop
```

所有命令可以显式传 `--runtime-dir /Linux/绝对路径`。`start` 确认新 Daemon 身份，不代表 Controller 已健康，应查看 status 的 HEALTHY。前台用 `... daemon run --port 8765`，Ctrl+C 停止整个系统。`stop` 等待关闭且不重启。原 `python -m eos_system` 单服务入口保留，新增 `EOS_PORT`（默认 8765），仍仅绑定 127.0.0.1。

发现手动 Controller 持锁时 Daemon 进入 BLOCKED，不接管或终止它。不同运行目录误用同一端口时，启动失败按上限退避；端口上其他服务的健康响应无法通过进程身份校验。不要删除占用中的锁文件。

运行目录需在 WSL Linux 文件系统；CLI 拒绝 `/` 和 `/mnt/...`。`status` 返回码 0 表示 Daemon 身份仍存活，非 0 表示没有有效实例；具体 Controller 健康看 state。EXHAUSTED / BLOCKED 的历史 sidecar 不表示活进程。

## 3. 心跳机制

`GET /api/health` 保留旧字段，新增 `controller`：

```json
{"controller": {
  "process": {"pid": 123, "ppid": 122, "boot_id": "...", "starttime": 12345,
              "pgrp": 123, "sid": 123, "state": "S"},
  "dispatch_alive": true, "stopping": false, "progress_age_s": 0.02
}}
```

进度由实际 Controller 取件、Worker 事件、等待核验、**有界回收等待**循环更新，使用 monotonic，不由独立心跳线程伪造。Daemon 同时核对自身子进程 PID/boot ID/starttime、线程存活、非停机及进度年龄；PID 存在或 HTTP 200 都不够。旧顶层 `status=ok` 仍表示原 HTTP/数据库可读探测，不能单独解释为调度线程健康。

连续失败阈值避免瞬时延迟；首次启动有宽限。Daemon 轮询被暂停超过 max(5s, 4×interval + 2×request_timeout) 时重新授予初始化宽限，避免 WSL 恢复后立即误杀，也避免把正常 HTTP 超时计作监护暂停。日志 UTC 只用于记录，超时、退避和耗时均用单调时钟。

## 4. 故障恢复与正常关闭

| CLI 参数 | 默认 | 用途 |
|---|---:|---|
| `--interval` | 1s | 轮询间隔 |
| `--request-timeout` | 2s | 单次 loopback HTTP 超时；不走环境代理 |
| `--startup-grace` | 45s | 每次服务初始化宽限 |
| `--progress-timeout` | 20s | 实际调度循环进度超时 |
| `--failures` | 3 | 连续失败次数 |
| `--max-restarts` | 3 | Daemon 此次生命周期最多恢复次数，允许 0 |
| `--backoff` | 2s | 首次退避 |
| `--backoff-cap` | 30s | 指数退避上限 |
| `--stop-grace` | 25s | 服务正常关闭/TERM 等待上限；KILL 另等最多 2s |

异常退出直接判定，无需等 HTTP 失败累计。无响应达到阈值后：pidfd TERM 自己的服务子进程，必要时 CONT 使 SIGSTOP 进程可以处理 TERM；超时 KILL。确认旧实例退出、再次检查 Controller 锁、退避后才重启。不可停止则 BLOCKED，不并排启动新实例。

退避 `min(cap, backoff × 2^(attempt-1))`；默认最多初次启动 + 3 次恢复。健康后**不自动清零次数**，避免间歇健康形成无限重启。达到上限记录 RESTART_LIMIT_REACHED、状态 EXHAUSTED、退出码 3。诊断后手动重新 start 才重置预算。阻塞/错误退出码 2，正常停止为 0。

受监护服务使用 SupervisedServer，在 Uvicorn 接收 SIGTERM/SIGINT、排空现有请求之前先写关闭意图；API lifespan 和 Controller.stop 也调用 `announce_stopping()`。`controller-stopping.json` / `controller-stopped.json` 含本次随机监督 token 及服务内核身份，分别表示主动关闭和清理完成；旧实例文件不会误匹配。即使 HTTP 已停或回放清理较慢，Daemon 仍等待正常关闭、不重启。主动关闭超时或关闭中崩溃记录 BLOCKED，而非违背意图自动恢复。Daemon.stop 的关闭意图同样优先；由 Daemon 因心跳故障主动 TERM 的服务则仍走故障恢复。

## 5. 文件、锁与身份安全

- `daemon.lock`：Daemon 生命周期内独占非阻塞 flock，不删除/替换锁文件；内核在进程退出时释放。
- `controller.lock`：保留原 Controller 最终互斥。Daemon 预检查不能代替 Controller.start 的原子锁。
- PID + Linux boot ID + `/proc/PID/stat` starttime；发信号前、打开 pidfd 后再次验证，不只信 PID 文件，不对历史 PGID 广播。
- `daemon-status.json`：自身/服务身份、最近成功心跳、重试次数、策略和最后事件。status 另查锁及真实身份，避免陈旧状态误报。
- JSON 使用同目录临时文件、fsync、原子 replace 和目录 fsync；临时文件默认 0600。只写运行目录，均非业务表。
- `daemon.log`：UTF-8，1MiB ×（当前 + 3 备份），包含服务 stdout/stderr。逐行读取上限 8192 字节，不每次打印健康心跳。
- `daemon-conflict.json`：只保留最近一次 Daemon 重复启动冲突；竞争者不操作活实例的滚动日志/状态。

## 6. Controller/Worker 协调与状态一致性

`worker-lease.json` 由 Controller 唯一维护：确认 Worker session/pidfd 后，在发送 start **之前**持久化内核身份，运行中仅成员变化时更新；正常清理成功后删除。清理不完整停止继续领取任务。

新 Controller 持锁后先 `WorkerJournal.recover()`：仍存活且身份吻合的 leader 重新 pin session/后代；leader 已退出则只向日志记录的确切身份发信号。未知同 session 成员、无法确认身份或清理不完整时拒绝启动，保留诊断，不用旧 PID/PGID 猜测。TERM/KILL 有界且发给 pidfd，不由 Daemon 操作。

确认旧 Worker 清理后才调用原 `Database.recover_interrupted()`：RUNNING/VERIFYING → FAILED/CONTROLLER_RESTART，旧候选作废、不重算；QUEUED 保留并正常领取；终态及已提交计划/指标不修改。没有 schema 迁移、重复成功提交或指标补写。内存临时对照随进程丢失，不伪造持久化恢复。

真实 Linux Worker 增加 `PR_SET_PDEATHSIG(SIGKILL)`，并复查 multiprocessing 原父 PID，处理注册期间父死亡竞态，使直接 Worker 不长期孤立；后代仍由 Controller 的日志与回收机制负责。IPC 信封、取消语义和算法接口不变。`reap_worker` 只新增可选 on_progress 回调，报告实际有界等待进度，避免把正常后代回收等待误判为 Controller 卡死。

## 7. 课程故障演示与定向测试

演示只使用 `/tmp/eos-watchdog-*`、随机空闲端口、临时 SQLite、真实 spawn Worker。测试桩不执行物理算法，不把输出当成正式认证；信号只发给自己创建并核实身份的进程，测试后自动停止、回收、移除临时目录。

```bash
cd /home/asus/projects/eos-course-runtime/.worktrees/controller-daemon
PY=/home/asus/eos-course-runtime/.venv/bin/python
export PYTHONPATH=tests

# A+B+C：打印 ps；SIGKILL Controller；新 PID 恢复；旧 Worker/后代退出；
# QUEUED 只领取一次；再 SIGKILL Worker，由 Controller 处理且 Daemon 不增加重启数
$PY -m unittest test_daemon.DaemonProcessTests.test_crash_recovery_three_processes_and_worker_failure -v
# 调度卡住但 HTTP 仍响应；短暂 SIGSTOP 不重启；第二个 Daemon 被拒绝
$PY -m unittest test_daemon.DaemonProcessTests.test_dispatch_hang_short_delay_and_singleton -v
# 持续 SIGSTOP 导致 HTTP 无响应，也能恢复
$PY -m unittest test_daemon.DaemonProcessTests.test_persistently_stopped_service_is_recovered -v
# D：故意不可用的临时数据库路径，只有初次 + 2 次重试；实际退避至少 .3/.6s
$PY -m unittest test_daemon.DaemonProcessTests.test_bounded_failure_and_backoff -v
# E：慢正常关闭不重启；后台 start / stop
$PY -m unittest test_daemon.DaemonProcessTests.test_normal_controller_stop_is_not_restarted test_daemon.DaemonProcessTests.test_detached_start_status_stop_commands -v
```

完整本次 Daemon 定向套件：

```bash
$PY -m unittest discover -s tests -p test_daemon.py -v
PYTHONPATH=tests $PY -m unittest test_controller_shutdown test_cli_startup -v
PYTHONPATH=tests $PY -m unittest test_controller_timeouts test_controller_cancel test_worker_process_group -v
```

交互观察也可 `unset PYTHONPATH` 后新建 `EOS_RUNTIME_DIR="$(mktemp -d /tmp/eos-daemon-demo-XXXXXX)"`，用真实场景目录和 `--port 18765` 启动；从 status 获取**该隔离实例** PID，执行 `ps -o pid,ppid,stat,cmd -p <PID列表>` 或 `pstree -ap <daemonPID>`。仅此测试实例可 `kill -9 <Controller测试PID>`，之后查看 status 新 PID 及 daemon.log，最后 daemon stop。禁止 pgrep 批量杀、killall 或向生产 8765 实例注入故障。

## 8. 实际结果与剩余限制

实测环境 `Linux 6.18.33.2-microsoft-standard-WSL2`、Python 3.10，实际 pidfd/prctl/flock，不只是 mock。一次隔离进程证据：

```text
PID     PPID    STAT  CMD
186586  186465  Sl    python -m eos_system.daemon run ... --port 46887
186608  186586  Ssl   python -m eos_system
186634  186608  Ssl   python -c from multiprocessing.spawn import spawn_main; ...
```

Controller 186608 被 SIGKILL 后，Daemon 186586 保持存活，新 Controller 186684 健康，原 Worker 186634 退出。原 attempt 失败、plan/metrics=null、没有重复 attempt。Worker 独立被杀时，按 EOF/进程退出发现先后可能为 IPC_DISCONNECTED 或 WORKER_EXIT，两者均为失败而非成功。

最终测试数量及末次含后代的进程证据见文末验证补充。未运行全量算法/浏览器/Orekit 测试，不操作正式服务，不修改场景 JSON。默认超时仅为保守课程默认值，高负载部署需按真实进度年龄调整，不因此放宽调度核验。

已知限制：

- 不是 cgroup 全树监管：算法自行 setsid 逃逸且从未观察到的后代无法保证定位；leader 和未登记后代同时消失也不能保证全面追踪。未知同 session 存活成员会 fail closed，需人工调查，不能宣传任意孤儿全自动恢复。
- 不可中断 D 状态、内核故障、硬断电、WSL 整体关闭、Daemon 自身被 SIGKILL 的自动恢复未覆盖。Daemon 崩溃后不盲目接管仍持锁的服务，需先确认并有序关闭残留实例。
- 不恢复中断算法的搜索内存，不重复执行无法确认安全性的旧任务；VERIFYING 依旧保守失败。重试耗尽且存在无法确认归属的进程时不会擅自杀进程，应保留运行目录人工诊断。
- Worker 日志对应当前串行执行槽；若未来实现多个同时活动的 Worker，需要改为按 attempt 多日志，不能直接复用一个 worker-lease.json。
- 无 schema 变化；API 只增加 health 字段，未增加 Web 远程进程控制。需李泽同复核 Controller/API 接入，何明涛复核父死亡信号与 Worker 回收边界。本轮本地实现不代表团队审核已完成。

### 最终验证补充

| 实际执行范围 | 结果 |
|---|---|
| `test_daemon.py` 全套（当时 12 项） | PASS，38.686s；真实进程崩溃/持续停止/调度卡死/短延迟/后代回收/慢关闭/退避与上限 |
| 最后追加的歧义 Worker 日志停机门禁，以及相关关闭复验子集 | PASS；6 项身份/门禁 + 2 项真实关闭 + 13 项 Controller 停机，共 21 项，24.860s |
| `test_controller_timeouts test_controller_cancel test_worker_process_group` | PASS，50 项，59.177s |
| `test_controller_shutdown test_cli_startup` | PASS，16 项，19.088s（之后 CLI 又追加关闭信号顺序用例） |
| 回收进度回调之后再跑 `test_worker_process_group` | PASS，15 项，2.221s |
| 最后 Uvicorn 关闭信号入口与真实恢复复验 | PASS，CLI 4 项 + 慢关闭/崩溃恢复/调度卡死 3 项，共 7 项，22.655s |

重复复验不重复计入独立用例；本次合计覆盖 80 个不同定向用例（Daemon 13、CLI 4、Controller 停机13、取消/超时及 Worker 组50）。不宣称全项目测试通过。

含真实同 session 后代的末次完整故障套件记录：Daemon **189641** → Controller **189668** → Worker **189707**，独立随机端口 **46003**。杀 Controller 后新 Controller **189758** 健康，Daemon PID 不变，旧 Worker 及已记录后代确认退出；下一 QUEUED attempt 只领取一次。再杀该 Worker，Controller 自行清理其后代并记失败，Daemon 恢复次数保持 **1**。无新计划或指标入库。

最后补充关闭信号入口后，又实际验证了 Daemon **191379** → Controller **191402** → Worker **191428**（端口 **45995**）；Controller SIGKILL 后恢复为 **191479**，Daemon PID 不变，原 Worker/后代退出，随后 Worker 单独故障不增加恢复次数。

开发中发现的两个错误断言（无计划应为 null；Worker 故障可能先发现 Pipe 断开）已按现有契约纠正。额外发现严格心跳下有界后代回收等待被误判，已增加实际回收循环进度回调，复验后没有 Daemon/Controller 争夺 Worker 恢复权。测试实例均已正常停止；没有向正式实例故障注入。

### PR 准备补验（2026-10-18）

- `python -m unittest discover -s tests -p test_daemon.py -v`：13 项全通过，39.988s。
- `python -m unittest discover -s tests -v`：539 项，531 通过、8 项 opt-in Orekit 跳过，0 失败/错误，166.981s。未执行大型场景或浏览器 Benchmark。
- 单独工作树仅 checkout 本地已有的原始 LFS 对象，未修改场景字节或重新生成数据；原根目录其他未提交修改不进入 PR。
- fetch 后 origin/main 仍为 7a1875f（PR #20），已是分支祖先，无需 rebase/merge。按用户后续请求创建 PR；等待独立审核及 Controller/Worker 负责人确认，不自行合并。
- 简体中文逐项命令、预期结果、常见错误和演示说明已纳入 [测试文档](../../L_readme/Daemon守护进程_测试与故障演示说明.md)。
