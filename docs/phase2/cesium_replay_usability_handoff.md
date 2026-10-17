# Cesium 回放易用性与跟随相机修复交接（2026-10-16）

## 范围

分支 `fix/cesium-replay-usability` 基于 main `daf4254`。本轮包含历史场景安全重定位、首次打开自动构建、触控板缩放，以及卫星点移除和主相机跟随稳定性修复；不改正式计划、指标、调度约束、Worker 或姿态样本。

## 相机根因与调用链

主 Viewer 没有第二个自定义逐帧相机写入者。正常卫星跟随由 Cesium `viewer.trackedEntity` 的 `EntityView.update()` 驱动；任务点俯视会先清除 tracked entity 再执行一次 `viewer.camera.flyTo()`。Fixed Payload View 的 `camera.setView()` 属于独立的第二 Viewer，只读取主时钟，不会写主相机。

问题来自跟随实体保留 Cesium 默认 `TrackingReferenceFrame.AUTODETECT`。回放加载后，卫星位置改为 READY 样本的 `CallbackPositionProperty`，而 Cesium 的 EntityView 会在每帧以当前/相邻时刻的位置重新判定 ENU、VVLH 或深空 north-up 基底。高倍速和端点附近一旦判定分支改变，主相机 transform 会瞬时采用另一套基底，看起来像地表近景与地球边缘/黑色太空间切换。卫星本体 orientation 并不是第二台使用者相机，但不应和相机框架混为一谈。

`draw/satellite-follow.js` 在 READY 数据安装完成后，将每颗卫星的主跟随框架明确设为 `TrackingReferenceFrame.ENU`。该框架只由同一主时钟下的卫星位置产生；不读取、不冻结也不改写本体 quaternion。模型、固定载荷方向、视锥和覆盖继续使用原姿态。任务列及 Fixed Payload View 选星会同步主 Viewer 的 selected entity；只有原先已在跟随卫星时才同步切换 tracked entity，因此不会擅自取得相机控制权。

## 显示变化

卫星 CZML `point` 在识别出带 `path` 的卫星后移除，`path` 与 label 保留；地面目标 point/label、任务连线、模型、姿态标记和传感器几何不变。Satellite Points 开关随之删除。

## 验证

- Python 静态交付/回放测试通过，新增脚本路由可读取。
- Node `satellite_follow.test.cjs` 验证 ENU 配置、不改物理 orientation、选星不隐式跟随、既有跟随在切星时保持。
- 隔离 Chromium 整合页验证自动构建仅一次、任务列选星、卫星 point 缺失、path 存在、ENU 框架、本体/载荷与资源加载，无 console/page/HTTP 错误。
- `camera-continuity-smoke` 用持续快速改变的物理 quaternion、两颗 2400 秒轨道做 60x 连续约 31 秒验收；排除明确的初始 viewFrom 和使用者切星过渡后，推进 1802.760 秒，141 个量测帧最大方向步进 0.925°，跟随距离为 500899.191 m，暂停漂移 0 秒；相邻 1 秒本体 quaternion 点积绝对值为 0.921，确认姿态没有被冻结；继续与切星通过。

大型真实场景的人工视觉复核仍建议由组员在目标 GPU/浏览器运行，但自动验收已覆盖报告中的 60x、30 秒、暂停/继续、切星、姿态持续变化和控制权边界。
