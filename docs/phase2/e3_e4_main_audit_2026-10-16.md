# 最新 main 的 E3 / E4 独立审查（2026-10-16）

审查基线：`daf4254f6a7c3157996ed77ba45278f648a405bf`，即 PR #12 合入后的 main。审查分支 `codex/e3-e4-audit` 从本轮重新 fetch 的 `origin/main` 创建，复用已附加的干净工作树。主要工作目录仍留在 main，五份未跟踪文档/测试保持原样。

**结论：E3、E4 尚未整体通过。四份冻结候选继续保留 candidate_only，可作为注册审核输入；不得据此直接发布、复用旧实验指标，或放行下一批正式场景重建。** 历史候选通过的物理/调度验收与最新 main 能否再现该结果是两项不同检查。

本轮新增审查脚本和文档，不修复生产实现，不改公共接口、缓存契约、Controller、Worker、数据库、registry、算法或 Cesium。实际执行只有只读核验、3 星短时导出、1 星/2 任务各 600 秒局部扫描及隔离测试；没有完整场景重算。

## 1. 范围和证据

E3/E4 职责按 [epoch_fix_implementation.md](epoch_fix_implementation.md) 第 7 节理解，并核对了 [restore_integration_handoff.md](restore_integration_handoff.md) v0.3.1、[six_scenario_scale_handoff.md](six_scenario_scale_handoff.md) v0.3.2，以及实际来源/回放/执行接口。后者的历史测试通过记录不替代本轮结果。

- E3：UTC 入口、轨道历元、EME2000/ITRF、CZML clock/availability/样本时间、缓存身份及显示插值。
- E4：Legacy/候选/静态身份、来源侧车、当前发布门禁、成对实验及学习来源隔离准备情况。
- 新脚本：[scripts/audit_e3_e4.py](../../scripts/audit_e3_e4.py)。这是针对本批冻结证据的 WSL/Linux 审查工具，不是通用场景发布器；依赖现有证据目录及可选 Orekit 环境。退出码 1 表示发现 FAIL，不能解释为物理验收通过。
- 物理/结构输出：`/home/meteor/eos-course-runtime/epoch-acceptance/e3-e4-main-daf4254-20261016/`。
- 测试日志（Windows）：`C:\Users\流星\.codex\worktrees\reintegrate-manifest-orbit\e3-e4-main-audit-evidence-20261016\`。
- 输入与八份被检查源码在运行前后 SHA/size/mtime 相同；四份侧车 SHA 与旧统一验收表一致。没有覆盖历史证据。
- 本轮重读四份既有物理/调度报告并冻结其哈希，未重新执行四场景的全量物理或求解验收。下表历史边界/调度 PASS 按既有报告引用。

| 本轮证据 | SHA-256 |
|---|---|
| audit_results.json | `266d05527b08871645706c5748f85d0a8deb4add3119df9758d101a52fbf1021` |
| final-evidence-index.json（本轮 43 个文件） | `f500b7a4f09009311b7671407d77d6c241b3b4f2ebfc62d611ed0322f561c8b7` |
| 审查脚本 | `93ad8e6c57377b192eba8027b52afe86866d8da5cc3ca8fab5c272f941040c6b` |
| Orekit 数据 ZIP | `1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985` |

Orekit 数据来自既有 `s1-10s20m-1d-20261016/data/orekit-data.zip`，没有下载。原始诊断主函数耗时 9.768 秒、进程自报 RSS 220732 KiB；GNU time 包含启动共 11.11 秒、峰值 RSS 221192 KiB、退出码 1。Manifest 另耗时 0.985 秒。这些数值不含本轮全部测试，也不是完整场景重算成本。

## 2. 审查结果

| 检查 | 状态 | 实际结果 |
|---|---|---|
| 整秒 Z / +00:00 / +08:00 / 约定 naive UTC | PASS | 公共 demo 导出相同绝对时间，本测试 CZML 字节也一致 |
| EME2000 / ITRF 位置和速度 | PASS | 3 星 × 3 时刻 × 2 参考系，共 18 项，和独立构造 KeplerianOrbit 的对照误差为 0 m / 0 m/s |
| 整秒 CZML 节点与独立 ITRF | PASS | 最大位置差 1.92×10⁻⁹ m；仅表示离散节点正确 |
| 小数秒 CZML 时间 | FAIL | .123456 被截为整秒，错误标时使节点位置误差最高 941.188 m |
| 非整采样区间末端覆盖 | FAIL | duration=650 s、step=300 s，只覆盖到 600 s，clock/availability 缺末端 50 s |
| build_czml 混合 aware/naive 样本 | FAIL | TypeError，未统一 UTC 后计算时间差 |
| 非法 sample.time | FAIL | AttributeError，缺少清晰的时间校验上下文 |
| 当前 main 的窗口扫描可复现性 | FAIL | GPM/M009、M020 重新出现约 26 / 49 s 截短 |
| 缓存 v2 与来源隔离 | PASS | 场景 SHA、步长和传播实现身份参与缓存路径；模拟传播身份变化得到新缓存，旧 v1 保留 |
| 四份冻结候选/Legacy/静态哈希 | PASS | 完整性和静态一致；未重新生成候选 |
| 当前 Manifest | WARN | 4 WARN、0 FAIL，20/20 任务各有窗口，通信窗口均为 0 |
| 发布门禁拒绝 candidate_only | PASS | 四份均被 capture_provenance 拒绝进入正式实验 |
| 强化 E4 来源契约 | WARN | 最小门禁仍信任本地 PASS 声明，详见后文负责人提案 |
| 浏览器 Cesium 中间点插值 | NOT RUN | 梁兆榮负责；本轮只测后端线性插值，并非浏览器验收 |
| 四场景全量物理/求解重跑 | NOT RUN | 引用已冻结报告；本轮没有重算或再次运行所有姿态采样检查 |
| E3 / E4 整体及正式发布 | FAIL / NOT APPROVED | 下述阻断项关闭并经负责人审核前保持候选状态 |

独立轨道对照固定 ALOS-2、GPM-CORE、SCD1，UTC 为 2025-11-18 12:00、2025-11-19 00:00、12:00。采用相同 Keplerian、MEAN anomaly、EME2000、WGS84、ITRF/IERS2010 与既有 simpleEOP 选项，另行构造 Orekit 参考对象。该结果验证实现内部一致性，不证明真实星历/摄像机几何精度。

## 3. 必须修复的源码问题

### 3.1 draw/orekit_to_czml.py

`build_czml::to_iso_z`（当前约 178 行）用 strftime 整秒输出，丢弃合法小数秒。实际 `demo` 输入 `2025-11-18T20:00:00.123456+08:00` 的位置按 .123456 秒传播，却标成 12:00:00Z；不能通过只比较整秒输入发现此问题。

`propagate_satellite_groundtrack` 的 while 网格没有补齐非整倍数 end。`build_czml` 又用最后样本设定 clock/availability，因此 650 秒请求被缩短为 600 秒。应保留请求时域且显式包含准确终点，不应向外插值伪造终点。

`build_czml` 应在任何排序、min/max 和相减之前复用共享时间解析器统一为 aware UTC，再输出保留必要小数位的 ISO Z。naive 只按现有历史 UTC 契约处理；失败时报带卫星/样本位置的 ValueError，禁止人工加减 8 小时。直接函数允许的输入类型应由负责人确认并写入测试。

建议最小回归：四种等价时刻、小数秒、负偏移/非法偏移、混合 naive/aware、非法类型、非整倍数结束、单点/空样本契约、clock/availability/epoch/每个 offset 与真实 ITRF 节点一致。不改变传播模型、轨道参数或卫星数据。**本轮未实施上述生产修复。**

### 3.2 utils/visibility.py 与重算工具未完整进入 main

当前 `utils/visibility.py` 仍包含粗扫描首次命中后只回退 fine_step 的旧逻辑（约 398–440 行），当前 `scripts/recompute_scenario_windows.py` 也没有冻结 `window_boundary_version`。与最终候选记录的源代码 SHA 不同，且不是 CRLF/LF 差异。

| 文件 | 当前 main SHA | 最终候选记录 SHA |
|---|---|---|
| utils/visibility.py | `757b9a0c9339f09f987a44ae245c0931e6dbbab2be1188b3498138ca140ec15c` | `401cf0ae4989af5ac088de9ac9f74dfb58f279018d44b506fa9e61bca0d4aae3` |
| scripts/recompute_scenario_windows.py | `3094955a00f13e4210654345b3d729bd7b4efb32b1d66cb7cab880fa4164e58e` | `1910797d01672e6779121d3b71d17a1b47d632cd783564447fe8a7c98465cfcc` |

`utils/time_parsing.py` 的原始字节 SHA 不同，但当前 LF 归一化后等于候选记录的 SHA；不能据此判断历元修复失效。`core/models.py` 原始字节 SHA 相同。本轮未处理无关换行差异。

局部参考采用与生产相同的目标高度、5° 仰角、45° TargetPointing Euler 限制、参考系和进入定义；以 1 秒完整局部网格找到 false/true 区间，随后二分至 1 微秒。没有以粗扫描两端不可见判断整区间不可见。

| GPM 任务 | 当前 main 起点 UTC | 独立参考进入 UTC（下界—上界） | main 起点误差上界 | 当前/参考可见姿态点数 |
|---|---|---|---:|---:|
| M009 | 2025-11-18 13:13:59 | 13:13:32.505564—32.505565 | 26.494436 s | 33 / 59 |
| M020 | 2025-11-19 09:23:59 | 09:23:09.456073—09.456074 | 49.543927 s | 17 / 66 |

相对参考首个 1 秒网格点分别截短 26、49 秒；和连续事件边界的误差需用上表，不能将两个口径混为一谈。

应从已验收源/原修复分支提取并审核 grid_v2、lazy_target_attitude_v1、同步内层片段/姿态和版本记录，再集成到最新 main；不能仅写入版本字符串。恢复相应边界/短窗口/零窗口及静态不变回归后再比较。该问题影响从当前 main 新建候选的可复现性，不会改变四份已冻结 JSON 的历史内容。本轮没有覆盖它们。

## 4. 回放缓存及插值

当前 `eos_system/visualization.py` 为 ORBIT_CACHE_VERSION=2，路径形如 `<sceneSHA>-v2-s300-<identity后16位>.czml`；identity 纳入轨道生成相关源码、数据和 wrapper 版本。当前实测 identity 为 `epoch-parser-v1-39f16443507cc19f2746afc49cc02f02d6b339d88fc1cca784009a52ea3780c0`。

**无需为本轮审查升级缓存版本或删除旧缓存。** 后续 CZML 源码修复会改变已参与 identity 的源文件，既有规则应隔离新旧缓存；届时还需实测新键。扩大身份字段或公共缓存协议须先由负责人批准。测试使用临时目录/生成桩，证明命名与隔离，不宣称重建了实际系统的全部缓存。

下面是实际 `replay/runtime.py::_orbit_samples / _position_at` 在 300 秒 ECEF 线性插值区间的中间点误差；参考为同一绝对 UTC 时刻的直接 Orekit ITRF。单位 m：

| 卫星 | +75 s | +150 s | +225 s |
|---|---:|---:|---:|
| ALOS-2 | 69818.811 | 93113.527 | 69825.561 |
| GPM-CORE | 68893.157 | 91869.063 | 68884.272 |
| SCD1 | 57783.454 | 77053.962 | 57780.600 |

这是后端插值 WARN，**不是 Cesium 浏览器的实测误差**。当前 10/20/135 秒的姿态资源网格不能恢复底层 300 秒轨道折线缺失的曲率。

交梁兆榮的浏览器验收步骤：

1. 固定 scene SHA、数据 ZIP SHA、CZML/回放配置和缓存身份，记录 Cesium 实际插值算法、阶数、参考系及版本。
2. 对每星同一 300 秒区间，在 T、T+75、T+150、T+225、T+300 的 Cesium JulianDate 取 position.getValue，导出 ECEF Cartesian3。
3. 以独立 Orekit 同时刻 ITRF 比较三维范数，记录节点/中间点最大误差；同时检查非整倍数结尾和小数秒。
4. 由负责人先定显示容差，再选择更密轨道节点或验证过的插值方式，修复后重新测量。页面仅能加载不能证明几何正确。
5. 浏览器验证前保留 NOT RUN。不得因此更改调度窗口或将示意 FOV 当作已验证物理约束。

## 5. 四份候选的 E4 身份与历史验收表

以下 SHA 本轮重新计算；静态比较覆盖现有 static_data 契约内的卫星、任务、原 ID、坐标、sensor 和资源配置。历史物理/调度状态、边界上界和完整生成成本引用冻结报告，**不是本轮重新执行所得**。

| 场景 | 片段 | 历史边界误差上界 s | 原重算 s | 原峰值 RSS KiB | 历史物理/调度 | 本轮 Manifest | 发布状态 |
|---|---:|---:|---:|---:|---|---|---|
| s1-10s20m | 110 | 0.999922 | 261.50 | 263900 | PASS / PASS | WARN | candidate_only |
| s1-20s20m | 222 | 0.999974 | 505.41 | 284560 | PASS / PASS | WARN | candidate_only |
| s2-10s20m | 132 | 0.986838 | 260.39 | 344720 | PASS / PASS | WARN | candidate_only |
| s2-20s20m | 363 | 0.998712 | 524.90 | 332316 | PASS / PASS | WARN | candidate_only |

所有候选均为 20/20 任务有窗口、0 个零窗口任务；这里的“有窗口”不等于满足所有连续拍摄约束。完整 SHA：

| 场景 | 候选 SHA-256 | 静态 SHA-256 | Legacy SHA-256 |
|---|---|---|---|
| s1-10s20m | `bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295` | `d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc` |
| s1-20s20m | `86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b` | `99459574e746c022709ed287b39e47ef9f5e310de44161e5e0699b923688136e` |
| s2-10s20m | `f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68` | `04452c8d55dd7024be5a300cb56c59aadf99589f709224904c64a2f0d29240d5` |
| s2-20s20m | `ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f` | `fb8ef1e9382175aeaa9b01518e4200333d2ee33c0d0eb0b5337648afbec1aed5` |

来源侧车：

| 场景 | 侧车 SHA-256 |
|---|---|
| s1-10s20m | `05e838a3a6c00d8c78d423ff7e61832741943ccd070b01c71a97def45cc19502` |
| s1-20s20m | `39ddbfd364a2d37106a88c1ff9dca91452b4e458e34c708987db16dc9c480bd9` |
| s2-10s20m | `30e4d84b9452ad9d417e688b7c790e5acc0283296fa920e1c88c193c3c8a223a` |
| s2-20s20m | `fc903cfc0091fed19dfe88f6c86d2a4e9f26e1d21d23128e39e352d40e4cd7e6` |

Legacy 在 `D:\VC\EOS-Course-Project\experiments\scenarios\small\`，即 WSL `/mnt/d/VC/EOS-Course-Project/experiments/scenarios/small/`；两种路径对应同一份文件。修复候选位于 WSL 的 `/home/meteor/eos-course-runtime/epoch-acceptance/<case>/candidate/`，Windows 可通过 `\\wsl.localhost\Ubuntu-22.04\home\meteor\eos-course-runtime\epoch-acceptance\` 访问；不是 main 中那六份 legacy_unknown 文件，也不会因为 git pull 自动出现。用 SHA 区分数据，禁止将候选复制覆盖 Legacy。

Manifest 本轮重新执行，结果为 PASS=0、WARN=4、FAIL=0。每份有相同三类 WARN：

- provenance：generator_version、generator_seed、source_dataset、source_group_id 未记录。
- distribution：dist0/dist1 只由文件名推断，未独立验证其分布标签。
- internal_id_reuse：Scenario_S1 / Scenario_S2 各在两种规模重复，不能单凭内部 ID 识别数据；registry_id 绑定完整内容 SHA。

Manifest 的 registered_file_count=4 是新报告的索引计数，**没有写入实际系统 registry/数据库**。结构 WARN 无 FAIL 不能当作物理正确或正式发布。

原侧车仍为 candidate_only、formal_release_eligible=false，部分状态仍 NOT_RUN；独立报告中的 PASS 不会自动回填这些声明。本轮 capture_provenance 对四份均明确拒绝，属于门禁正确。仅从 UI 指向候选目录不会完成转正。

E4 来源契约提案（本轮未改）：当前最小门禁要求 complete、released、formal_release_eligible、物理 PASS 和部分非空版本字段，但合成探针表明缺少 window_boundary_version、静态 SHA、调度验证和绑定报告 SHA 的本地声明仍能通过。它目前信任本地声明，不能等价于审核过的发布证据。请李泽同/刘懋兴审核如何绑定完整源 SHA、Orekit 数据/实现、静态 SHA、窗口版本、独立物理及调度报告 SHA、审核结论；涉及公共快照/API/存储的变更另行批准。

## 6. 必须保留的物理与实验限制

- 1 秒网格仍可能漏掉完全位于相邻采样点之间、短于采样间隔的窗口。边界误差 <1 秒仅对已找到并正确括住的事件，不是全时域无漏检证明。
- 20 星 dist0 的历史负向探针：SKYSAT-C2/M001 的 11 s 拍摄、SCD1/M007 的 13 s 拍摄，可被公共离散窗口验证器接受，但比独立连续退出分别晚 0.486354–0.486355 s、0.198823–0.198824 s。历史实际 20 任务计划最小退出余量 36.660885 s，未出现该问题。此处引用旧报告，没有本轮重跑；正式实验前须由约束负责人确定连续全时长保护政策，不能擅自收紧公共约束后仍沿用同一实验版本。
- Keplerian 与当前姿态约束内部一致不验证真实摄像机安装/FOV、初始姿态、最短四元数转向、天气或真实射频链路。comm=0 且无地面站代表未配置，不能用于评估下传/地面站冲突。
- 历史 seed/源数据/母场景族缺失不能编造补齐。不能仅凭 dist 标签声称训练和测试独立；Legacy/修复对、同母场景衍生规模应放在同一数据组。
- 算法 D 若用旧窗口特征/标签需再生成并重新训练/评估；能否复用必须提供未受影响证据。新旧场景 A/B/C/D 和基线需同 SHA、约束/指标版本、seed/预算建立全新 run，旧结果保留 legacy 标记，禁止混算。
- 50 星两份 Legacy 约 78.52/149.53 MiB，超过当前 E2 默认 64 MiB 输入上限；回放能加载不代表重算内存安全。本轮未放宽限制、未启动 50/100 星计算。

## 7. 实际测试结果与局限

| 检查 | 本轮结果 |
|---|---|
| test_epoch_parsing.py | 23/23 通过；进程 1.617 s |
| test_window_recompute.py | 44 项：43 通过、1 可选跳过；8.865 s |
| test_scenario_manifest.py | 47/47 通过；1.623 s |
| test_integrated_replay.py | 6/6 通过；35.889 s |
| test_scenario_scale.py | 11 项：10 通过、1 失败；11.380 s |
| Node 四组（固定载荷 geometry/state/view、replay acceptance） | 4/4 通过；测试框架 0.327 s |
| 全量 unittest discover | 未通过；240 s 上限退出 124、GNU time 240.03 s、RSS 100132 KiB；已有 Controller/HTTP 多项 FAIL，未得到完整最终计数 |
| Controller 单项复验 | test_real_reference_worker_success_records_zero_exit 仍失败：FAILED != SUCCEEDED；1 项 2.405 s |

专项 Python 合计 131 项：129 通过、1 跳过、1 失败。不是全量通过声明。

六场景目录失败的明确原因：审查工作树六份均为 LFS pointer，断言 all ready 不成立；不下载副本，不将此判断为主工作目录的数据缺失。相同只读目录检查在主工作目录六份均 ready。诊断见本轮 catalog-diagnostic.json / primary-catalog-diagnostic.json。

全量测试的 Controller/HTTP FAIL 不能由 LFS 断言解释，且单项可复现。尚未定位根因，不能未经对照归因为环境或推断最新 main 必有某个具体生产缺陷；需要 W2 负责人隔离复查。测试只使用隔离数据库；未改实际库。运行结束后按审查工作树 cwd 检查，未发现 unittest/multiprocessing 遗留进程，未终止用户进程。

## 8. 如何复现（小预算，不全场重算）

在本审查分支的 WSL 工作树，使用已有 venv 和数据。每次用新的、尚不存在且在仓库之外的输出目录；脚本拒绝覆盖已有目录。本脚本的输入目录结构按本批冻结证据固定。

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
/usr/bin/time -v /home/meteor/eos-course-runtime/venv/bin/python -B \
  scripts/audit_e3_e4.py \
  --evidence-root /home/meteor/eos-course-runtime/epoch-acceptance \
  --out-dir /home/meteor/eos-course-runtime/epoch-acceptance/e3-e4-main-daf4254-20261016-recheck-01 \
  --orekit-data /home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-1d-20261016/data/orekit-data.zip
```

实际原运行使用不带 recheck-01 的目录，当前 main 上预期退出 1，结果文件存在并记录 FAIL。省略 --orekit-data 仅执行纯时间/来源核查，Orekit 必须标为 NOT_RUN。

四目录结构复核（实际原运行 out-dir 为上文 manifest-current-main；重跑必须换新目录）：

```bash
/home/meteor/eos-course-runtime/venv/bin/python -B scripts/build_scenario_manifest.py \
  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-grid-v2-lazy-20261016/candidate \
  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s1-20s20m-grid-v2-lazy-20261016/candidate \
  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s2-10s20m-grid-v2-lazy-20261016/candidate \
  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s2-20s20m-grid-v2-lazy-20261016/candidate \
  --out-dir /home/meteor/eos-course-runtime/epoch-acceptance/e3-e4-manifest-recheck-01
```

专项命令逐个执行，环境设 PYTHONDONTWRITEBYTECODE=1、BLAS/OMP/MKL 线程=1：

```bash
python -B -m unittest discover -s tests -p test_epoch_parsing.py -v
python -B -m unittest discover -s tests -p test_window_recompute.py -v
python -B -m unittest discover -s tests -p test_scenario_manifest.py -v
python -B -m unittest discover -s tests -p test_integrated_replay.py -v
python -B -m unittest discover -s tests -p test_scenario_scale.py -v
node --test tests/fixed_payload_geometry.test.cjs tests/fixed_payload_state.test.cjs tests/fixed_payload_view.test.cjs tests/replay_acceptance.test.cjs
# 本轮全量实际命令；存在失败/超时，不能作为成功凭据
timeout -k 10s 240s python -B -m unittest discover -s tests -v
```

其中 python 实际为 /home/meteor/eos-course-runtime/venv/bin/python；日志保留各进程退出码和耗时。后续先修已知阻断再重跑相关专项；Controller 需负责人隔离故障后再全量复核，不反复无差别运行。

## 9. 审查通过后应做什么

当前先完成步骤 1–3；**尚未满足可以直接跳到发布/算法大规模实验的条件**。

1. **恢复正确可复现实现。** 基于最新 main 的独立分支集成已验收的 visibility_grid_v2 / lazy_target_attitude_v1 与 provenance 记录；按源/数据 SHA 找回确切版本，保留 1 秒边界、姿态、零窗口和静态不变回归。不重新随机生成任务，不覆盖四份候选。
2. **关闭 E3 阻断。** 最小 CZML 时间/终点修复及自动测试；梁兆榮完成真实浏览器插值验证和容差说明。W2 负责人定位当前全量测试失败；必要的公共协议改动另行提案。
3. **关闭 E4 审核事项。** 刘懋兴/李泽同审核连续拍摄保护、来源字段/报告绑定、历史 unknown 和 ML 分组政策。重新用最终合入代码核对四候选的输入/报告身份及系统加载/合法性；有算法变化的结果必须使用新的文件和 SHA。
4. **提交修复 PR 并审核。** 专项和必要集成测试通过后，PR 清楚列出 PASS/WARN/NOT_RUN，不能把现有候选自动标成 released。PR 合并后在新的最新 main 上最终复验。
5. **经明确批准后转正和注册。** 建立新的发布包/发布侧车绑定候选内容 SHA、父 Legacy SHA、静态 SHA、代码/数据/版本和独立报告 SHA；保留原 candidate_only 侧车及证据。如果 JSON 字节不变内容 SHA 可相同，发布包身份/侧车 SHA 必须区分；若改任何 JSON 派生数据则新 SHA。由负责人审核注册到新数据源，不覆盖 Legacy、不继承旧 run 的指标。
6. **重跑正式对照实验。** 冻结基线/A/B/C/D 的公共约束、指标、预算、seed 和场景 SHA，建立新 RunConfig/run；旧结果只作 legacy 对照。D 先完成来源分组与特征/标签重建。
7. **再讨论 50 星及更大规模。** 先给输入容量/内存、超时、磁盘和停止条件的小预算方案，审批后才重算到新目录。本轮未启动这一阶段。

## 10. 分支与每次提交顺序

当前审查不在 main 直接修改；新分支基于本轮 fetch 的最新 origin/main。按用户要求，**每一笔 commit 前**都必须再次更新并 rebase 到最新 main，而非只在 push 前做一次。

```bash
git fetch origin main
git rebase origin/main
# 如 base 有变化，先重新审查/运行受影响专项，更新证据
# 处理完冲突并验证后才暂存本轮精确文件
git add scripts/audit_e3_e4.py docs/phase2/e3_e4_main_audit_2026-10-16.md COURSE_SETUP.md
git diff --cached --check
git commit -m "chore(audit): record E3 and E4 blockers on restored main"
git push -u origin codex/e3-e4-audit
```

rebase 前须保持已跟踪文件干净或单独保存本轮改动，不混入他人文件；禁止 git add .。分支已推送后若 rebase 改写其历史，普通 push 可能拒绝，应先核实远端是否有他人提交，不能自动 force 覆盖。不得对 main force push。若提交/推送前远端 main 又有新提交，重新 fetch/rebase、解决冲突并补验证；本报告的实测基线必须仍有明确记录。

本报告只支持“审查发现及后续实施安排”，不支持“E3/E4 已发布完成”的声明。
