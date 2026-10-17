# R2-B / I1：CAABS Algorithm Registry 集成修复

任务日期：2026-10-18（Asia/Shanghai）。结论：**I1 的查询、参数校验、Solver构造及导入顺序验收通过；待人工代码审核。** 不代表I2、来源完整性、连续曝光认证或正式发布通过。

## 1. 基线与缺陷复现

工作树 `D:/VC/EOS-Course-Project-i1`，分支 `fix/caabs-registry-i1`，HEAD `0a1a9418659be9d7b9e4dad90484ac2cd087c593`，已包含 CAABS Core PR #17。开始前 status --short 和 diff --stat 均为空，已记录 branch/log/worktree list/origin/main。没有切分支、修改其他工作树或更新Git提交。

首先阅读 conflict_beam.py、algorithm_registry.py、factory.py、Runner、RunConfig/参数兼容入口、API元数据路由和R1 I1记录。三个完全独立的Windows Python进程按下列实际命令执行；路径为当前工作树，解释器为 `D:/Anaconda/python.exe`，均带 `-B`，child显式UTF-8输出：

```python
# 进程一（PID 64996）
import algorithms.conflict_beam
import eos_system.algorithm_registry as registry
registry.list_algorithms()

# 进程二（PID 62456）
import eos_system.algorithm_registry as registry
import algorithms.conflict_beam
registry.list_algorithms()

# 进程三（PID 18748）
from eos_system.algorithm_registry import get_algorithm
get_algorithm("caabs").public_info()
```

| 真实入口 | 修复前 | 修复后，同解释器/同命令 |
|---|---|---|
| conflict_beam → Registry | 退出0；只有两个旧算法 | 退出0；包含caabs |
| Registry → conflict_beam | 退出0；只有两个旧算法 | 退出0；包含caabs |
| Registry单独导入后get_algorithm(caabs) | 退出1，KeyError再包装为ValueError | 退出0，返回实际CAABS参数schema/元数据 |
| 公共make_context / spec.build / solve | 未登记，不能从Registry到达 | 真正CAABSParams、ConflictBeamScheduler，非空Schedule公共约束重放通过 |

修复前真实异常链：

```text
eos_system/algorithm_registry.py:124, get_algorithm
    return _SPECS[algorithm_id]
KeyError: 'caabs'
...
eos_system/algorithm_registry.py:126, get_algorithm
    raise ValueError(f"算法未登记：{algorithm_id}") from exc
ValueError: 算法未登记：caabs
```

**没有复现当前基线的循环导入异常，也没有制造该失败。** 原R1文档I1明确描述的是“未来eager登记条件触发风险，当前未登记版本无此故障”。本次实际故障是缺少caabs登记；原始依赖方向会阻碍直接eager登记，二者必须区分。before.json保存完整argv、PID输出、退出码和未经截断的完整堆栈，不以上述节选代替原始日志。

## 2. 根因与最小方案

原来 AlgorithmParams / SolveContext / Solver 定义在Registry里，CAABS为了取得类型而导入Registry。若在Registry模块初始化时反向导入CAABSParams/ConflictBeamScheduler，algorithm-first时会读到尚未定义CAABSParams的半初始化模块。仅把反向import放在Registry基类定义之后，仍不能消除这条环；本次没有在真实工作树人为尝试这种有缺陷的中间实现。

本次建立明确依赖：

```text
CAABS → algorithms.solver_contracts → 既有领域模型
Registry → CAABS + algorithms.solver_contracts
Runner/Worker → Registry（原公共导出继续可用）
```

具体生产改动仅三个文件：

1. 新增 [algorithms/solver_contracts.py](../../../algorithms/solver_contracts.py)，原样移动 AlgorithmParams、SolveContext、Solver 的定义；字段、默认取消回调、frozen/extra规则及solve签名不变。该模块不导入Registry/工厂，不做自注册、JVM初始化、文件写入或运行上下文构造。
2. [conflict_beam.py](../../../algorithms/conflict_beam.py) 仅把一行契约import改到中立模块。Beam Search、canonical assignment/state key、SafeConflictIndex、候选、预算/取消及优化策略全部不动。
3. [algorithm_registry.py](../../../eos_system/algorithm_registry.py) 从中立模块导入并继续导出原公共名字；显式登记caabs，params_model使用原CAABSParams，build直接返回ConflictBeamScheduler，version直接引用VERSION=0.1.0。没有为新Solver使用LegacySearchAdapter，也不捕获build时的旧context。

旧factory没有适配这个直接solve协议，保持其原有search算法、参数映射与行为不变；本次不向create_algorithm增加一个签名不相容的caabs别名。公共接入通过get_algorithm/make_context/spec.build。新契约文件位于algorithms/，现有algorithm_source_sha256自动遍历该目录，因此会纳入算法代码身份，不必改config或物理部署身份算法。

兼容范围：Registry原导出的三个类型与新模块对象为同一对象；旧调用方import保持有效；旧pickle的Registry类型全局引用可以解析到新对象，专测此行为。类型的规范__module__位置改变是明确的实现调整，不宣称所有任意序列化实例都获得新保证。CompletionParams、AdaptiveRepairParams、AlgorithmSpec、旧两个注册项和旧适配逻辑保持原行为；Pydantic schema由原实际模型生成。

核心Diff为：

```diff
-from eos_system.algorithm_registry import AlgorithmParams, SolveContext
+from algorithms.solver_contracts import AlgorithmParams, SolveContext
```

以及共用类型定义迁移、Registry的caabs显式项。完整tracked/new文件Diff在本机审核目录的 `review.diff`，不通过暂存产生Diff，不修改Git索引。

## 3. 自动化证据

新增 [test_algorithm_registry_i1.py](../../../tests/test_algorithm_registry_i1.py)，17个方法覆盖：

- 四种独立进程检查：两种实际导入顺序、Registry独立查询/校验/构造、中立契约导入不初始化Registry或factory。没有用同进程reload冒充独立进程。
- 原公共类型重导出身份及旧pickle类型引用；实际CAABS版本、owner/category、schema、默认值和五参数模型。
- 合法边界、strict整数/布尔、越界/未知字段/非对象、把seed或budget误放专属参数中的负例；冻结模型及公共validate_algorithm_params/make_context一致。
- Registry确实构造CAABS并用两任务内存夹具返回非空Schedule，逐条调用真实公共ConstraintModel重放；build阶段取消context不会污染solve收到的本次context。
- 用真实RunConfig、临时JSON、Loader和Runner.prepare/run_prepared走接线/序列化；此空夹具不代表物理可行性数据。
- 旧两算法仍构造LegacySearchAdapter并完成同一小夹具，seed/预算/Adaptive参数映射不变。
- 实际GET /api/algorithms的ASGI响应200及CAABS schema，与Registry完全一致；只测试元数据路由，不启动Controller lifespan或提交运行，不声称网络/HTTP到正式发布全闭环。

WSL指定解释器 `/home/meteor/eos-course-runtime/venv/bin/python`，实际Python 3.10.12、Pydantic 2.14.1；Windows补充环境为Python 3.13.5、Pydantic 2.10.3。从 `/mnt/d/VC/EOS-Course-Project-i1` 执行下列模板，完整argv和环境以JSON回执为准：

```bash
PY=/home/meteor/eos-course-runtime/venv/bin/python
"$PY" -B -m unittest discover -s tests -p 'test_algorithm_registry_i1.py' -v
"$PY" -B -m unittest discover -s tests -p 'test_algorithm_conflict_beam.py' -v
# 另分别执行 test_adaptive_repair.py / test_transition_model.py / test_continuous_exposure.py
```

公共选择项实际为 test_system_v02.RegistryTests，以及 WorkerIpcTests 的 test_legacy_adapter_still_uses_engine_contract、test_legacy_start_normal_exit_and_event_sequence、test_real_spawn_runs_empty_test_scenario；通过将tests放入sys.path后用unittest.main显式执行，原始命令完整保留。真实spawn用既有空场景，只证明进程/IPC候选正常路径，不是实际曝光认证。

| 本轮项目WSL验收 | Run | PASS | FAIL/ERROR | SKIP | 退出码 |
|---|---:|---:|---:|---:|---:|
| I1新增专项，最终版本 | 17 | 17 | 0/0 | 0 | 0 |
| CAABS Core专项 | 48 | 48 | 0/0 | 0 | 0 |
| Adaptive Repair | 3 | 3 | 0/0 | 0 | 0 |
| Transition model | 4 | 4 | 0/0 | 0 | 0 |
| 公共连续曝光回归 | 15 | 14 | 0/0 | 1 | 0 |
| Registry/Worker选择回归 | 4 | 4 | 0/0 | 0 | 0 |
| 合计 | **91** | **90** | **0/0** | **1** | 各命令0 |

公共曝光SKIP是原有真实Orekit opt-in；没有开启真实场景重算或把跳过计为通过。基础算法版本仍0.1.0；没有运行完整默认测试套件或算法benchmark，不把这组有限回归写为全量PASS。

Windows补充结果：I1最终17项中16 PASS、1 SKIP（本机未安装FastAPI）；Core48、Adaptive3、Transition4均PASS，曝光14 PASS/1 SKIP。Windows实际复现的三个原始查询进程全部在修复后退出0。

保留的中间失败及限制：初版补充HTTP测试误引入环境没有的httpx，在WSL产生1 ERROR；已改用现有ASGI接口，不安装或增加依赖，最终WSL17项全部通过。Windows最初HTTP测试缺FastAPI；现在对缺少这一可选HTTP层的环境明确SKIP，不称HTTP已通过。Windows选定旧公共4项仍为1 PASS / 1 FAIL / 2 ERROR：一项无法导入缺FastAPI的test_system_v02，一项os.setsid在Windows不存在，一项POSIX Worker启动发failed而非started。未修改这些既有测试/Worker来掩盖平台限制；同四项在项目WSL全通过。初次失败日志未删除或覆盖。

## 4. 证据位置与可审核Diff

全部测试和原始日志在新临时/运行审核目录，不提交Git：

- Windows：`C:/Users/流星/AppData/Local/Temp/eos-i1-20261018-w189156x/`。preflight.json记录开始Git状态/解释器/关键文件SHA；before.json / after.json保存同三命令的完整输出/退出码。各windows-*.stdout/stderr及windows-tests.json保留原始尝试；windows-registry-final记录最终17项16通过/1跳过；review.diff含本次全部修改与新文件。
- WSL：`/home/meteor/eos-course-runtime/audits/i1-registry-20261018-20261017T164730054184Z/`。tests.json及每项receipt/stdout/stderr保存首次实际测试，registry-final.receipt.json及对应日志保存HTTP测试修正后的最终17/17，旧失败仍保留。目录名含任务日期和实际UTC创建时间，不混作客户端时区。
- 最终范围/SHA、Git status和diff --check回执位于Windows delivery_check.json；日志本机位置不假装可跨开发者移植。

审核者可在工作树用git diff查看tracked改动，并直接阅读两个新增Python文件；new文件未暂存，常规git diff --stat不会包含它们，不能据此漏审。

## 5. 影响范围、交付与剩余事项

生产源码：新增algorithms/solver_contracts.py；修改algorithms/conflict_beam.py一行import、eos_system/algorithm_registry.py。新增tests/test_algorithm_registry_i1.py。同步algorithm_integration.md、conflict_beam.md的有日期后续说明、COURSE_SETUP.md，并新增本文和 [独立PR草稿](caabs_i1_registry_pr_draft_20261018.md)。历史R1/I1记录不改写为“当时已登记”。

I2涉及的schedule_output.py、verification.py、Loader、ConstraintModel、连续认证、Controller、Worker、来源/发布门禁、SQLite模式和冻结场景均不修改。最终比较conflict_beam原文件与现文件，除指定import语句外内容相同；CAABS策略、canonical key和SafeConflictIndex没有接口以外改动。Registry能构造Solver不代表I2来源消歧或严格连续曝光已解决，不能据此获得成功保存/导出/回放或正式实验发布资格。

建议按I1限定范围审核该独立Diff；公共契约定义位置及登记元数据由李泽同确认集成影响，I2另行处理。全量回归、真实场景计划和正式认证均未由本轮证据覆盖。最终git diff --check退出0且无诊断，四个新增文件独立空白检查无诊断；14份受保护文件核对通过，迁移的三个定义及Registry其余类/函数AST一致。当前9个改动/新增文件、全部完整SHA及完整Diff已写入审核回执。停止等待人工审核；未执行git add、commit、push、merge、rebase或创建PR。
