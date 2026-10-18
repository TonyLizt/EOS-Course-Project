# Cesium 单层算法比较选择区

日期：2026-10-18。仅局部前端调整，不改数据库、算法、指标、回放加载或页面分栏。

- Cesium 的共享比较组件启用 `compactSelection`，复用新增算法的 `add-algorithm-option` 标签、复选框与选中配色。所有选项直接放在一个响应式 Grid 内，无 Fieldset、Legend、分组边框、重复标题、实验/模型副标题、序号或排序箭头。
- 每项只有复选框与友好算法名，标签整行可点击；保留原 change 事件、焦点恢复、键盘 Space 与 focus-visible 样式。布局根据容器宽度自动换行，最小列宽 190px（窄容器最多占满可用宽度）。
- 选择项采用当前实验的稳定成员顺序；“按算法/按实验”仅影响结果表，不重组选择项。多选状态、原六项指标、当前 Run 高亮和结果表切换算法入口不变。
- Cesium 数据仍来自当前持久实验，比较前排除临时标记与尚无有效计划/指标的 Run；左侧算法管理保留运行中和失败项的原反馈，不受这次筛选影响。
- 首页比较区保留既有结构：共享组件默认不启用紧凑模式，因此临时对照来源说明不会被本轮改动移除。

修改：`experiment-ui.js` 的 compactChoices / comparison 可选模式，`cesium-experiment.js` 的模式启用与有效结果筛选，`cesium-experiment.css` 的单层选择区样式；没有改动 Cesium HTML 布局。

验证：6 项 Node 测试通过；只读 Chromium/Cesium 两星夹具检查单层结构、算法名唯一、标签点击与 Space 切换、多选结果、两种查看方式不重组选择项、切换后 Metrics/Intervals/高亮、右侧比较位置和原两星载荷存在。不重跑调度算法、不创建新实验，不操作用户 8765 服务。

测试文件：`tests/experiment_interactions.test.cjs`、`tests/browser/cesium-comparison-selection.cjs`。隔离夹具中的历史认证注入仅用于交互测试，不代表物理认证或大型场景性能验证。本轮仅本地提交，不 Push/PR。更新后强制刷新页面即可，无新增后端 API。
