# CAABS 阶段2：精确增量状态身份与目标

依据[阶段0](caabs_round1_baseline.md)的Profile，本阶段保留安全深复制，减少完整规范键和评分的重复计算；没有改公共约束、候选来源、Runner计时或评分权重。

## 机制与正确性边界

- `incremental_keys`：每任务每候选计算一次完整、类型敏感、包含姿态/下传/资源的canonical_assignment_key。新状态对父状态排序键执行二分插入；仍使用精确元组相等性去重，没有哈希碰撞丢状态风险。
- `(task_index, canonical_key)`不变。排序在一次solve内固定，skip游标不丢失；贪心初解只作为incumbent，不加入主Beam。
- assignment、sat_angles和metadata仍由原clone_schedule/branch_schedule独立复制。公共ConstraintModel只读检查候选，deepcopy不改变原始规范语义，因此可以复用精确键。没有共享可变assignment来换取速度。
- `incremental_objective`独立可消融。累积收益、等待秒数和卫星负载，保留原权重与截断；BD仍调用公共负载辅助函数。只有非负整数收益、整秒时域/位置/时长、总和小于2^52的域启用，保证改变累加顺序不会引入浮点差异；小数/负收益、亚秒和超大值回退完整ObjectiveModel。
- 新增full/incremental_key_calls、full/incremental_objective_calls、skip_states和dedup_input_states。实际去重率使用duplicate_states/dedup_input_states；旧版未暴露分母，旧版0重复可确定为0，否则留空，不伪造精确分母。
- stop_phase增加state_copy、candidate_keys和incumbent_copy，正常完成为completed；levels_completed仍只记完整剪枝层。

## 测试

专项61/61通过，0跳过，1.273秒。新增逐前沿状态比较，四组目标权重、整数/小数收益下的公共完整分数必须逐值相等；完整键必须完全相等。另覆盖负收益、亚秒回退、无墙钟截断时搜索前沿/最终计划一致、容器类型身份及分支隔离。原取消/预算和来源约束测试保留。

## 独立消融

[原始结果](caabs_round1/stage2.json)、[CSV](caabs_round1/stage2.csv)、[全指标](caabs_round1/stage2.md)。三族×三规模×四变体，共36组，各一次、2秒、seed41、公共模型重建回放全部通过。

| 任务数 | 阶段1完成/RT | 仅增量键 | 仅增量目标 | 两者 |
|---|---|---|---|---|
|20|15 / 0.259s|15 / 0.148s|15 / 0.237s|15 / 0.148s|
|100|47 / 1.391s|47 / 1.231s|47 / 1.376s|47 / 1.239s|
|300|115.67 / 1.951s|122.33 / 1.951s|115.33 / 1.951s|122.33 / 1.958s|

键缓存是明确有效的改动。增量目标在小场景单独有少量收益，但叠加键缓存后未显示稳定额外收益；最终默认配置拟启用键缓存，目标增量保留显式实验开关。

## 固定工作量诊断

另用30秒上限，保证uniform20的两变体都完整完成全部搜索：均615个评分状态、20个已安排任务，同一计划SHA。数据见[诊断证据](caabs_round1/stage2_diagnostics.json)。

| 项 | 阶段1 | 键+目标增量 |
|---|---:|---:|
|完整计划键计算|615|1|
|增量键组合|0|614|
|公共完整score调用|615|0|
|增量score调用|0|615|
|cProfile运行时间（只作诊断）|1.861s|1.051s|
|tracemalloc Python分配峰值|9,497,109B|2,158,015B|
|tracemalloc运行时间（只作诊断）|1.972s|1.075s|

内存是求解期间Python分配峰值，不是整机RAM或JVM内存；普通结果另保存独立子进程RSS及Windows进程生命周期峰值，后者包含导入和场景加载。不能把带仪器的RT混入正常胜负表。

复制仍是剩余主要成本。当前嵌套姿态可变，未证明可安全共享，按任务要求保留复制；不加入不必要的全候选冲突图或重写公共资源模型。
