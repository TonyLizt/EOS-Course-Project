# 第一阶段：运行 EOS-Bench 与自定义算法

本目录是官方 EOS-Bench 提交 `ee282656e8b2f6fd0d3cf84677b40966e2780ef3` 的独立 Git 工作树，分支为 `codex/course-project`。原始仓库在 `/Users/tonylizt/Projects/EOS-Bench`，数据集在 `/Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data`。准备脚本只读取数据集，所有派生实例、计划和日志均写在本目录的 `output/`。

## 环境

官方 README 建议 Python 3.10+、Java 17，并列出 `orekit-jpype`、`jpype1`、`numpy`、`pandas`、`matplotlib`、`scipy`、`pulp`、`torch`。本阶段读取预计算场景并运行两个启发式算法，只需 `requirements-course.txt` 中的三个包。场景重新生成需要 Java/Orekit；MIP 需要 PuLP；PPO 需要 PyTorch。本机系统 `python3` 是 3.9，不适合此仓库；本次使用 Codex 附带的 Python 3.12。

可在有 Python 3.10+ 的环境中这样准备：

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-course.txt
```

本机现有 `.venv` 使用附带的 Python 3.12 创建，含可用的 NumPy、Matplotlib、ijson；可直接运行以下命令。

## 官方 README 的完整流程与本项目的输入输出

| 阶段 | 官方入口 | 读入 | 写出 | 本次是否执行 |
|---|---|---|---|---|
| 生成场景 | `main_generate.py` | `input/` 中的卫星配置、目标配置，或随机任务参数 | `output/Scenario_*.json`、场景汇总 | 否；已下载预计算场景 |
| 切分母场景 | `input/scenario_splitter.py` | 下载数据集中的 7 天场景 JSON | 较短规划期的场景 JSON | 是；由 `prepare_first_step.py` 调用，写到本项目 `output/` |
| 难度分析 | `Characterisation/analyze_combined_conflict.py` | 场景 JSON | 冲突指标报告和 Excel | 否；官方 README 将其列为可选分析步骤 |
| 调度与评估 | `main_scheduler.py` | `output/` 下所有 `Scenario_*.json`；算法名及参数 | `output/schedules/` 中的计划 JSON、甘特图 PNG、`runlog_batch_*.txt`；PPO 模型写到 `output/models/` | 是；运行两个启发式算法 |
| 三维展示 | `main_draw.py` | 一个场景 JSON、可选的计划 JSON | `draw/orbit.czml`，并启动本地 Cesium 页面 | 否；已有甘特图，需要展示时再运行 |

官方 README 给了两种使用方式：终端传参，或编辑脚本末尾的默认配置后直接运行。我们现在用终端传参，输入仍遵循官方 `SchedulingProblem → ConstraintModel → Schedule → 指标和输出` 流程。下载数据集不在代码仓库内；本项目仅从 `/Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data` 读取两个母场景。该数据集不需要搬进 `output/`，也没有被修改。

## 重现这次小实验

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
.venv/bin/python prepare_first_step.py --data-root /Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data --seed 20260927
PYTHONHASHSEED=0 MPLBACKEND=Agg .venv/bin/python main_scheduler.py --algos completion_first pressure_repair --workers_other 1
.venv/bin/python verify_schedules.py output/Scenario_S2_Sats1_M30_T1d_dist0_seed20260927.json output/schedules/scheduler_Scenario_S2_Sats1_M30_T1d_dist0_seed20260927_c2_*.json
.venv/bin/python verify_schedules.py output/Scenario_S3_Sats3_M60_T1d_dist0_seed20260927.json output/schedules/scheduler_Scenario_S3_Sats3_M60_T1d_dist0_seed20260927_c2_*.json
```

`main_scheduler.py` 会递归扫描 `output/` 中所有 `Scenario_*.json`；若以后添加更多实例，上述调度命令会一起运行它们。输出计划与甘特图在 `output/schedules/`，最新运行表为 `runlog_batch_*.txt`。`output/` 和 `.venv/` 被 Git 忽略。

## 数据来源与修复后实测

两个源文件分别为 `output_s1/Sats1_M100_T7d_dist0.json` 和 `output_s3/Sats3_M200_T7d_dist0.json`。SHA-256 分别为 `b61f4de708894f0bc30b6e0614aafc2ac9340880306ed0617fdc50cf492d198a` 和 `7aa6e152163a4484841c45fd2f181ec914db2b622396fe153a187badd05cc272`。切分参数是从起点开始 24 小时、30/60 个任务、种子 20260927；这是从母场景派生的课程小实例，不是论文公布的原始实验集合。

| 实例 | 算法 | TP | TCR | BD | TM | RT（秒） |
|---|---|---:|---:|---:|---:|---:|
| 1 星 / 30 任务 | completion_first | 128 | 0.800 | 1.000 | 0.587 | 0.017 |
| 1 星 / 30 任务 | pressure_repair | 128 | 0.800 | 1.000 | 0.556 | 0.011 |
| 3 星 / 60 任务 | completion_first | 336 | 0.917 | 0.769 | 0.369 | 0.092 |
| 3 星 / 60 任务 | pressure_repair | 336 | 0.917 | 0.695 | 0.304 | 0.051 |

`pressure_repair` 是本项目的初版算法：按窗口稀缺度和重叠压力安排任务，优先选择占用较少其他任务机会的候选位置，再有限次尝试移出一项任务并重插。每次加入任务都调用共享的 `ConstraintModel`。`verify_schedules.py` 检查了四份计划的任务唯一性、窗口包含关系、共享约束模型可行性、TCR，以及敏捷卫星的姿态角转向是否成功解析。两个小实例里它没有提高完成率；TM 与 RT 的差异只是一次运行的结果，不能据此证明稳定优势。下一阶段应在更多实例和多个种子上比较，并做压力排序、修复步骤的消融。

**转向约束修复记录：** 官方提交的姿态提取函数不识别本数据的 `pitch_angles/yaw_angles/roll_angles`，原计划的同星相邻任务因此全部使用 11.66 秒回退值；`ConstraintModel.__init__` 还漏存了转向参数。本分支已同时修复这两个问题，对基线和自定义算法统一生效。修复前的场景、计划与日志保存在 `output_original_fallback/`；修复后的结果在 `output/`，两个文件夹不可混合作为同一模型的实验。两个版本的派生场景 SHA-256 完全一致。当前四份计划分别有 23、23、52、52 个敏捷相邻转向，这些转向角全部成功解析；旧计划在修复后的模型下已有不合规项。`tests/test_transition_model.py` 覆盖字段解析以及敏捷、非敏捷转向参数。

## TCR 优先算法实验

论文对齐的**配置**是 3 颗敏捷卫星、200 个任务、24 小时、Standard-Agility，并分别测试全球随机（`dist0`）和区域聚集（`dist1`）。比较官方 Greedy-TCR、SA-TCR、GA-TCR、ACO-TCR 与本项目的 `adaptive_repair`；MIP-TCR 可在安装 PuLP 后作为限时参考。全部方法在同一个派生 JSON 上使用相同的 `ConstraintModel`、`earliest` 放置模式、下传比率 1、完成率目标及确定的随机种子。TCR/完成数是首要指标，TP、BD、TM、RT 一并记录。Greedy 与新算法有自身的隐含完成率优先规则；SA/GA/ACO/MIP 使用权重 `(TP=0,TCR=1,TM=0,BD=0)`。

`algorithms/adaptive_repair.py` 先跨全部可用窗口分配候选名额，再动态统计当前可行位置数，优先排入位置最稀缺的任务；之后用最多两层的挪位增广链和局部取出重排（ALNS）寻找能增加完成数的安排。其目标按完成数、TP、提前执行时间作字典序比较，并对每一次插入调用共享约束模型。`tests/test_adaptive_repair.py` 覆盖窗口多样性、挪位重插与完整计划可行性。

只读母场景分别为数据集的 `output_s3/Sats3_M200_T7d_dist0.json` 和 `output_s3/Sats3_M200_T7d_dist1.json`。实验入口 `experiments/tcr_study.py` 将派生场景、计划、甘特图、`manifest.json`（源与派生文件 SHA-256）和 `results.csv` 统一写入 `output/experiments/tcr_study/`；每份计划另用 `verify_schedules.py` 回放。先跑论文配置下的首个 24 小时片段：

```bash
cd /Users/tonylizt/Projects/EOS-Course-Project
.venv/bin/python -m experiments.tcr_study \
  --data-root /Users/tonylizt/Documents/3rd/操作系统原理课程设计/EOS-Bench-data \
  --offsets 0
```

需要扩展到多个时间片时，可使用 `--offsets 0 16 32 48 64 80 96 112 128 144`；`--prepare-only` 只切分场景，`--run-only` 只运行已切分场景，`--algos` 可指定算法；更新某算法已有结果时加 `--rerun --algos adaptive_repair`。`--run-only` 会核对清单中的场景哈希与种子，防止误用不同实例。**这些时间片源自同一份 7 天母场景且部分重叠，不是论文中由独立目标子集生成的十个实例。** 因此论文 Excel 的统计结果只作为配置和趋势参考；严格的性能比较是所有算法在本实验同一份派生实例上的成对对比。运行前确认没有把修复前后的转向模型结果混在一起。MIP 不在默认算法列表中，需另装 PuLP；限时未证最优时不得标为全局最优。

### 首轮成对结果（2026-09-28）

本轮的独立实验记录（文件变更、命令、输入输出、全部指标和限制）见 `experiments/reports/2026-09-28_tcr_pilot.md`。

每格为 **完成任务数 / 200**。同一行的所有算法使用同一份派生场景、相同转向约束和相同完成率目标，均通过计划回放验证。`0h` 与 `48h` 是不重叠的两个时间片，但同分布的时间片仍来自同一母场景，不能视为独立论文重复实验。

| 分布 / 起点 | Greedy-TCR | SA-TCR | GA-TCR | ACO-TCR | adaptive_repair |
|---|---:|---:|---:|---:|---:|
| 全球随机 / 0h | 183 | 187 | 184 | 187 | **187** |
| 区域聚集 / 0h | 150 | 172 | 156 | 171 | **175** |
| 全球随机 / 48h | 188 | 192 | 191 | 192 | **192** |
| 区域聚集 / 48h | 141 | 165 | 148 | 158 | **168** |

全量指标与各次运行时间见 `output/experiments/tcr_study/results.csv`。这些是算法默认迭代参数下的首轮效果，**没有对各算法施加相同计算时间上限**；不能据此声称运行时间或统计显著性占优。MIP 未运行，因为当前精简环境未装 PuLP。

在区域聚集 / 0h 场景，用实验相同的算法种子 `20260928` 做消融：静态稀缺构造 173，启用动态稀缺构造 175，再加增广链仍为 175，完整 ALNS 也为 175。ALNS 对次级 TP/时序质量有改进，但该场景完成数的增量来自动态构造；增广链的重插机制另有单元测试验证。下一轮应在更多独立实例上检查修复模块的收益与随机种子敏感性。
