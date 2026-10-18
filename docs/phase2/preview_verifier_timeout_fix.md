# 规划预览核验超时与连续失败修复记录

日期：2026-10-18。分支：`feat/console-layout-polish`。本次保留同分支既有控制台布局改动，未提交或推送。

## 1. 三次实验的实际故障

| 实验前缀 | 模式与场景 | 实际原因 | 修复后用原配置隔离复验 |
| --- | --- | --- | --- |
| `6ae98557` | formal，10 星 20 任务原版场景 | 两算法均为 `CONTINUOUS_INCONCLUSIVE / UNTRUSTED_PHYSICAL_SETTINGS` | 两算法仍被拒绝，属于正式认证门禁 |
| `8ac4d944` | planning_preview，10 星 20 任务 epoch_fixed_v1 | 首个算法 `CERTIFICATION_TIMEOUT`，后一个 `PREVIOUS_VERIFIER_STILL_RUNNING` | profit_first、balance_first 均 SUCCEEDED，各 20 个任务 |
| `84225c7f` | planning_preview，3 星 30 任务演示场景 | 两算法均被前一实验未退出的核验线程阻塞 | 两算法均 SUCCEEDED，各 17 个任务 |

六次 Worker 都正常退出并返回候选，故障出现在 Controller 核验阶段。没有改写原 FAILED 记录，没有删除或重算原场景文件，没有把预览结果当成正式认证结果。

## 2. 根因与复现

- 原预览直接在 Controller 核验线程调用 Orekit，读取 Windows 挂载盘上的 `utils/orekit-data.zip`。原生调用期间，Python 的合作式 deadline 无法打断 Java 初始化。
- 独立诊断分别在后台线程、主线程直接读挂载盘数据包，12 秒、18 秒采集栈时均停在 `_OrekitContext.create()` 的 `FramesFactory.getITRF(...)`。
- 同包复制到 Linux 临时盘后，初始化约 3.93 秒完成。真实两个 profit_first 配置的候选生成及核验约 6.67、6.13 秒完成。这些是本机观测值，不是其他机器的性能保证。
- Controller 外层 30 秒期限只让当前运行失败，不能终止卡住的原生调用；旧核验槽仍被占用，导致后续预览连带失败。

## 3. 修复结构

- `eos_system/planning_preview.py`：保留 `audit_preview` 公共入口。非空计划先把 Orekit 数据包复制到 Linux 临时目录，核对原包/副本 SHA-256，再启动专用子进程。
- `eos_system/preview_audit_process.py`：只接收 Controller 提供的配置和规范化计划，执行原真实 Orekit 曝光采样逻辑；不写数据库，不签发正式认证凭据。
- 子进程期限使用外层剩余时间减 0.5 秒，为回收与凭据检查留出时间；超时由 `subprocess.run` kill/wait，父进程负责清理临时副本。没有进程级共享的僵死 JVM 留在 Controller 中。
- 子进程只返回 JSON 数据；Controller 核对 run ID、场景 SHA、计划 SHA、任务数和预览版本，再在自身进程签发 PreviewReceipt。无效响应、异常退出和物理拒绝均不能记为成功。
- 空计划仍检查场景 SHA 和期限，但不启动 JVM。`EOS_OREKIT_DATA` 可指定数据 ZIP；未设置时使用仓库内默认包。
- 正式认证路径、30 秒外层期限、约束和 0.05 秒预览采样步长均保留。预览成功仍为 `SAMPLED_PREVIEW / NOT_CERTIFIED`，不能获得正式认证导出资格。

## 4. 验证与运行恢复

执行：

```bash
PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 python -B -m unittest test_preview_process test_planning_preview test_certification_final_p1 -q
```

47 项通过。新增测试覆盖真实超时子进程的 kill/wait、超时后下次预览、临时副本清理、异计划凭据拒绝、物理拒绝保留、进程崩溃/无效 JSON 拒绝、空计划不启 JVM。单元测试模拟证据明确标记 UNIT_TEST_INJECTION_ONLY，不用于真实物理验收。

另在自动清理的临时 SQLite 中，复制原六次运行配置，串行经过真实 Worker、IPC、Controller、Orekit 和入库流程：四次预览成功，两次正式认证按原原因拒绝；预览认证状态均为 NOT_CERTIFIED。正式用户数据库只读用于获取配置，隔离数据库及脚本结束后清理。

确认实际队列无 QUEUED/RUNNING/VERIFYING 后，停止并重启本会话启动的后端。实际服务健康检查 `status=ok`、`dispatch_alive=true`，可刷新控制台继续运行。

## 5. 使用和限制

- 当前演示、算法调试、比较与回放选择“规划预览”，重新创建实验；历史 FAILED 保留诊断意义。
- `6ae98557` 的正式拒绝不是前端或 Worker 崩溃。要取得正式结果，仍需可信物理配置与连续区间证明；本修复不提供这些证明。
- 采样通过不能证明采样点之间绝无不可见间隙。其他场景若确实违反视线/姿态等物理约束，仍会被拒绝。
- 超时隔离针对本次实际出错的预览 Orekit 核验；正式认证仍沿用既有线程和门禁，本次不宣称其原生挂起也可进程回收。
- 每次非空预览暂时复制一份约 20 MB 数据包，有额外启动开销；副本在结果返回、拒绝或超时后删除，不累积缓存。父进程被外部强制 SIGKILL/系统断电时，Python finally 不能保证执行，适用一般临时文件限制。
- 本轮只做相关定向回归及六运行真实集成复验，没有重跑全仓库测试、全部算法或前端完整回放测试。
