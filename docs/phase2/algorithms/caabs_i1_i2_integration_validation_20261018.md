# R2-C6：I1 + I2 正式集成版本验收（2026-10-18）

结论：**INTEGRATION REVIEW PASS WITH CONDITIONS**。

实际集成源码的完整默认回归通过，真实非空任务经过 Registry、CAABS、独立 Worker、Controller 和可信来源核验，并进入真实连续曝光审查。连续审查返回 `INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE`，系统正确拒绝正式结果入库和 JSON/CSV 导出。因此，本报告支持提交 I2 Draft PR 供人工审查，**不宣称真实非空正式存储/导出闭环通过，不构成物理认证或发布批准，也不满足无条件合并 main 的条件**。

## 1. 实际基线与范围

| 项目 | 本轮实测 |
|---|---|
| 工作树 | `D:\VC\EOS-Course-Project-i2` |
| 分支 | `fix/source-window-i2` |
| HEAD | `0b8dbd4bef5b01bac6538c69a166ee87a62701f6` |
| 本地 origin/main | `5e37ba720a9222a70d834d84e96c740601a3d236` |
| 实际远端 main | `git ls-remote origin refs/heads/main` 同上；本轮结束前复核一致 |
| 开始状态 | `git status --short`、`git diff --stat`、暂存区均为空 |
| HEAD 相对 main | 17 文件，1177 插入、117 删除；完整 Diff 归档于外部证据目录 |

实际提交关系为 `0b8dbd4 → 5e37ba7 → I1 PR #18`，不是此前基于 `0a1a941` 的临时组合源码。此次未进行代码覆盖、Merge 或 Rebase。已核对 `COURSE_SETUP.md` 的 I1/I2 历史记录及 `docs/phase2/algorithm_integration.md` 的中立 Solver 契约和 I2 说明均保留。

17 个既有集成变更文件：`COURSE_SETUP.md`、`docs/phase2/algorithm_integration.md`、I2 修复报告、I2 PR 草稿、来源契约、`framework_handoff.md`、`interface_design_target.md`、`eos_system/exporting.py`、`eos_system/verification.py`、`schedulers/constraint_model.py`、`schedulers/scenario_loader.py`、`schedulers/schedule_output.py`、`schedulers/source_windows.py`、两份来源专项测试、`utils/certification_identity.py`、`verify_schedules.py`。准确路径和逐行内容见 `head-vs-main.diff`。

对 main→HEAD 的独立保护检查：CAABS 搜索核心、I1 Registry/中立 Solver 契约、Controller、Worker、公共 HTTP 合约、Storage/SQLite Schema、严格连续曝光实现和 `.gitattributes` 无差异；Assignment dataclass 的 AST 与 main 相同。I2 公共模型仅进行来源校验及时间兼容修复，未扩展 Assignment 字段。源文件比较与测试结束后的复核均在写本报告之前完成，结果见 `analysis.json.scope`。

## 2. 证据目录、源码和数据身份

本机证据目录 E：

```text
C:\Users\流星\AppData\Local\Temp\eos-i1-i2-integration-20261018-c2693b86fb744f1096be8deec527883e
```

原生 WSL 源码目录 N：

```text
/home/meteor/eos-course-runtime/audits/i1-i2-integrated-0b8dbd4-lcz2prgt
```

真实系统诊断目录 R：

```text
/home/meteor/eos-course-runtime/audits/c6-real-system-0b8dbd4-6wn0wtoo
```

这些都是本机审计路径，不是仓库可移植路径。正式交付前应把 E、R 及依赖的历史回执归档到团队约定的证据存储；本轮未将数据库、日志、场景或 ZIP 加入 Git。

`git ls-files -z` 清点后，将 **283 个受跟踪文件**逐字节复制至 N；`native-snapshot.json` 对每个文件记录原路径、SHA-256、大小、复制后 SHA-256 和大小，全部相等。另有 **18 个 experiments/scenarios 下的受跟踪输入**记录完整 SHA/大小，通过目录链接只读使用实际工作树输入，不重复复制大型数据。该区别在清单中明确标注。比较的是干净 HEAD 的实际签出字节（包括 Windows 签出换行），Git blob 身份另由 `head-tree.txt` 保存，未把 LF blob 和 CRLF 签出混称同一字节身份。

默认回归和真实系统诊断完成后，283 个工作树文件、283 个原生副本文件和18个原输入均重新核对，全部未改变。Orekit 数据位于 N 的 `utils/orekit-data.zip`，SHA-256：

```text
1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985
```

## 3. 完整默认回归

环境：Ubuntu-22.04 / WSL2，`Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.35`；解释器 `/home/meteor/eos-course-runtime/venv/bin/python`，Python 3.10.12，Pydantic 2.14.1。运行目录为 N，设置 `PYTHONDONTWRITEBYTECODE=1`、`MPLBACKEND=Agg`、`EOS_OREKIT_DATA=N/utils/orekit-data.zip`，没有修改测试时限或开启额外 opt-in 开关。

实际 `full-default.json.argv` 执行下面的默认发现及退出判断（完整 `-c` 文本保存在回执中，另含环境和计数打印）：

```python
suite = unittest.defaultTestLoader.discover('tests')
r = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not r.wasSuccessful())
```

| 项目 | RUN | PASS | FAIL | ERROR | SKIP | 退出码 | 总耗时 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 本次实际集成 HEAD 完整默认集 | 497 | 489 | 0 | 0 | 8 | 0 | 150.717 秒 |

下列各组包含在上述一次完整运行中，不叠加计入总数：

| 测试模块/范围 | 结果 |
|---|---|
| I1 Registry | 17/17；含独立进程导入顺序与真实公开构造 |
| I2 来源身份 | 31/31 |
| I2 P2 | 15/15 |
| CAABS Core | 48/48；联合四组共111/111 |
| Adaptive | 3/3 |
| 连续流水线 / 认证部署身份 | 17/17、40/40 |
| 公共曝光边界 | 14 PASS、1 SKIP |
| Controller 取消 / 停机 / 超时 | 13/13、13/13、21/21 |
| Worker IPC / 进程组 | 19/19、15/15 |
| Manifest | 47/47 |

8 个跳过分别为真实曝光 opt-in 1、E3/E4 Orekit opt-in 3、轨道导出 opt-in 1、轨道插值 opt-in 2、窗口重算 Orekit opt-in 1。逐项名称和理由保存在 `full-default.json.result.skipped`；这些不计作通过。本轮小场景真实 Orekit 诊断也不能代替这些专用案例。

UTC 修复位于 `schedulers/constraint_model.py:292` 起，调用既有解析器先转 UTC 再创建 naive UTC 局部副本；来源步长校验位于 `schedulers/source_windows.py:36` 起及 `schedulers/scenario_loader.py:214` 起。P2 15 项覆盖直接构造 Assignment、原对象不变、非零偏移、混合 Schedule、微秒边界、半开相邻区间、通信冲突、三级零步长、负数/NaN/Inf/布尔/非整数微秒、默认值及合法0.5/1/2秒，未更改既有容差。

完整 stdout、stderr 和真实退出码分别为 E 的 `full-default.stdout.txt`、`full-default.stderr.txt`、`full-default.json`。默认套件中的模拟认证正向案例仍只是单元测试证据；下一节在另一全新 Python 进程执行，不导入测试模块或模拟认证。

## 4. 真实非空系统验收

### 4.1 输入和执行方法

使用生产 `Scenario.calculate_visibility_windows` 和实际 Orekit 计算一个新的诊断输入：1星、2任务、1地面站、60秒时域、1秒扫描、2秒曝光。目标和站点取卫星在时域中点的真实星下点，避免手写观测/通信窗口。轨道为 a=7000km、e=0.001、i=60°、RAAN=10°、argp=20°、M=30°，历元 `2025-11-18T12:00:00Z`。

诊断 NON_AGILE 卫星显式声明 yaw/pitch/roll 各180°能力，传感器数据率10Mbps、功率5W；这是该新诊断场景的宽能力配置，不是修改全局姿态或认证规则，也不代表生产数据物理合理性验收。输入标识 `C6_DIAGNOSTIC_ONLY / not_a_release`，生成2个观测分组、1个通信分组，有真实窗口生成记录。

输入 `R/scenarios/small.json` 大小19,623字节，完整 SHA-256：

```text
bf4dcb78b568c3a4f6c1ef0779076e01bc7fa5a2ab4afa2aeaa3f13e7f8a89a9
```

先调用实际 Registry、`prepare` 和 `run_prepared` 构造 CAABS/CAABSParams，得到非空计划；随后使用真实 FastAPI 应用生命周期、真实 API 路由、Controller、子进程 reference Worker、独立 Verifier 和隔离的真实 SQLite。因环境缺少 TestClient 所需的 `httpx2`，仅传输层使用直接 ASGI 请求，没有启动 TCP/浏览器；不把本次结果扩大为网络部署验收。

`sys.setprofile` / `threading.setprofile` 只读观察 Worker 候选抵达正式 `verify_candidate` 的参数、来源恢复返回值和实际物理审计返回值，保存原始候选 JSON；没有替换函数、参数、Worker、Verifier、证书或返回值，观察器错误为0。所有新数据和数据库写入 R，不触碰历史数据库或冻结数据。生产30秒认证上限及其他正式时限不变。

实际命令：在 N 运行 `/home/meteor/eos-course-runtime/venv/bin/python -B E的WSL路径/system_acceptance.py`，完整 argv/环境见 `system-command.json`，退出码0，耗时29.438秒。脚本 SHA-256：

```text
e646365085840aa77c15d149ebc0fa8a738fc9b8943b0c90a3983bef782bba45
```

此退出码表示诊断预期断言成立，不表示下面 FAILED 运行获得正式成功。

### 4.2 非空算法和可信来源核验结果

| 算法 | run_id | 实际候选 | sat/gs 来源 ID | 最终状态 |
|---|---|---:|---|---|
| CAABS | `03e4d879-2ef6-4c0d-8d4e-41982786c3ad` | 1条，M1 | 1 / 1 | FAILED / CONTINUOUS_INCONCLUSIVE |
| Completion | `a7eb873b-b181-48dc-931d-38343df093c5` | 1条，M2 | 2 / 1 | FAILED / CONTINUOUS_INCONCLUSIVE |
| Adaptive | `3ef714f2-99b1-47d0-a17f-1023d2af69d5` | 1条，M1 | 1 / 1 | FAILED / CONTINUOUS_INCONCLUSIVE |

三个 Worker 均通过真实进程通道传递非空候选，Controller 所收到的来源 ID 与可信 Scenario 恢复结果一致。观测均为 `12:00:29→12:00:31` UTC、圈号1、传感器 `S_sensor`；CAABS/Adaptive 通信为 `12:00:44.500000→12:00:46.500000`，Completion 为 `12:00:58→12:01:00`。公共约束和来源恢复成功后才进入真实物理认证。

实际 `continuous_exposure_audit_v3` 对每个2秒曝光执行41个点评估，采样边界状态 PASS，但严格连续状态为 INCONCLUSIVE，原因 **NO_CONTINUITY_CERTIFICATE**。有限点检查不能排除采样点间隐藏不可见间隙，不能代替解析/区间证明。最深实际阶段为**正式 Verifier 的真实连续物理认证**，不是 Solver 名称查询或空计划测试。

### 4.3 SQLite 和正式导出边界

R 的真实 SQLite 读回结果：runs=6、run_attempts=6、run_events=60，**plans=0、assignments=0、metrics=0、exports=0**。Controller 保留真实运行及失败/取消/超时诊断，未写入正式成功计划。Worker 事件按原设计仅存运行耗时，不存完整候选；观察器的 `observed/*-candidate.json` 是诊断文件，不是成功结果导出。

实际 CAABS JSON/CSV 导出 API 均 HTTP409，消息“实验尚无正式成功结果”；直接 `render_json` / `render_csv` 也拒绝，理由 `no continuously certified successful plan`。

因此：

- Worker→Controller→Verifier 的非空来源身份传递：实测通过。
- SQLite 失败运行和生命周期状态持久化、导出拒绝门禁：实测通过。
- 正式成功 Assignment 在 SQLite、JSON、CSV 间的真实非空往返：**BLOCKED，未完成**。单元测试中的存储/导出往返只能证明受控接口行为，不能补足这个真实认证缺口。
- 未创建伪造证书、注入认证成功或绕过成功事务来补齐闭环。

## 5. 真实反向核验与生命周期

对独立诊断副本作负向输入修改，保留原始输入字节；各副本及计划保存于 R，不能混充历史场景。正式 Verifier 和 CLI 公开核验入口返回一致：

| 输入 | 两入口拒绝原因 | 进入连续认证次数 |
|---|---|---:|
| 伪造 sat_window_id=999999 | UNKNOWN_SAT_WINDOW_ID | 0 |
| 换用另一个任务的已存在观测窗口 ID | SAT_WINDOW_SOURCE_MISMATCH | 0 |
| 伪造 gs_window_id=999999 | UNKNOWN_GS_WINDOW_ID | 0 |
| 同任务复制同时间来源后删除显式 ID | AMBIGUOUS_LEGACY_SAT_SOURCE | 0 |
| 实际来源窗口 time_step=0 | SAT_WINDOW_SOURCE_MISMATCH | 0 |

未预期接受数为0。另向计划自报 `continuous_verified=True` 和连续通过声明，真实认证仍返回 `ContinuousCertificationError / NO_CONTINUITY_CERTIFICATE`。Solver/JSON 自报不能替代可信 Scenario 或物理证明。更全面的错误传感器、卫星、时间边界、三级步长等负向分支由本轮完整套件中的31+15项覆盖；这里不将单元测试分支冒称六次系统运行均覆盖。

| 实际运行 | run_id | 结果与证据 |
|---|---|---|
| 合法微小搜索预算0.000001秒 | `814029d8-c5a1-4690-b8c1-2487c4848841` | TIMED_OUT / SEARCH_BUDGET；未进入认证；未修改正式认证时限 |
| 活跃 Worker 取消 | `062352f8-d1e1-49f0-9dfe-3a2809d8656e` | API202时为 RUNNING，worker started后发起；cancel_ack后 CANCELLED / CANCELLED |
| 认证期间取消 | `7fdfb428-77af-4a70-9e87-a6354077d4ee` | API202时为 VERIFYING；记录 CERTIFICATION_FAILURE_AFTER_CANCEL，最终 CANCELLED / CANCELLED_DURING_VERIFY |

全部六次 Worker 的进程退出码0；WORKER_REAP 均 `alive=false`、`live_members=0`、`identity_confirmed=true`、`signal_errors=[]`，无观察到的残留进程。取消案例用真实生命周期自然竞争，不延长或替换业务时限；这不证明所有操作系统/负载下的时序行为。

## 6. 公共兼容性与部署身份

Completion、Adaptive、CAABS 的真实非空来源核验均成功，三者连续认证均按同一规则被阻断。默认回归包括公共 ConstraintModel、两个 Verifier、JSON/SQLite/导出路径、取消/超时、部署身份边界；没有观察到新增算法接口回归。

来源 ID 属于可信 Scenario 快照中 Loader 重建的观测/通信各自编号空间，必须结合 Scenario SHA；相同裸 ID 不跨场景认证。显式非法 ID 不退回旧式匹配，历史无 ID 仅在完整语义唯一匹配时兼容。来源身份正确、离散约束通过、严格连续证明、正式发布资格仍是四个不同结论。

`utils/certification_identity.py:18` 的 `SOURCE_NAMES` 已包含 `schedulers/source_windows.py`，来源解析器受进程冻结的部署身份约束。源码/部署/数据上下文变化必须重启并重新认证，旧部署凭证不能当作新版本凭证复用；认证身份40项回归通过。本轮没有可用的真实物理通过证书，未声称实测了跨部署真实成功证书迁移。该机制的可信本机部署及启动/端点身份检查边界仍保留，不能描述为对抗恶意文件系统的证明。

`eos_system/exporting.py:57` 新增 `sat_window_id`、`orbit_number`、`gs_window_id`，是现有 CSV 表头中插入的列。仓库内可见消费者以下载/字段方式使用，未发现依赖旧位置的 CSV 导入器；**仓库外按列位置消费的工具尚未验收**，需李泽同确认表头消费规则及版本说明。未改变 HTTP/Worker/Controller 原有协议或 SQLite Schema。

## 7. 历史失败、异常和证据可靠性限制

原 Windows 挂载路径历史运行仍是465 RUN、429 PASS、28 FAIL、8 SKIP、退出1，531.116秒。本次没有重跑或解决该路径全量测试。原记录位于：

```text
C:\Users\流星\AppData\Local\Temp\eos-i2-20261018-359047ceed9b4b60b25b99988ca5f97c\full-suite.{json,stdout.txt,stderr.txt}
```

原28条 failure 分类为 Adaptive 2、shutdown 6、timeouts 20（包括子测试），不把 failure 条数等同于28个独立测试方法。后续 P2 报告已单独处置 Adaptive 反例；其余26条不能仅凭本次原生文件系统通过就认定原路径已解决或基线本来如此。

本次逐一核对原三份日志与旧 delivery-check 身份，均一致：

| 文件 | SHA-256 |
|---|---|
| full-suite.json | f1a50604dffdcebec6933b951e67dd8f5c6cea5ffff007647da73a83ff3d7d68 |
| full-suite.stdout.txt | 01872243cefc3c5556f1507727bc9f05d8eeef19b6fcb87cde1ef6d75fe3075c |
| full-suite.stderr.txt | 0225e2de3e14d90f93dfc16d787ef79a6bdd13e7655664769b2af89a983b50a0 |

本轮准备阶段异常也保留，不隐藏为成功运行：初次复制遇到 Git 引号文件名，改用 NUL 分隔后重新建副本；第一次系统脚本在 JVM 启动前导入 Orekit 帮助函数失败；第二次缺 TestClient 的 httpx2，随后改为直接 ASGI 传输。各次 attempt 脚本、输出和退出码回执存 E，最终系统进程退出0。这些是外部审计脚本/依赖准备问题，未因此修改产品实现或安装依赖。

最终系统 stderr 仍有 JPype/JDK `System::load` native-access 警告；本次不影响运行，但未来 JDK 限制需要环境负责人跟踪。未为消除警告修改启动参数。准备异常、正式异常和预期负向拒绝应分别阅读原始日志。

## 8. 问题、责任边界与交付闸门

本轮**未发现新增 I1/I2 代码 P0/P1/P2 缺陷**；下列事项仍限制验收范围，不能因测试退出0而关闭：

| 项目 | 状态 / 责任与后续要求 |
|---|---|
| 真实连续曝光区间证明缺失 | 正式发布及真实成功存储/导出阻断。物理认证负责人和李泽同确认后续证明方案；不得降级规则或让规划可行替代认证 |
| 挂载路径28条失败历史 | 环境时序限制未关闭。运行环境/进程生命周期负责人另案复现；本报告仅证明原生 WSL 本次运行 |
| CSV外部消费者 | 公共契约待李泽同确认；建议按字段名消费并发布列变化说明，不自行改Schema或回退来源身份 |
| 8个真实Orekit opt-in | 本轮NOT RUN；按相应物理/可视化交付闸门单独执行，不得计为默认回归通过 |
| 证据仍在本机临时目录 | 人工评审前归档并保留完整清单/日志；避免报告路径过期后只剩汇总数字 |
| API网络/浏览器部署 | 本轮仅真实ASGI路由及生命周期；TCP部署与浏览器不是本次实测范围 |

**可提交 Draft PR：是**，以代码和来源身份修复为范围，完整披露上述阻断，并附本报告和原始回执。本轮没有创建 PR。

**是否可整合当前 main：当前 HEAD 已含实际 main 5e37ba7**，没有需要再次 Rebase 的新提交，也未发现未整合 I1 文件。远端若再变化，应重新核对重叠文件及回归，不能沿用本报告。

**是否满足合并 main：尚不满足无条件合并。** 需要非作者独立评审、李泽同对公共来源/CSV契约签收，并明确批准“身份修复可合并、物理发布继续阻断”的范围。如果合并验收要求真实非空成功SQLite→JSON/CSV闭环，则该条件本轮未满足，必须获得真实连续证明后补测，不能用模拟证书补验。

## 9. 对现有交付材料的必要更新建议

本轮不改写既有历史报告，建议人工审核后追加带日期的 C6 集成附录，保留原失败/覆盖版本的原始结论：

1. `caabs_i2_source_window_fix_20261018.md`：补充实际0b8dbd4已整合I1、完整497/489/8结果和六次真实运行；将“未Rebase/主线仅临时组合”限定为历史时点；明确正式非空入库/导出受NO_CONTINUITY_CERTIFICATE阻断。
2. `assignment_source_window_contract_v1.md`：关联实际集成SHA和本报告；重申Scenario SHA+Loader来源编号空间、UTC及步长既有语义；补充CSV消费者签收事项和真实认证边界，保留公共负责人待确认状态。
3. `caabs_i2_source_window_pr_draft_20261018.md`：基线改为main5e37ba7/实际提交0b8dbd4，验证栏使用本次原生等字节完整结果；区分真实来源链通过、物理认证阻断和模拟单元往返；保留旧挂载失败及8项跳过，删除任何不符合当前状态的“尚未提交/Rebase”现状描述（历史记录保留）。

## 10. 本轮新增内容与复核入口

本轮仓库变更仅为新增本报告及 `COURSE_SETUP.md` 的 C6 入口；没有修改Python、既有测试、历史原始输入、冻结候选、侧车、正式数据库或认证门禁。

E 中的主要回执：`initial-git.json`、`head-vs-main.diff`、`head-tree.txt`、`native-snapshot.json`、`prepare_and_test.py`、`full-default.{json,stdout.txt,stderr.txt}`、`system_acceptance.py`、`run_system.py`、`system-command.json`、`system-acceptance.json`、`system.{stdout.txt,stderr.txt}`、`analysis.json`。R 中包括 `generation.json`、输入及负向副本、`registry-preview.json`、六份运行回执、`observed/`、`observations.json`、`negative-results.json`、`http.json`、`sqlite-readback.json`、隔离 `results.sqlite3`。这些足以复核实际命令、输入、源码/数据身份、进程退出、来源恢复和认证阻断，不能只引用本报告计数。

最终 `git diff --check`、状态和证据文件SHA清单另存 E 的 `final-review.json` / `evidence-files.json`。本轮不执行暂存、提交、推送、合并、Rebase或创建PR；完成后等待人工审核。
