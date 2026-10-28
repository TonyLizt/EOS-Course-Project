# 最终算法兼容更新交接（2026-10-28）

## 1. 本次范围

基于最新 `main` 的 `6f04161`，在 `lzt-final-change` 工作。
按李泽同最终决定，仅更新算法，继续使用原全组统一场景；新交付五场景的登记、目录和导入工具已撤回。
前端、API 请求合同、Controller/Worker、数据库、指标、物理核验与姿态规则均保持主分支实现。
LAVIS 代码、原权重及清单保持原样，不训练、不改场景、不迁移数据库。

## 2. 参考来源与移植边界

远端 `feat/hmt-scenes-10-30-20261028` 的 `e10086a` 只有87个新增场景/工具文件，没有算法修改。
李泽同确认允许参考交付 ZIP 的 `baseline_runtime` 算法快照。ZIP SHA256：
`dc25888d9d4213f61f497d4a7dfed243f3629dfe7527552e9de2a892518e5404`。
整体身份、CRC和691项文件SHA已核对。

快照还包含216份系统差异。本轮只选择搜索机制，未整包覆盖，未合并该分支。
快照的 Score/v2、硬预算执行合同、新物理执行缓存/评分协议未引入。
因此用独立兼容版本号记录成果，不把当前代码冒充发送方的完整部署。

## 3. 算法更新

| 算法 | 集成版本（原生） | 本轮接入 |
|---|---|---|
| DARTIS | `0.5.0-course.1` | 自适应空隙补点；有界单任务撤销续排；可选两任务交换、聚合资源释放/迁移 |
| CAABS | `0.5.0-course.1` | 有界来源网格覆盖；当前计划边界补点；不同已选任务集合的束内多样性 |
| RABAS | `1.2.0-course.1` | 保留任务包竞价；可选共享任务跨星迁移以释放受阻卫星的资源 |
| LAVIS | 保留主分支版本 | 原v4模型及已存在R1公共目标适配继续使用，不改模型推理、特征或物理域 |

公共 Registry 显示版本沿用既有 `+objective-v1` 后缀，表示主分支R1适配；并非本次新增评分规则。
目标、完成率/收益/时效等指标和展示综合分仍按主分支计算。算法内部 Bid、近似松弛度不作为实验指标。

### 新参数

- DARTIS：`adaptive_rescue_positions_per_window=12`、`local_repair_rounds=2`；设为0可关闭。
  两任务交换 `conflict_exchange=false`、聚合资源修复 `aggregate_resource_repair=false` 默认关闭。
- CAABS：`grid_coverage=true`、`dynamic_repair_limit=12`、`diversity_slots=2`；可分别关闭用于对照。
- RABAS：`cross_star_repair=false` 默认关闭；开启后受总时间、检查次数、替代放置数及接受次数限制。
- 各参数由现有注册表自动生成网页控件，已补齐中文说明，不增设页面或新接口。

### 实际修复

- CAABS：锚点恰好填满上限时先返回，避免补网格多生成一个候选。
- RABAS：删除诊断里的内部排序元组。元组包含datetime，会导致真实JSON IPC失败；保留任务、卫星、报价等可序列化诊断。
- 新增来源网格、边界补点、撤销续排、跨星修复、候选上限和诊断序列化回归。

## 4. 代码入口

| 路径 | 职责 |
|---|---|
| `algorithms/deadline_insertion.py` | DARTIS主循环、补点与局部搜索衔接 |
| `algorithms/dartis_repair.py` | 单任务撤销、两种续排顺序与完整重放 |
| `algorithms/dartis_exchange.py` | 可选两任务冲突交换 |
| `algorithms/dartis_resources.py` | 可选同轨聚合资源释放和迁移 |
| `algorithms/conflict_beam.py` | CAABS来源网格、动态补点及束内多样性 |
| `algorithms/auction_bundle.py` | RABAS参数、竞价与跨星修复衔接 |
| `algorithms/rabas_cross_star.py` | 可选跨星共享任务迁移及完整重放 |
| `eos_system/algorithm_registry.py` | 同步算法能力说明；维持现有构造和R1入口 |
| `tests/test_final_algorithm_integration.py` | 新机制及JSON边界的合成测试（非物理证书） |

## 5. 使用与核验

继续在工作台选择已有的“全组统一开发集 eos-course-v1（80份）”，工程物理核验模式；
LAVIS选择原 `lavis-v4-opportunity`。输入目录和运行目录沿用个人环境配置，不写死到仓库。
本次不把新的Nadir场景用于旧模型，不把旧manifest改写为兼容证明。

原生算法可选机制与R1整体预算共享：有限搜索未必覆盖全部候选，不能据少量兼容验收宣称全面性能提升。
工程曝光采样通过仍不等于严格连续区间认证。

本轮无自动commit、push或PR；组长先测试，随后明确授权再提交。

## 6. 实际验收

定向回归：172项，失败0，错误3，跳过1；跳过原因按真实日志保存。

扩展检查中的3个错误均为MIP缺少PuLP依赖，并非更新算法失败；本轮未安装依赖或修改MIP。Windows Node另行验证19个实际算法Schema通过，RABAS注册/新进程导入两项通过。

原80场景四档规模代表验收：20/20成功，单Worker、seed42、每算法10秒；包含三传统算法、原LAVIS v4和FCFS。

| 场景 | 算法 | 状态 | 完成任务 |
|---|---|---|---:|
| EOS-G0001 | fcfs | SUCCEEDED | 16 |
| EOS-G0001 | dartis | SUCCEEDED | 16 |
| EOS-G0001 | rabas | SUCCEEDED | 16 |
| EOS-G0001 | caabs | SUCCEEDED | 16 |
| EOS-G0001 | lavis | SUCCEEDED | 16 |
| EOS-G0026 | fcfs | SUCCEEDED | 33 |
| EOS-G0026 | dartis | SUCCEEDED | 33 |
| EOS-G0026 | rabas | SUCCEEDED | 33 |
| EOS-G0026 | caabs | SUCCEEDED | 33 |
| EOS-G0026 | lavis | SUCCEEDED | 33 |
| EOS-G0062 | fcfs | SUCCEEDED | 32 |
| EOS-G0062 | dartis | SUCCEEDED | 32 |
| EOS-G0062 | rabas | SUCCEEDED | 32 |
| EOS-G0062 | caabs | SUCCEEDED | 32 |
| EOS-G0062 | lavis | SUCCEEDED | 32 |
| EOS-G0076 | fcfs | SUCCEEDED | 62 |
| EOS-G0076 | dartis | SUCCEEDED | 62 |
| EOS-G0076 | rabas | SUCCEEDED | 62 |
| EOS-G0076 | caabs | SUCCEEDED | 62 |
| EOS-G0076 | lavis | SUCCEEDED | 9 |

JSON、逐任务CSV、比较计划接口及统计CSV/ZIP已真实调用；这是兼容验收，不是全80场景性能矩阵。

本轮10秒短预算下，LAVIS在EOS-G0076完成9/80，其他受检算法62/80；成功表示核验/存储链路可用，不表示效果相同或学习算法领先。此轮按要求保留原权重和候选策略，没有为追求成绩改训练或数据。正式展示可沿用原60秒协议，若要评价新算法提升需另做同条件成对比较。
