# EOS-v1 建设前资产审计（2026-10-23）

分支 `test/basic-algorithms-web-acceptance-20261023`，HEAD `4a743105c910caea6953cc1adf1726fb9592f1ae`，与任务指定值一致。未跟踪的历史审计、场景ZIP、全组交付包和两个历史测试保持原位；本任务不会覆盖它们。

## 初步结论（实施前）

- `input/10_satellites.json`、`20_satellites.json`、`50_satellites.json`、`100_satellites.json`实际记录数分别为10、20、50、100；这是轨道原始输入，尚无任务和观测窗口。40星必须从真实50/100星输入确定性选取，不能复制卫星改ID。
- `experiments/scenarios/`有12份场景JSON：6份Legacy母场景及6份历元修复场景。规模为10/20、20/20（各1天、两种分布）和50/100（3天、两种分布）。Legacy可加载不等于真实物理通过；已知原10星20任务样例有不可见曝光起点。
- 全组交付包包含独立的development和final_test区域，以及压缩归档和校验和。新任务只审计公开development；冻结final_test仅登记位置，不读取任务、标签或评测结果。
- 现有共享生成器仅覆盖10/20、10/40、20/40、20/80；高冲突生成器采用合成轨道，不能把其卫星数量当作来自真实卫星输入的规模证明。它们的OrbitGrid、采样核验、来源记录和流式结构审计可以复用。
- 公共接口为`scenario_id`、`metadata`、`satellites`、`missions`、`ground_stations`、`observation_windows`、`communication_windows`；结果仍由独立Controller核验。窗口数组及角度必须通过已有来源检查。
- 当前算法比较注册表包含原13种和新增6种；初始模型`completion_first`、`adaptive_repair`另有公共注册接口，矩阵须区分其角色。
- PPO/LAVIS的模型域有物理版本、姿态定义、earliest放置、默认约束、无地面站等限制；R1适配器负责公共TP/TCR目标。新Nadir场景不能直接套用旧姿态训练的权重。必须实际检查工件与域，不修改manifest、摘要或隐藏失败。
- 默认路径当前有环境变量`EOS_SCENARIO_DIR`、runtime/scenarios、仓库experiments/scenarios，以及数据库登记数据源。新canonical目录需要显式登记并保留这些旧调用，不能仅移动文件。
- 现有`data/registry/`已有raw_input_manifest和scenario_artifacts索引。新登记采用独立文件，不覆盖旧索引。

## 复用工具与风险

`scripts/build_scenario_manifest.py`流式检查结构、引用、时间及角度；`recompute_scenario_windows.py`重算窗口并保持静态输入；`build_shared_dataset.py`共享Orekit网格、生成来源记录、独立0.05秒曝光采样；`audit_shared_dataset_samples.py`保存几何样本；`build_conflict_dataset.py`提供候选冲突测量；`validate_basic_schedulers.py`提供真实API/Worker/Verifier链路。后两者的固定规模/模型选择不能直接充当此次动态全算法矩阵。

本轮新增只读审计脚本`audit_scenario_assets.py`，详细文件SHA、规模、窗口数、结构问题和ZIP条目统计保存于`data/registry/eos-v1-asset-audit-20261023.json`。结构PASS/WARN不代表连续物理认证，原数据和报告均不自动升级为正式benchmark。

实施顺序：先建立不复制场景的统一索引，再试生成代表性规模，测量真实冲突和生成成本，同时真实验证两个目标及模型域；只有这些结果可解释后才扩展96实例。无法通过的实例或算法必须进入失败/待执行清单。
