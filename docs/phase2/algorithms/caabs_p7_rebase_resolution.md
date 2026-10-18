# CAABS P7 Rebase 冲突解决记录（2026-10-19）

唯一工作树`D:/VC/EOS-Course-Project-caabs-latest`，分支`feat/caabs-hardening-20261018`。备份`backup/caabs-pre-rebase-4f6cd37`保留原HEAD `4f6cd37d870d4ef3e0a3767f535c8178f561c07e`，目标`2d8a808c58334dd5c6c085e9753bbd5aa86eced1`（PR #24）。初始实查为暂停在be92f1d、剩11提交，只有continuous_exposure未合并；未重新发起rebase、skip、abort、reset或选择整个ours/theirs。

## 三处实际冲突

| 重放提交/文件 | 双方意图与最终合并 | 当时针对性检查 |
|---|---|---|
| be92f1d / utils/continuous_exposure.py | main的fresh标志选择共享数据的LF规范物理源码指纹，不是缓存；CAABS开发合同必须校验真实场景、Raw、任务、生成器、部署及数据。保留fresh=False和后续fresh赋值/分支，在读侧车前保留capture_development_provenance失败即不可信。两条来源路径不互相降级。 | AST；曝光15（14通过/1真实物理opt-in未开）、真实开发来源8/8、共享8/8、隔离预览5/5，均退出0；日志conflict-be92。最终全量全部opt-in已开、无跳过。 |
| 3f2cff0 / eos_system/planning_preview.py | main已把核验移到独立子进程并复制、校验数据包；旧CAABS变更只让原本直连的Auditor读环境ZIP。保留main的data_path参数及隔离进程/回收，环境ZIP选择已由父进程实现；清理重复os导入。Worker延迟重导入、取消ACK、JVM主线程约束照常保留。 | AST；preview_process5、planning_preview2、worker_runtime2全部通过，退出0；conflict-3f2。 |
| 0b9f48d / tests/test_experiments.py | 双方都要求新物理源码不得套用历史展示层兼容例外。保留main对当前/两个历史摘要的参数化拒绝测试，再保留CAABS对历史pair互认正例以及切回当前源码的409负例；不改生产兼容白名单、不改旧实验。 | experiments12全通过；recompute45中44通过/1真实物理opt-in未开，退出0；conflict-0b9。后续全量真实重计算亦实际运行。 |

每次均先读完整函数/当前patch、测试后仅add解决文件并continue。第三次continue重放其余提交成功，Rebase结束HEAD `eb3b21eb18a8ba3c8c9eb9efb863f9314b76d3de`，15个提交全部保留。

## 原15提交映射

| 原SHA | 新SHA | range-diff |
|---|---|---|
| 8cf282b | 552cf5b | = |
| 7025151 | 3f696e8 | = |
| ee7d0e2 | c2e5943 | !，window_physics_sources新增使hunk上下文变化 |
| be92f1d | 48ea591 | !，保留fresh及开发合同 |
| 3f2cff0 | 2cc671f | !，上游独立进程已涵盖环境ZIP选择 |
| aa7a9b7 | 0bb7762 | !，main新增engineering exporter使import上下文变化 |
| 0b9f48d | e2495cc | !，双方实验兼容正负例并存 |
| c5090ba | a6b2167 | = |
| f1a8432 | d083ae3 | = |
| 78d07c4 | 882d683 | = |
| 11de4ce | 5d0efe8 | = |
| 4d2ff79 | 1619771 | = |
| 9336aae | a650d12 | = |
| 37cbaf6 | 534ab9e | = |
| 4f6cd37 | eb3b21e | = |

执行了任务指定的`git range-diff ba114dd..backup/caabs-pre-rebase-4f6cd37 origin/main..HEAD`；原15条一一对应，10条patch相同、5条需要查看上下文/合并，没有删除/丢失/skip。纯15条的结果另冻结在`range-diff-original-15.txt`，后续P7修复是额外提交，不假冒重放等价。CAABS核心与备份分支`git diff ... -- algorithms/conflict_beam.py`为空；50项核心测试保留。

## Rebase后发现并实际修复的独立问题

1. Windows autocrlf把冻结数值fixture变成CRLF；工作字节SHA变5b23b153…，Git blob仍是原edbb4787…，曝光两个真实测试失败。新增.gitattributes的精确LF规则，恢复Git原blob字节，**不更改冻结SHA或物理期望值**。原历史运行/场景不变。
2. main的窗口物理闭包只含visibility/time_parsing，新增相对姿态依赖却在attitude_frames。临时副本修改该文件仍得到相同摘要，负例失败。v2闭包加入attitude_frames，继续保留完整部署source_identity检查；旧v1不能自动追认。独立预览进程入口也加入完整部署身份。
3. 开发侧车错误generator_version被接受；JSON数组触发AttributeError；缺侧车的带开发声明场景经来源入口降级Legacy。先保存真实/纯负例失败，再加入版本、对象结构、窗口记录检查，并对三种执行模式禁止缺侧车降级。截断/符号链接/Raw及SHA篡改仍拒绝。
4. main的Console只有隐藏physical_validation选项，开发合同只允许planning_preview。真实HTML的Chromium反例确认无法明确选择。仅含开发限定场景的目录显示预览选择，默认工程模式与三工作区保留；用户必须明确选预览，未授权模式不能提交，后端仍独立拒绝。没有添加正式资格。
5. DrvFS定向停机测试在VERIFYING只等4秒而非Controller已有30秒期限。原13项1失败；额外3次均失败，线程栈在Storage.finish_success的源码SHA读盘。分成Worker里程碑和验证完成两阶段等待，并新增WORKER_REAP早于VERIFYING的顺序断言；生产预算/超时不改。修复后3次重复和13项全部通过。

新main的共享数据生成器、数据规格/splits、三工作区、HTTP、工程结果导出和独立Preview进程均未被旧实现覆盖。正式连续认证依然INCONCLUSIVE；详见[完整P7验收](caabs_p7_integration_acceptance.md)与[Draft PR材料](caabs_p7_draft_pr.md)。本轮未push、建PR、merge或更改其他worktree，用户任务书一直未跟踪。
