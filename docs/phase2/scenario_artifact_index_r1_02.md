# R1-02：Scenario Artifact / Provenance 只读索引

日期：2026-10-17（Asia/Shanghai）。工作树 `D:/VC/EOS-Course-Project-registry`，分支 `feat/registry-provenance`，基线 `d0d9325759f078ef13f41cc9eee74c5e7733758a`。开始时 git status --short、git diff --stat 均为空；已检查 branch/log/worktree list。完整前后 Git 状态与测试日志只放系统临时目录。

本次只实施 R1-02：独立文件索引、来源矩阵、只读核验函数/CLI、合成夹具单测。Raw 30 个文件独立于 10 个 Scenario Artifact 统计；不是 40 个场景。四候选仍 candidate_only、formal_release_eligible=false，未经正式批准。80 条既有真实曝光均 INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE，本轮没有重新求解或重新认证，也没有注册、审批、发布或修改历史状态。

## 1. 规范检索与版本边界

已检索实际位置并阅读：

- 仓库：`docs/phase2/team_collaboration.md`、`interface_design_target.md`、`database_design_target.md`、`database_current_v03.md`，以及当前 E3/E4、插值、连续曝光修复报告。
- 仅本机 Downloads：`C:/Users/流星/Downloads/E3_E4_B1_B2_B3_Parallel_Task_Assignment_v1.0.md`、`Scenario_Registry_and_Provenance_Contract_v1.0.md`。两份均明确是 PROPOSED/待审核，未发现已签署 R1-01 决定，不能当作获批发布协议。
- 仅另一工作树的审核目录：`D:/VC/EOS-Course-Project/docs/phase2/e4-review-20261017-124539/E4_registration_audit_report.md` 和 `registration_review_draft.json`。只读引用，没有复制/改写为本分支的正式审核。草案签署/approvals 仍为空。

四个外部规范/审核文件在本仓库缺失的事实、可用位置、SHA 已明确进入 evidence 节点；不假装它们随 Git 移植。旧审核的 daf4254/B1 FAIL、旧网格探针被接受、Cesium NOT_RUN 是历史状态；后续 0c55223/4eda1f3/d0d9325 实现与新曝光报告单列，不能用旧结论描述现在 main，也不能据后续修复把旧报告改绿。

## 2. 索引文件与路径模型

- [`data/registry/scenario_artifacts.v1.json`](../../data/registry/scenario_artifacts.v1.json)：`scenario_artifact_index_v1`，30 raw_inputs、10 scenario_artifacts、10 lineage_edges、209 evidence；包含生产身份、Git 对象/主线/审核工具对照。该文件不是正式 Registry 或 R1-03 审核 Schema。
- [`data/registry/raw_input_manifest.csv`](../../data/registry/raw_input_manifest.csv)：Raw 独立清单，列 raw_id/relative_path/sha256/file_size_bytes/observed_record_count/source_kind/evidence_level；没有加入现有 27 字段 Manifest。
- [`eos_system/scenario_artifacts.py`](../../eos_system/scenario_artifacts.py)：只读 Python 核验函数。
- [`scripts/verify_scenario_artifacts.py`](../../scripts/verify_scenario_artifacts.py)：只向 stdout 输出 JSON；无输出文件参数、目录登记、API、数据库或发布调用。

所有文件以完整 SHA-256 + 字节数锁定。Scenario 节点 id/registry_id 为原内容型 `s{S}_m{M}_t{days:g}d_{sha}`；scenario_id 在本索引中明确是内容身份，不是已实现的 API 路由。internal_scenario_id 与原 filename/文件 stem 分开保留，绝不改 JSON 内部 ID。

路径对象的 `kind=repo_relative` 只接受仓库根下的规范 POSIX 相对路径；`kind=local_evidence` 必须有显式根名称+相对路径，调用方绑定根后才能读取。原路径/规范化路径都记录；`original_path` 是历史/本机位置证据，解析器从不自动使用它。拒绝绝对相对路径混用、盘符、反斜线、`..`、非规范路径和符号链接逃逸。没有绑定本机根时是 MISSING_EVIDENCE/WARN，不是已核实。

本机 WSL 示例（以下三个路径都是本机证据位置，不是跨开发者默认路径）：

```bash
cd /mnt/d/VC/EOS-Course-Project-registry
PY=/home/meteor/eos-course-runtime/venv/bin/python
"$PY" -B scripts/verify_scenario_artifacts.py \
  --evidence-root epoch_acceptance=/home/meteor/eos-course-runtime/epoch-acceptance \
  --evidence-root e4_audit=/mnt/d/VC/EOS-Course-Project/docs/phase2/e4-review-20261017-124539 \
  --evidence-root reference_docs=/mnt/c/Users/流星/Downloads
```

其他机器须将已核实同 SHA 档案配置为自己的根；也可不绑定，只检查仓库可用项并保留 WARN。该工具复用现有 Manifest 的 streaming/bounded reader 做静态投影，未改 Manifest。大于 16 MiB 的 Legacy 需要 ijson（当前 WSL 已有 3.6.0），缺包时拒绝读取而不是截断/伪造通过；本轮没有安装依赖。推荐在项目指定 WSL Python 中核验大文件。

## 3. Raw 实际清点

`input/**/*.json` 共 30：20 份卫星配置、10 份城市坐标。`input/scenario_splitter.py` 是工具源码，不算 Raw 数据；100 星及 200/500/1000 星只有 Raw 配置，没有凭空增加 Scenario Artifact。

observed_record_count 来自实际 JSON 顶层记录数，不把文件名数字当已认证来源；没有为文件伪造 imported_at、上游数据集、历史生成 seed。

| 仓库相对路径 | 类型 | 实际记录数 | 完整 SHA-256 |
|---|---|---:|---|
| input/1000_satellites.json | raw_satellites | 1000 | `90aa02509deb1651808af91af27d6535f70e3458beb6240afa56b40c762d5128` |
| input/1000_satellites_100_10.json | raw_satellites | 1000 | `a47cb35730401e69eb4307e7e7a3c6f765af3e2fe337b7a5316c19e0161eda3d` |
| input/1000_satellites_10_100.json | raw_satellites | 1000 | `75f70962a944bd658dbe7856283a2b1e15e26c7c63bbef3703e89c891614bd80` |
| input/100_satellites.json | raw_satellites | 100 | `62b26da976a3347d9fa2e9af9d47bd0d337371f424b5a4033fdc79225bcc1b6a` |
| input/100_satellites_20_5.json | raw_satellites | 100 | `325f0b8e77231a168a7eec782b4087cdf750b2759f6bb8987028c14c735d6e54` |
| input/100_satellites_4_25.json | raw_satellites | 100 | `9e055b1076c81b12bbff7410812a9118bf0cbd1165bd26822fd674c500413f69` |
| input/10_satellites.json | raw_satellites | 10 | `c707ee30417d7e1a0448b644f90d6595235ae4cc8262fa2645f5f85d1fadc241` |
| input/1_satellites.json | raw_satellites | 1 | `2130d62f90de12fa060c5b1b69d76ac774176b87b42823dfa8b2ff610f4228d4` |
| input/200_satellites.json | raw_satellites | 200 | `e92c213b9183fdecd4598449435e62cc75256eecf3d6d56b203e0a3c41bda4fd` |
| input/200_satellites_10_20.json | raw_satellites | 200 | `db2b4b76ba52c12c4822e928e1f82867679f3240b325f002bdcdbccbf537942c` |
| input/200_satellites_40_5.json | raw_satellites | 200 | `8e8fa7732e2522b565f2ff86bfaaeea60b91403128aa1cd5cc0a5daa2ac0ac7a` |
| input/20_satellites.json | raw_satellites | 20 | `6158d5a05cc413e39aaf4f239084f66f34b52e1b2634596d05bb118ed5e8225e` |
| input/3_satellites.json | raw_satellites | 3 | `2dc436ea844835c72e192faccd7a05d6f4baea8c38a34069c3a4d280e0472342` |
| input/500_satellites.json | raw_satellites | 500 | `4a931544044fe53cc3b7e8451939a952d695620d6c5979fdf94477dd5a1a9159` |
| input/500_satellites_10_50.json | raw_satellites | 500 | `300a39cf0c264ad8b7d4dabeb06359be8e4d4d0716a24ae2f3df5ac0db206946` |
| input/500_satellites_50_10.json | raw_satellites | 500 | `258d724ae7cefd4d1583c51df4bc4f4030f6171b7f0de4313df1b732445583eb` |
| input/50_satellites.json | raw_satellites | 50 | `b84dcc5e6bb6285ae2de48df967f475ef3780b582d9b248ab95300042a2a32a1` |
| input/50_satellites_25_2.json | raw_satellites | 50 | `016ae03b64e968c5e85c6579d5cdb58e53670ef56dd26e2e524e955036ab01fe` |
| input/50_satellites_5_10.json | raw_satellites | 50 | `30085f00d7fcea494e4d6af95071f279e45b76ab546d02235447170d339710fb` |
| input/5_satellites.json | raw_satellites | 5 | `bf5f0b79ebf04c620466e444e8773cedeec09b4752950cbc4fbbe81ec83e2b03` |
| input/cities_data/cities_01.json | raw_cities | 100 | `ba5b91c509b85a29a751e1b2323772dc7e068bcaf5f4348c2f4f6863252962d2` |
| input/cities_data/cities_02.json | raw_cities | 100 | `b55baca348f1bdd3c34407f262e0495aeac32ebae7ce4c5eab3c39a53e874d55` |
| input/cities_data/cities_03.json | raw_cities | 100 | `b33fdc41f3c085d88e645ebe320772d53be2970b08575ce44fe4c829f302bd72` |
| input/cities_data/cities_04.json | raw_cities | 100 | `70f9a7d2d3af33f13c00975857e6174f928ef90b2c9a0ebad3f44536da8490b3` |
| input/cities_data/cities_05.json | raw_cities | 100 | `0183e1761b28deed2dc6fd55e654a781f9b822d62214dc3239415e6d7d17dd5b` |
| input/cities_data/cities_06.json | raw_cities | 100 | `9707e728cc97b59468f49b299f9cecd187444e2e95412df427ae3031c7f35bd0` |
| input/cities_data/cities_07.json | raw_cities | 100 | `206b2c2fae16848324bb834388e0bf50c344020a554370c5bc7f31515619f67b` |
| input/cities_data/cities_08.json | raw_cities | 100 | `2944ac015f5ab80034a0b9d1d619e5a99efb0f63064444c1092a5b287650f79a` |
| input/cities_data/cities_09.json | raw_cities | 100 | `af5e749f7b3f69fc23262bdaa74ef9692ad3c7b3f5bd9c706aa65c407bfb5733` |
| input/cities_data/cities_10.json | raw_cities | 100 | `6884bc3d4c8ef6099095e270c4244e6b3538ce9f1397bec20fe3ad9cc0c3c029` |

## 4. 十个 Scenario Artifact 的完整覆盖

六份 Legacy 的文件路径均在当前工作树 experiments/scenarios，实测为完整 JSON，不是 LFS 指针；四候选只读取 WSL 原位档案。没有复制场景到 Git、改名、覆盖或重新生成。

| 类型 / 原文件名 | 完整场景字节 SHA-256 | 静态字段 SHA-256 | 状态 |
|---|---|---|---|
| legacy / Scenario_S1_Sats50_M100_T3.0d_dist1.json | `58b12c20a0c933736fc6005d947e359b0dac1b309d10eac003b49e8fb211b929` | `5b66c338c323dd822708bb5ed8dfc88a34fbb13807628f13682fb25a1392e7a1` | legacy_readonly |
| legacy / Scenario_S2_Sats50_M100_T3.0d_dist0.json | `665ac26c011a57ec1743910ebf63946e5a0f626bf13a63b2e71a9e65b7c748b7` | `7e44e38301e4c919dff2a7d25b02b8078feeea62cd44f9a68631818aca542fcd` | legacy_readonly |
| legacy / Scenario_S1_Sats10_M20_T1.0d_dist1.json | `d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc` | `c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295` | legacy_readonly |
| legacy / Scenario_S1_Sats20_M20_T1.0d_dist1.json | `99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e` | `180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b` | legacy_readonly |
| legacy / Scenario_S2_Sats10_M20_T1.0d_dist0.json | `04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5` | `2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68` | legacy_readonly |
| legacy / Scenario_S2_Sats20_M20_T1.0d_dist0.json | `fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5` | `1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f` | legacy_readonly |
| candidate / Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json | `bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295` | candidate_only |
| candidate / Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json | `86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b` | candidate_only |
| candidate / Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json | `f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68` | candidate_only |
| candidate / Scenario_S2_Sats20_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json | `ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f` | candidate_only |

静态 SHA 的版本为 exclude_two_window_fields_canonical_json_v1：只剔除顶层 observation_windows、communication_windows，保留所有其余字段/未知字段，JSON ensure_ascii=false/sort_keys=true/紧凑分隔符/拒绝 NaN 后 SHA-256。它不能替代原文件字节 SHA，也不能用来认证完整 Raw 来源链。

四候选对应的原侧车、E3 Markdown、E3 summary、E3 evidence_index、E4 报告/草案、原批次审核、连续曝光报告全部具有独立证据节点。179 个原 E3 索引文件逐项实测 SHA/大小匹配；索引自身也独立锁定。S1/20 初始 physics_report FAIL 与 refined PASS 一起保留；原侧车 physical/scheduling NOT_RUN 不更新。旧两候选 SHA 明确列入 excluded_intermediate_sha256，没有输入场景集合。

## 5. 已建立与未证实的关系

| Candidate SHA-256 | 对应 Legacy 母场景 SHA-256 | 可靠性 |
|---|---|---|
| `bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc` | DECLARED_CORROBORATED：原侧车声明 + 实测母子字节与静态数据 + E3 支持 |
| `86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e` | DECLARED_CORROBORATED：原侧车声明 + 实测母子字节与静态数据 + E3 支持 |
| `f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5` | DECLARED_CORROBORATED：原侧车声明 + 实测母子字节与静态数据 + E3 支持 |
| `ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5` | DECLARED_CORROBORATED：原侧车声明 + 实测母子字节与静态数据 + E3 支持 |

另外六条 Legacy → Raw 卫星配置边全部为 raw_input_hypothesis / FILENAME_ONLY；只表达规模/文件名提示的待核来源，不是已认证派生。城市配置只作独立 Raw 集合，哪份城市文件生成了哪组任务尚未恢复，不擅自连接。Candidate 的 Raw 上游也只继承这条不确定关系。

四候选母子边只证明本次重算 lineage，不能恢复 Legacy 的 seed、原 generator、原始目标/卫星数据导入过程；source_group_id 与 lineage_group_id 不自动等价，全部 lineage_group_id=null。不同规模/母 SHA 不能据此分为独立 ML Train/Test 家族。分布 dist0/dist1 仍只有 filename-only 证据，内部 Scenario_S1/Scenario_S2 跨规模复用仍 WARN。

## 6. B1-01 五项源码追溯补充

必须分开四种身份：

1. 原生产侧车声明的五项实际文件 SHA（工作区代码加基线提交）。
2. 历史 base_git_sha=`84f5bda90e6ba87816a552d41bbf21bd2adfcf0b`；recompute_tool_git_sha=null，不能充当原工具已提交的证据。
3. 当前已合并主线 0c55223 → 4eda1f3 → d0d9325 的 Git 对象与本工作树检出字节。
4. R1-02 审查工具本次源文件 SHA；index.review_tool_identity 不冒充生产版本或已有 Commit。

五项均找到字节完全匹配原侧车的本地 Git 对象（完整候选列表在 source_reconciliation，不仅如下最早/代表对象）：

| 文件 | 原侧车生产 SHA-256 | 实测匹配 Git 对象 |
|---|---|---|
| core/models.py | `4b2f938df07091d28de96dd48f654fbe467ac33d6a0143e8eb13e8a000b2d569` | `e4d82c93135ab6a39d204c48759ca63348d8ccc7:core/models.py` |
| scripts/build_scenario_manifest.py | `ac91b2dad72c8625f1401785a5c82e00a24f58719c80bb29669296249ca3a37d` | `e4d82c93135ab6a39d204c48759ca63348d8ccc7:scripts/build_scenario_manifest.py` |
| scripts/recompute_scenario_windows.py | `1910797d01672e6779121d3b71d17a1b47d632cd783564447fe8a7c98465cfcc` | `e4d82c93135ab6a39d204c48759ca63348d8ccc7:scripts/recompute_scenario_windows.py` |
| utils/time_parsing.py | `66fa6c4fa0371dab4e5cba0707aa5ebf14da6d7b6b2bd61876086ba2786846f9` | `84f5bda90e6ba87816a552d41bbf21bd2adfcf0b:utils/time_parsing.py` |
| utils/visibility.py | `401cf0ae4989af5ac088de9ac9f74dfb58f279018d44b506fa9e61bca0d4aae3` | `e4d82c93135ab6a39d204c48759ca63348d8ccc7:utils/visibility.py` |

状态为 VERIFIED_BYTES_ONLY：取 Git blob 原始字节算 SHA，而非通过控制台文本重编码。恢复的字节与侧车声明一致，是来源佐证；仍没有仅凭 Git 对象证明生产时进程执行了该代码，因此 production_execution_proof 单独记录 NOT_VERIFIED。本轮未找回生产进程本身或伪造工具 commit。

主线三提交的逐文件原始字节 SHA：

| 文件 | 0c55223 blob SHA-256 | 4eda1f3 blob SHA-256 | d0d9325 blob SHA-256 |
|---|---|---|---|
| core/models.py | `57fb855c46dba5e1fa9aacddd8d1afffdddaaa441996445aea6920146301c941` | `57fb855c46dba5e1fa9aacddd8d1afffdddaaa441996445aea6920146301c941` | `57fb855c46dba5e1fa9aacddd8d1afffdddaaa441996445aea6920146301c941` |
| scripts/build_scenario_manifest.py | `7317fdf0926406e301459bf12ef8e2b10316fda45d33fdc2974eeeb6334e00a2` | `7317fdf0926406e301459bf12ef8e2b10316fda45d33fdc2974eeeb6334e00a2` | `7317fdf0926406e301459bf12ef8e2b10316fda45d33fdc2974eeeb6334e00a2` |
| scripts/recompute_scenario_windows.py | `1910797d01672e6779121d3b71d17a1b47d632cd783564447fe8a7c98465cfcc` | `1910797d01672e6779121d3b71d17a1b47d632cd783564447fe8a7c98465cfcc` | `4d4d51a91ce7e34b7a35f45f6f06a267fb3a207ef88e2dc743b91dfeb45e71ca` |
| utils/time_parsing.py | `66fa6c4fa0371dab4e5cba0707aa5ebf14da6d7b6b2bd61876086ba2786846f9` | `66fa6c4fa0371dab4e5cba0707aa5ebf14da6d7b6b2bd61876086ba2786846f9` | `66fa6c4fa0371dab4e5cba0707aa5ebf14da6d7b6b2bd61876086ba2786846f9` |
| utils/visibility.py | `aed8db5eaf86703f3736f80e651854e98f05923b1cfe8203c5050eb16cb846e1` | `aed8db5eaf86703f3736f80e651854e98f05923b1cfe8203c5050eb16cb846e1` | `c003fffdef52ef81b3cd994ac2463142783a5c6519ccb9d490f180b66950c2f2` |

本工作树实际检出字节（换行可与 Git blob 不同）：

| 文件 | 本轮实测字节 SHA-256 |
|---|---|
| core/models.py | `4b2f938df07091d28de96dd48f654fbe467ac33d6a0143e8eb13e8a000b2d569` |
| scripts/build_scenario_manifest.py | `ac91b2dad72c8625f1401785a5c82e00a24f58719c80bb29669296249ca3a37d` |
| scripts/recompute_scenario_windows.py | `fd17c6d10e0a907260a324c31201063815e5ce7cb8c4f56f3a37d8fc90ccc2d2` |
| utils/time_parsing.py | `c0647dbd650fcb477b7247612605cb3b7d6b9fd834a358fa378b6d58eb674b2f` |
| utils/visibility.py | `6e5416cb8d459fc16b87d4c90b4abb7569a5a9887687098cabb5a1540a6a09cf` |

0c55223/4eda1f3 的五项 AST 均与恢复生产 blob 一致，即使某项原始字节因换行/注释不同；AST 相同也不是依赖环境/执行语义的完整证明。d0d9325 的 visibility 与重算工具 AST 已不同，包含连续边界/新派生来源记录等后续修复，应记录为后继实现，不能要求新代码 SHA 冒充旧生产 SHA。其余三项 AST 一致。所有逐文件比较和 AST 结果在索引中逐项记录。

已知实现提交关系来自本地 Git 实测：

- `0c5522363e6b8233cc58064d4a2429a1790b55b9`，父 `daf4254f6a7c3157996ed77ba45278f648a405bf`，fix(e3-e4): preserve replay time semantics and CZML precision。
- `4eda1f3b341eee2a7c2450d51818650f6afe451b`，父 `0c5522363e6b8233cc58064d4a2429a1790b55b9`，fix(replay): reduce orbit interpolation error with true samples。
- `d0d9325759f078ef13f41cc9eee74c5e7733758a`，父 `4eda1f3b341eee2a7c2450d51818650f6afe451b`，fix(scheduling): enforce verified exposure certification。

三者都是单父提交，当前本地证据无法认证各自的 PR 编号或 PR merge commit；pr_number=null，未查询远端平台，不能发明“已知 PR 合并号”。0c 修复时间与恢复 grid/lazy，4eda 修复真实节点插值，d0 加强曝光认证，不改变四冻结 JSON 的历史身份。

## 7. 验证器范围、状态与测试

verify_index(index, repo_root=..., evidence_roots=...) 返回 scope/status/counts/checks/scenario_details；不修改传入对象。checks 同时有 level（PASS/WARN/FAIL）、category（VERIFIED/MISSING_EVIDENCE/CONTRADICTORY_EVIDENCE/INVALID_IDENTITY）、code、subject、reason。缺文件或未绑定本机根为 WARN/缺证据；坏 SHA/文件内容矛盾为 FAIL/矛盾证据；坏 Registry ID、非法路径、悬空引用、错类型关系或旧候选混入为 FAIL/无效身份。状态仅代表只读身份/关系核验，绝非审核批准。

会重算每个可用文件的实际 SHA、大小；场景另流式检查实际内部 ID、规模、内容型 Registry ID、静态 SHA。Candidate 还核对原侧车的结果/母/静态/Registry/complete/原候选状态/源码摘要，检查唯一 Legacy 母边；E3 summary 和连续曝光汇总按真实字段/明确唯一 case 选择绑定 SHA。审核草案仅作为 SHA 锁定的外部证据，不实现其审批 Schema、状态机或授权规则。缺少来源材料不会被静态相等或同名自动补齐。

原始数据、侧车、计划和证据的 SHA/大小/mtime 已在采集前后冻结核对；全部未变。临时日志和副本不进入仓库。

实际 WSL 测试（已有 Python 3.10.12、ijson 3.6.0；无依赖安装）：

| 验证 | 实际退出码 | 总数 / 通过 / 失败 / 错误 / 跳过 |
|---|---:|---|
| unit | 0 | 25 / 25 / 0 / 0 / 0 |
| manifest | 0 | 47 / 47 / 0 / 0 / 0 |
| full | 0 | 371 / 363 / 0 / 0 / 8 |
| real-index | 0 | WARN，checks={'PASS': 275, 'WARN': 28, 'FAIL': 0} |
| unbound-index | 0 | WARN，checks={'PASS': 55, 'WARN': 236, 'FAIL': 0} |

实际运行目录：`/tmp/eos-r1-02-check-l5whrw2o`；summary.json 记录完整 argv、cwd、环境、源码逐文件 SHA；stdout/stderr 独立保存。测试在 Linux 临时副本中运行，所有原已跟踪文件由指定工作树只读复制并逐项 SHA 校验，新模块/CLI/测试/索引字节也锁定；避免 DrvFS 进程启动预算影响。完整默认套件未开启额外 Orekit opt-in 开关，跳过数按实测保留，不冒充这些真实物理集成已运行。

```bash
PY=/home/meteor/eos-course-runtime/venv/bin/python
"$PY" -B -m unittest discover -s tests -p test_scenario_artifacts.py -v
"$PY" -B -m unittest discover -s tests -p test_scenario_manifest.py -v
"$PY" -B -m unittest discover -s tests -v
git diff --check
```

新增合成测试覆盖同名异内容、错误 SHA/Registry、缺本机证据/侧车、错母/源码摘要、静态未知字段变更、静态相同却缺父声明、Raw 假设不可认证、未知 ML 家族、旧候选混入、保持 candidate_only/INCONCLUSIVE、E3 错 subject、唯一汇总选择、路径逃逸/符号链接、重复身份/JSON key、只读字节与退出码。没有打开真实候选运行求解器。

中间记录也保留：Windows 沙箱初次临时文件创建被拒；授权后的 Anaconda 3.13 在 freshly-written 文件上触发原 Manifest/指纹“file changed before opening”，24 项中 20 error；同字节代码 WSL 初轮 24/24 通过。未修改现有 Manifest 指纹逻辑或降低源文件变化保护来消除 Windows 异常，本次受验环境是 WSL。第一版真实报告关联检查因假设连续曝光顶层有 SHA 报 4 FAIL；检查实际 reports[]/summary 结构后修正索引关联，原结果留在临时 real_verification.initial.json。这是索引开发中的映射修正，不是数据矛盾或认证变绿。

## 8. 交付文件、提交条件与下一任务边界

新增六文件：eos_system/scenario_artifacts.py、scripts/verify_scenario_artifacts.py、tests/test_scenario_artifacts.py、data/registry/scenario_artifacts.v1.json、data/registry/raw_input_manifest.csv、本文。只修改 README.md 的文档链接和 COURSE_SETUP.md 的本次简短记录。没有修改现有 27 字段 Manifest、SQLite、Controller/Worker、正式 Registry/发布流程、Raw、Legacy、候选或连续曝光认证结果。

提交 R1-02 的条件：人工审查确认六/四/三十计数、完整 SHA 与只读范围；认可外部未签署规范仅为参考及 Raw 来源不足；本工作树仅含上述文件，git diff --check 和最终输入保护核验通过；至少另一成员审核，涉及索引消费契约由李泽同确认。满足这些条件只能准备代码提交，不能发布候选。**本轮未 git add、commit、push、merge 或创建 PR。**

R1-03 可复用：schema_version/collection_id、registry_id+sha256 关联、独立 evidence id/location/SHA/size、候选母边、分层证据等级、原报告状态与缺字段、load_index/resolve_location/file_sha256/inspect_scenario/verify_index 的只读结果。R1-03 另行制定 review schema/revision、审批/发布分离、缺证据 fail-closed/历史追加规则与审核器测试；R1-04 才能在批准后接入 API/Controller/RunConfig。现有校验 PASS/WARN、原外部草案以及此索引均不能作为自动放行依据。

下一步为人工审核，本轮到此停止，不自动继续 R1-03/R1-04。
