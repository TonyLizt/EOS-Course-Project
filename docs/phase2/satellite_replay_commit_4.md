> 历史专题记录：当前 v0.3.1 的实现、接口过渡与剩余分工见[修复集成交接](restore_integration_handoff.md)。下文保留当时的版本与验收语境。

# 卫星回放 commit 4：逐星视锥与 WGS84 覆盖

- 日期：2026-10-14
- 分支：`feat/satellite-body-fixed-payload-replay`
- 预期提交：`feat(viewer): add per-satellite sensor frustums and footprints`
- 前置：[`satellite_replay_commits_1_3.md`](satellite_replay_commits_1_3.md)

## 范围与资料流

`draw/fixed-payload-geometry.js` 是无渲染器依赖的几何层：它按 `forward=-Z/right=+X/up=+Y` 生成中心射线与矩形 FOV 四边采样，再使用 commit 2 同一 `camera_to_ecef_quaternion_xyzw` 转到 ECEF。`draw/cesium_viewer.html` 注入 CesiumJS 1.136 的 `IntersectionTests.rayEllipsoid` 与 `Ellipsoid.WGS84`，对每条射线选取最近非负交点。

| 输入/状态 | 显示行为 |
|---|---|
| `IDLE` | 不显示视锥与覆盖 |
| `SLEWING` | 琥珀色中心线、边界射线与半透明侧面 |
| `OBSERVING` | 绿色几何与 WGS84 覆盖；仍使用 `[start,end)` |
| 全部边界命中 | 以 ECEF Cartesian 点绘制完整覆盖，可跨日期变更线 |
| 部分边界无交点 | 只显示有效射线，诊断 `PARTIAL_HORIZON`，不拼多边形 |
| 全部无交点 | 诊断 `NO_BOUNDARY_INTERSECTION`，覆盖为 `null`，不沿用前一帧 |

每颗星建立自己的绝对时间求值器与 Cesium Entity，因此同时转向/拍摄不依赖全局第一个 assignment。默认每条 FOV 边采样 4 段，共 16 条边界射线。覆盖绘制点沿椭球法线抬高 20 m 以减少 z-fighting，求交记录本身不改。

## 语义边界

- FOV 保留 `square_full_angle_display_assumption`；水平和垂直完整角都使用 sidecar 已登记的 45°，不改源场景。
- 中心射线指向原任务目标高度；中心 marker 表示射线与 WGS84 椭球的交点。两者在目标高度非零时不是同一点。
- 几何版本从 `pending-commit-4` 更新为 `wgs84-ray-ellipsoid-v1`，进入 manifest 和回放缓存身份。
- 视锥/覆盖只是显示派生物，不更改正式计划、任务完成率、metrics、exports 或实验状态。
- 新静态资源路径为 `GET /visualization/fixed-payload-geometry.js`；没有 SQLite 迁移或新的可写 API。

## 验证

```bash
node tests/fixed_payload_state.test.cjs
node tests/fixed_payload_geometry.test.cjs
python3 -m unittest \
  tests.test_replay_contracts \
  tests.test_replay_timeline \
  tests.test_satellite_asset -v
```

Node.js 测试覆盖：已知球面中心命中、FOV 边界次序、部分地平线、全部无交点、转向/拍摄颜色、精确半开端点及两星同时独立阶段。Python 回放定向测试 **9/9** 通过。

Cesium 冒烟测试：

```bash
python3 -m http.server 8099 --bind 127.0.0.1
PLAYWRIGHT_MODULE=/path/to/playwright \
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers \
node tests/browser/sensor-geometry-smoke.cjs
```

CesiumJS 1.136 + Chromium 141（Playwright build 1194）实测结果为 `status=COMPLETE`、`rayCount=16`、`hitCount=16`、1 个覆盖 primitive，无控制台错误。首轮冒烟测试发现 CesiumJS 1.136 没有 `Cartesian3.toArray()`；正式 Viewer 与测试页已改为明确读取 `x/y/z`，随后复测通过。

## 尚存限制

- 当前姿态仍是 `geometry_pointing_illustration`，不是 Orekit 姿态或动力学验证。
- 当前只求 WGS84 椭球交点，不校验地形遮挡，也不以覆盖结果重新评价任务。
- 选星、持续固定载荷第二视图、双视图同钟和窗口纵横比处理属于 commit 5。
