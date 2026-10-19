# LAVIS 独立高冲突场景（lavis-conflict-v1）


> 当前仅作旧物理版本的数据与来源档案。main PR #25修改姿态/FOV/跟踪合同后，旧来源证据不能在当前代码下使用。不要修改侧车、旧规格或SHA强行放行；请先按项目`docs/phase2/algorithms/lavis_main_rebase_handoff.md`完成新版本数据迁移。

本目录仅保存公开规格、来源隔离报告、质量报告和训练/验证划分。完整场景、标签、权重均在运行目录，不能将大型生成物加入 Git。

## 数量与用途

| 范围 | 独立轨道家族 | 场景数 | 用途 |
| --- | ---: | ---: | --- |
| HC-F001 至 HC-F032，每家族 V1/V2 | 32 | 64 | 训练/开发，可生成标签 |
| HC-F033 至 HC-F048，每家族 V1/V2 | 16 | 32 | 高冲突验证，用于选模型，不生成训练标签 |
| 原 eos-course-v1 最终测试 | 20 原来源 | 20 | 继续由数据负责人封存，不在本包、不登记后端 |

同一 HC 家族的两个变体共用轨道，必须一起划分；不能按文件随机打散。新家族不由原场景裁剪或扰动，轨道、历元、目标和窗口从头生成。读取冻结测试索引只用于来源排重，不读取测试场景、窗口、标签或私有种子。

新数据可以用于全组传统算法与 LAVIS 的同场景比较；算法比较必须统一约束、目标和时间预算。它属于合成高冲突开发数据，验证成绩不是冻结测试成绩，也不能代表实际业务分布。

## 分发与接入

完整目录结构应保留：

```text
lavis-conflict-v1/
  dataset_spec.json
  isolation_report.json
  quality_report.json
  generation_source/       # 实际生成源码快照
  splits/                  # train_development.json / validation.json
  development/
    scenarios/             # 96个场景JSON
      provenance/          # 场景来源证明，不能漏拷
    generation_configs/    # 新轨道家族与目标生成证据
    checks/                # 结构、物理采样及候选重叠统计
```

把完整数据目录或校验过 SHA-256 的压缩包交给组员。在网页“数据源”登记解压后 **development/scenarios** 的 WSL 路径；不要只拷96个JSON。机器学习训练传入 `--extra-dataset <lavis-conflict-v1目录>`，原 `--dataset` 仍指向 eos-course-v1。

窗口扫描为5秒；每场景5至10段完整曝光抽查，总875段、646075个真实Orekit采样时刻通过。该检查不是所有窗口的逐点遍历；实际实验仍由 Controller 对所选计划做全曝光0.05秒采样核验，保持 NOT_CERTIFIED，不声称连续区间证明。

算法、来源政策、复现命令及实际模型效果见 [扩充说明](../../../docs/phase2/algorithms/lavis_conflict_expansion.md)。
