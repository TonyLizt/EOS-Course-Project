# 统一调度控制台与精确 Gantt（2026-10-17）

## 页面设计和数据边界

首页沿用单页深色控制台：左侧共用实验条件及逐算法参数编辑器，右侧为条件分组比较、可分页历史和单次 Run 详情。算法详情使用原生模态 dialog，支持 Escape、焦点约束和返回触发按钮。窄屏依次堆叠，长表格在自身区域滚动。

- `/api/algorithms` 是唯一算法清单。当前仅注册 `completion_first baseline-1` 与 `adaptive_repair baseline-1`；Factory 中的其他实现没有被擅自发布到正式运行接口。详情的策略、目标、限制来自这两份实际实现。
- 勾选一个或多个算法，一次提交逐项调用既有 `POST /api/runs`。HTTP 请求顺序提交，计算仍由 Controller 的既有有界 Worker 队列决定并发；每项独立 Run ID。部分提交失败不会撤销已接受任务，逐项显示可重试原因。
- 参数 JSON 按算法分别保留，详情展示注册表参数 schema；所有参数仍由注册表、RunRequest 和 Controller 校验。种子、预算、约束、目标权重为批次共同快照。两种算法均采用固定策略，页面明确说明权重不改变其核心目标。
- 比较最多 12 个 Run，支持历史分页勾选及本批自动加入，选择仅保存在当前浏览器 sessionStorage。不是新的服务端批次对象；不同浏览器不共享批次。
- 每个 Run 的状态、错误、配置、事件、TP/TCR/BD/TM/RT/RV、完成及未完成任务数都从现有 API 读取。取消沿用原接口。算法详情可查看当前定义和历史固化版本／参数，二者分开显示。
- Gantt、Cesium、导出继续使用原 Run 路由；没有计划可用时不展示会被后端拒绝的导出和可视化操作。历史 SUCCEEDED 不冒充当前连续认证通过，连续认证状态单独显示。

## 比较口径

`comparison.js` 按以下共同条件分组：场景 SHA、物理版本、算法/共享约束代码摘要、约束参数、放置策略、种子、预算、目标权重、指标 schema，以及已有连续认证状态/版本/证据类型。缺少基本身份的 Run 单列。算法名称、版本和专属参数逐 Run 展示，允许为对照变量；预算不同等共同条件差异会形成不同组。

TP/TCR/BD 越大越好，TM/RT/RV 越小越好。TM 是 `timeliness_utils.timeliness_metric` 的归一化等待值，不是 `1-TM` 得分；未完成任务记入整个周期等待。RV 无多次收益样本时保持空值。仅同组至少两个成功记录标记单指标最佳值及并列；INCONCLUSIVE 记录不标最佳值。没有新增综合分数、全局最优标签或单种子统计显著性结论。

`scenario_catalog.py` 为自定义和正式派生场景补充规模摘要，复用静态场景投影、按 SHA 缓存小摘要，内置清单已有规模不重复扫描窗口数组。物理版本和验证状态从当前 provenance 读取，UNKNOWN 不变成 PASS。注册、SHA 重验及正式发布门禁保持原逻辑。

## Gantt 根因与交互

旧实现只有 `button.title` 原生提示，没有应用级 Tooltip 或可点击详情。原生提示依赖浏览器的鼠标停留规则，键盘和触屏无法可靠读取；同时 `Math.max(widthPct, 0.5)` 与 `min-width:24px` 把短任务强行扩宽，同一行邻近任务可能覆盖，指针命中后画的任务。整图按固定跨度显示，只提供两个分钟级端点标签，没有放大、平移或定位机制。

另用旧版页面和一天跨度的三条微型记录做了 Chromium 复现：M1 的显示宽度被扩成 24px，指针位于 M1 矩形中心时 `elementFromPoint` 实际命中 M2；页面没有 `role=tooltip` 元素。这证实了邻近短任务覆盖与缺少显式详情的组合问题；不能据此声称所有浏览器的原生 title 均失效。

现在由 `timeline.js` 处理纯 UTC 解析和时间窗口计算，`gantt.js` 渲染当前窗口：

- 实际任务条宽度严格按原始起止时间映射，裁剪只发生在可视边界，不设置伪造的最小时长。全周期下可能为亚像素细线，通过任务选择器可直接放大。
- 悬停/焦点出现显式 `role=tooltip`；Escape 关闭；点击、Enter 或触摸固定下方精确详情。详情包含卫星、任务、开始、结束、持续时长和可用的优先级。
- 放大/缩小按钮、半窗口前后平移、全周期恢复、筛选任务范围、UTC 起止输入及全周期位置滑块。
- 任务选择自动聚焦包含前后余量的秒级窗口。卫星筛选和文本搜索支持任务/卫星定位。时间轴区域支持 +/-、左右键和 Home。
- 时间刻度根据可视跨度与实际像素宽度自适应到天、小时、分钟、秒，完整日期始终可见。同卫星真实重叠的观测分层显示。
- legacy naive 时间按 UTC 解析，与 Cesium 保持一致。仅改变视窗，不修改 Schedule、算法、轨道、姿态或指标。
- `/visualization/gantt/{run_id}` 继续重定向至原页面；静态资源由 `/static` 提供，同时保留仓库根 `http.server` 的 `/draw/gantt_viewer.html` 入口。

## API 与数据库影响

没有新建运行端点、数据库表、IPC 消息或 Controller 状态。只有两个已有 GET 响应增加字段：

- `/api/algorithms.items[]` 增加 `strategy/objectives/limitations/availability`。
- `/api/scenarios.items[]` 对可读取场景补齐 `satellite_count/mission_count/duration_s` 与 provenance 状态；读取失败时 `availability=invalid`，并给出 `validation_message`。

浏览器批次无事务语义：队列满时允许部分成功，用户可按逐项结果单独重试。比较不是重复种子实验协议的替代品。

## 定向验证与限制

- Node：`node tests/console_timeline.test.cjs`，5 项通过；覆盖公平分组、参数对照、指标方向、缺失 RV、UTC 解析及缩放后原始曝光不变。
- Python：`test_console_catalog` 的 2 项，以及 `test_system_v02.RegistryTests`、`test_scenario_scale.CatalogTests.test_list_explains_missing_pointer_and_corruption`、`test_http_submission_rechecks_sha_even_after_cached_listing`，合计 5 项通过。未跑全量测试或场景重算。
- Chromium：`tests/browser/serve_console_fixture.py` 配合 `console-gantt-smoke.cjs`。使用临时数据库；验证单次和两算法批次 POST、独立 Run ID、真实 Worker 终态、两条成功历史的分组和指标、算法 dialog、详情与原可视化链接、轮询焦点、秒级缩放和平移、Hover/键盘、日期范围、窄屏和触屏详情。
- 成功历史数据使用显式 `UNIT_TEST_INJECTION_ONLY` 测试 receipt，并在同一 QA 进程种入。它仅验证 UI 的成功结果分支，不构成真实物理认证或真实求解成功证据。新提交使用真实 Controller/Worker、未经替换的门禁；无来源证据的微型输入被正确标记 FAILED，错误可见。
- 现有生产连续认证门禁在缺少可信窗口/连续证据时拒绝计划。本次未放宽该门禁，不能据本轮 UI 验收宣称新真实场景已通过求解及认证。没有运行大型仿真、真实 Cesium GPU 回放或全部算法实验。
- 测试机器缺少中文系统字体，截图中文字显示受限；DOM 中的中文文本、标签和交互已验证。未宣称通过完整 WCAG 审计。
- 本次分支基于已合并的 `f230c3b`；原工作区较旧且有大量未提交改动，因此保留原目录，使用独立 checkout 交付，避免覆盖其他成员工作。

复现（路径均可替换）：

```bash
PYTHONPATH=tests python -B -m unittest test_console_catalog -v
node tests/console_timeline.test.cjs
python -B tests/browser/serve_console_fixture.py --coord /tmp/eos-console-qa.json
# 另一终端，安装现有 Playwright 后：
EOS_BROWSER_QA_COORD=/tmp/eos-console-qa.json node tests/browser/console-gantt-smoke.cjs
```
