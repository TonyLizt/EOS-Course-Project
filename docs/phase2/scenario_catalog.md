# 统一场景目录与使用方式

原始卫星输入位于`input/`；它们只有轨道记录，不是可运行的调度场景。新Canonical JSON仅位于`data/scenarios/eos-v1/`，Legacy留在`experiments/scenarios/`并由`data/scenarios/eos-v1/legacy/index.json`只读索引。归档ZIP和全组旧交付包保持原样。冻结final_test没有进入本轮生成、训练或验证。

新场景的原始输入SHA、生成器版本/实际代码SHA、Git提交、种子、时间跨度、物理合同和血缘写入`provenance.json`。`validation.json`记录结构检查与0.05秒选定完整曝光采样；不声称连续认证。`characterization.json`统计实际源区间的候选机会、重叠、卫星集合交集及容量压力。`quarantine.json`明确记录生成试验失败或难度定义错误，不删除试验数据。

## 统一入口

`eos_system.dataset_registry`在Web、API、CLI和矩阵工具中共用安全发现/解析。它返回同一场景ID及SHA；提交时再次校验SHA。元数据JSON不会被当成场景。Canonical目录自动尝试登记为`canonical-eos-v1`数据源；同路径已有来源时复用其ID。显式`EOS_SCENARIO_DIR`指向Canonical的新数据库可能只使用`runtime`，实际ID查询`GET /api/data-sources`，既有来源仍可使用。

无显式场景环境变量且Canonical数据已经建成时，新默认入口采用Canonical目录。旧CLI和旧目录API保留。新的统一Benchmark CLI使用以下矩阵命令，沿用公共API、Controller、独立Worker和独立Verifier，支持当前注册表中的全部比较算法；初始模型角色另外在清单中记录。

```bash
python -B scripts/audit_scenario_assets.py --output /path/to/new-asset-audit.json
python -B scripts/generate_scenarios.py             # 五个指定代表规模
python -B scripts/generate_scenarios.py --all       # 按固定96实例计划续跑
python -B scripts/generate_narrow_scenarios.py       # 三份父场景的窄窗口子集
python -B scripts/plot_scenario_difficulty.py        # 完整96实例的统计及图表
python -B scripts/validate_scenarios.py index
python -B scripts/validate_scenarios.py list --satellites 20 --difficulty high_conflict
python -B scripts/validate_scenarios.py list --scale S8 --tasks 200
python -B main_scheduler.py --canonical list --scale S8
python -B main_scheduler.py --canonical matrix --budget 5 --workers 2
python -B scripts/train_canonical_models.py --episodes 100
python -B scripts/install_canonical_models.py --report experiments/runs/eos-v1/model-installation.json
python -B scripts/validate_scenarios.py matrix --budget 5 --workers 2 \
  --orekit-data /path/to/orekit-data.zip --output experiments/runs/eos-v1/matrix.json
python -B scripts/validate_canonical_initial_models.py \
  --orekit-data /path/to/orekit-data.zip --output experiments/runs/eos-v1/initial-models-full.json
python -B scripts/report_scenario_dataset.py --matrix experiments/runs/eos-v1/matrix-full.json
python -B scripts/verify_dataset_preservation.py
```

`index`同时复查公共Loader、计数、来源镜像和清单SHA；拒绝失配和重复ID。矩阵可限定`--scenario-ids`或`--limit`执行批次，保留预期与未执行数量；再次执行同一命令续跑。算法清单动态读取，不通过忽略不可用算法制造通过。每种算法/目标单独提交，错误不会阻断其余算法的失败记录。

API支持`GET /api/scenarios?source_id=canonical-eos-v1&satellite_count=20&task_count=40&difficulty_profile=high_conflict&scale=S4`；Web在同一个数据源里读取这些实例，并提供相同四个字段的组合筛选。清除筛选可恢复全部场景，筛选为空时不能提交；旧来源缺少规模字段时仍能使用。

该API示例以已登记`canonical-eos-v1`为前提；若来源复用为`runtime`，相应改用`source_id=runtime`。场景ID、SHA和筛选规则不变，数据源别名不作为跨数据库的固定契约。

网页算法列表直接保留后端Registry全部条目，移除旧交付界面按ID隐藏MIP的规则。不可用算法仍显示后端原因并禁用，矩阵不会因不可用而跳过。

当前可用103个实例：96核心、4个保留的r2试验、3个窄窗口子实例。6个早期失败/难度定义错误试验保留在原位，由quarantine明确排除。不得把r2修订和窄窗口父子关系当成独立核心种子；训练/测试分组还应参考Manifest的lineage_equivalence_group。每实例validation.json是生成时证据快照，full_matrix_status=PENDING不会被回写；当前算法/目标验收状态查统一Manifest和矩阵。

## 模型和结果

本轮新增模型ID为`ppo-eos-v1-dev-20261023`、`lavis-eos-v1-dev-20261023`，保存在`experiments/runs/eos-v1/models/`，不覆盖旧权重。两者在3个明确的r2训练源上实际训练；它们是开发兼容性模型。PPO使用原训练函数100轮；LAVIS使用原特征、候选和续排标签协议。R1适配器仍负责将公共TP/TCR目标与训练目标分别记录。

启动Web时可显式设置`EOS_RUNTIME_DIR`为项目下的`experiments/runs/eos-v1`，从而使用此处的新模型和数据库；也可使用上面的安装器将这两个不可变新ID登记到现有运行目录，保留旧数据库。安装器只接受同ID同字节或不存在的新目录，校验既有工件未变；可用`--runtime /path/to/runtime`指定目标。选择Nadir场景时应选用这两个新ID；旧模型的物理域限制仍生效，不能编辑旧manifest放行。当前会话已经将新ID安装到默认WSL运行目录，重启Web服务后可刷新目录。

矩阵成功只计实际执行并通过独立核验的记录。空计划、预算耗尽但返回可行计划、硬超时、模型缺失、场景域不兼容、物理核验失败和接口错误分开报告。`solver_diagnostics`是求解器遥测，不能作为物理证据。工程采样通过不是严格连续区间认证。

比较算法从list_algorithms动态读取；completion_first/adaptive_repair按初始模型角色单列验证。默认纯FCFS/SJF等六种基础策略保留队列语义，公共权重用于同任务同开始时刻的可行放置择优及统一评价，不声称全局TP/TCR搜索。

矩阵追加保存同名`.jsonl`及`.progress.json`；JSON每约5分钟检查点落盘，正常退出和受控退出再输出完整JSON/CSV。中断后用相同路径、源码和模型ID续跑，已终态记录默认不重做。`--retry-failed`显式保留attempt_history后重试失败；不要用反复重试删除预算失败。读取实时进度时，进度文件可能领先JSON；续跑严格核对journal身份和完整性，不能忽略损坏记录。

矩阵采用跨场景滚动提交，`--submission-window 24`限制未终态提交总数（允许1至24），Worker并发仍由`--workers`单独限制为1至8。不会等同一目标批次的最后一个超时算法才提交下一场景；单次请求、预算、算法和物理核验保持不变。旧终态不自动重试；续跑时也检查场景SHA、目标权重和预算，条件改变应使用新结果文件。

最终可运行`python -B scripts/audit_canonical_matrix.py`独立检查3914组合覆盖、输入SHA、公开约束、目标、实际模型工件与核验receipt。规范CSV/JSON为`experiments/runs/eos-v1/compatibility_matrix`，原harness字段和失败记录同时保留；ALGORITHM_TIMEOUT未进入物理核验，规范verification_status为NOT_RUN，不宣称物理谓词失败。审计未完成矩阵时须显式加`--allow-partial`，不能将其当成最终全量验收。

Linux物理执行使用项目已安装的Orekit/JVM环境及可读的orekit-data.zip。Windows工作区仍为唯一场景数据源；运行源码快照和数据库可放在WSL本地以降低挂载I/O。全量矩阵使用受控并发4→8、每轮5秒，前后RT不能当成同并发性能排名。来源、日志、执行快照摘要与并发切换零活动运行证据位于experiments/runs/eos-v1。

建设进度、完整场景清单与实际矩阵结果见`scenario_dataset_build_report.md`及`data/registry/`。

## 查看本轮归档实验

全量执行结束后，SQLite通过在线备份保存在`experiments/runs/eos-v1/fast-runtime/`，附带新模型和回放资源；没有覆盖默认运行目录的历史数据库。归档清单记录SQLite完整性检查与文件SHA。数据库还保留38次滚动提交试跑、两次单并发诊断及一条已完成恢复记录，不能将其行数误当成主矩阵组合数。

在已安装项目依赖的WSL Python环境中，从项目根目录启动：

```bash
export EOS_RUNTIME_DIR="$PWD/experiments/runs/eos-v1/fast-runtime"
export EOS_SCENARIO_DIR="$PWD/data/scenarios/eos-v1"
export EOS_OREKIT_DATA="$PWD/utils/orekit-data.zip"
python -m eos_system
# 默认打开 http://127.0.0.1:8765/
```

常规开发继续使用原运行目录即可；新模型已安装到本会话默认WSL运行目录。两个并发FAILED各做了一次相同请求条件的单并发诊断并通过，原并发矩阵仍记FAILED；并发可靠性根因未根治，不能据此写成全算法全部通过。106次MIP超时没有加预算重试。
