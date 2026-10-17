# 统一实验、算法比较与可视化交互交接

> 后续 UI 修订：比较现仅保留按算法/按实验，两种均可勾选与组内排序；新增算法改为复选确认；Cesium 待添加列表不重复显示已有算法；修复 Hide/Show Grid。以下三模式描述为初版历史，当前行为见 [UI 修正交接](ui_polish_handoff.md)。

日期：2026-10-18。分支：`feat/unified-experiment-interactions`。本轮只本地提交，不 Push/PR，不操作用户 8765 服务，不改调度核心、姿态、轨道或连续认证门禁。

## 用户操作

1. 首页选择场景和初始排程模型，勾选算法。合并原“算法参数编辑对象”和“本批运行算法”为唯一卡片列表：勾选决定参与，右侧三角独立展开说明和参数，支持键盘及 aria-expanded。没有独立“参数/说明”按钮。
2. 一次提交创建一个持久 Experiment，算法各有 Run ID、参数、状态、日志、指标、计划及回放。列表仅一行，实验 ID 为入口，日期不再是突出按钮。名称使用注册元数据，不显示内部运行后缀。
3. 进入实验后比较其活动算法。可直接创建对照实验，复用全部条件及算法参数，仅切换初始排程模型；新 Experiment/Run ID 独立，原结果保留。服务端再次验证场景 SHA、代码/约束、预算、种子、算法参数等一致性，不允许通用条件组混比。
4. 比较模式共用一个数据集：按算法把相同算法相邻展示；按实验保留实验及内部顺序；混合可勾选结果并上下移动。不为失败或无有效计划的记录展示成功指标，不计算综合评分。初始模型对不同算法的实际作用见注册说明，不能假定每种算法都使用初始解。

## Cesium：原布局内增量

在原 Metrics 下、Display Controls 上增加实验区；主地球、Fixed Payload View、Observation Intervals 和时间控制仍使用原页面。当前算法卡片可切换回放、展开说明/参数和确认移除；全注册列表保留已加入算法的灰色禁用提示，新增算法可以配置参数并加入同一实验。移除只停用关联并按原取消协议处理，不删除历史结果；重新添加生成新 Run。

算法比较表高亮当前 Run，支持上述三种组织方式和合法模型对照。切换通过原 Run 路由完整加载对应页面，所有 Schedule、Replay、Metrics、Intervals、Gantt URL 指向同一 Run，避免旧异步请求跨算法覆盖。仅在同一实验且时间有效时尽力恢复时间、倍速及暂停状态；不承诺保留主相机或载荷选中状态。没有新增外层 iframe，没有新增主相机更新器。

## Gantt：真实时间不变

在同一卫星轨道行内按鼠标到真实任务条矩形的距离命中，阈值 12px。精确命中优先，其次距离和中心距离；完全等距且无法区分时不任意选邻居。吸附只改变命中判断及轮廓反馈，不扩大绘制条宽或修改时间。离开范围、滚动、缩放、Escape 清除吸附。保留原 Tooltip、点击/触屏固定详情、键盘焦点、搜索、缩放与平移。返回 Cesium 和打开 Gantt 均沿用实际 Run ID。

## 模块与接口

- `experiment-ui.js`：共享算法名称、卡片/三角、结果表和三种比较排序。
- `console.js`、`app.js`、`index.html`、`style.css`：实验列表、统一配置、对照、详情及比较。
- `cesium-experiment.js/css`、`draw/cesium_viewer.html`：原侧栏内算法管理、比较、Run 导航与有限时钟恢复。
- `timeline.js`、`gantt.js/css`、`draw/gantt_viewer.html`：纯命中算法、吸附交互与反馈。
- `gantt-runs.html/js`：以实验为单位展开算法结果入口。
- 数据、事务、迁移和新增 API 见[实验管理交接](experiment_management_handoff.md)。原 Schedule/Replay/Gantt 数据源、WorkerIPC 与算法注册 ID 不变。

本次涉及的首页、详情、算法配置、实验比较、Gantt 选择入口及后端面向用户错误统一为简体中文；原英文、技术标识和用户历史数据未改写。

## 实际定向验证

- Python：27 项通过，涵盖原子提交/回滚、幂等、移除/取消/重加、模型对照及并发重验、备份迁移、算法/预览门禁和 CLI。
- Node：11 项通过，其中新增 4 项覆盖比较范围/排序、不变性、无效计划、三角语义和吸附边界/密集歧义。
- 真实 Chromium + Cesium 1.136/SwiftShader、2 星合成夹具：无外层 iframe；原地球和两星载荷视图存在；验证三角键盘操作、一个实验多算法、三种比较、对照复制、算法新增/安全移除、回放切换后 RT/Intervals/各 URL/高亮一致、5 秒短条吸附/详情/缩放/导航，以及移动端首页无横向溢出。捕获到的浏览器错误为空。夹具明确使用测试认证注入，不代表正式物理认证。
- 真实已发布小型 S2 场景（10 星/20 任务），规划预览：profit_first、timeliness_first 两算法及另一个初始模型的对照，共 4 Run 均完成 20/20、TCR=1；严格对照接口返回 200，正式导出保持 409。复用已成功实验，只计算必要的两组，不做全面 Benchmark。

测试入口：`tests/test_experiments.py`、`tests/experiment_interactions.test.cjs`、`tests/console_timeline.test.cjs`、`tests/browser/console-gantt-smoke.cjs`、`tests/browser/planning-preview-smoke.cjs`。浏览器夹具与真实预览分离，不能把合成数据当作物理正确性证明。

## 限制与启动

- 当前环境 7 种算法可用；MIP 缺 PuLP/CBC，PPO 缺 PyTorch/可信模型与共享约束接入时保持禁用，不伪造执行。
- 无批次证据的历史 Run 作为独立 legacy 实验保留，不按日期猜测合并，也不作为公平单变量对照。
- 未执行完整 WCAG 审计、实体触屏测试、50 星长时 GPU/内存测试；不宣称覆盖这些场景。主载荷渲染、姿态物理和调度质量不是本轮修改范围。
- 程序位于独立 worktree，根目录启动器会跳转。用户需自行停止旧服务后重新启动；热刷不能更新旧进程的后端路由。启动时数据库升级至 v4，先做不覆盖旧备份的在线备份；旧 v3 程序不能直接打开升级库。

```bash
cd /home/asus/projects/eos-course-runtime
EOS_SCENARIO_DIR=/home/asus/projects/eos-course-runtime/experiments/scenarios \
/home/asus/eos-course-runtime/.venv/bin/python -m eos_system
```

之后打开 `http://127.0.0.1:8765/` 并强制刷新。本轮没有启动或停止该端口的用户服务。
