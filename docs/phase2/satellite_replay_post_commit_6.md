# 卫星回放 commit 6 后续整合与交互修正

## 1. 范围与结论

- 基线：`6a7c285 feat(replay): integrate replay delivery and document validation`
- 分支：`feat/satellite-body-fixed-payload-replay`
- 整理日期：2026-10-15（Asia/Hong_Kong）
- 性质：commit 6 正式链路后的兼容修正、Cesium 交互恢复和显示增强

commit 6 的只读 replay API、资产 identity 和缓存边界保持不变；后续工作解决了正式排程时间格式、CesiumJS 1.136 API、浏览器缓存、任务跳转、视锥可读性及原生选取追踪等真实页面问题，并补充固定载荷任务点和主地球俯视交互。没有修改 SQLite 模式、调度算法、正式计划、指标、Controller 或 Worker 协议。

## 2. 后续提交

| Commit | 目的与结果 |
|---|---|
| `ed60809` | 将排程器既有的无时区 ISO 字串按其既定 UTC 语义转换为 replay 显示时间；原计划字节和数据库不变。浏览器保留实际 replay 错误，不再被模糊 fallback 覆盖。 |
| `79851bd` | 移除 CesiumJS 1.136 不存在的 `Quaternion.fromElements()`；任务列时间也按 UTC 解析。点击任务后暂停在精确开始端点，避免高倍速首帧越过数秒任务。 |
| `08d06b9` | 将仅有中心/边界线的 FOV 改为有 16 条边界、半透明侧面与端面的 3D 方锥。部分地平线仍显示视场包络，但不伪造完整 WGS84 footprint。 |
| `6422935` | 移除对 Cesium 原生 `LEFT_CLICK` 的覆盖，改为监听 `selectedEntityChanged`。恢复单击选取、信息框和双击追踪，同时同步 Fixed Payload View。 |
| `b5ebe21` | 为中心线、边界、侧面、端面和 footprint callback 增加缺值/端点保护；为三个 replay JS 加版本参数，避免新 HTML 与旧缓存脚本混用导致 Viewer 停止。 |
| `a3622b1` | Fixed Payload View 显示当前任务黄点、红色外框、任务 ID 和经纬度；主地球单击任务点会解除卫星追踪，并从该点上方约 600 km 以正下视角查看。 |

## 3. 当前交互

1. 从成功实验详情打开“Cesium 回放”，不要用只传 `schedule` 的旧 `main_draw.py` 页面验证 replay 功能。
2. 单击任务列表会选择对应卫星，并暂停在任务原始开始时间；使用者确认视锥后可自行继续播放。
3. 单击主地球卫星使用 Cesium 原生选取；双击卫星进入相机追踪。选中的卫星同时同步到 Fixed Payload View。
4. `SLEWING` 显示琥珀色、`OBSERVING` 显示绿色半透明方锥。方锥是当前方形完整角 FOV 的显示包络，不是圆形光学锥或成像可行性证明。
5. Fixed Payload View 在活动任务期间显示当前任务点、ID 和经纬度；IDLE 时隐藏任务点。
6. 单击主地球任务点会退出卫星追踪，并飞到任务点上方约 600 km 的 `-90°` 俯视视角。Home 控件可回到全局视图。

## 4. 时间、几何与资料边界

- `scenario_loader` 会把来源时间换算为 UTC 后移除 `tzinfo`，正式 schedule 因而保存无偏移 ISO 字串。HTTP replay 只在内存显示副本补上 `+00:00`；cache identity 仍对原正式计划的规范字节求哈希。
- 任务阶段保持半开区间 `[start, end)`；到达 `sat_end_time` 的同一刻视锥和当前任务点立即隐藏。
- 视锥端面是 FOV 显示包络。WGS84 footprint 只有所有边界射线均有交点时才绘制；部分地平线不会拼接假的地面覆盖。
- Landsat 8 仍是通用示意外观，原卫星 ID 不变；姿态仍是几何指向示意，第二 Viewer 仍是地图/椭球模拟视野。
- replay 请求、选取、追踪、任务跳转和俯视操作都不写 SQLite，也不改变正式任务时间、任务完成率或导出文件。

## 5. 验证证据

环境：WSL2 / Python 3.10.12 / Node 24.20.0 / CesiumJS 1.136 / Chromium 141（Playwright build 1194）。

定向自动测试：

```bash
MPLCONFIGDIR=/tmp/eos-mpl-cache \
  ~/eos-course-runtime/.venv/bin/python -m unittest \
  tests.test_replay_delivery tests.test_replay_timeline \
  tests.test_replay_contracts tests.test_satellite_asset -v

node tests/fixed_payload_state.test.cjs
node tests/fixed_payload_geometry.test.cjs
node tests/fixed_payload_view.test.cjs
node tests/replay_acceptance.test.cjs
```

结果为 Python **10/10** 及 Node.js **4 组通过**。真实页面使用成功实验 `965cfdc1-cb00-4500-b993-c20b8c23416c` 验证：

- Landsat 8 GLB 返回 HTTP 200；页面报告 1 个模型、16 条 FOV 边界及半透明侧面。
- M017 在 `2025-11-18T13:40:49Z` 为 `OBSERVING`；精确到 `13:40:55Z` 后为 IDLE，未出现 callback 例外。
- 单击与双击卫星分别得到 `selectedEntity=ALOS-2_39766`、`trackedEntity=ALOS-2_39766`。
- Fixed Payload View 显示 `M017` 及 `-12.5300°, -22.1100°`。
- 选择 M017 后解除追踪，相机俯角为 `-90°`、高度约 600 km。
- Chromium 的 Cesium render panel、page error 与 console error 均为空。

完整 unittest 的既有 HTTP cancel 测试停滞限制仍与 [commit 6 最终验证](../replay/final-validation.md)相同，本轮不声称完整 discover 全部通过。

## 6. 审核提示

- 审核者应在重新启动服务后从系统结果页打开回放；脚本 URL 已带版本参数，但旧页面仍建议用 `Ctrl+Shift+R` 更新。
- 重点检查任务开始/结束端点、部分地平线、单击/双击卫星、任务点俯视以及 Fixed Payload View 的任务标记。
- 本分支仍待独立组员审核并通过 PR 合并；本文记录实现与验证，不代表已合并到 `main`。
