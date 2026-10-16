> 历史专题记录：当前 v0.3.1 的实现、接口过渡与剩余分工见[修复集成交接](restore_integration_handoff.md)。下文保留当时的版本与验收语境。

# 卫星本体与固定载荷回放 commit 1–3 交接

- 日期：2026-10-14
- 分支：`feat/satellite-body-fixed-payload-replay`
- 负责范围：梁兆榮的 Cesium/回放显示层；公共 HTTP 接口需李泽同审核
- 对应提交：`aa1e6f5`、`1ac478f`、`dac4d22`

## 1. 目的与边界

这三个 commit 将已成功实验的正式计划扩展为可重现的卫星本体和固定载荷回放。回放是显示派生物，不是新的求解器：它不重跑调度、不修复计划、不改写母场景，也不将显示假设反向用于约束或指标。

| Commit | 已完成内容 | 主要文件 |
|---|---|---|
| 1 | 只读输入契约、哈希/身份校验、隔离输出要求、可版本化 manifest 与显示配置 | `replay/contracts.py`、`replay/read_only.py`、`replay/manifest.py`、`replay_configs/display-profile-v2.json` |
| 2 | 从已提交计划构建 `SLEWING/OBSERVING` 阶段、几何指向姿态和固定载荷状态；提供只读 HTTP sidecar | `replay/timeline.py`、`replay/document.py`、`draw/fixed-payload-state.js`、`eos_system/api.py` |
| 3 | Cesium 载入本地 Landsat 8 GLB，按时间设置本体姿态与固定载荷方向，并保留点/标签回退 | `draw/cesium_viewer.html`、`assets/satellites/landsat8.glb`、`assets/satellites/asset-manifest.json` |

## 2. 资料流与契约

```text
SQLite 中的 SUCCEEDED 运行
  ├─ 正式计划 + RunConfig 场景 SHA-256
  ├─ 只读场景 JSON（重算 SHA-256）
  └─ display-profile-v2.json
             │
             ▼
GET /api/runs/{run_id}/visualization/replay
             │  replay manifest + segments + sensors + models
             ▼
Cesium CZML 位置 + fixed-payload-state.js 姿态
             │
             ├─ Landsat 8 示意本体
             └─ 固定载荷方向标记
```

`GET /api/runs/{run_id}/visualization/replay` 只接受存在且拥有正式计划/指标的 `SUCCEEDED` 运行。场景不存在、实际字节与已提交 SHA-256 不符、计划与场景 ID 不一致或显示配置无效时返回 409。返回内容包含输入哈希、构建器代码哈希/版本、坐标系、四元数顺序、旋转方向和姿态来源，便于复核。

时间阶段使用绝对时间的半开区间 `[start, end)`，同一时刻的结果与播放、拖动或回退调用顺序无关。任务之间的转移时间复用当前 checkout 的 `schedulers.transition_utils`；如果两个任务间隙不足，显示段会裁到前一任务结束时间，并在 `diagnostics` 记录降级原因，不移动正式观测时间。

## 3. 显示资产与轴向假设

- 资产：NASA Science Landsat 8 GLB，780,280 bytes。
- SHA-256：`8b599e867be20589cd35e55ed1d46da104299b430b1827b548a25d3fad0a314d`。
- 来源与署名：NASA/Christopher R. Meaney；完整验证记录见 [`../replay/landsat8-validation.md`](../replay/landsat8-validation.md)。
- 用途：数据集卫星的通用示意外观。源 ID 继续是 ALOS-2、AQUA、CARTOSAT-2C 等，不因 GLB 而重命名。
- 轴向：`body_to_ecef`、四元数 `xyzw`，相机轴为 `forward=-Z,right=+X,up=+Y`。当前 `model_to_body` 为单位四元数，属待实物轴向资料校准的视觉假设。

外观缩放或日后校准 `model_to_body` 不得改变载荷方向；载荷单独使用恒定 `sensor_mount_quaternion_xyzw` 表示相机—本体变换。

## 4. 验证记录

Ubuntu / Python 3 定向测试：

```bash
python3 -m unittest \
  tests.test_replay_contracts \
  tests.test_replay_timeline \
  tests.test_satellite_asset -v
node tests/fixed_payload_state.test.cjs
```

结果：Python **9/9** 通过；Node.js 测试通过。真实 `scenarios/` 输入的 `build_replay_document` 冒烟检查成功，测试前后场景 SHA-256 不变。两个已记录的受保护场景哈希为：

- `demo-s1-30...`：`00274bc1d4bce0ccf427edeac70b9742ad4fd7f21111e4969b9ce1c90c5342c0`
- `demo-s3...`：`71058543bcf5040e0108f4c1a0d233cefe5f7e88401fe377f44ee0d3b0b83a72`

Landsat 8 浏览器冒烟检查使用 CesiumJS 1.136 + Chromium 141，从本地 HTTP URL 建立 1 个 Entity model primitive，截图中几何/材质可见，控制台无错误。可选复现命令见资产验证文档。

完整 `python -m unittest discover -s tests -v` 已尝试，但在既有 `test_http_cancel_uses_existing_route_and_temporary_database` 长时间停滞，在当时的最新 FastAPI 与项目锁定 FastAPI 0.115.6 / Starlette 0.41.3 环境均可复现，因此中断，本交付不声称全量测试通过。

## 5. 已知限制与后续接点

- 姿态来源是 `geometry_pointing_illustration`，不是 Orekit 姿态导出，也不构成动力学可行性证明。
- 当前观测目标与载荷视场采用显示配置中的方形 45° 全角假设，不应解读为真实仪器标定。
- commit 1–3 尚未绘制视锥、地面足迹，也未实现地平线/地球边界裁剪和第二固定载荷视图。
- 如果 Cesium 无法加载回放 sidecar 或 GLB，页面保留原卫星点/标签回退；该回退不影响计划、指标或导出。
- 本轮没有 SQLite 模式、Controller 状态、Worker IPC、算法公共契约或旧计划 JSON 的迁移。
