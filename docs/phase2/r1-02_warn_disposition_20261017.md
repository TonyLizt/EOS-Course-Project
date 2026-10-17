# R1-02 WARN 人工审核与处置记录（2026-10-17）

本记录由 Codex 按刘懋兴本轮指令完成逐项证据复核与处置意见编制。**结论：R1-02 只读索引在下述限制下具备有条件签收条件；28 个 WARN 全部保留，未关闭或改为 PASS。完整历史来源认证、连续曝光认证与正式发布均未批准。** 实际人员是否接受限制、签收及签字仍须人工确认，不冒称刘懋兴或李泽同已经签署，也不修改任何既有 approvals。

## 1. 基线、实际核验与证据保存

工作树：`D:/VC/EOS-Course-Project-registry`；分支 `feat/registry-provenance`；HEAD `d0d9325759f078ef13f41cc9eee74c5e7733758a`。开始时已有上一轮六新增文件及 README/COURSE_SETUP 两项修改，本轮原样保留。本次只新增本审核记录；完整核验输出写入一个全新 WSL 审核目录，未改现有索引、Raw CSV、源码、原始数据、旧审核或 Git 索引。

已完整解析索引 JSON（30 Raw、6 Legacy、4 Candidate、10 条来源边、209 份证据节点），阅读 Raw CSV、CLI、核验实现与 [R1-02 来源矩阵/实施报告](scenario_artifact_index_r1_02.md)，并检查当前 config.py/RunRequest 的身份消费规则。四类 WARN 原文来自完整检查数组，不根据汇总数字重造。

本轮重新执行原解释器、原工作目录和原三个证据根，**真实退出码 0；PASS 275 / WARN 28 / FAIL 0；总体 WARN**。共 303 条检查，数字是检查条数，不是场景数或认证数量。开始 UTC `2026-10-17T11:56:10.674425+00:00`，结束 UTC `2026-10-17T11:56:28.186286+00:00`。

```bash
cd /mnt/d/VC/EOS-Course-Project-registry
/home/meteor/eos-course-runtime/venv/bin/python -B scripts/verify_scenario_artifacts.py \
  --evidence-root epoch_acceptance=/home/meteor/eos-course-runtime/epoch-acceptance \
  --evidence-root e4_audit=/mnt/d/VC/EOS-Course-Project/docs/phase2/e4-review-20261017-124539 \
  --evidence-root reference_docs=/mnt/c/Users/流星/Downloads
```

原始 stdout 按字节完整保存为 `/home/meteor/eos-course-runtime/epoch-acceptance/r1-02-warn-review-20261017T115631314017Z/verification.json`，SHA-256 **`d601f063c98498cb2884c1b3de3ce8b6c4624d01604c799ad488305fac94dce3`**；stderr 与 argv、cwd、实际 returncode、环境、前后输入保护摘要及本轮元数据审查保存在同目录 `receipt.json`，没有只保留汇总。环境为 3.10.12，ijson 3.6.0；没有启动 JVM、求解器或重新认证曝光。上述绝对路径是本机证据位置，不假装为可移植仓库路径。

原上一轮输出的完整 SHA 为 `d601f063c98498cb2884c1b3de3ce8b6c4624d01604c799ad488305fac94dce3`；本轮结果与原结果 `完全一致`（逐项 level/category/code/subject/reason 及完整 JSON 内容核对），没有过滤、消除 WARN。核验时按索引显式解析的 249 个既有文件前后 SHA/大小/mtime 完全一致；全部 11 个本轮受检仓库文件（含上一轮未提交成果）也未改。

本轮使用文件的字节身份：

| 文件 | 完整 SHA-256 |
|---|---|
| data/registry/scenario_artifacts.v1.json | `8515d0a46e1605d6dd6ebc1a6370054ae55683568529708e37ce13e8df6c54a3` |
| data/registry/raw_input_manifest.csv | `46be7d17a58980ecc1ba40ad1dd2dab2b49decd8bc9df200239c0ea65d244168` |
| scripts/verify_scenario_artifacts.py | `e7610d7ad54acf2fc1c51340234f4515299c3db19c590ea0da03fc43209f943f` |
| eos_system/scenario_artifacts.py | `d426781c03214e281a31cad7457aa50b649d2efca8a1af3acd926c9c9d2f125b` |
| docs/phase2/scenario_artifact_index_r1_02.md | `c67ea3c63786f9528e02e2d0d23cad1528fc730ddd4eeae8ca0e45ecfb272970` |
| eos_system/config.py | `1a70ab4a9415f455aab24c777f885d95f6e4f871f262586a52f678847717caaf` |
| eos_system/contracts.py | `e819031bb0976296ca84fce2ac04d0d8489d6d0c245f5a76875f8b9f736fb75c` |

## 2. 分类口径与数量

校验器原 category 的 28 项全部为 MISSING_EVIDENCE。下列 A/B/C 是本处置记录的**主处置类别**，不回写校验器分类，不把已记录的限制等同已补齐来源：

| WARN 代码 | 数量 | 主处置类别 | 本轮处置及影响 |
|---|---:|---|---|
| HISTORICAL_FIELDS_UNKNOWN | 10 | B：阻止来源认证的未解决问题 | 原值保持 null/未知。可作为只读归档已记录限制被接受；仍不能认证历史 generator/seed/dataset/group/ML 独立家族 |
| DISTRIBUTION_FILENAME_ONLY | 10 | A：可作为历史数据已记录限制接受 | 只保留“未认证的文件名分布标签”；不能据此认证生成分布、抽样机制或分布实验分组 |
| RAW_ORIGIN_NOT_VERIFIED | 6 | B：阻止来源认证的未解决问题 | Legacy→Raw 仅假设；保留假设等级，不能认证完整 Raw 来源链或推断哪个城市源产生任务 |
| INTERNAL_ID_REUSE | 2 | C：需要契约/消费端规则确认的结构性问题 | 索引内容键已区分，当前无 Registry ID 碰撞；须确认所有消费者区别内部名、文件选择 ID、内容型 Registry ID，不能用内部名联结来源 |
| 合计 | 28 | A=10、B=16、C=2 | 主分组互斥计数；同一场景可触发多个检查，B 的 16 条不是 16 个独立场景或独立根因 |

A 类也会阻止其对应的“历史分布已认证”声明；B 类在仅提供只读索引时可以连同限制交付。C 类不意味着现有索引键失效，也不授权本轮修改契约/API。所有条目均写明能接受的范围、不能接受的声明及负责人待确认事项。

## 3. 场景身份、原数据及证据定位表

下表 A01–A10 仅为本文定位编号。每条 WARN 仍保留完整原 subject；权威关联键是 registry_id + scenario_sha256。索引 JSON 使用 `/scenario_artifacts/N`（零基），Raw CSV 使用 raw_id；二者 SHA 已在第 1 节冻结。

| 本文编号 / 索引位置 | 类型、原文件名 | 完整 Registry ID（含场景 SHA） | 静态 SHA-256 |
|---|---|---|---|
| A01 / `/scenario_artifacts/0` | legacy；`Scenario_S1_Sats50_M100_T3.0d_dist1.json` | `s50_m100_t3d_58b12c20a0c933736fc6005d947e359b0dac1b309d10eac003b49e8fb211b929` | `5b66c338c323dd822708bb5ed8dfc88a34fbb13807628f13682fb25a1392e7a1` |
| A02 / `/scenario_artifacts/1` | legacy；`Scenario_S2_Sats50_M100_T3.0d_dist0.json` | `s50_m100_t3d_665ac26c011a57ec1743910ebf63946e5a0f626bf13a63b2e71a9e65b7c748b7` | `7e44e38301e4c919dff2a7d25b02b8078feeea62cd44f9a68631818aca542fcd` |
| A03 / `/scenario_artifacts/2` | legacy；`Scenario_S1_Sats10_M20_T1.0d_dist1.json` | `s10_m20_t1d_d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc` | `c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295` |
| A04 / `/scenario_artifacts/3` | legacy；`Scenario_S1_Sats20_M20_T1.0d_dist1.json` | `s20_m20_t1d_99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e` | `180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b` |
| A05 / `/scenario_artifacts/4` | legacy；`Scenario_S2_Sats10_M20_T1.0d_dist0.json` | `s10_m20_t1d_04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5` | `2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68` |
| A06 / `/scenario_artifacts/5` | legacy；`Scenario_S2_Sats20_M20_T1.0d_dist0.json` | `s20_m20_t1d_fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5` | `1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f` |
| A07 / `/scenario_artifacts/6` | candidate；`Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json` | `s10_m20_t1d_bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295` |
| A08 / `/scenario_artifacts/7` | candidate；`Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json` | `s20_m20_t1d_86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b` |
| A09 / `/scenario_artifacts/8` | candidate；`Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json` | `s10_m20_t1d_f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68` |
| A10 / `/scenario_artifacts/9` | candidate；`Scenario_S2_Sats20_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json` | `s20_m20_t1d_ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f` |

Legacy 的原文件按索引 repo_relative 路径读取；Candidate、原 sidecar 与 E3 报告按 epoch_acceptance 显式证据根读取。6 条 Raw 假设都指向 10/20/50_satellites.json；Raw 30 份自身字节可核实，并不能由文件存在、名称、记录数或静态相同证明它们曾生成某 Legacy。

对应 Raw 原件：

| Raw 节点 / 仓库相对路径 | 完整 SHA-256 |
|---|---|
| `raw:input/10_satellites.json` / `input/10_satellites.json` | `c707ee30417d7e1a0448b644f90d6595235ae4cc8262fa2645f5f85d1fadc241` |
| `raw:input/20_satellites.json` / `input/20_satellites.json` | `6158d5a05cc413e39aaf4f239084f66f34b52e1b2634596d05bb118ed5e8225e` |
| `raw:input/50_satellites.json` / `input/50_satellites.json` | `b84dcc5e6bb6285ae2de48df967f475ef3780b582d9b248ab95300042a2a32a1` |

候选侧车及共同证据节点（定位规则/完整原路径均在索引 `/evidence`，原 SHA 以该索引与本轮完整输出交叉锁定）：

| Evidence ID | 角色 / 位置 | 原文件完整 SHA-256 |
|---|---|---|
| `s1-10s20m-grid-v2-lazy-20261016:sidecar` | producer_sidecar；`epoch_acceptance:s1-10s20m-grid-v2-lazy-20261016/candidate/provenance/Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json.provenance.json` | `05e838a3a6c00d8c78d423ff7e61832741943ccd070b01c71a97def45cc19502` |
| `s1-20s20m-grid-v2-lazy-20261016:sidecar` | producer_sidecar；`epoch_acceptance:s1-20s20m-grid-v2-lazy-20261016/candidate/provenance/Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json.provenance.json` | `39ddbfd364a2d37106a88c1ff9dca91452b4e458e34c708987db16dc9c480bd9` |
| `s2-10s20m-grid-v2-lazy-20261016:sidecar` | producer_sidecar；`epoch_acceptance:s2-10s20m-grid-v2-lazy-20261016/candidate/provenance/Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json.provenance.json` | `30e4d84b9452ad9d417e688b7c790e5acc0283296fa920e1c88c193c3c8a223a` |
| `s2-20s20m-grid-v2-lazy-20261016:sidecar` | producer_sidecar；`epoch_acceptance:s2-20s20m-grid-v2-lazy-20261016/candidate/provenance/Scenario_S2_Sats20_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json.provenance.json` | `fc903cfc0091fed19dfe88f6c86d2a4e9f26e1d21d23128e39e352d40e4cd7e6` |
| `contract` | proposed_norm；`reference_docs:Scenario_Registry_and_Provenance_Contract_v1.0.md` | `d474e1b1ef8856dc0e5dced11623428fa71078dd92fed0d05a2effbb9a9de171` |
| `parallel` | proposed_norm；`reference_docs:E3_E4_B1_B2_B3_Parallel_Task_Assignment_v1.0.md` | `5a133b5dda2ca29261d575e3b785732f8915ed5a35ce6dd23d2c3988aaa19dd5` |
| `e4-audit` | e4_audit；`e4_audit:E4_registration_audit_report.md` | `66b98d3ba670ba68909d67a119ce4bc4caed53b3a516d92273ff57c0b1e651f4` |
| `e4-review` | e4_review；`e4_audit:registration_review_draft.json` | `9e2c6d32bf4c0aef224532d07cfa5ab7268534e4e4e26e2c35b0ac0313abedd1` |
| `continuity-summary` | continuous_exposure_summary；`epoch_acceptance:continuous-exposure-final-p1-20261017T035340Z/audits/summary-verified.json` | `21bce52a998d901de64a7a2b99cdf5f1437400f6cd283fbfb564f508c680137f` |

契约、并行分工文件仍为外部 PROPOSED 设计稿，E4 review 仍未签署，只支持解释职责/字段边界，不提供已恢复的历史来源认证。本轮元数据复核只对当前索引列出的档案/侧车/报告作结论，不声称已穷尽所有可能的历史存档。

## 4. 全部 28 项 WARN 的逐项审查与处置

本节 W01–W28 严格按完整核验 JSON 中 WARN 的原顺序列出；JSON 指针 `/checks/N` 使用原检查数组零基位置，不是 WARN 子集序号。原 code、subject、reason 不改写；所有条目状态保持 WARN。

### W01 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s50_m100_t3d_58b12c20a0c933736fc6005d947e359b0dac1b309d10eac003b49e8fb211b929`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/259`（第 1 节保存的原 JSON）。
- 对应场景：A01，`Scenario_S1_Sats50_M100_T3.0d_dist1.json`；索引 `/scenario_artifacts/0`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 交叉审查：常规相邻 sidecar 在索引检查的位置未发现（仅该位置结论）；producer_identity 的历史 generator/seed/source map 为 null。外部 contract 是规则提案，不是该场景生成记录。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W02 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s50_m100_t3d_58b12c20a0c933736fc6005d947e359b0dac1b309d10eac003b49e8fb211b929`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/260`（第 1 节保存的原 JSON）。
- 对应场景：A01，`Scenario_S1_Sats50_M100_T3.0d_dist1.json`；索引 `/scenario_artifacts/0`。
- 对应证据：节点 `distribution_label=dist1`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W03 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s50_m100_t3d_665ac26c011a57ec1743910ebf63946e5a0f626bf13a63b2e71a9e65b7c748b7`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/261`（第 1 节保存的原 JSON）。
- 对应场景：A02，`Scenario_S2_Sats50_M100_T3.0d_dist0.json`；索引 `/scenario_artifacts/1`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 交叉审查：常规相邻 sidecar 在索引检查的位置未发现（仅该位置结论）；producer_identity 的历史 generator/seed/source map 为 null。外部 contract 是规则提案，不是该场景生成记录。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W04 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s50_m100_t3d_665ac26c011a57ec1743910ebf63946e5a0f626bf13a63b2e71a9e65b7c748b7`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/262`（第 1 节保存的原 JSON）。
- 对应场景：A02，`Scenario_S2_Sats50_M100_T3.0d_dist0.json`；索引 `/scenario_artifacts/1`。
- 对应证据：节点 `distribution_label=dist0`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W05 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/263`（第 1 节保存的原 JSON）。
- 对应场景：A03，`Scenario_S1_Sats10_M20_T1.0d_dist1.json`；索引 `/scenario_artifacts/2`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 交叉审查：常规相邻 sidecar 在索引检查的位置未发现（仅该位置结论）；producer_identity 的历史 generator/seed/source map 为 null。外部 contract 是规则提案，不是该场景生成记录。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W06 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/264`（第 1 节保存的原 JSON）。
- 对应场景：A03，`Scenario_S1_Sats10_M20_T1.0d_dist1.json`；索引 `/scenario_artifacts/2`。
- 对应证据：节点 `distribution_label=dist1`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W07 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/265`（第 1 节保存的原 JSON）。
- 对应场景：A04，`Scenario_S1_Sats20_M20_T1.0d_dist1.json`；索引 `/scenario_artifacts/3`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 交叉审查：常规相邻 sidecar 在索引检查的位置未发现（仅该位置结论）；producer_identity 的历史 generator/seed/source map 为 null。外部 contract 是规则提案，不是该场景生成记录。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W08 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/266`（第 1 节保存的原 JSON）。
- 对应场景：A04，`Scenario_S1_Sats20_M20_T1.0d_dist1.json`；索引 `/scenario_artifacts/3`。
- 对应证据：节点 `distribution_label=dist1`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W09 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/267`（第 1 节保存的原 JSON）。
- 对应场景：A05，`Scenario_S2_Sats10_M20_T1.0d_dist0.json`；索引 `/scenario_artifacts/4`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 交叉审查：常规相邻 sidecar 在索引检查的位置未发现（仅该位置结论）；producer_identity 的历史 generator/seed/source map 为 null。外部 contract 是规则提案，不是该场景生成记录。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W10 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/268`（第 1 节保存的原 JSON）。
- 对应场景：A05，`Scenario_S2_Sats10_M20_T1.0d_dist0.json`；索引 `/scenario_artifacts/4`。
- 对应证据：节点 `distribution_label=dist0`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W11 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/269`（第 1 节保存的原 JSON）。
- 对应场景：A06，`Scenario_S2_Sats20_M20_T1.0d_dist0.json`；索引 `/scenario_artifacts/5`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 交叉审查：常规相邻 sidecar 在索引检查的位置未发现（仅该位置结论）；producer_identity 的历史 generator/seed/source map 为 null。外部 contract 是规则提案，不是该场景生成记录。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W12 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/270`（第 1 节保存的原 JSON）。
- 对应场景：A06，`Scenario_S2_Sats20_M20_T1.0d_dist0.json`；索引 `/scenario_artifacts/5`。
- 对应证据：节点 `distribution_label=dist0`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W13 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/271`（第 1 节保存的原 JSON）。
- 对应场景：A07，`Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/6`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 侧车交叉审查：`s1-10s20m-grid-v2-lazy-20261016:sidecar`，原 SHA `05e838a3a6c00d8c78d423ff7e61832741943ccd070b01c71a97def45cc19502`；historical_generator_version=null，provenance_scope=recompute_lineage_only。已知重算 source_files_sha256、epoch/window/propagation 版本是局部重算身份，不能填回母场景原生成版本或 seed。其 Legacy 母 SHA 为 `d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc`。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W14 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/272`（第 1 节保存的原 JSON）。
- 对应场景：A07，`Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/6`。
- 对应证据：节点 `distribution_label=dist1`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W15 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/274`（第 1 节保存的原 JSON）。
- 对应场景：A08，`Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/7`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 侧车交叉审查：`s1-20s20m-grid-v2-lazy-20261016:sidecar`，原 SHA `39ddbfd364a2d37106a88c1ff9dca91452b4e458e34c708987db16dc9c480bd9`；historical_generator_version=null，provenance_scope=recompute_lineage_only。已知重算 source_files_sha256、epoch/window/propagation 版本是局部重算身份，不能填回母场景原生成版本或 seed。其 Legacy 母 SHA 为 `99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e`。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W16 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/275`（第 1 节保存的原 JSON）。
- 对应场景：A08，`Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/7`。
- 对应证据：节点 `distribution_label=dist1`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W17 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/277`（第 1 节保存的原 JSON）。
- 对应场景：A09，`Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/8`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 侧车交叉审查：`s2-10s20m-grid-v2-lazy-20261016:sidecar`，原 SHA `30e4d84b9452ad9d417e688b7c790e5acc0283296fa920e1c88c193c3c8a223a`；historical_generator_version=null，provenance_scope=recompute_lineage_only。已知重算 source_files_sha256、epoch/window/propagation 版本是局部重算身份，不能填回母场景原生成版本或 seed。其 Legacy 母 SHA 为 `04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5`。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W18 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/278`（第 1 节保存的原 JSON）。
- 对应场景：A09，`Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/8`。
- 对应证据：节点 `distribution_label=dist0`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W19 — HISTORICAL_FIELDS_UNKNOWN

- 原代码：`HISTORICAL_FIELDS_UNKNOWN`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575`。
- 原始原因：`generator_version, generator_seed, source_dataset, source_group_id, certified_ml_lineage`。
- 完整核验输出位置：`verification.json#/checks/280`（第 1 节保存的原 JSON）。
- 对应场景：A10，`Scenario_S2_Sats20_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/9`。
- 对应证据：本节点 `missing_fields` / `producer_identity` / `lineage_group_id=null`；原文件本轮实读 `metadata.extra={}`。
- 侧车交叉审查：`s2-20s20m-grid-v2-lazy-20261016:sidecar`，原 SHA `fc903cfc0091fed19dfe88f6c86d2a4e9f26e1d21d23128e39e352d40e4cd7e6`；historical_generator_version=null，provenance_scope=recompute_lineage_only。已知重算 source_files_sha256、epoch/window/propagation 版本是局部重算身份，不能填回母场景原生成版本或 seed。其 Legacy 母 SHA 为 `fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5`。
- 主处置 B／未解决：保留五项缺失标记，不猜测补 seed、版本、dataset、source_group 或 ML 家族；certified_ml_lineage 是索引的缺证据标记，不是本轮新增 Manifest 字段。
- 可接受范围：可有条件作为‘历史来源未核实’的只读档案索引交付；不可接受范围：完整历史来源认证、可复现实例独立性声明、据此作已认证 Train/Test 分组。
- 后续责任建议：刘懋兴查找原生成清单、命令/配置、Raw 哈希、生成器源码及随机性记录；原始生成者身份和能否恢复记录待人工确认。李泽同确认消费端如何显示 unknown 与限制用途。
- 关闭条件／待确认：只有可核验且绑定该完整 SHA 的原证据或有范围的正式评审决定才能追加结论；无随机种子是否属于“不适用”也须有算法/历史记录支持。新生成器的记录不能补证旧场景。本轮不关闭本 WARN。

### W20 — DISTRIBUTION_FILENAME_ONLY

- 原代码：`DISTRIBUTION_FILENAME_ONLY`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575`。
- 原始原因：`distribution label is not authenticated historical generation evidence`。
- 完整核验输出位置：`verification.json#/checks/281`（第 1 节保存的原 JSON）。
- 对应场景：A10，`Scenario_S2_Sats20_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json`；索引 `/scenario_artifacts/9`。
- 对应证据：节点 `distribution_label=dist0`、`distribution_evidence=FILENAME_ONLY`，原文件名如上；本轮实读的 metadata.extra 与顶层 distribution_type 摘要在 receipt.json.metadata_review 中。原文件名和字节身份没有改变。
- 主处置 A／限制可接受：允许保留并展示为‘未认证文件名标签’，不得升级证据级别或 WARN→PASS；不因此认证目标抽样算法、均匀/集中等实际分布语义。
- 仍阻止的声明：未经原生成配置/方法/输入与该 SHA 的绑定证据，不允许写成‘历史生成分布已认证’，也不能仅以 dist 标签宣称实验组采样策略一致。
- 后续责任建议：刘懋兴维护标签来源与说明；李泽同确认展示/导出消费者保留 evidence_level 与“未认证”提示。真实历史分布是否可恢复、是否允许在特定研究中只按文件名分组，均待人工确认。
- 关闭条件／待确认：找到版本化生成规则与原参数、来源和该 SHA 的对应记录后另行评审；名称相似或重新生成相似点集不构成补证。本轮保留 WARN，只建议接受有限展示用途。

### W21 — RAW_ORIGIN_NOT_VERIFIED

- 原代码：`RAW_ORIGIN_NOT_VERIFIED`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s50_m100_t3d_58b12c20a0c933736fc6005d947e359b0dac1b309d10eac003b49e8fb211b929`。
- 原始原因：`candidate Raw association only; historical seed/generator/target provenance not recovered`。
- 完整核验输出位置：`verification.json#/checks/283`（第 1 节保存的原 JSON）。
- 对应场景：A01，`Scenario_S1_Sats50_M100_T3.0d_dist1.json`；索引 `/scenario_artifacts/0`。
- 对应证据：索引 `/lineage_edges/0` 声明 `s50_m100_t3d_58b12c20a0c933736fc6005d947e359b0dac1b309d10eac003b49e8fb211b929` → `raw:input/50_satellites.json`，relationship=`raw_input_hypothesis`、evidence_level=`FILENAME_ONLY`；Raw CSV 对应 raw_id=`raw:input/50_satellites.json`，Raw 原 SHA `b84dcc5e6bb6285ae2de48df967f475ef3780b582d9b248ab95300042a2a32a1`。原边说明：`Scale/file naming suggests this Raw input; no historical generation record. City-source choice remains unknown.`。
- 主处置 B／未解决：Raw 文件字节和 Legacy 文件字节均可核实，但缺少它们之间真实生成过程的绑定证据。只保留假设边，不能认证完整 Raw 来源链、城市源选择或任务生成/变换过程。
- 可接受范围：作为显式不确定的候选映射留在只读索引；不可接受范围：把这条边当认证 parent、把名称/卫星数量/静态相等当作完整来源证明。下游 Candidate 的已核实 Legacy 母边不会自动提升这条 Raw 假设。
- 后续责任建议：刘懋兴查找原 Raw 输入清单及字节 SHA、原生成命令/源码、目标源与变换/抽样参数；原生成者协助身份待确认。李泽同确认链路中部分已核实、部分未知时的消费端规则。
- 关闭条件／待确认：需有能从该 Raw 内容及真实参数追溯到该 Legacy 内容的可信历史档案，或明确范围的独立证据评审；新试生成可以建立新链，不能据此改写旧链。本轮不关闭 WARN，不认证 Raw 完整来源。

### W22 — RAW_ORIGIN_NOT_VERIFIED

- 原代码：`RAW_ORIGIN_NOT_VERIFIED`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s50_m100_t3d_665ac26c011a57ec1743910ebf63946e5a0f626bf13a63b2e71a9e65b7c748b7`。
- 原始原因：`candidate Raw association only; historical seed/generator/target provenance not recovered`。
- 完整核验输出位置：`verification.json#/checks/284`（第 1 节保存的原 JSON）。
- 对应场景：A02，`Scenario_S2_Sats50_M100_T3.0d_dist0.json`；索引 `/scenario_artifacts/1`。
- 对应证据：索引 `/lineage_edges/1` 声明 `s50_m100_t3d_665ac26c011a57ec1743910ebf63946e5a0f626bf13a63b2e71a9e65b7c748b7` → `raw:input/50_satellites.json`，relationship=`raw_input_hypothesis`、evidence_level=`FILENAME_ONLY`；Raw CSV 对应 raw_id=`raw:input/50_satellites.json`，Raw 原 SHA `b84dcc5e6bb6285ae2de48df967f475ef3780b582d9b248ab95300042a2a32a1`。原边说明：`Scale/file naming suggests this Raw input; no historical generation record. City-source choice remains unknown.`。
- 主处置 B／未解决：Raw 文件字节和 Legacy 文件字节均可核实，但缺少它们之间真实生成过程的绑定证据。只保留假设边，不能认证完整 Raw 来源链、城市源选择或任务生成/变换过程。
- 可接受范围：作为显式不确定的候选映射留在只读索引；不可接受范围：把这条边当认证 parent、把名称/卫星数量/静态相等当作完整来源证明。下游 Candidate 的已核实 Legacy 母边不会自动提升这条 Raw 假设。
- 后续责任建议：刘懋兴查找原 Raw 输入清单及字节 SHA、原生成命令/源码、目标源与变换/抽样参数；原生成者协助身份待确认。李泽同确认链路中部分已核实、部分未知时的消费端规则。
- 关闭条件／待确认：需有能从该 Raw 内容及真实参数追溯到该 Legacy 内容的可信历史档案，或明确范围的独立证据评审；新试生成可以建立新链，不能据此改写旧链。本轮不关闭 WARN，不认证 Raw 完整来源。

### W23 — RAW_ORIGIN_NOT_VERIFIED

- 原代码：`RAW_ORIGIN_NOT_VERIFIED`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc`。
- 原始原因：`candidate Raw association only; historical seed/generator/target provenance not recovered`。
- 完整核验输出位置：`verification.json#/checks/285`（第 1 节保存的原 JSON）。
- 对应场景：A03，`Scenario_S1_Sats10_M20_T1.0d_dist1.json`；索引 `/scenario_artifacts/2`。
- 对应证据：索引 `/lineage_edges/2` 声明 `s10_m20_t1d_d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc` → `raw:input/10_satellites.json`，relationship=`raw_input_hypothesis`、evidence_level=`FILENAME_ONLY`；Raw CSV 对应 raw_id=`raw:input/10_satellites.json`，Raw 原 SHA `c707ee30417d7e1a0448b644f90d6595235ae4cc8262fa2645f5f85d1fadc241`。原边说明：`Scale/file naming suggests this Raw input; no historical generation record. City-source choice remains unknown.`。
- 主处置 B／未解决：Raw 文件字节和 Legacy 文件字节均可核实，但缺少它们之间真实生成过程的绑定证据。只保留假设边，不能认证完整 Raw 来源链、城市源选择或任务生成/变换过程。
- 可接受范围：作为显式不确定的候选映射留在只读索引；不可接受范围：把这条边当认证 parent、把名称/卫星数量/静态相等当作完整来源证明。下游 Candidate 的已核实 Legacy 母边不会自动提升这条 Raw 假设。
- 后续责任建议：刘懋兴查找原 Raw 输入清单及字节 SHA、原生成命令/源码、目标源与变换/抽样参数；原生成者协助身份待确认。李泽同确认链路中部分已核实、部分未知时的消费端规则。
- 关闭条件／待确认：需有能从该 Raw 内容及真实参数追溯到该 Legacy 内容的可信历史档案，或明确范围的独立证据评审；新试生成可以建立新链，不能据此改写旧链。本轮不关闭 WARN，不认证 Raw 完整来源。

### W24 — RAW_ORIGIN_NOT_VERIFIED

- 原代码：`RAW_ORIGIN_NOT_VERIFIED`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e`。
- 原始原因：`candidate Raw association only; historical seed/generator/target provenance not recovered`。
- 完整核验输出位置：`verification.json#/checks/286`（第 1 节保存的原 JSON）。
- 对应场景：A04，`Scenario_S1_Sats20_M20_T1.0d_dist1.json`；索引 `/scenario_artifacts/3`。
- 对应证据：索引 `/lineage_edges/3` 声明 `s20_m20_t1d_99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e` → `raw:input/20_satellites.json`，relationship=`raw_input_hypothesis`、evidence_level=`FILENAME_ONLY`；Raw CSV 对应 raw_id=`raw:input/20_satellites.json`，Raw 原 SHA `6158d5a05cc413e39aaf4f239084f66f34b52e1b2634596d05bb118ed5e8225e`。原边说明：`Scale/file naming suggests this Raw input; no historical generation record. City-source choice remains unknown.`。
- 主处置 B／未解决：Raw 文件字节和 Legacy 文件字节均可核实，但缺少它们之间真实生成过程的绑定证据。只保留假设边，不能认证完整 Raw 来源链、城市源选择或任务生成/变换过程。
- 可接受范围：作为显式不确定的候选映射留在只读索引；不可接受范围：把这条边当认证 parent、把名称/卫星数量/静态相等当作完整来源证明。下游 Candidate 的已核实 Legacy 母边不会自动提升这条 Raw 假设。
- 后续责任建议：刘懋兴查找原 Raw 输入清单及字节 SHA、原生成命令/源码、目标源与变换/抽样参数；原生成者协助身份待确认。李泽同确认链路中部分已核实、部分未知时的消费端规则。
- 关闭条件／待确认：需有能从该 Raw 内容及真实参数追溯到该 Legacy 内容的可信历史档案，或明确范围的独立证据评审；新试生成可以建立新链，不能据此改写旧链。本轮不关闭 WARN，不认证 Raw 完整来源。

### W25 — RAW_ORIGIN_NOT_VERIFIED

- 原代码：`RAW_ORIGIN_NOT_VERIFIED`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s10_m20_t1d_04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5`。
- 原始原因：`candidate Raw association only; historical seed/generator/target provenance not recovered`。
- 完整核验输出位置：`verification.json#/checks/287`（第 1 节保存的原 JSON）。
- 对应场景：A05，`Scenario_S2_Sats10_M20_T1.0d_dist0.json`；索引 `/scenario_artifacts/4`。
- 对应证据：索引 `/lineage_edges/4` 声明 `s10_m20_t1d_04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5` → `raw:input/10_satellites.json`，relationship=`raw_input_hypothesis`、evidence_level=`FILENAME_ONLY`；Raw CSV 对应 raw_id=`raw:input/10_satellites.json`，Raw 原 SHA `c707ee30417d7e1a0448b644f90d6595235ae4cc8262fa2645f5f85d1fadc241`。原边说明：`Scale/file naming suggests this Raw input; no historical generation record. City-source choice remains unknown.`。
- 主处置 B／未解决：Raw 文件字节和 Legacy 文件字节均可核实，但缺少它们之间真实生成过程的绑定证据。只保留假设边，不能认证完整 Raw 来源链、城市源选择或任务生成/变换过程。
- 可接受范围：作为显式不确定的候选映射留在只读索引；不可接受范围：把这条边当认证 parent、把名称/卫星数量/静态相等当作完整来源证明。下游 Candidate 的已核实 Legacy 母边不会自动提升这条 Raw 假设。
- 后续责任建议：刘懋兴查找原 Raw 输入清单及字节 SHA、原生成命令/源码、目标源与变换/抽样参数；原生成者协助身份待确认。李泽同确认链路中部分已核实、部分未知时的消费端规则。
- 关闭条件／待确认：需有能从该 Raw 内容及真实参数追溯到该 Legacy 内容的可信历史档案，或明确范围的独立证据评审；新试生成可以建立新链，不能据此改写旧链。本轮不关闭 WARN，不认证 Raw 完整来源。

### W26 — RAW_ORIGIN_NOT_VERIFIED

- 原代码：`RAW_ORIGIN_NOT_VERIFIED`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`s20_m20_t1d_fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5`。
- 原始原因：`candidate Raw association only; historical seed/generator/target provenance not recovered`。
- 完整核验输出位置：`verification.json#/checks/288`（第 1 节保存的原 JSON）。
- 对应场景：A06，`Scenario_S2_Sats20_M20_T1.0d_dist0.json`；索引 `/scenario_artifacts/5`。
- 对应证据：索引 `/lineage_edges/5` 声明 `s20_m20_t1d_fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5` → `raw:input/20_satellites.json`，relationship=`raw_input_hypothesis`、evidence_level=`FILENAME_ONLY`；Raw CSV 对应 raw_id=`raw:input/20_satellites.json`，Raw 原 SHA `6158d5a05cc413e39aaf4f239084f66f34b52e1b2634596d05bb118ed5e8225e`。原边说明：`Scale/file naming suggests this Raw input; no historical generation record. City-source choice remains unknown.`。
- 主处置 B／未解决：Raw 文件字节和 Legacy 文件字节均可核实，但缺少它们之间真实生成过程的绑定证据。只保留假设边，不能认证完整 Raw 来源链、城市源选择或任务生成/变换过程。
- 可接受范围：作为显式不确定的候选映射留在只读索引；不可接受范围：把这条边当认证 parent、把名称/卫星数量/静态相等当作完整来源证明。下游 Candidate 的已核实 Legacy 母边不会自动提升这条 Raw 假设。
- 后续责任建议：刘懋兴查找原 Raw 输入清单及字节 SHA、原生成命令/源码、目标源与变换/抽样参数；原生成者协助身份待确认。李泽同确认链路中部分已核实、部分未知时的消费端规则。
- 关闭条件／待确认：需有能从该 Raw 内容及真实参数追溯到该 Legacy 内容的可信历史档案，或明确范围的独立证据评审；新试生成可以建立新链，不能据此改写旧链。本轮不关闭 WARN，不认证 Raw 完整来源。

### W27 — INTERNAL_ID_REUSE

- 原代码：`INTERNAL_ID_REUSE`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`Scenario_S1`。
- 原始原因：`internal name spans multiple content identities and is not a unique lineage/registry key`。
- 完整核验输出位置：`verification.json#/checks/293`（第 1 节保存的原 JSON）。
- 对应证据：索引中该 internal_scenario_id 关联 5 个不同 SHA／Registry ID；十个内容 ID 均唯一，完整输出包含相应 SCENARIO_IDENTITY PASS。具体成员如下：
  - A01：`s50_m100_t3d_58b12c20a0c933736fc6005d947e359b0dac1b309d10eac003b49e8fb211b929`。
  - A03：`s10_m20_t1d_d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc`。
  - A04：`s20_m20_t1d_99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e`。
  - A07：`s10_m20_t1d_bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e`。
  - A08：`s20_m20_t1d_86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779`。
- 消费端实读证据：eos_system/config.py 的 list_scenarios_in 返回文件 stem 作为 scenario_id，resolve_scenario_in 按登记 source 根 + `<stem>.json` 解析；RunRequest 另含 source_id。相关源文件 SHA 在第 1 节。文件选择 ID、内部名与内容型 Registry ID 是不同语义；本轮没有对所有外部消费者作穷尽审查。
- 主处置 C／结构性确认待办：接受历史内部名复用作为数据事实，不改名或重写原文件；来源/审计联结使用 registry_id + 完整 scenario_sha256，禁止以内部名单独唯一查找或作 ML 家族。当前索引不因该历史复用发生碰撞。
- 契约建议（未实施）：明确 internal_scenario_id 仅展示/历史名；保留现有 `(source_id, filename stem)` 兼容入口；若未来引入内容型 Registry ID 解析，必须由服务端受控映射到确定 SHA/位置，并版本化快照与兼容策略。是否修订正式 Registry 契约、哪些消费端需要调整，待李泽同与数据负责人确认，不由本记录推定已批准。
- 后续责任建议：李泽同主责公共 ID 语义及消费端规则确认；刘懋兴维护映射和证据。此建议未通知或代签成员，也不宣称所有消费端已符合。
- 处置结果：在当前只读索引有内容键的范围可保留此限制；跨系统按内部名唯一联结不得放行。本轮保留 WARN，结构性待办未关闭。

### W28 — INTERNAL_ID_REUSE

- 原代码：`INTERNAL_ID_REUSE`；level=`WARN`；原 category=`MISSING_EVIDENCE`。
- 原场景身份 / subject：`Scenario_S2`。
- 原始原因：`internal name spans multiple content identities and is not a unique lineage/registry key`。
- 完整核验输出位置：`verification.json#/checks/294`（第 1 节保存的原 JSON）。
- 对应证据：索引中该 internal_scenario_id 关联 5 个不同 SHA／Registry ID；十个内容 ID 均唯一，完整输出包含相应 SCENARIO_IDENTITY PASS。具体成员如下：
  - A02：`s50_m100_t3d_665ac26c011a57ec1743910ebf63946e5a0f626bf13a63b2e71a9e65b7c748b7`。
  - A05：`s10_m20_t1d_04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5`。
  - A06：`s20_m20_t1d_fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5`。
  - A09：`s10_m20_t1d_f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4`。
  - A10：`s20_m20_t1d_ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575`。
- 消费端实读证据：eos_system/config.py 的 list_scenarios_in 返回文件 stem 作为 scenario_id，resolve_scenario_in 按登记 source 根 + `<stem>.json` 解析；RunRequest 另含 source_id。相关源文件 SHA 在第 1 节。文件选择 ID、内部名与内容型 Registry ID 是不同语义；本轮没有对所有外部消费者作穷尽审查。
- 主处置 C／结构性确认待办：接受历史内部名复用作为数据事实，不改名或重写原文件；来源/审计联结使用 registry_id + 完整 scenario_sha256，禁止以内部名单独唯一查找或作 ML 家族。当前索引不因该历史复用发生碰撞。
- 契约建议（未实施）：明确 internal_scenario_id 仅展示/历史名；保留现有 `(source_id, filename stem)` 兼容入口；若未来引入内容型 Registry ID 解析，必须由服务端受控映射到确定 SHA/位置，并版本化快照与兼容策略。是否修订正式 Registry 契约、哪些消费端需要调整，待李泽同与数据负责人确认，不由本记录推定已批准。
- 后续责任建议：李泽同主责公共 ID 语义及消费端规则确认；刘懋兴维护映射和证据。此建议未通知或代签成员，也不宣称所有消费端已符合。
- 处置结果：在当前只读索引有内容键的范围可保留此限制；跨系统按内部名唯一联结不得放行。本轮保留 WARN，结构性待办未关闭。

## 5. 分项结论与签收意见

### 5.1 文件身份核验

本次读取范围内 30 个 Raw、六 Legacy、四 Candidate 及引用证据的完整字节 SHA/大小均匹配；场景内容型 ID 和静态哈希也匹配。没有实际 SHA 矛盾、无效身份或缺本机根导致的 FAIL，文件身份层可接受。275 PASS 是多个具名检查通过，不是 275 个场景或 80 条曝光认证通过。

### 5.2 来源关系核验

四条 Candidate→Legacy 的原侧车结果/母 SHA、静态保持和声明关系有相互佐证，局部重算链可接受，范围止于其已知 Legacy 母场景。六条 Legacy→Raw 仍是 FILENAME_ONLY 假设，城市/目标选择、历史生成参数和独立来源家族未认证。静态相同不证明完整 Raw 上游，母子 SHA 不证明 ML 来源独立。

### 5.3 未解决的证据缺口

- 历史原 generator_version、generator_seed、source_dataset、source_group_id 及 certified_ml_lineage；Candidate 已知重算工具身份不能替代它们。
- dist 文件名与真实目标生成/抽样策略的历史绑定，六条 Raw 假设和未知城市源的真实生成记录。
- 匹配历史 Git blob 只佐证源码字节；base_git_sha 不是原工具已提交/执行的凭证，生产执行过程没有因本轮审核变为已认证。
- 内部名、文件选择 ID、内容 ID 的公共契约与外部消费者遵守情况，R1-01 签署、正式审核/发布权威均待人工确认。没有已批准决定的证据时不得自行假定。
- 这些 WARN 不是全部发布门禁。原四计划 80 条实际曝光仍为 INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE，本轮只读复核原汇总、未重算；已合入的窗口/时间/插值修复及旧 E3 局部 PASS 均不能补造连续证书或正式批准。回放最终用途的验收和发布范围仍需相应负责人决定。

### 5.4 R1-02 是否可以签收

**建议可在明确限制下签收“只读 Artifact/Provenance 索引及 WARN 已记录”这一 R1-02 交付范围。** 条件是保留全部 28 WARN、原始 SHA/侧车/报告和未知值；使用内容型复合键；只把 Raw 边视为假设；不作来源完整、独立 ML family、连续曝光或已发布声明；消费端不绕过现有候选门禁。A 类接受的是限制，B 类保持未解决，C 类进入契约确认待办，不以“签收索引”关闭这些事项。

数据签收人建议刘懋兴，公共身份/消费契约确认建议李泽同；**实际签收、接受限制的决定日期及签名均待上述人员人工确认**。本轮只有受托证据审阅和处置意见，不把此文档当作 release_attestation，不代签，不更新既有审核状态或审批数组。

### 5.5 进入试生成之前的前置条件

下列为建议的试生成准入清单，实际尺度、预算、负责人和批准状态尚未从现有证据确定，须人工确认。R1-02 有条件签收不构成试生成启动授权；本轮没有启动任何生成，更没有正式 100 份批量生成。

1. **明确试生成目的与授权预算**：刘懋兴提出小批验证计划，写清输入、星数/任务数/时长、数量、资源预算、停止条件、验收目标及新输出目录，具体值待批准。不能将“100 组规划”当作本轮已批准预算。
2. **冻结本次真实输入和生成身份**：对计划实际使用的 Raw/母场景、生成器源码/依赖/数据包与参数逐一冻结 SHA；确定 seed 的真实使用规则或以证据说明不适用；记录生成命令、UTC、版本、父关系和失败/完成状态。若沿用未知 Legacy，上游必须继续标 unknown，不能通过试生成补证旧历史。
3. **确认身份和证据消费契约**：李泽同/刘懋兴确认内容键与旧选择 ID 的区别、必要的来源记录、完成标记与验收范围；R1-03 审核 Schema、R1-04 正式接入尚未在此实施。是否要求它们的特定部分先完成，再进行哪一种隔离试验，待人工决定，不能臆造依赖已批准。
4. **先证明生成/审查链能如实留证**：在获准的小夹具上验证只写新目录、失败不形成完成/发布记录、静态保持和版本/源 SHA 可复查；现有候选、Legacy、Raw、原 sidecar 不被覆盖。具体冒烟样例和阈值需负责人确认，本轮不执行。
5. **来源独立性和比较用途单独决定**：需要 ML 独立家族或特定分布实验时，先定义并验证 lineage 分组及分布规则；仅不同 SHA、seed 或名字不足以认证。若试验只为新生成流程留证，历史缺口可作为已披露限制保留；不必谎称所有旧来源已恢复才能开展一个另行批准的新链试验。
6. **把生成试验与发布分开**：生成成功、规划可行、哈希匹配和有限采样均不意味着连续认证或发布。若试生成计划依赖当前四候选作为已认证物理/benchmark 基准，必须先解决相应连续性、用途验收和正式批准要求；否则明确限定只作隔离测试，四候选继续 candidate_only / formal_release_eligible=false。

## 6. 本轮变更与验证边界

只新增本文和同一全新 WSL 审核目录中的 verification.json / receipt.json；不改 README、COURSE_SETUP、现有索引/CSV、核验代码、Raw、Legacy、Candidate、SHA、侧车、数据库或正式 Registry。用户本轮“只新增审核记录及必要核验输出”的要求优先，未追加其他版本文档。

本轮没有重新运行与文档处置无关的全套单测，也没有把上一轮 25/47/371 的结果冒充本轮新执行；实际执行的是同解释器只读 CLI、完整 WARN 对照、元数据/侧车/来源边审查及前后文件保护核验。交付时另核对 git diff --check 与新文档空白/28 项覆盖，以及原有未提交文件未变；检查回执在系统临时目录保留。未执行 git add、commit、push、merge 或创建 PR，完成后停止等待人工审核。
