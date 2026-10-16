# 轨道插值缺陷独立定位与回归验收（2026-10-17）

结论：固定三颗不同轨道特征的真实卫星、650 秒局部实例中，原 300 秒线性插值最大误差 93,187.287 m，修复后后端最大 0.013271 m；真实 Cesium 1.136 与 READY 消费端通过独立 Orekit 对照。原 0/300/600 秒传播节点正确。此次修复不改变已通过的 P0 时间语义、调度算法、窗口或正式计划。四份候选保持原 SHA，继续为 candidate；本报告不是自动发布批准。

## 1. 分支、依赖与边界

- 新分支 `fix/orbit-interpolation`，先从 fetch 后的 `origin/main=daf4254f6a7c3157996ed77ba45278f648a405bf` 创建，再快进继承已验收 P0 `12f8849597ce9a4f1d7875eed832082b87c1682f`。提交前再次 fetch/rebase：main 未变，P0 提交未重写。
- 当前 main 尚未包含 P0。本次新增提交只含下列插值改动；先审查相对 `12f8849` 的差异，依赖 P0 合入后再整理面向 main 的 PR。不可把依赖中的 P0 当作本次新工作。
- 没有整场重算、正式计划生成、数据库/registry/Controller/Worker/算法改动，没有改写旧验收报告或清理历史缓存。
- 主工作目录五份既有未跟踪文件保持原 SHA；开发及提交在独立 managed worktree。

## 2. 根因与链路

| 层 | 原行为与证据 | 判断 |
|---|---|---|
| Orekit | Keplerian MEAN anomaly，UTC，EME2000→ITRF，WGS84；直接传播节点和 CZML 反解节点差 < 1 µm | 节点正确，无 C/D/E 证据 |
| 轨道采样 | 系统默认 300 秒，650 秒实例只有 0/300/600/650 四个真节点 | A：间隔与所用插值不匹配 |
| 后端 `replay.runtime._position_at` | ECEF 位置做两点线性插值，圆弧变弦 | B：主要误差来源 |
| READY 消费 `fixed-payload-state.js` | 服务端已插值的 5/20/135 秒位置再线性插值 | G：第二次插值会增加误差 |
| CZML/浏览器 | 原 position 未声明插值，Cesium 默认线性；主页面还会使用 READY 位置覆盖 position | F：复现相同机制，不是仅浏览器渲染误差 |
| ground track | 真传播位置转 WGS84 经纬高，再反解 ECEF，节点正确；中间位置使用上述插值 | 不修改真实传播数据来补显示误差 |

圆轨道弦中点误差近似 `r × (1 - cos(ωΔt/2))`，随步长平方增长。仅修 CZML 元数据不能修复已被后端线性采样损坏的 READY 资源；仅把线性节点加密至 60 秒，原型仍有 3–4 km 误差。300 秒四节点即便使用可用最高三阶，也有约 1.5–2.3 km 误差，不能把四个节点称为完整五阶。

Cesium 的参考系、默认线性插值及 interpolation 配置见 [官方 SampledPositionProperty 文档](https://cesium.com/learn/cesiumjs/ref-doc/SampledPositionProperty.html)。没有人工加减时间或修正空间位置。

## 3. 最小修复与文件

| 文件 | 本次变化 |
|---|---|
| `eos_system/visualization.py` | 系统轨道真节点默认 300→60 秒，增加实际 Orekit 采样密度 |
| `eos_system/orbit_generate.py` | CLI 默认复用上述常量，避免两个默认值分离 |
| `replay/runtime.py` | ECEF 位置使用最多六个相邻真节点的局部五阶 Lagrange；相对秒计算，精确节点直接返回 |
| `draw/fixed-payload-state.js` | READY 位置同样使用有界局部插值；保留整数微秒索引、阶段判断及姿态 SLERP |
| `draw/orekit_to_czml.py` | position 增加标准 CZML `LAGRANGE` / `interpolationDegree=5` |
| `tests/test_orbit_interpolation.py` | 五项纯回归和两项可选真实 Orekit 回归 |
| `tests/orbit_interpolation.test.cjs` | 独立合成轨道及真实 READY fixtures 消费端回归 |
| 本报告、README、COURSE_SETUP | 操作变化、证据与边界记录 |

没有公共函数签名、API、数据库、配置字段或缓存键结构变更。缓存仍 v2；现有 `s{step}` 与传播源码 SHA 自然区分新轨道缓存；READY 的 `source_bundle_sha` 已包含 runtime、JS 和采样模块，修复后生成不同身份。旧 READY 数据保持历史身份，不能视为新精度验收结果；旧文件不删除。历史一/二节点输入仍可读，二节点仍线性，不承诺稀疏历史数据达到新精度。

## 4. 独立参考及复现

固定 UTC 起点 `2025-11-18T12:00:00.123456Z`，局部时域 650 秒。真实卫星参数从只读旧 20 星候选提取：ALOS-2（约 7014 km、98°）、GPM-CORE（约 6802 km、65°）、SCD_1（约 7121 km、25°）。参考直接创建独立 Orekit KeplerianOrbit / KeplerianPropagator，在每个查询绝对时刻传播至 ITRF；不把生产插值结果用作真值。复用已有 E3 的独立参考构造器与数据 SHA 锁定，不更改 P0 测试。

共 1,968 个查询：每星 0..650 的每整数秒，以及 37.5/112.5/147.3/449.3/649.9 秒，包含新 60 秒节点之间的查询。修复前基线严格使用同一轨道、同一 UTC 的 0/300/600/650 秒真节点和原两点线性式。不是比较不同 epoch 的两个场景。

| 卫星 | t=150 原误差 m | t=150 修复 m | t=450 原误差 m | t=450 修复 m | 全查询修复最大 m |
|---|---:|---:|---:|---:|---:|
| ALOS-2 | 93,113.5490 | 0.0027600 | 93,187.2871 | 0.0027476 | 0.0132701 |
| GPM-CORE | 91,869.0332 | 0.0027341 | 91,789.0251 | 0.0027344 | 0.0131425 |
| SCD_1 | 77,053.9526 | 0.0013066 | 77,055.4091 | 0.0013027 | 0.0062845 |

0/300/600 秒原线性基线节点误差为 0；修复后的 CZML→ECEF→后端节点误差不超过 5.6×10⁻⁹ m。本例全部后端查询 < 1 m，最大误差改善超过一百万倍。阈值在生产代码修改前固定；原实现先红（纯 Python 11 个 subtest failure、1 个元数据 error，Node 合成检查失败），修复后通过，没有调整既有测试或放宽预算。

## 5. 浏览器与 P0 验证

真实 in-app browser 加载官方 Cesium 1.136、实际生成的 CZML 和仓库实际 `fixed-payload-state.js`，在页面显示定量结果并下载 JSON。CZML 与 READY 均比较同一组直接 Orekit 真值，不运行调度器或真实服务写接口。

| 路径 | 查询数 | 最大误差 | 结果 |
|---|---:|---:|---|
| 原 Cesium 默认线性（相同 300 秒真节点） | 1,968 | 93,187.287117 m | 成功复现原缺陷 |
| Cesium CZML getValue（60 秒真节点，五阶） | 1,968 | 0.0132701 m | PASS，阈值 1 m |
| READY，5 秒采样再插值 | 1,968 | 0.0132701 m | PASS，阈值 1 m |
| READY，20 秒采样再插值 | 1,968 | 0.0132701 m | PASS，阈值 1 m |
| READY，135 秒采样再插值 | 1,968 | 1.644531 m | PASS，阈值 5 m |
| 全量 Python（含三组 opt-in） | 274 | 0 failed / 0 skipped | PASS |
| Node 原四组 + 新一组 | 5 组 | 全通过 | PASS |
| 真实三维整页视觉/截图 | — | 浏览器截图接口返回 Unable to capture screenshot | NOT RUN，不冒充像素级验收 |

P0-1 完整细网格/延迟姿态、P0-2 CZML 微秒、P0-3 非整终点、P0-4 aware UTC 全部随完整回归再次通过。`utils/visibility.py`、`utils/time_parsing.py`、`scripts/recompute_scenario_windows.py` 原字节不变；CZML `_sample_times` / `propagate_satellite_groundtrack` / `demo` AST 不变；JS 微秒解析和 SLERP 原函数文本不变。EME2000/ITRF 位置速度由原独立 E3 测试再次验证，阈值仍为 1 µm / 10⁻⁹ m/s。

## 6. 四份候选保护

以下全部只读重新计算候选与静态 SHA，均匹配先前验收。23 份 frozen_files（含 Legacy、侧车、历史报告与 Orekit 数据）逐项 SHA 通过；另记录 16 份既有调度/计划相关 JSON 的哈希并做完成后复核。未重新生成正式计划。

| 场景 | 候选 SHA-256 | 静态 SHA-256 |
|---|---|---|
| 10×20 dist1 | bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e | c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295 |
| 20×20 dist1 | 86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779 | 180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b |
| 10×20 dist0 | f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4 | 2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68 |
| 20×20 dist0 | ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575 | 1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f |

本次不重复 Manifest 或全场景窗口验收；其历史 WARN 不因插值修复消失。连续曝光保护、正式来源补齐、亚秒隐藏短窗口漏检及全时段完备性限制继续保留。

## 7. 命令、证据与成本

WSL Ubuntu 22.04，原有虚拟环境、Java、Orekit。数据：
`/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-1d-20261016/data/orekit-data.zip`，SHA `1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`。

为避开 /mnt/c 全量测试 I/O 使用新建 Linux 原生只读源码快照；231 份源码/输入文件逐项 SHA 校验。六份大输入复用历史隔离测试副本的只读硬链接，不连接真实候选或生产数据库；前后 SHA 均复核。测试临时库由既有测试隔离创建，无正式计划改写。

```bash
# 在项目根目录或已核验的只读源码快照内；Python 环境需含现有项目和 Orekit 依赖
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export EOS_OREKIT_DATA=/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-1d-20261016/data/orekit-data.zip
export EOS_RUN_ORBIT_INTERPOLATION_TESTS=1
export EOS_RUN_E3_E4_OREKIT_TESTS=1
export EOS_RUN_OREKIT_TESTS=1
PY=/home/meteor/eos-course-runtime/venv/bin/python
/usr/bin/time -v "$PY" -B -m unittest discover -s tests -p test_orbit_interpolation.py -v
/usr/bin/time -v timeout -k 10s 240s "$PY" -B -m unittest discover -s tests -v
for t in tests/*.test.cjs; do node "$t" || break; done
```

本地 Orekit 测试引用已有测试 fixture 路径；旧 fixture 固定路径为 `/home/meteor/eos-course-runtime/epoch-acceptance/s1-20s20m-1d-20261016/candidate/Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1.json`，SHA `5e7a7702d60d194f403c30b157089243135b4287bef48b4114af5c83899addda`。其他电脑必须先提供同一只读 fixture，当前测试不会自动下载或随机重建它；Orekit ZIP 可通过 `EOS_OREKIT_DATA` 指定。可选 `EOS_ORBIT_INTERPOLATION_EVIDENCE` 指向全新空目录，保存 CZML/READY/参考 JSON；文件以排他创建模式写入，不覆盖既有证据。

- 新专项 7/7：unittest 6.604 s；GNU time 墙钟 7.80 s；峰值 RSS 249104 KiB；退出 0。
- 全套 274/274：unittest 89.938 s；墙钟 90.90 s；峰值 RSS 500828 KiB；退出 0。该 RSS 含完整系统测试，不等同于轨道生成常驻内存。
- Linux 新报告根 `/home/meteor/eos-course-runtime/epoch-acceptance/orbit-interpolation-20261017/`：`source-sha256.json`、`full.stdout.log`、`full.stderr.log`、`node.stdout.log`、`protected-inputs.json`。
- Windows 新专项证据 `C:/Users/流星/.codex/worktrees/reintegrate-manifest-orbit/orbit-interpolation-evidence-20261017/`：红/绿测试日志、`prototype.json`、`integration/orekit-comparison.json`、`integration/ready-consumer.json`、`browser-result.json` / `browser-beforeafter-result.json` 与源码保护记录。大证据不入 Git。
- 浏览器独立页是上述目录 `browser/beforeafter.html`；静态复现命令 `python -m http.server 8879 --bind 127.0.0.1 --directory <browser目录>`，打开 `http://127.0.0.1:8879/beforeafter.html`。需访问固定版本 Cesium CDN，输出真实数值，非静态伪造 PASS。

## 8. 开销与放行范围

真节点数量约增五倍；局部插值每次最多六点/三坐标，内存有界，不对全时域做高次多项式。不放宽 200000 姿态样本、100000 目标或 64 MiB 资源预算。纯计数估算 50 星×3 天×60 秒为 216050 个轨道节点，保守 JSON 槽位估算 <64 MiB；未实际运行该规模，也未保证 600 秒现有构建超时一定满足。后续由负责人批准后测量实际生成成本。

显式调用 `demo(..., orbit_step_s=300)` 仍合法，保持 P0 兼容；没有六点时降为可用次数，不能保证亚米精度。metadata 时间步长大于 60 秒时，既有 max 步长规则仍生效，未修改 P0 入口；此类输入、很短时域、高偏心率、长时段及比 135 秒更稀的 READY 数据不在本次量化保证范围。原姿态 SLERP 的角度精度也未被本次位置测试重新认证。

本固定重现的轨道插值 blocker：PASS；全量时间回归：PASS；四候选/历史证据保护：PASS；完整正式回放页面、全时域性能与最终发布：待负责人独立审核，不自动放行正式场景。

## 9. 英文提交与 PR 草稿

Commit: `fix(replay): reduce orbit interpolation error with true samples`

PR title: `Fix curved orbit interpolation across backend, CZML and READY playback`

> Sparse 300-second ECEF positions were linearly interpolated in both the replay builder and READY consumer, creating 77–93 km midpoint errors despite correct Orekit nodes. Use true 60-second Orekit samples and bounded local degree-five position interpolation, with standard CZML Lagrange metadata. Keep P0 UTC/microsecond/endpoint behavior and quaternion SLERP unchanged.
>
> Validation: 274 Python tests and all five Node groups pass, including independent three-orbit Orekit comparisons and real Cesium 1.136 queries. Maximum backend/CZML error is 0.0133 m in the 650-second fixture; 135-second READY samples remain below 1.645 m. Four acceptance candidate hashes and historical evidence are unchanged. No formal schedule or database is regenerated.
>
> Depends on P0 commit 12f8849; review the interpolation commit separately and merge P0 first. Existing cache identities isolate the new artifacts without deleting old data. Larger-scale performance, sparse legacy data and formal release remain outside this validation.

## 10. 本次测试源文件 SHA-256

- `draw/orekit_to_czml.py`: `40255cb12f2f5d2e984b41ebbb53c759fe9636012d7feb3e721a646ec6d8d84a`
- `replay/runtime.py`: `bb151e6dec6d62cbc8192f5003551bf092ddad36b18e6ebac32e958d916f2824`
- `draw/fixed-payload-state.js`: `c90edb0ac9ff9c71e7361d200822e2e174dfcae7c13617d9b75cbe6e38d3a3b7`
- `eos_system/visualization.py`: `d220b7d703084d416dec69d9936de256ae6e4c05c369a54d8fcc446f08570ec0`
- `eos_system/orbit_generate.py`: `da6f87c0441c600896561da2b86980765d9c2c8cd5e6dda54f05bed0e520a154`
- `tests/test_orbit_interpolation.py`: `9df27b6a8d0a6efd982f24db64f9f5da18947377c740c76f99f4e6e06b583b2a`
- `tests/orbit_interpolation.test.cjs`: `a3a5deee4a8157f980b1193f53158e16153cbb63a927b38589897e34d105fd3a`
