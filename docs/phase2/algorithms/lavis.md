# LAVIS：学习型分配价值引导插入调度

> **2026-10-19 rebase 后状态：**已接入main PR #25的新物理模型。下文v1/v2/v3成绩均为旧物理版本的历史结果；旧96场景的来源证据和旧冻结权重不能在当前代码中继续使用，当前本机兼容生产模型数为0。必须重建新版本场景/划分、重新打标签和训练，禁止手改SHA或沿用旧成绩。详见[集成交接](lavis_main_rebase_handoff.md)。


日期：2026-10-18；算法0.1.0；从main `2d8a808` 建立 `feat/lavis-learning-scheduler`。主责李泽同，刘懋兴配合数据，何明涛配合Worker。沿用此前批准的v1.1方案；先交付可训练、可验证、可接入的第一版。

## 1. 机制与适用域

LAVIS（Learned Assignment-Value Insertion Scheduling）用监督回归预测一个完整分配的后续完成价值，每轮仅选择一个最高原始分数的可行候选并插入当前计划。新一轮重新扫描可行集合、重算动态特征，没有在线Beam、竞价、ALNS或教师续排后处理。

- 模型：scikit-learn HistGradientBoostingRegressor，24维共享特征，固定版本、种子、单线程，early_stopping=False。
- v1目标：完成率权重大于0，其余权重0；earliest、默认资源与机动约束、无地面站、physical_validation。API和Worker拒绝不兼容配置，不静默忽略权重。
- 有限池：每任务最多16个来源窗口，按卫星轮转；每任务最多32候选、总计4096，源记录处理上限200000。敏捷按配置起点，非敏捷按现有居中网格；只生成一个配置位置，不展开整段离散时间网格。
- 候选先通过共享来源、角度、几何和空计划检查并冻结；逐轮重查共享离散资源/转向，赢家再做完整检查。Controller仍独立恢复来源、检查约束及真实Orekit全曝光0.05秒采样。
- 相等分数按稳定身份裁决；非常接近的分数仍按原始值排序；非有限预测失败。预算不足以完成整轮时保留上一轮计划，取消上报异常而非成功。

这是课程项目自定义名称，不声明最优或必定优于传统算法。空池仅表示所限候选中无解。

## 2. 训练数据与标签

原始场景只读，严格读取仓库splits中的60训练来源与20验证来源白名单。核对每个原场景SHA、来源组和provenance，不递归发现场景、不读取私有final_test目录。共享星座与单一历元会限制泛化结论。

状态轨迹混合稀缺度规则与固定随机键。每来源最多10个状态、每状态最多8候选，每个候选固定承诺后分别续排：R1稀缺度优先，R2按同状态相同随机键构造。续排只能添加任务，最多10000次共享约束检查。标签为 `((n1+n2)/2 - n0) / r`，不是教师动作标志、成功概率或最优Q值。平分标签保留；未采样候选不标负例。

特征从当前场景、池和部分计划获得，不含标签/任务ID编码或全数据统计。特征顺序冻结在`algorithms/lavis/protocol.py`；训练与推理共用`features.py`。每来源等权、来源内状态等权、状态内候选等权；记录实际状态数、行数、区分状态率和哈希。

8组参数按20验证来源完整调度的完成总数选优，平分按参数规范键稳定裁决，RT另报；这与原方案“其次RT”的建议有所调整，避免小幅计时噪声改变配置选择。仅在60训练来源补一次模型轨迹标签，重训后只有验证完成数增加才采用，否则保留基础模型及其真实训练清单。另跑43/44两个种子；重复训练不当新来源。

## 3. 目录与复现

```text
algorithms/lavis/              协议、候选、特征、模型、求解、标签、训练
scripts/lavis.py               离线标签与训练CLI
scripts/evaluate_lavis.py      冻结模型/已有基线的独立验证CLI
experiments/ml_protocol.json   无个人路径的实验协议
requirements-ml.txt            固定ML依赖；不强迫传统算法安装
<EOS_RUNTIME_DIR>/derived/lavis-v1/   标签与生成协议
<EOS_RUNTIME_DIR>/models/lavis/<model_id>/
    model.joblib              真实训练权重，禁止同ID覆盖
    manifest.json             完整登记标志与冻结身份
    training_report.json      参数试验、消融、来源与逐场景轨迹
```

在WSL项目目录、已有虚拟环境中：

```bash
python -m pip install -r requirements-ml.txt
python -B scripts/lavis.py dataset --dataset "$EOS_RUNTIME_DIR/datasets/eos-course-v1" --output "$EOS_RUNTIME_DIR/derived/lavis-v1" --limit 2
python -B scripts/lavis.py dataset --dataset "$EOS_RUNTIME_DIR/datasets/eos-course-v1" --output "$EOS_RUNTIME_DIR/derived/lavis-v1"
python -B scripts/lavis.py train --dataset "$EOS_RUNTIME_DIR/datasets/eos-course-v1" --output "$EOS_RUNTIME_DIR/derived/lavis-v1" --model-id lavis-v1 --budget 15
python -B scripts/evaluate_lavis.py --dataset "$EOS_RUNTIME_DIR/datasets/eos-course-v1" --output "$EOS_RUNTIME_DIR/derived/lavis-v1/independent-validation.json" --model-id lavis-v1 --audit
```

先设置本机EOS_RUNTIME_DIR为绝对路径，并激活已装课程/Orekit依赖的同一虚拟环境。已有标签仅在协议完全一致时恢复；不覆盖已有模型或报告，后续实验使用新的模型ID/报告名。模型与标签不进Git；仅清理工具创建的.partial，既有用户数据不自动删除。

## 4. 模型登记、系统接口和数据库

- 公共签名不变；SolveContext末尾增加默认空model_provenance，兼容原位置参数。
- HTTP只接受算法参数model_id。服务端从运行目录受控根读取登记清单，冻结manifest SHA、权重SHA、特征/候选/物理域、依赖、训练代码/来源/划分等身份。
- RunConfig增加默认空model_provenance，沿用现有config_json/config_sha256保存，不迁移表。模型是算法侧身份，从实验公共配置剔除，但进入幂等和单变量对照检查。
- Worker复核清单和权重，将校验过的同一份字节加载到内存，检查依赖与维度；Controller复查冻结身份。模型缺失/更换或版本域错误明确拒绝，无规则回退。
- GET /api/models列可用模型；注册表Schema给model_id提供选项，现有参数表自动显示“冻结模型”。未安装依赖或无兼容模型时LAVIS禁用，原算法可运行。
- 实验详情原配置展开项显示快照；JSON导出provenance.model_provenance可追溯。CSV原列不变，模型身份配合JSON下载。
- joblib仅用于团队自训、受控目录中的可信制品，SHA校验不是任意外部pickle安全保证，不能增加网页上传加载入口。

## 5. 验收与尚待工作

机制回归含两星两任务反例、受控分数交换选择、动态掩码、长窗口有界、取消、非有限预测、配对标签、来源划分及制品替换。合成例明确只测离散机制；真实Orekit与HTTP验收另记。

消融共用同一候选池/构造器：训练模型、固定稀缺度、常数、随机分数；另比较仅静态特征的训练模型。区分来源验证成绩、训练标签诊断、真实核验与UI接入，不混写成最终测试成绩。训练/开发期RT受本机负载影响，最终公平计时需在冻结环境单独重跑。

最终20测试未开放；四算法统一基准、冻结测试评估、跨历元/星座验证、训练分布扩展仍需后续安排。现有物理门禁是有限采样而非严格连续区间证明。

参考：原批准方案；[HGB官方说明](https://scikit-learn.org/1.7/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)、[持久化与版本限制](https://scikit-learn.org/stable/model_persistence.html)。

## 6. 本轮实际训练与验收结果

冻结模型 `lavis-v1`，权重SHA-256：`c0be3fcf9f419f2498ea1cfe26ed842b7123eba3d106915ffa2b0e9ba010af92`。权重79,113字节；模型、清单与含逐场景轨迹的报告合计约5.5MB，派生标签/核验报告约31.7MB，均不进入Git。仓库只保存小型[验证汇总](../../../experiments/reports/lavis_v1_validation_summary.json)。

- 60来源基础标签3240行，410个状态中18个有区分度，约4.4%。基础标签生成合计181.74秒；完整训练/模型选择/补采样/消融流水线261.71秒。失败的开发期代码变化中止不计入此成功流水线耗时。
- 8组配置最佳：100轮、15叶、learning_rate=0.05、min_samples_leaf=10、L2=1、seed42、禁用自动早停。
- 另补1877行训练模型轨迹标签，但重训验证完成数为714，未提高，最终保留仅使用3240基础标签的原模型。未采用样本不算进最终权重的训练行数，仍保留供误差分析。
- 另外两个学习种子43/44均完成715个任务；这些重复训练不当作新来源。

| 同一构造器/候选池的版本 | 20验证来源完成总数 / 900 | 场景宏平均TCR |
| --- | ---: | ---: |
| LAVIS训练模型 | 715 | 79.000% |
| 固定稀缺度 | 715 | 79.000% |
| 固定流随机分数 | 715 | 79.000% |
| 常数分数 | 714 | 78.875% |
| 仅静态特征训练模型 | 714 | 78.875% |

**尚无证据表明当前模型明显优于规则/随机消融。** 训练内best-set命中率97.56%不能当成未见来源泛化成绩；大量平标签会让该数值偏高。额外未见的两星两任务离散反例，真实冻结模型仍选错第一步，只完成1/2（池内最优2），因此不能把“受控测试模型能改变选择”写成“真实模型已学会所有稀缺性机制”。该例不改成训练数据或加入特判；算法效果专项仍待完善。

### 物理与系统闭环

- 冻结模型独立重跑20验证来源：715任务、145155次Orekit采样调用，全部来源SAMPLED_PHYSICAL_PASS。仍为NOT_CERTIFIED，未使用最终20测试。
- 实际HTTP四档各一实验，LAVIS与profit_first各4次，共8次全部SUCCEEDED。LAVIS分别17/20、27/40、34/40、70/80；基线四例同完成数。Worker PID为1210/1410/1602/1810，各自退出码0（Controller PID805）。开发期负载下RT仅诊断，不作最终公平速度结论。
- 四例JSON/CSV、schedule、Gantt路由通过；JSON权重SHA与冻结制品一致。EOS-G0016的LAVIS回放已READY，示意姿态仍不等于动力学认证。
- 非法目标权重及模型路径请求返回422，未入队。浏览器实际看到可用LAVIS卡片、中文说明、冻结模型下拉和已保存实验比较。
- 定向Python回归44项：43通过、1项因WSL无Node跳过；该跨语言检查另外用Windows Node对实际14个注册Schema执行通过。前端22项通过。未声称全仓库测试或所有分辨率验收。

### 下一步效果开发

保持验证与最终测试隔离；优先在60训练来源内改进状态/候选采样、分析平标签和高冲突决策，必要时由数据负责人补充独立高冲突训练来源。目标归一化和特征若修改需升级协议、重打标签、重新训练并做同池消融，不能静默替换lavis-v1或拿最终测试挑方案。当前可作为算法D的可运行首版与实验基础，不能签署“已证明算法优越性”或完整D4最终评测完成。


## 7. 高冲突数据扩充（2026-10-19）

后续已新增48个独立轨道家族、96个场景，将训练/验证扩展到124/52场景。保留上述v1结果，不重写其训练身份；新版使用独立ID，沿用同一推理/特征/约束合同。新增数据、家族隔离、标签改进和实际验证结果集中在[高冲突扩充记录](lavis_conflict_expansion.md)，日常测试请按该记录选择对应冻结模型。新增高冲突验证属于开发验证，不能当最终测试。
