# Canonical eos-v1（开发数据）

新场景的唯一权威JSON位于本目录。每个SCN目录包含`scenario.json`、`provenance.json`、`validation.json`、`characterization.json`。现有Loader需要的`provenance/scenario.json.provenance.json`是来源记录的字节相同兼容镜像，不是第二份场景；登记时核对镜像一致性。

`standard/`、`realistic/`、`stress/high_conflict/`、`stress/resource_overload/`分别保存低冲突、混合、高冲突和资源过载；`stress/narrow_window/`为实际父窗口内的三份窄窗口子集。任务为明确标注的合成开发请求，轨道来自真实原始卫星输入。40星从真实50星清单按ID排序取40条，不复制卫星改ID。

`dataset_plan_v3.json`为当前96实例目标表。旧试验计划和原始试验JSON保留。出现`quarantine.json`的目录不进入可用场景清单，其原因和替代实例可查询；物理采样通过不能替代加载、约束和实际求解检查。r2是初始姿态补齐的试验版本，r3用公共约束实际执行的存储容量构造资源压力。

`legacy/index.json`只索引`experiments/scenarios/`，没有复制Legacy场景。冻结最终测试集不参与此次构建或训练。所有生成物保持development状态，未宣称连续区间认证或正式发布。

当前96核心+4保留试验+3子实例，共103可用。validation.json为生成时采样证据，不随矩阵回写；最新算法/目标结果查看data/registry/scenario_manifest.json和experiments/runs/eos-v1/matrix-full。r2/r3同源修订与父子场景不能跨训练/测试拆分，统一Manifest提供血缘等价组。

统一查询、生成、核验和矩阵命令见仓库的`docs/phase2/scenario_catalog.md`。
