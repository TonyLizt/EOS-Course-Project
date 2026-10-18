# 轻量比较筛选与内存临时 Gantt

日期：2026-10-18。仅本地提交，不 Push/PR，不操作用户 8765 服务。

## 界面职责

控制台选择区改为轻量筛选：正式/临时来源与初始模型只在每个来源的标题显示一次，下面是可直接勾选的算法名。没有算法 Fieldset/重复标题，不展示状态、核验、任务数、指标或入口。查看模式只组织结果表，不重建筛选卡片层级。Cesium 继续使用此前的单层名字复选区。

结果表保留算法、短来源标签、初始模型、状态/核验、完成数、TP/TCR/BD/TM/RT/RV 和 Gantt。核验/错误降为小字，指标方向继续以顶部说明为准，不在每个列标题重复箭头。正式结果沿用原 Gantt 路由；已成功核验的临时结果显示“临时 Gantt”，失败/未就绪项不生成链接。

## 原因与数据通道

此前临时服务仅保留指标，完成后丢弃计划；原 Gantt URL 以正式 Run 为入口，所以临时项只能显示纯文本。本轮在 `TemporaryControls.schedules` 字典保留核验后的最小时间轴数据：场景起止及每条任务的卫星、任务、传感器、真实开始/结束和可用优先级。不保留姿态数组、CZML 或可用于完整导出的计划，轮询详情也不夹带任务列表。

新增：

- `GET /api/temporary-controls/{control_id}/runs/{run_id}/schedule`：检查当前临时会话、成员归属及成功结果，返回 Gantt 子集。响应和错误禁止缓存。
- `GET /visualization/temporary-gantt/{control_id}/{run_id}`：检查数据可用后进入原 Gantt 页面，以新的临时 Schedule API 为源，而不是伪造 `/api/runs/...`。

复用原 Gantt 的时间映射、秒级缩放、平移、搜索、12px 吸附、Tooltip 与键盘详情；来源明确标为“临时对照”，没有 Cesium 链接。临时 API 不调用 Database，不写 Experiment、Run、计划、指标或文件，不注册 Replay。原正式 Run/Cesium 路由查不到临时 ID；Cesium 页面也显式拒绝临时 Schedule URL/数据。

## 生命周期

删除、租约过期和关闭服务会清除最小 Gantt 数据。已打开的临时 Gantt 每五秒检查会话，失效或连接中断时清空条形图、任务详情和旧筛选数据，禁用操作并提示重新创建；不会继续展示缓存的旧结果。重新载入页面重新取数据，已删除对象返回 404。BFCache 恢复也重新加载核实。

控制台离开/刷新时仍尝试删除当前临时对照。Gantt 的有效访问会续租，若删除通知未送达，仍打开的 Gantt 可以在原两小时硬上限内继续查看；所有页面停止访问后按原 90 秒租约过期。临时数据不能跨服务重启恢复。

## 文件与定向验证

- `experiment-ui.js`：filterChoices、比较表的紧凑信息和临时链接；`style.css`、`cesium-experiment.css`：筛选/核验文字层级。
- `temporary_controls.py`：私有最小 Schedule、成员检查和取消清理；`api.py`：临时 Schedule/Gantt 路由、缓存及 Cesium 拒绝。
- `gantt.js`：临时源标记、禁用 Cesium 入口、租约检查和清空；两张 viewer HTML 仅作来源中性文字及临时回放保护。
- 4 项临时服务 Python 测试通过，含两个空小场景真实 Worker、Database.write 抛错保护、正式八表计数不变、Gantt 数据读取/成员隔离/删除清理及 Cesium URL 拒绝。
- 7 项 Node 交互检查通过，覆盖轻量筛选无结果详情、稳定多选、正式/临时 Gantt 路由分离以及既有选择/吸附逻辑。
- 一次 Chromium 两星夹具、一个临时对照：勾选过滤、指标与正式链接保留；临时图任务条、UTC 精确时间、5 秒曝光、缩放平移、吸附及键盘详情；正式列表/Run 数保持 3/5，临时 ID 的 Run/Cesium 均 404；删除后图表清空、操作禁用、数据 API 404，刷新仍无旧条。页面错误为空。

浏览器夹具的 `--synthetic-temporary` 明确使用 UNIT_TEST_INJECTION_ONLY 认证来隔离绘图/生命周期验证，不声称这是实际物理观测证据；真实 Worker 的核验与不落库由 Python 测试单独覆盖。没有大型场景、全面 Benchmark 或 GPU 长时测试。删除后的图表清空存在最多约五秒检测延迟；网络短暂中断时采取保守清空，需刷新重试。加载新 API 需自行重启旧后端进程。
