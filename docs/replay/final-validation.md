# 卫星整体姿态与固定载荷回放：最终验证

> 本文记录 `6a7c285` 时的 commit 6 验收基线。真实页面测试后完成的 UTC/Cesium 相容、3D 视锥、追踪恢复、callback 防护及任务点交互，统一记录在 [`../phase2/satellite_replay_post_commit_6.md`](../phase2/satellite_replay_post_commit_6.md)。

- 验收日期：2026-10-15（Asia/Hong_Kong）
- 分支：`feat/satellite-body-fixed-payload-replay`
- 环境：WSL2 Linux 6.18.33.2，Python 3.10.12，Node 24.20.0，Intel Core Ultra 7 155H
- 浏览器：CesiumJS 1.136，Chromium 141.0.7390.37（Playwright build 1194）

## 六个功能提交

| # | Commit | 交付 |
|---|---|---|
| 1 | `aa1e6f5` | 只读契约、独立配置、manifest 与输入完整性 |
| 2 | `1ac478f` | 确定性本体姿态、原转移时长及任务阶段 |
| 3 | `dac4d22` | NASA Landsat 8 示意外观、本体旋转与固定载荷 |
| 4 | `c9bf048` | 逐星视锥、WGS84 中心交点、覆盖及地平线降级 |
| 5 | `93fe0cf` | 列表/地球/任务选星与同钟固定载荷第二视图 |
| 6 | 包含本报告的提交 | 正式链路、资产/cache identity、边界/性能/不变性验收 |

`f7c55e3` 是 commit 1–3 后按团队规范补充的独立文档提交，不计入六个功能 commit。

## 运行方法

```bash
~/eos-course-runtime/.venv/bin/python -m eos_system
```

1. 在 <http://127.0.0.1:8765/> 提交并等待实验成为 `SUCCEEDED`。
2. 从结果页打开“Cesium 回放”。页面读取正式 schedule、CZML 轨道和只读 replay sidecar。
3. 主地球查看整体本体、转向/拍摄视锥和 WGS84 覆盖。
4. 从卫星列表、主地球实体或任务列表选星，在“Fixed Payload View”查看与主时钟同步的模拟视野。
5. 用 Cesium 自带控件暂停、改倍速或拖动时间；点任务行可精确跳到原开始时刻。

轨道 CZML 首次生成需要 `requirements-visualization.txt` 中的 Orekit/JVM 依赖。页面的 CesiumJS 仍来自固定 1.136 CDN，浏览器需可访问该资源。

## 不变性与资产

| 对象 | SHA-256 |
|---|---|
| `demo-s1-30_Sats1_M30_T1d_seed20260927.json` | `00274bc1d4bce0ccf427edeac70b9742ad4fd7f21111e4969b9ce1c90c5342c0` |
| `demo-s3-30_Sats3_M30_T0.25d_seed20260927.json` | `71058543bcf5040e0108f4c1a0d233cefe5f7e88401fe377f44ee0d3b0b83a72` |
| `assets/satellites/landsat8.glb` | `8b599e867be20589cd35e55ed1d46da104299b430b1827b548a25d3fad0a314d` |

交付测试在临时 SQLite 中建立一份已核验 `SUCCEEDED` 计划，连续请求两次回放：两次返回同一 cache identity 与同一有界缓存文档；回放前后场景字节 SHA 和 SQLite `get_run()` 的规范快照完全一致。三个本地 JS 资源及 GLB 的正式 FastAPI route 全部解析到存在文件。

模型来源为 NASA Science Landsat 8，署名 NASA/Christopher R. Meaney，详见 [`landsat8-validation.md`](landsat8-validation.md)。回放 identity 包含场景、计划、显示配置、builder、传播、姿态、几何、资产 manifest 和实际模型 bundle 哈希。缓存最多 16 份且仅在进程内；请求先重验输入，不将回放状态写入正式数据库。

## 验证结果

- Python：回放契约/阶段/资产 9 项通过；正式交付、重复请求、资源与不变性 1 项通过。
- Node.js：`fixed_payload_state`、`fixed_payload_geometry`、`fixed_payload_view`、`replay_acceptance` 四组通过。覆盖一星两任务、多星同时、无任务非敏捷星、缺轨道、地平线/无交点、跨 UTC 日期、半开端点和倒序/跳转求值。
- Chromium WGS84 冒烟：16/16 边界射线命中、1 个覆盖 primitive、无控制台错误。
- Chromium 第二 Viewer：180×180、aspect 1、FOV 45°、`shouldAnimate=false`、用户输入关闭，权威时间精确为 `2026-01-01T00:00:05Z`。
- 性能点测：300 次完整几何求值（每次 16 条 WGS84 边界射线）共 17.8 ms。这是 headless Chromium 隔离几何点测，不包含轨道网络加载、GLB 或双 Viewer 完整帧，不作为最大星数承诺。

全量命令：

```bash
MPLCONFIGDIR=/tmp/eos-mpl-cache timeout 90s \
  ~/eos-course-runtime/.venv/bin/python -m unittest discover -s tests -v
```

全量执行在前 10 项通过后停在既有 `test_http_cancel_uses_existing_route_and_temporary_database`，90 秒后由 `timeout` 中断，退出码 124。该停滞与先前 commit 1–3 验收记录一致；因此不声称全量 unittest 通过。

## 限制

- 姿态来源是 `geometry_pointing_illustration`，不是 Orekit 姿态导出、真实执行机动力学或成像可行性证明。
- 单值 FOV 使用明示的方形全角假设；不把 `observation_swath_width_km` 强制匹配回放矩形。
- 覆盖使用 WGS84 椭球，不包含地形遮挡。地表 20 m 抬高只用于抗闪烁，不改实际交点。
- Landsat 8 是通用示意外观；模型—本体轴校准仍为待实物资料确认的单位四元数。
- 第二 Viewer 是地图/椭球模拟视野，不是真实卫星照片；离线环境需后续打包 CesiumJS/底图资源。
- 显示不修改任务、观测时间、完成率、利润、TCR、BD、TM、RT 或 exports；严格算法计时实验应关闭回放以避免 GPU/CPU 资源争用。
