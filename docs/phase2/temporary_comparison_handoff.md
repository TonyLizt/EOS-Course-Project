# 临时对照、稳定比较与 Cesium 右侧比较区

日期：2026-10-18。分支：`feat/unified-experiment-interactions`。仅本地提交，不 Push/PR；不操作用户 8765 服务。

## 当前交互

比较只保留“按算法”“按实验”。删除手动排序按钮、序号、专属状态/事件和样式；仍可通过复选框选择结果。顺序来自实验活动成员的稳定存储顺序：按实验先正式后临时，各自保留算法顺序；按算法依首次出现顺序分组，同一算法先正式后临时。筛选不改变剩余结果顺序。指标标题的方向箭头仍表示指标优劣方向，不是排序控件。

首页右上角创建按钮现在调用新的临时 API，不再调用持久化 `/control`。创建期间显示“创建中…”，服务端接受成功后变成“移除临时对照”，同时展示 QUEUED/RUNNING/VERIFYING/成功或失败。移除期间禁用重复操作，成功后清除结果、恢复创建按钮。临时模型控件在已有对照时锁定。临时结果明确标注来源，没有 Run 详情/Cesium/Gantt 入口。正式算法集合改变后旧临时对象会被移除，避免不公平比较。

Cesium 左侧 Metrics 与算法管理保留；完整比较标题、选择控件、指标表及当前算法高亮一起移到右侧 Observation Intervals 之后。仅从当前持久实验加载结果，不请求临时 API，不展示临时对象或旧模型对照候选。表格允许必要的横向阅读，取消固定高度的内部纵向滚动。主地球、载荷宫格、任务表、跟随和时间控制未重构。

## 真正的非持久化计算

旧按钮确实通过 `POST /api/experiments/{id}/control` 创建持久实验。本次保留该旧接口作为显式持久化实验的兼容 API，但首页和 Cesium 都不再调用它。

新增 `TemporaryControls` 是受锁保护的 Python 字典，不是 SQLite 临时库或另一套磁盘数据库，不创建数据库连接。服务端重新验证原场景 SHA、来源、代码/约束、算法集合、参数、种子、预算和执行模式，仅改变初始模型；拒绝缺依赖、版本变化或无完整身份的 legacy 来源。

Controller 先处理原正式队列，空闲后从内存队列领取临时任务，保持同一时刻仅一个 Worker。执行方法增加结果接收对象参数，正式路径默认仍是原 Database；临时路径使用字典接收对象。两者共享原 Worker spawn、IPC、身份确认、预算、超时、取消、进程组回收和独立核验。正式路径的调用签名兼容既有测试替身。临时核验同样要求可信 PreviewReceipt 或 CertificationReceipt，不能凭 Worker 自报或随便填入成功指标。

临时完成只保留指标、配置、状态和必要错误，不保留可回放计划，不调用目录导出，不创建 Experiment/Run/attempt/event/plan/assignment/metric 数据库记录，不登记 Replay。临时 Run ID 不存在于正式 API 的数据源中。正式数据库的认证、Earth Occlusion 与指标公式未改变；正式来源失败时如实显示失败，不能自动降级预览来产生可比成功结果。

## 生命周期与容量

- `POST /api/experiments/{id}/temporary-control`：接收 `{schedule_model:...}`，可带 Idempotency-Key，返回内存对象。
- `GET /api/temporary-controls/{id}`：轮询状态，同时续租；默认 90 秒无访问则取消过期，硬上限两小时。
- `DELETE /api/temporary-controls/{id}`：立即从可查询比较对象移除，排队任务取消，运行任务按原协议请求取消；重试删除幂等。
- 最多两个临时对象，活动任务数量受 max_queued 限制；不增加 Worker 并发。正式队列优先，临时任务可能等待。
- 页面切换实验或 pagehide 尝试删除；刷新不恢复临时句柄。即使网络中断未送达删除，续租停止后仍会过期。清理检查在轮询、状态检查、派工及关闭时执行，不引入额外清理线程。
- 删除中的活动任务保留最小内存墓碑供原取消/回收协议使用；终态后清除。核验完成晚于删除时不接受结果。服务重启直接丢失所有临时对象，Controller 关闭前请求取消。整个生命周期没有临时结果文件。

## 文件

- `temporary_controls.py`：字典接收对象、租约、容量、幂等、取消、可信结果接收。
- `controller.py`：正式优先的共享派工、执行/核验接收对象、临时禁止导出。
- `api.py`：冻结条件复核、新 API、启动关闭连接。
- `console.js`、`experiment-ui.js`、`index.html`、`style.css`：双状态操作、临时轮询/清理、稳定筛选及无排序卡片。
- `cesium-experiment.js/css`、`draw/cesium_viewer.html`：比较区移动与仅当前正式实验数据。
- `test_temporary_controls.py`、`experiment_interactions.test.cjs`、`console-gantt-smoke.cjs`：隔离、生命周期和界面回归。

## 本轮验证

- 14 项 Python：4 项临时对象测试及 10 项原实验兼容测试。临时真实 Worker 在同一空小场景执行两个算法，经原独立核验成功；同时将正式 Database.write 替换为抛错，检查八张正式表记录数均不变。另覆盖同请求幂等、无正式 Run/Replay 关联、容量拒绝、来源变化、伪造 receipt、删除中取消、晚结果拒绝及过期清理。
- 3 项原 Controller 定向回归：真实进程取消确认、原成功提交、无合作 Worker 超时回收，全部通过。
- 12 项 Node：5 项共享交互及 7 项时间轴回归通过。验证默认顺序不因传入选择顺序改变、临时成功指标可见但没有持久化链接。
- 一次真实 Chromium/Cesium 两星夹具回归通过：无排序控件，两种模式可筛选；创建后按钮切换、四行对比但正式列表/Run 数不变；删除恢复两行且临时 API 404；Cesium 比较区在右侧 Intervals 下方且无临时结果，高亮及切换 Metrics/Intervals/Gantt 正常；原新增/移除算法、宫格隐藏恢复、Gantt 交互继续通过。页面错误为空。该夹具的历史认证注入仅用于测试，不代表正式物理认证。

未运行大型场景或全面 Benchmark。真实 Worker 的新增临时测试使用空小场景；未声称重新验证复杂观测物理或大规模性能。没有数据库 schema 变更。需用户自行重启旧后端进程加载新 API，然后强制刷新网页。
