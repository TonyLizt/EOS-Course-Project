# Daemon 守护进程：测试与故障演示说明

日期：2026-10-18

适用分支：`feat/controller-daemon`

实现提交：`68a8876`

环境：WSL2 Ubuntu / Linux、项目 Python 3.10 虚拟环境

## 一、测试目标与安全边界

验证独立 Daemon 能够监护 FastAPI/Controller 进程，发现异常退出或持续无响应，并执行有次数限制和退避的恢复。同时验证正常关闭不被误判，Worker 故障仍由 Controller 处理。

本文推荐使用项目已有的自动化故障测试：

- 自动创建 `/tmp/eos-watchdog-*` 临时运行目录、SQLite 数据库和随机空闲端口。
- 使用真正的 Linux Daemon、服务和 spawn Worker 进程，不仅是模拟进程对象。
- 只对测试创建并验证身份的进程发送 SIGKILL / SIGSTOP 等信号。
- 不操作正在使用的 8765 服务，不修改正式实验、正式结果或原始场景 JSON。
- 测试正常完成或进入清理流程后，关闭自身进程并清理临时目录。
- 测试 Worker 使用受控加载/等待桩，不代表执行了完整卫星调度算法，也不构成物理认证证据。

**禁止使用 `killall` 或按进程名称批量结束 Python。不要将正式服务 PID 代入故障注入命令。**

## 二、测试前准备

在 WSL Ubuntu 终端执行：

```bash
cd /home/asus/projects/eos-course-runtime/.worktrees/controller-daemon
PY=/home/asus/eos-course-runtime/.venv/bin/python

git branch --show-current
git log -1 --oneline
"$PY" --version
```

对应本次交付版本的预期输出：

```text
feat/controller-daemon
68a8876 feat(daemon): implement independent controller watchdog and recovery
Python 3.10.x
```

后续新增提交可能改变最新 Commit Hash，不应仅因此判定测试失败；需要确认仍包含 Daemon 实现。若当前路径不存在或无法导入 `eos_system.daemon`，先确认工作树及代码版本，不要在旧根目录反复启动服务。

以下命令中的 `PYTHONPATH=tests` 仅对该条命令生效，不会长期修改终端环境。

## 三、推荐：一次执行完整 Daemon 定向套件

```bash
"$PY" -m unittest discover -s tests -p test_daemon.py -v
```

当前版本预期结尾：

```text
Ran 13 tests in ...s

OK
```

耗时受系统负载影响，不要求与开发记录完全一致。若只需要确认功能，运行本节即可，不必再重复执行下面所有单项测试。

判定原则：

- `OK` 且无跳过：本条命令所含测试通过。
- `FAILED` 或 `ERROR`：失败，保留完整输出。
- `skipped` / `SKIP`：对应项目未执行，不应宣称已经验证通过。

## 四、按功能分别测试

### 测试 A：独立进程、Controller 崩溃恢复及 Worker 故障分工

```bash
PYTHONPATH=tests "$PY" -m unittest \
test_daemon.DaemonProcessTests.test_crash_recovery_three_processes_and_worker_failure -v
```

测试步骤：

1. 启动隔离 Daemon 和服务。
2. 创建测试任务，启动 Worker 及同 session 后代。
3. 使用 `ps` 输出实际 PID、PPID、状态及命令。
4. 对测试 Controller 发送 SIGKILL。
5. 验证 Daemon 持续存活、新 Controller 恢复、原 Worker 和已记录后代退出。
6. 验证旧运行失败、没有计划或指标被误提交，QUEUED 任务仅领取一次。
7. 再单独结束 Worker，确认由 Controller 收尾，Daemon 不增加服务重启次数。

预期输出包含：

```text
PROCESS EVIDENCE
    PID    PPID STAT CMD
    ...     ...  ... python -m eos_system.daemon run ...
    ...     ...  ... python -m eos_system
    ...     ...  ... python -c from multiprocessing.spawn import spawn_main; ...

RECOVERY EVIDENCE daemon=... old=... new=... worker=... reaped
...
OK
```

通过条件：Daemon、Controller、Worker 的 PID 不同；Controller 的 `old` 与 `new` 不同；Daemon PID 不变。Worker 单独故障可能先被识别为 `IPC_DISCONNECTED` 或 `WORKER_EXIT`，都应是失败终态，不能成为成功结果。

### 测试 B：调度卡死、短暂暂停及重复 Daemon

```bash
PYTHONPATH=tests "$PY" -m unittest \
test_daemon.DaemonProcessTests.test_dispatch_hang_short_delay_and_singleton -v
```

预期：

- 第二个 Daemon 被锁拒绝，不能抢占现有实例。
- 短暂 SIGSTOP / SIGCONT 不触发重启。
- 即使健康 HTTP 仍可访问，实际调度循环持续停止推进，也会触发 `HEARTBEAT_TIMEOUT` 并恢复。
- 最终显示 `OK`。

### 测试 C：Controller 持续无响应

```bash
PYTHONPATH=tests "$PY" -m unittest \
test_daemon.DaemonProcessTests.test_persistently_stopped_service_is_recovered -v
```

预期：持续 SIGSTOP 导致 Controller 无法响应健康请求；达到连续失败阈值后，Daemon 受控结束旧实例并启动新实例。新 Controller PID 不同，最终显示 `OK`。

### 测试 D：连续启动失败、有界重试与退避

```bash
PYTHONPATH=tests "$PY" -m unittest \
test_daemon.DaemonProcessTests.test_bounded_failure_and_backoff -v
```

测试故意将临时数据库路径设为不可用，使服务连续启动失败。

预期：

- 测试策略最多允许 2 次恢复，因此总启动次数为初次 + 2 次，不是无限重启。
- 两次恢复退避分别至少约 0.3 秒、0.6 秒。
- 最终 Daemon 状态为 `EXHAUSTED`，Daemon 子进程退出码为 3。
- **unittest 命令本身最终显示 `OK`**，因为验证失败保护正是该测试的目的。

上述为加速测试参数；实际默认策略为最多恢复 3 次，退避从 2 秒开始，上限 30 秒。健康后不自动清零生命周期恢复次数。

### 测试 E：正常关闭与后台管理命令

```bash
PYTHONPATH=tests "$PY" -m unittest \
test_daemon.DaemonProcessTests.test_normal_controller_stop_is_not_restarted \
test_daemon.DaemonProcessTests.test_detached_start_status_stop_commands -v
```

预期：

- Controller 正常关闭，即使清理过程较慢，也不会被自动重启。
- 后台 `start`、状态确认及 `stop` 命令工作正常。
- 最终状态为 `STOPPED`，正常关闭返回码为 0，实例锁释放。
- unittest 结尾显示 `Ran 2 tests ... OK`。

### 测试 F：真实 Worker 的父进程死亡保护

```bash
PYTHONPATH=tests "$PY" -m unittest \
test_daemon.DaemonProcessTests.test_reference_worker_parent_death -v
```

预期：使用真实 `worker_main`，仅替换耗时加载函数。Controller 被 SIGKILL 后，Linux 父进程死亡信号使直接 Worker 退出，Daemon 恢复服务，原运行标记 `CONTROLLER_RESTART`，最终显示 `OK`。

### 测试 G：身份校验与保守恢复门禁

```bash
PYTHONPATH=tests "$PY" -m unittest test_daemon.IdentityTests -v
```

当前预期为 6 项测试通过，重点包括：

- PID 相同但启动时间不匹配时不发信号。
- 手动 Controller 持锁时，Daemon 不启动第二个服务。
- PID 活着但调度线程已死或进度超时，不视为健康。
- 发现未知同 session 成员时阻止恢复，不盲目杀进程。
- 歧义 Worker 日志未解决时，Controller 不能宣称正常清理完成并释放锁。
- 重试参数和指数退避计算符合预期。

## 五、可选：相关 Controller / Worker 回归

仅当修改相关接口后需要补查时执行，不必每次演示都运行。

```bash
PYTHONPATH=tests "$PY" -m unittest \
test_controller_shutdown test_cli_startup -v

PYTHONPATH=tests "$PY" -m unittest \
test_controller_timeouts test_controller_cancel test_worker_process_group -v
```

当前版本预期分别为 17 项和 50 项通过，结尾均为 `OK`。这些测试覆盖原有取消、超时、停机持锁、PID/session 校验和 Worker 回收等兼容性；不运行大型卫星场景 Benchmark。

## 六、可选：手动观察 Daemon 状态和进程树

本节用于观察真实后台实例，不必启动正式服务。新开一个终端，从准备步骤的工作树执行：

```bash
PY=/home/asus/eos-course-runtime/.venv/bin/python
export EOS_RUNTIME_DIR="$(mktemp -d /tmp/eos-daemon-demo-XXXXXX)"
export EOS_SCENARIO_DIR=/home/asus/projects/eos-course-runtime/experiments/scenarios

"$PY" -m eos_system.daemon start --port 18765
"$PY" -m eos_system.daemon status
```

预期：start 输出 Daemon PID。初始化期间状态可能为 `STARTING`，稍后再次执行 status，应为 `HEALTHY`，且包含：

```text
daemon.pid
controller.pid
state: HEALTHY
restarts: 0
last_healthy_at
daemon_alive: true
```

如果 18765 已占用，请换一个未使用端口并相应修改后续 URL。不要结束占用端口的未知进程。

确认健康及查看日志：

```bash
curl -fsS http://127.0.0.1:18765/api/health
tail -n 30 "$EOS_RUNTIME_DIR/daemon.log"
```

健康响应预期包含 `controller.process`、`dispatch_alive: true`、`stopping: false`、较小的 `progress_age_s`。只看到顶层 `status: ok` 不能单独证明调度线程健康。

从 status 获取本测试实例的 PID 后，手动替换以下占位符再运行：

```bash
ps -o pid,ppid,stat,cmd -p <Daemon_PID>,<Controller_PID>
pstree -ap <Daemon_PID>
```

预期：Controller 的 PPID 指向 Daemon。没有提交任务时通常没有算法 Worker，这是正常现象；要稳定展示三进程和故障恢复，优先执行测试 A。

**手动实例不必再执行 kill 故障注入；上面的自动化测试已经安全覆盖。**

观察结束后关闭：

```bash
"$PY" -m eos_system.daemon stop
"$PY" -m eos_system.daemon status
```

预期：stop 成功；之后 status 显示 `daemon_alive: false`，历史状态通常为 `STOPPED`。此时 status 返回非 0，表示没有正在运行的 Daemon，不是停机失败。临时运行目录会保留日志供检查，可在确认进程全部退出后自行清理；不要删除正式运行目录。

## 七、已有验证证据

实现阶段已在 `Linux 6.18.33.2-microsoft-standard-WSL2` 实际执行定向测试，不是仅提供尚未运行的命令。

一次实际演示记录：

| 角色 | 故障前 PID | 恢复后 |
|---|---:|---|
| Daemon | 191379 | PID 不变，持续存活 |
| Controller | 191402 | 新 PID 191479，恢复健康 |
| Worker | 191428 | 原 Worker 及已记录后代退出 |

以上 PID 仅为历史证据，**不能直接用于当前 kill 命令**。每次测试的 PID、端口和临时目录都会变化。

开发阶段合计覆盖 80 个不同定向用例，相关命令和复验范围详见实现文档；重复执行不重复计数。本测试文档编写时没有重新执行这些测试，当前用户环境是否通过，应以实际运行输出为准。

### PR 提交前补验（2026-10-18）

在本测试文档初次编写后，按团队协作规范重新执行：

```bash
"$PY" -m unittest discover -s tests -p test_daemon.py -v
"$PY" -m unittest discover -s tests -v
```

实际结果：Daemon **13 项通过，39.988 秒**；完整默认 Python 套件 **539 项，531 项通过、8 项 opt-in Orekit 测试跳过，0 失败、0 错误，166.981 秒**。没有启用大型场景 Benchmark 或浏览器长时间测试。测试工作树仅展开本地已缓存的 LFS 原始对象，没有更改场景内容或重新生成数据。

创建 PR 前已 fetch 并确认 `origin/main` 为 `7a1875f`（PR #20），且已是本分支祖先，无需 rebase 或额外 merge。合并前仍需独立组员审核，并由 Controller / Worker 负责人确认公共接口影响。

## 八、异常处理和已知限制

1. `ModuleNotFoundError`：先检查是否位于 Daemon 工作树、Python 路径是否正确；单项测试需要 `PYTHONPATH=tests`。
2. `Address already in use`：手动实例更换测试端口，不杀未知进程。自动化测试使用随机端口，但极少数情况下仍可能发生分配竞争，可保留输出后重试。
3. `pidfd` / `prctl` 不支持：需在支持相应 Linux 接口的 WSL2 环境运行；跳过不等于通过。
4. 超时：保留完整错误和进程输出，确认系统负载。不能直接关闭身份校验或无限放宽重试来让测试通过。
5. `EXHAUSTED`：表示恢复预算耗尽，应诊断原因后再手动启动，不是持续后台重试。
6. `BLOCKED`：可能存在外部 Controller、未知遗留成员或清理不完整。不要删除锁或身份日志强行绕过门禁。
7. 当前不是 cgroup 全树监管：从未被观察到且自行逃逸 session 的后代无法保证自动定位。测试通过不代表任意恶意后代都能恢复。
8. 不恢复算法搜索内存；中断的 RUNNING / VERIFYING 按保守失败处理，不重算旧 attempt，不伪造成功结果。
9. WSL 整体关闭、内核故障、不可中断 D 状态以及 Daemon 自身被 SIGKILL 的自动恢复不属于本次已验证范围。

## 九、测试记录模板

| 日期 | 分支 / Commit | 测试命令或编号 | PASS / FAIL / SKIP | PID / 关键输出 | 备注 |
|---|---|---|---|---|---|
| 待填写 | 待填写 | 测试 A | 待填写 | 待填写 | 待填写 |

进一步设计、默认参数、文件锁、Worker 日志和模块协作边界，参见：

`/home/asus/projects/eos-course-runtime/.worktrees/controller-daemon/docs/phase2/daemon_implementation_and_validation.md`
