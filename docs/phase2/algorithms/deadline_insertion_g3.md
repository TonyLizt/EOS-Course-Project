# DARTIS G3 最小离线对照与可信场景依赖（2026-10-18）

## 结论与范围

- **G3：PENDING。** DARTIS-LLF、DARTIS-EDF、Greedy `completion_first`、RABAS 已在同一 legacy 派生场景完成可复现的 Solver 候选与公共离散回放；CAABS 因窗口来源验证未通过而**不可比较**，不能把空计划的 0/30 当作算法质量结果。
- 本记录不声称运行了真实 Orekit planning preview、正式连续物理认证或 Controller/SQLite 正式提交。本次离线脚本不调用 HTTP/Worker，G2 的真实 HTTP/Worker 生命周期证据见 [DARTIS 专题记录](deadline_insertion.md)。
- 五算法有效对照的剩余输入依赖是团队提供真实生成且带匹配来源证据的同版本场景。当前缺口不是 DARTIS 求解器失败；不得伪造 grid_v2/v3 记录、关闭 CAABS 门禁或将 legacy 与修复物理版本混排。

## 环境、输入与统一配置

| 项 | 本次实际值 |
|---|---|
| Git HEAD | `036317f5357500b35d8ad1bd4faae92cbf1fb249` |
| 环境 | WSL2 Ubuntu 22.04；Python 3.10.12；`PYTHONHASHSEED=0` |
| 只读母文件 | `/mnt/f/EOS-Bench/output_s1/Sats1_M100_T7d_dist0.json` |
| 母文件 SHA-256 | `b61f4de708894f0bc30b6e0614aafc2ac9340880306ed0617fdc50cf492d198a`，运行前后相同 |
| 临时派生 | `split_scenario_file`：30 任务、起点 0h、时长 24h、拆分 seed 20260927；1 星、37 窗口 |
| 本次派生 SHA-256 | `3c3b777271ebfff8a820f2c56875ed4412832dd2ae929a0de1bf9ac05b43d962` |
| 统一搜索配置 | `execution_mode=planning_preview`、`placement_mode=earliest`、`schedule_model=completion_first`、seed 42、每算法 5 s 请求预算、默认 `ConstraintOptions` |
| 统一目标权重 | `w_profit=1, w_completion=0, w_timeliness=0, w_balance=0` |
| 算法参数 | DARTIS-LLF：`priority_mode=llf`；DARTIS-EDF：`priority_mode=edf`；Greedy、RABAS、CAABS：各注册表默认值 |

所有变体分别通过 `RunConfig → runner.prepare() → Solver.solve()` 运行，候选转换成标准计划结构。脚本以新加载的场景，调用与 Controller 相同的来源校验、`SourceWindowIndex.restore`、`candidate_exposure`、`ConstraintModel.is_feasible_assignment` 和 `compute_evaluation_metrics` 入口独立离散回放。它没有 Controller 的外部硬超时与正式事务，因此表中 RT 是一次 Solver 墙钟测量，**不是生产正式指标**。

历史首次探针使用相同母文件，但其派生 SHA 为 `c405f7f23a8c34cd4c76ac3ceac79b90dec75610fb45d671dec59df9115c2da9`，完整派生选项未留成可执行脚本；原数值保留在 [先前探针记录](deadline_insertion.md)。本次以新脚本及本节派生 SHA 为可复现基准，**不把两个不同 SHA 的结果合并统计**。

## 实际结果

下面是设置 `PYTHONHASHSEED=0` 后一次完整复跑；相同命令重复两次，派生 SHA、完成数、TCR、TP、TM、DARTIS 截断统计及 CAABS 拒绝原因一致，RT 有正常墙钟波动。

| 变体（版本） | Solver 候选完成数 | 离线 TCR | 离线 TP | 离线 TM | Solver RT s | 来源与公共离散回放 | 候选截断统计 | 结果 |
|---|---:|---:|---:|---:|---:|---|---|---|
| DARTIS-LLF `0.1.0` | 24/30 | 0.800 | 128 | 0.608835 | 0.682396 | PASS | 窗口 0；位置 61,378；大网格 0 | 正常返回；full 重算 24 次 |
| DARTIS-EDF `0.1.0` | 24/30 | 0.800 | 128 | 0.543262 | 0.457995 | PASS | 窗口 0；位置 41,046；大网格 0 | 正常返回；full 重算 24 次 |
| Greedy `completion_first` `baseline-1` | 24/30 | 0.800 | 128 | 0.586764 | 0.085392 | PASS | 未暴露统一截断计数 | 正常返回 |
| RABAS `1.0.0` | 24/30 | 0.800 | 128 | 0.628293 | 0.539813 | PASS | 未暴露统一截断计数 | 正常返回 |
| CAABS `0.1.0` | 空计划 0/30 | **不可比较** | **不可比较** | **不可比较** | 0.000406 | 仅空计划结构回放 PASS | 构造器调用 0；截断不适用 | **来源验证未通过** |

DARTIS 的「位置截断」是各轮受限搜索跳过位置的**累计计数**，不是不重复的物理机会数。Greedy/RABAS 未暴露相同口径的统计，表内「未暴露」不能解读为 0。五种配置均正常返回，但 CAABS 在构造候选前被来源门禁挡住；37/37 窗口为 `INCONCLUSIVE/UNTRUSTED_WINDOW_PROVENANCE`，所以不计算它在本场景的算法质量排名。本场景只有 1 星，也未独立统计真实冲突程度；不能替代优先要求的 2–3 星冲突场景。

没有固定 `PYTHONHASHSEED` 的先期复跑中，Greedy 的 TM 曾跨进程变化；固定为 0 后两次复跑一致。本记录不推断该差异的内部根因，也不修改 Greedy。

**结果层级：**

1. **Solver 原始候选**：上表完成数、RT、DARTIS 搜索统计。
2. **来源与公共离散约束回放**：四个非空候选 PASS；CAABS 仅空计划结构 PASS，窗口来源门禁失败。
3. **Orekit planning preview**：NOT_RUN。当前虚拟环境缺 `orekit_jpype`/`jpype`。
4. **正式连续物理认证**：NOT_RUN；无生产认证收据、无正式计划或 SQLite 成绩。

## 可信场景排查与机制

[CAABS](../../../algorithms/conflict_beam.py)直接以 `planning_window()` 过滤每个机会；[窗口来源函数](../../../utils/continuous_exposure.py)要求与原场景 SHA、窗口算法版本和来源源码身份匹配的生成记录。[其他算法使用的预览入口](../../../schedulers/preview_exposure.py)允许 legacy 窗口作为标明限制的离线预览，因此本场景只能提供四算法的离散对照。

仓库 `experiments/scenarios` 的小/中场景实体仍为 Git LFS 指针；已有 `epoch_fixed_v1` 侧车不包含可满足当前 grid_v2/v3 门禁的完整窗口生成证据。只读检查母数据 `/mnt/f/EOS-Bench/output_s3/Sats3_M200_T7d_dist0.json`（SHA-256 `7aa6e152163a4484841c45fd2f181ec914db2b622396fe153a187badd05cc272`）发现 3 星、200 任务的 **5,508/5,508** 窗口也返回 `UNTRUSTED_WINDOW_PROVENANCE`。把它拆成 10–30 任务不会生成缺失的物理来源证据。文档引用的四份 grid_v2 候选位于另一环境 `/home/meteor`，本机不可读取。

DARTIS 的 LLF/EDF 排序键分别以受检松弛度/窗口截止期为首键；[A-4 反例](../../../tests/test_algorithm_deadline_insertion.py)验证首选任务不同，动态最早开始时间反例验证插入后重新评估。本场景两者完成数相同、TM 和累计受检位置数不同；不宣称 DARTIS 必然优于基线。

## 可复现命令与回归

在项目根目录执行；脚本只读母文件，派生场景只写入自动清理的 `TemporaryDirectory`，JSON 结果写到 stdout，拆分日志写到 stderr。它不写 SQLite、正式结果目录或 EOS-Bench 母数据。

```bash
cd /home/mint/projects/EOS-Course-Project
PY=/home/mint/eos-course-runtime/.venv/bin/python
PYTHONHASHSEED=0 "$PY" -m experiments.dartis_g3_probe \
  --source /mnt/f/EOS-Bench/output_s1/Sats1_M100_T7d_dist0.json \
  --expected-source-sha b61f4de708894f0bc30b6e0614aafc2ac9340880306ed0617fdc50cf492d198a \
  > /tmp/dartis-g3-offline.json
git diff --check
```

本轮相关专项 10 个测试模块共 **173 项：171 通过、2 跳过、0 失败**。跳过原因分别是小场景 LFS 实体缺失和需显式启用的真实 Orekit 曝光测试。复跑命令：

```bash
for p in test_algorithm_deadline_insertion.py test_dartis_integration.py \
  test_nine_algorithms.py test_algorithm_registry_i1.py \
  test_algorithm_auction_bundle.py test_algorithm_conflict_beam.py \
  test_rabas_integration.py test_source_window_identity.py \
  test_continuous_exposure.py test_planning_preview.py; do
  "$PY" -m unittest discover -s tests -p "$p" -q
done
```

## 后续依赖与 PR 表述

五算法有效 G3 对照仍需团队提供可读取的真实生成场景及匹配来源证据，优先 2–3 星、10–30 任务且已确认存在冲突；同时记录场景 SHA、物理版本、窗口生成源码身份和统一核验环境。拿到该输入后沿用同 seed、预算、目标与约束复跑，不改 CAABS 的来源准入。

**算法 A 的 G1/G2 实现及本次四算法离线证据可进入 PR 代码审查。** 若团队把五算法可信同场景结果列为 PR 合并或 G3 最终验收硬条件，该项仍是**外部场景依赖，状态 PENDING**；不能把当前文档称为完整五算法 G3 PASS，也不能归为 DARTIS 搜索逻辑失败。
