# 全组统一场景数据与统一工程物理核验交接

日期：2026-10-18。状态：100份完成、压缩分包完成；公开80份已接入本地后端，四档实际实验/导出通过，示例回放READY。未提交或推送Git。

## 1. 这次的验收口径

李泽同确认日常无需并列“规划预览/正式认证”两个模式。首页改为单一 `physical_validation` 流程：统一约束、来源窗口恢复、资源、转向检查及真实 Orekit 全曝光 0.05 秒含端点采样全部通过，才能保存计划/指标、导出和回放。

这叫**工程物理采样核验通过**，不叫严格连续区间证明。结果 JSON/CSV 明确包含 `SAMPLED_PHYSICAL_PASS`、`physical_validation` 和核验范围；`continuous_certification.status` 仍为 `NOT_CERTIFIED`。真实采样发现不可见点时拒绝；不能声称有限采样排除了所有采样间隙。

历史 `formal` 请求和记录保持原连续认证门禁；`planning_preview` 旧接口保留兼容。两者不再作为首页新建实验选项，也不把旧失败结果回填成成功。旧API默认值仍保留兼容，新接入方请显式提交 `execution_mode=physical_validation`。

## 2. 数量、来源和划分

| 档位 | 卫星/任务 | 时长 | 训练/开发 | 验证 | 最终测试 |
| --- | --- | --- | --- | --- | --- |
| P10-20 | 10 / 20 | 1天 | 15 | 5 | 5 |
| P10-40 | 10 / 40 | 1天 | 15 | 5 | 5 |
| P20-40 | 20 / 40 | 1天 | 15 | 5 | 5 |
| P20-80 | 20 / 80 | 1天 | 15 | 5 | 5 |
| 合计 | 100份 | | 60 | 20 | 20 |

每档 dist0/dist1=13/12。采用固定卫星输入、固定2025-11-18 UTC起始的公共时域，独立生成100个新任务集合；不是旧任务裁剪、窗口拷贝或重命名。共享星座关系明确记录，不宣称跨星座泛化。位置、优先级、需求时长分别由明确记录的本地随机流控制。优先级1–10、曝光5–15秒；不筛掉零窗口任务，不根据算法成绩补抽任务。

公开80份（60开发/20验证）的完整集合按来源组划分。20份最终测试采用私有独立种子重新生成并冻结，不登记在日常后端，不提供给算法开发调参。公开脚本可推导的初版试制测试已替换并清理；公开80份的原始字节和划分未改变。四算法、参数及ML模型冻结后再由数据负责人统一执行。

## 3. 文件位置与交付内容

实际数据：`<EOS_RUNTIME_DIR>/datasets/eos-course-v1/`；压缩包位于同级 datasets 目录，公开开发和私有测试分开。实际个人路径仅写本机交付说明，不写入仓库。

```text
 datasets/
 ├─ eos-course-v1-development.zip       # 发全组：80场景及60/20划分
 ├─ eos-course-v1-final_test.zip        # 交数据负责人保管：20冻结场景
 ├─ eos-course-v1-archives.json         # 文件大小及SHA-256
 └─ eos-course-v1/
    ├─ dataset_spec.json               # 完整私有规格；不公开测试种子
    ├─ README.md
    ├─ splits/                        # 60开发/20验证，原始SHA与来源组
    ├─ development/
    │  ├─ scenarios/                  # 只登记这一层；来源侧车在provenance/
    │  ├─ generation_configs/
    │  ├─ generation_source/           # 实际生成代码逐字节快照
    │  ├─ delivery_manifest.csv        # 80行，不含表头
    │  ├─ lineage_manifest.json
    │  ├─ checks/                     # 结构、片段检查及逐采样测量
    │  └─ manifest_basic/             # 复用原27字段工具
    └─ final_test/                     # 对应20行；另含test_freeze.json
```

公开包不包含测试目标、测试种子或完整100来源分配表。私有原件和完整规格由数据负责人保管；代码与公共说明可共享。大型JSON、数据库和训练数据不提交Git，仓库只保留脚本、公开小型规格/拆分与交接说明。

## 4. 生成与检查方法

- 静态卫星能力可复用现有模板，但逐颗核对原始 `input/10_satellites.json`、`20_satellites.json` 的六根数/Epoch与ID；旧任务和窗口全部丢弃。配置保存真实原始输入SHA及静态模板来源。
- 原Epoch解析器严格解析，不回退当前时间。模型为原有 Orekit Keplerian / WGS84 / ITRF / TargetPointing 和已有姿态限制，阈值仰角5度。
- 完整一日10秒网格计算，不做可能漏掉未采样长窗口的粗区间跳跃。所有卫星共享同一Orekit位置网格，只用等价地面仰角公式筛掉明确不可能点；临界点交回原始Orekit。可见网格点继续求真实姿态，退出边界由原二分函数细化至1微秒。
- 10秒网格仍可能漏掉短于步长的通过；边界细化不是连续证明。该代价和步长写入规格，不冒称旧1秒扫描精度或论文原始重复实验。
- 每场景最多10个按固定顺序均匀选定的片段；放得下完整需求曝光才检查；0.05秒含端点重新传播和求姿态。保存测量时间、仰角、姿态、阈值、源码/数据SHA及未完成连续证明的状态。
- 无地面站，因此没有地面站/下传覆盖；零窗口任务保留。缺少窗口本身不是丢弃任务的理由。
- 原始场景生成后保持只读。补充测量报告只写派生 checks 文件；压缩包和校验清单同步更新。

## 5. 系统接入与协作

1. 解压公开包到各自运行目录，复制场景时同时复制 `scenarios/provenance`。核对压缩包和场景SHA。
2. 网页目录管理只登记 `development/scenarios`；选择“全组统一开发集 eos-course-v1（80份）”。无需把100份写入原内置六场景清单。
3. 以 `source_id + scenario_id` 提交实验，算法、初始模型、参数、预算保持原接口；新代码显式传 `physical_validation`。
4. 成功记录走已有 SQLite plans/assignments/metrics 事务；事件为 `PHYSICS_VALIDATED`，不伪造 `CONTINUOUS_CERTIFIED`。无需数据库schema迁移。
5. JSON和CSV导出、目录输出、Gantt、Cesium和临时模型对照保留。历史预览仍按原语义显示，历史严格认证仍检查原凭据。
6. A/B/C仅从共享原场景读取；D只从train_development白名单生成特征和标签，派生文件放 `<EOS_RUNTIME_DIR>/derived/lavis-v1/`。不得递归读取整个datasets把final_test误用于训练。
7. 跨真实源码版本的旧实验不能沿用“仅展示变化”的例外追加算法；应建新实验。兼容白名单未放宽。

## 6. 验证范围

- 四档各1个开发来源，各用 profit_first/balance_first 真实 Worker、IPC、Controller 和 Orekit，共8运行全部 SUCCEEDED；完成任务数分别16/16、33/33、27/27、62/62。JSON/CSV与回放源可用，结果明确未经严格连续认证。
- 同时构造真实不可见曝光，返回 REJECTED / NONVISIBLE_EXPOSURE_START，未作为成功结果。
- 最终合并定向94项通过；随后数据合同8项复验通过，包含新增私有种子不可由公开公式推导的用例（与前次存在重叠）。前端20项通过，比较区文案修改后对应7项再次通过。
- 批量生成器对3个任务与原始Orekit完整全天10秒扫描进行逐窗口、逐姿态数组对照，一致；不把3个任务对照冒称100份全网格独立复算。
- 尚不宣称全算法横向基准、ML训练、最终测试成绩、严格连续认证或全天所有潜在窗口已被穷尽。

## 7. 复现命令

运行环境需按README配置现有依赖；命令中的路径以本机配置替换。生成输出须使用新的、仓库外目录，工具拒绝覆盖。

```bash
python -B scripts/build_shared_dataset.py --output "$EOS_RUNTIME_DIR/datasets/eos-course-v1" --step-s 10 --limit 100 --finalize
python -B scripts/audit_shared_dataset_samples.py --dataset "$EOS_RUNTIME_DIR/datasets/eos-course-v1"
```

本批实际生成代码快照、源码SHA与基线提交一同保存；后续脚本升级不能被当成旧数据的实际生成版本。


## 8. 最终签收结果

- 100个新任务集合，四档各25份；80行公开清单、20行私有清单，60/20/20来源划分和100份源码/配置/检查记录齐全。
- 最终100份的948段完整曝光、185,648个采样时刻通过真实Orekit采样检查；最低实测仰角约5.000506度。未把采样PASS改写为连续认证PASS。
- 每份场景SHA与清单一致；两包ZIP CRC检查及SHA检查通过。公开包不含final_test目录、私有完整规格或私有测试分配表。
- 100份逐场景生成计时合计807.822秒（不含全部流程开销，不作为算法性能比较）；运行目录数据与报告约102.4MB。Windows只额外保存两个压缩包和使用说明，没有再解压一套重复场景。
- 实际后端四档各一条收益优先实验均SUCCEEDED，完成任务数16/20、33/40、27/40、62/80；JSON/CSV和可视化Schedule实际HTTP检查通过。
- EOS-G0001示例回放已构建为READY。Cesium姿态仍是确定性几何示意，非Orekit姿态认证；诊断中未出现转向降级/fallback，保留原有示意与采样频率警告。READY不等于载荷校准或动力学验收。
- 废弃的可预测测试原件、重建目录及受管临时ZIP已清理；原历史实验保留。最终测试不注册、不运行算法成绩、不用于调参。

### 压缩包

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| eos-course-v1-development.zip | 24569481 | `3c012d2050358e58fde8e40a0799d252ef11ad5030bf884ca2b8f2d5c8df4fa2` |
| eos-course-v1-final_test.zip | 6467436 | `5eda9fc30ec0f138cefcccec1de331cb703d0fcd2a60b69a4ef372470c6f2088` |

### 窗口来源兼容规则

新共享数据使用`orekit-window-physics-lf-v1`，对实际窗口几何与Epoch代码进行LF规范化指纹检查，仅消除CRLF/LF差异，不忽略真实代码差异。完整生成部署源码仍以原始字节快照和基线提交保存。Controller/API/Storage更新不会自动使旧窗口失去来源，物理代码变动仍要求重新核对数据。旧Legacy/v2证据规则没有放宽。

公开开发与重新生成的私有测试，分别保存各自实际代码快照及哈希；私有测试调整的是种子保管机制，窗口/物理模型、分布规则和配额一致。包内公开旧源码快照仅证明公开80份的实际来源，其中初版试制测试分配已作废，不能当作最终测试来源。

### 组员操作

李泽同把development包发全组，final_test包仅交数据负责人刘懋兴保管。训练与调参只使用公开60/20划分。核对组员代码已支持physical_validation及新来源规则，再登记development/scenarios；不要在旧正式模式下把NO_CONTINUITY_CERTIFICATE当成数据损坏，也不要手改侧车PASS。
