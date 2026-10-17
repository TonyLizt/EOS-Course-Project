# Assignment 来源窗口契约 v1（I2 审查稿，2026-10-18）

适用基线：0a1a941。本文描述 fix/source-window-i2 工作树实现，待李泽同确认公共集成影响；不代表已合并、发布或连续认证通过。

## 1. 身份与时间

观测身份为 `(可信 Scenario SHA-256, observation, Loader retained ordinal)`；通信身份为 `(可信 Scenario SHA-256, communication, Loader retained ordinal)`。Loader 在各自命名空间中，按 JSON 遍历顺序对保留的有效窗口从1连续编号。观测编号跨任务、卫星和传感器；通信编号跨卫星及地面站。两类编号可相同，不得互换命名空间解释。

编号取实际 TaskWindow.window_id / CommWindow.window_id，不是历史生成器的全局编号，不读取 JSON 中自行添加的 window_id。改变输入顺序、内容或 Loader 保留规则后，不得跨快照复用身份。没有新造历史 UUID、seed 或历史来源证明。

Assignment dataclass 已有 sat_window_id 和 gs_window_id，本次不增加字段或改变构造签名。JSON 观测行输出 sat_window_id；有地面站时同时输出 gs_window_id。CSV 增加这两列及 orbit_number；CSV 仍是结果表，不是含完整姿态和配置的计划导入格式。完整往返使用 JSON 和可信 RunConfig/Scenario。

有效显式 ID 必须是正整数；布尔、字符串、浮点、null、0和负数均拒绝，不退回时间搜索。没有地面站时，不接受非空通信字段。Loader 使用 naive UTC；带偏移的导入时间归一到同一 UTC，保留微秒。

2026-10-18 P2修正：直接传给公共ConstraintModel的aware Assignment同样先用 `parse_orbit_epoch` 转换到UTC，再去掉tzinfo。观测与通信时间、既有Schedule中参与冲突比较的时间均使用归一后的局部副本；不改写调用方的Assignment、Schedule或Scenario，不改变时间字段契约。不能直接删除非零偏移。

执行和冲突采用既有半开语义 `[start,end)`。来源必须完整包含正时长执行段，终点可等于来源终点。观测须满足现有曝光时长校验、圈号、步长对齐（保留旧 `1e-6` 索引容差）、非敏捷中心及姿态切片规则。下传须严格晚于观测结束，满足可信配置时长比例并完整落在真实通信窗口内；有交集不足以通过。

解析出的来源步长须遵循既有planning规则：有限、严格为正，并能表示为整数微秒；显式0、负数、非有限值及非整数微秒步长不能成为1秒缺省。全局配置缺失或None仍沿用原有1秒缺省，窗口/分组键缺失仍继承上级；已解析TaskWindow中的None不是有效来源网格，窗口/分组显式null仍拒绝。布尔值不得经float转换冒充数值步长。CLI与正式Verifier共用该来源拒绝规则；本次不改变连续物理认证。

## 2. 独立核验

1. Controller 核对实际 Scenario SHA 与 RunConfig 并重新加载文件；CLI 根据实际输入构造身份。两者核对计划场景 ID/时域，拒绝计划或 provenance 中冲突的 Scenario SHA 声明。缺失历史 SHA 不代表历史来源已认证；独立调用方须固定可信输入或使用 CLI expected SHA 闸门。
2. SourceWindowIndex 在一次核验中建立两类编号索引，拒绝重复/无效加载身份，不用全局缓存或首项回退。
3. 显式观测 ID 定位后验证任务、卫星、传感器及所属卫星、轨道、时间、中心/对齐、姿态；资源按可信传感器规格重算。
4. 通信 ID 定位后验证卫星、地面站、时间和下传长度；重建 Assignment 时保留两个实际来源 ID。
5. 共享约束重放。Controller 另外保留 planning_exposure 及连续认证，成功事务、导出和回放仍需原 CertificationReceipt。

公共 ConstraintModel 检查规划 Assignment 的来源编号、归属、圈号、中心/对齐及通信引用。它保留旧内存问题缺少传感器规格的规划容错和既有姿态/转向解析约定；独立 Verifier 仍要求真实传感器归属并完整比对来源姿态。规划容错不是正式核验豁免。窗口包含和规划可行均不能签发连续证书。CLI 普通 verify 仍是 DISCRETE_ONLY，连续入口仍独立审计。CLI 使用默认 ConstraintModel；非默认 RunConfig 应由 Controller Verifier 按可信配置核验。

## 3. 历史兼容与限制

字段缺失才进入历史兼容。观测先按完整来源语义过滤，恰好一个才接受；多个时间包含窗口可以经轨道、中心或姿态消歧。仍有两个等价来源时拒绝 AMBIGUOUS_LEGACY_SAT_SOURCE，不猜当初选择。通信来源不唯一则拒绝 AMBIGUOUS_LEGACY_GS_SOURCE。重建的新官方计划会输出解析所得 ID，不回写输入或历史库。

若两个窗口全部可核验属性相同，任一合法显式 ID 均能指向其真实记录；本契约不能证明生产者当时的内部选择，也不能识别同时重写所有自报字段的意图。它验证引用一致性，不是生成器签名或历史认证。

## 4. 跨模块影响

| 消费端 | 影响 |
|---|---|
| Solver / Candidate Pool / CAABS | 已填写实际 ID；dataclass及solve签名不改，搜索和canonical key不改。自定义Solver须填写真实来源。 |
| Worker / Controller | 复用公共输出及Verifier；IPC信封、取消、状态和发布门禁不改。 |
| API / 前端 | 计划JSON增加来源键，请求模型和路由不改；页面按已知键读取。严格字段白名单消费端需确认。 |
| SQLite / 缓存 | plan_json、assignment_json保存完整对象，不加列或迁移；新增字段进入原计划摘要，形成新缓存身份。 |
| 导出 / 导入 | JSON保留身份，CSV增三列；JSON加载后走同一来源解析。 |
| 部署身份 | 新 source_windows.py 纳入 SOURCE_NAMES；变更部署后须重启，不重标旧证书。 |
| 历史结果 | 原文件、证据和数据库不改；唯一解析与正式认证分别判断。 |

待李泽同确认：快照内 Loader ordinal 的名称/版本管理、显式null拒绝、历史歧义拒绝、CSV增列对外部消费端的影响，以及来源错误的用户呈现。连续物理认证仍是独立闸门。
