# 全组公共场景索引 eos-course-v1

此处只保存公开规格和60训练/开发、20验证划分，不保存大型场景。共100个独立任务来源，公开80份、最终保留20份。四档各25份：P10-20、P10-40、P20-40、P20-80，均1天。

从统一公开压缩包解压到运行目录，登记development/scenarios；将provenance侧车一并保留。根据splits中的artifact_id、scenario_sha256和lineage_group_id选择数据，禁止把最终测试用于训练和调参。

旧试制测试的可推导种子已废弃；最终测试由外部私有清单控制，目标与真实种子不在此目录。物理检查是工程采样核验，不代表严格连续区间证明。详见[数据交接](../../../docs/phase2/shared_scenario_data_delivery_report.md)。
