# CAABS 阶段1：候选覆盖、排序和预算内初解

基线及环境见[阶段0](caabs_round1_baseline.md)。本阶段评分权重不变：完成数优先，其次公共ObjectiveModel，默认profit1。

## 机制

- 新增严格整数 `candidate_check_limit=16`（1–128），每父状态计入预筛选拒绝的尝试次数；`branch_limit=8`（范围不变）改为实际进入搜索的可行子节点上限，skip不计入。即使前缀冲突也可以继续检查尾部。该语义变化随版本0.3.0标识，旧语义可用check_limit=branch_limit进行机制对照。
- `candidate_diversity`轮换现有earliest/center/latest锚点，保留原窗口卫星/时域采样。它不增加新物理放置模式，不保证全部窗口或位置覆盖；可能损失某些早放置候选。
- `task_order=scarcity`用经过公共空计划构造核验的候选，按非空、不同卫星窗口机会数、卫星数、最晚受检开始时间、收益密度、ID排序。它是有界采样估计，不是完整可行机会数或动态剩余机会数。
- `greedy_incumbent`在相同solve预算内，从完整任务序列建立可行初解；仍按原rank决定是否保存。初解不进入主Beam的游标，避免污染去重语义。预备候选和初解耗时均计入RT，取消仍随checkpoint执行。
- 候选缓存只存在于一次solve的闭包；捕获同一problem/ConstraintModel/参数/证据域，不跨场景、跨约束或跨次solve复用，不缓存动态父计划可行性。无需对可变证据建立长期缓存身份。
- 新增prepared_tasks、candidate_cache_hits、candidate_checks、feasible_children、greedy_tasks_completed；正常结束stop_phase改为completed。
- 保留assignment、姿态、metadata安全深复制；保留公共ConstraintModel和Controller独立核验。

## 独立消融

[固定变体参数](caabs_round1/stage1_variants.json)、[原始数据](caabs_round1/stage1.json)、[CSV](caabs_round1/stage1.csv)、[完整指标表](caabs_round1/stage1.md)。
uniform/clustered/downlink×20/100/300×六变体，一次/格，共54组；相同seed41、2秒上限、相同约束和空外部初始模型；任务层面改变顺序的开销包含在预算内。子进程串行，交替算法运行次序。所有54组PUBLIC_PASS且未超预算；这不是统计显著性检验或物理认证。

| 任务数 | 旧版 | 仅检查预算分离 | 仅候选轮换 | 仅排序 | 仅贪心 | 全组合 |
|---|---:|---:|---:|---:|---:|---:|
|20|14.33|14.33|14.00|14.67|14.33|15.00|
|100|31.67|33.33|33.33|36.00|40.00|47.00|
|300|29.33|27.33|28.67|37.33|106.00|116.00|

取舍：候选预算扩大在300任务降低完成数，更多分支复制挤占后续任务；候选轮换在downlink20由10降为9。组合在小场景平均RT由0.190增至0.256秒，100任务由1.303增至1.374秒，300任务由1.908增至1.951秒，不能宣称提速。组合TP/TM平均改善，但尚需重复实验和其他分布；单独预算分离在小场景BD由0.9046降至0.8947。

此时排序、贪心及轮换仍是可消融开关，尚未根据这一次结果冻结最终默认配置。第二阶段优先处理已测出的完整键/评分开销，后续再决定默认方案。

专项57/57通过，0跳过，1.031秒；新增六项覆盖候选尾部、检查/子节点上限、模式轮换、公共可行性排序、预算内完整incumbent、跨solve证据失效及严格参数。原分支隔离、去重、取消、预算测试保留。

```powershell
python -B scripts/benchmark_caabs.py --output output/caabs/stage1 --variants docs/phase2/algorithms/caabs_round1/stage1_variants.json --budget 2 --repeats 1
python -B scripts/report_caabs.py --inputs output/caabs/stage1 --output docs/phase2/algorithms/caabs_round1 --stem stage1
```
