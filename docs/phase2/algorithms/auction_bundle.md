# RABAS：资源感知任务包竞价调度

更新：2026-10-20；算法B，负责人：梁兆榮；算法ID：`rabas`；当前版本：`1.1.1`。

当前完整说明与逐参数变化见 [RABAS原理与优化说明](../RABAS_algorithm_explanation_20261020.md)，全部实验、失败结果和验收边界见 [跨规模实验报告](../RABAS_cross_scale_report_20261020.md)。本文件原1.0.0说明及早期实验保留在Git历史；其单路径、静态独占、两位置和丢弃半轮报价等描述不再适用于当前实现。

## 机制与接口

RABAS在单个Worker内中心化竞价：各星局部构造真实有界任务包，中心选择一个报价，完整重放后更新唯一全局计划，中标后所有卫星重新报价。默认最大包2，可配置3；可选多起点只影响当前卫星的局部路径，不是跨轮Beam Search，也不是分布式CBBA。

复用`solve(problem, constraints, context) -> Schedule`、原公共候选构造器、原ConstraintModel、Schedule/Assignment、ObjectiveModel、EvaluationMetrics及Controller独立核验。注册表直接构造`ResourceAwareBundleAuctionScheduler`，不消耗初始计划。没有更改Worker、IPC、数据库、场景或其他算法。

## 当前采用的优化

- 候选模板缓存上限4096；计划列表浅复制，Assignment不原位修改；轮候选与机会缓存中标后清空。
- 可加目标精确增量、BD公共函数差值；负优先级或亚秒时间域回退完整公共目标。
- 当前计划下的有界动态机会见证与机会损失，只对入围项估计；内部报价不是正式TP。
- 有界任务多特征排序、原始网格earliest/center/latest/gap；下传也保留center并增加latest/合法空隙提案。所有真实插入重新公共验证，不改窗口。
- 预选窗口总量/剩余时间决定搜索宽度、窗口数、位置数与保护任务数；没有场景身份或答案匹配。
- 检查/搜索上限保留已完成报价，剩余总预算内完整重放后方可接受；用户取消仍异常，Worker硬超时不伪装成功。

## 默认参数的取舍

位置上限默认从2增至4，允许1–8；新增dynamic_scarcity=true、diverse_candidates=true、opportunity_probe_tasks=4、adaptive_search=true。多起点支持1–4但默认1；同星1换2修复支持至多64次但默认0；future_aware_rank经验证回退默认false。包大小2、任务宽度8、窗口4、轮检查20000、转向/资源/机会权重0.1/0.1/0.5保持原默认。详细作用、范围与实际自适应阈值见说明文档。

## 验证与限制

最终全量718项、50跳过、无失败；原22项专项+10项新增反例，以及集成/预算协议测试通过。独立公共模型测试每规模两个未开发结构族，所有预选算法/seed结果完整公开。首轮下传回归暴露后整批转验证，修复冻结后使用新族重新独立测试，没有继续调参。

Small平均完成数并列组最优但不是逐实例或次级指标最优；Medium/Large在预算内有效返回的方法中领先。10秒验证存在Adaptive Repair胜RABAS。真实Small/Medium预览核验成功，历史Large物理核验失败，三个formal均不可信物理设置而失败。因此不能宣称三规模正式性能全面领先。

诊断位于直接Solver返回的`Schedule.metadata['rabas']`；外部序列化如何暴露它以当前公共serializer为准，本轮未新增IPC字段。性能脚本在Solver边界读取，Controller事务是否保存结果由原框架决定。

## 复现与交付

见实验报告的完整命令；新脚本为`benchmark_rabas_cross_scale.py`、`benchmark_rabas_real.py`、`verify_rabas_controller.py`、`profile_rabas_cross_scale.py`及`report_rabas_cross_scale.py`。全部结果写入显式独立输出目录，不覆盖已有目录。研究夹具是明确标记的非物理合成输入，不能用作生产认证证据。

本轮基线`89dff80`，分支`perf/rabas-cross-scale-optimization`，最终算法冻结`cfe53ad`；只本地Commit、不Push、不建PR。详细阶段历史见 [阶段记录](rabas_cross_scale.md)。
