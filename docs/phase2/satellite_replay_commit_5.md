> 历史专题记录：当前 v0.3.1 的实现、接口过渡与剩余分工见[修复集成交接](restore_integration_handoff.md)。下文保留当时的版本与验收语境。

# 卫星回放 commit 5：同钟固定载荷视图

- 日期：2026-10-14
- 分支：`feat/satellite-body-fixed-payload-replay`
- 预期提交：`feat(viewer): add synchronized fixed payload views`

## 用户操作

Cesium 回放左侧的“Fixed Payload View”列出原卫星 ID 和机动类型。用户可通过三种入口选星：

1. 点击卫星列表按钮；
2. 点击主地球上匹配原卫星 ID 的实体；
3. 点击任务列表，同时选择该 assignment 的卫星并跳到原开始时间。

状态栏显示原卫星 ID、当前阶段、任务 ID 和姿态质量。“Hide fixed payload view”隐藏面板后停止额外渲染；再次显示时按主时钟重建当前状态。

## 时钟、姿态与资源边界

- 主 Viewer 的 `clock.currentTime` 是唯一权威时钟。第二 Viewer 设置 `shouldAnimate=false` 且不使用默认渲染循环，每帧克隆主时间。
- 相机 `position/direction/up` 来自 commit 2 的同一 `evaluateSatelliteState`。设置模拟相机不会更改卫星本体姿态或增加镜头云台自由度。
- 第二 Viewer 不加载主场景的卫星模型、视锥、覆盖和标注，避免在载荷画面前遮挡地表。
- 第二 Viewer 关闭用户相机输入；切换卫星复用同一个时钟监听器和 Viewer，页面卸载时销毁 Viewer。
- 等待、转向和拍摄都持续更新画面；主场景视锥隐藏不会停止载荷视图。无任务星使用既有默认对地姿态。

## 固定光学 FOV

`draw/fixed-payload-view.js` 使用水平/垂直半角正切之比计算光学纵横比：

```text
aspect = tan(horizontal_full_fov / 2) / tan(vertical_full_fov / 2)
```

有效 Cesium 容器使用留白放入面板，而不是将方形 45° FOV 拉伸到面板比例。相机近/远裁剪设为 10 m / 50,000 km，仅影响渲染，不改覆盖求交。

## 验证

```bash
node tests/fixed_payload_state.test.cjs
node tests/fixed_payload_geometry.test.cjs
node tests/fixed_payload_view.test.cjs
```

Node.js 测试验证相机 pose 复制、状态文本、45°×45° 光学比例，以及 320×180 与 180×320 面板都得到 180×180 有效画面。

CesiumJS 1.136 + Chromium 141（Playwright build 1194）冒烟测试结果：

```json
{"width":180,"height":180,"time":"2026-01-01T00:00:05Z","shouldAnimate":false,"inputsEnabled":false,"aspectRatio":1,"fovDegrees":45}
```

浏览器控制台无错误。该测试确认时钟、FOV、留白和交互禁用；完整正式 run 的使用与性能记录在 commit 6 交付中完成。
