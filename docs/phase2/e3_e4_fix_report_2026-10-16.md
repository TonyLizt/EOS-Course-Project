# E3/E4 缺陷修复与回归报告（任务日期 2026-10-16）

本任务于 Asia/Shanghai 2026-10-16 开始、2026-10-17 完成验证；文件名遵照任务指定日期。

- branch：`fix/e3-e4-time-semantics`。
- base：最新 `origin/main` `daf4254f6a7c3157996ed77ba45278f648a405bf`；未以 audit 分支为父分支。
- 审查依据：[独立审查 78e634b](https://github.com/TonyLizt/EOS-Course-Project/blob/78e634b7184714a8b45c3a33d3f7566f2a801a26/docs/phase2/e3_e4_main_audit_2026-10-16.md)；已完整读取并按实际 main 核查。
- 本次提交的最终 HEAD 以 Git 提交及交付消息为准；测试源码的实际字节 SHA 见下表，避免用基线 HEAD 冒充运行源码版本。

**结论：P0-1～P0-4 已修复；最终 Python 267 passed / 0 failed / 0 skipped，Node 4/4 通过。真实浏览器时间/端点/微秒阶段验收通过。300 秒轨道插值精度仍 WARN，连续物理拍摄保护和正式来源审核仍 Pending review。没有将 E3/E4 写成全部发布完成。**

## 1. 工作区保护与范围

主工作目录 `D:\VC\EOS-Course-Project` 保持 main，不删除/覆盖/移动/重命名/提交原有五份未跟踪文件。修复在已有干净托管工作树新建的 fix 分支执行，audit 分支及提交未改写。提交前再次 fetch/rebase 最新 main；仅暂存本报告列出的精确文件。

未修改卫星轨道模型、参考系、传感器/FOV/资源/ID、Controller、Worker/IPC、数据库 Schema、registry、算法 factory、A/B/C/D、公共调度约束和指标。没有新依赖，没有整场重算、正式 benchmark 或正式场景注册。测试使用隔离数据库；实际运行库不变。

只从历史提交提取相关逻辑，未整次 revert/cherry-pick 其他模块，也未处理无关 CRLF/LF。混合换行 CZML 文件仅处理本轮新增/替换行的换行，AST 不变；git diff --check 通过。

## 2. 逐项根因、修复与链路核查

| 问题 | 首次出错位置/当前行为 | 正确行为与最小修复 |
|---|---|---|
| P0-1 M009/M020 截短 | `utils/visibility.py::compute_visibility_and_attitude` 原粗扫描记第一个可见粗点 g_start，细扫描 local_start=g_start-fine_td，只回退 1 秒；正确历元解析后仍未计算进入侧前置点 | 恢复完整 scenario-anchored 细网格 `_scan_visibility_grid`，不再以粗点命中为检出前提；保留相同 Keplerian、仰角与 TargetPointing 限制；按半开窗口同步更新姿态数组 |
| P0-2 CZML 小数秒 | Python datetime、AbsoluteDate 和传播样本保留微秒；`draw/orekit_to_czml.py::build_czml::to_iso_z` 首次用整秒 strftime 丢失精度 | 入口统一 aware UTC，ISO 输出保留微秒；clock、availability、position.epoch 和 offset 表示同一绝对时刻，不只修标签 |
| P0-2 显示样本第二处精度丢失 | `draw/fixed-payload-state.js` 的 Date.getTime() 将 READY 采样/阶段压成毫秒；2 微秒窗口甚至被压成零长度 | 内部用 BigInt UTC 微秒索引，比较/二分保持整数，仅在插值比例处将时间差转 Number；仍使用相同线性位置和 SLERP，不更改数据格式/公共导出 |
| P0-3 650 秒尾段 | `propagate_satellite_groundtrack` 原 while 步进越过 end；serializer 从末样本取时域，650→600 | 增加私有 `_sample_times` 闭采样网格，包含准确 end 一次；650/300 得到 0,300,600,650；零时长得到单个 0 点，其他边界同样覆盖 |
| P0-4 aware/naive | `build_czml` 在统一 UTC 前 min/max 和相减，混合输入 TypeError；非法输入 AttributeError | 在输入边界复用 `parse_orbit_epoch`，aware 转 UTC，naive 按已有 UTC 契约处理；复制样本而不修改调用者数据，非法 sample.time 以含卫星/样本位置的 ValueError 拒绝 |

已沿原始轨道/epoch→窗口→内层姿态→E2 JSON 序列化→调度计划→回放资源→CZML/Cesium 核查。M009/M020 的问题发生在窗口扫描，不是 epoch、时区或 CZML floor。没有任何生产 task_id 特判、26/49 秒常量补偿或人工加减 8 小时。

`core/scenario.py` 转发时间并消费窗口，`recompute_data/serialize_windows` 保持静态字段与原始任务并重新写出派生窗口；原逻辑可正确传递新边界，无需重写。CZML 轨道导出不直接包含观测窗口，页面展示的拍摄开始来自共享调度器的 assignment，不要求等于窗口进入时刻。

恢复来源：`571662b:utils/visibility.py` 字节 SHA `401cf0ae4989af5ac088de9ac9f74dfb58f279018d44b506fa9e61bca0d4aae3`，与最终候选记录完全一致；E2 历史 `e4d82c9:scripts/recompute_scenario_windows.py` 字节 SHA `1910797d01672e6779121d3b71d17a1b47d632cd783564447fe8a7c98465cfcc`。只提取实质修复，当前窗口/E2 完整 AST 与这两个历史实现分别一致；不声称当前工作树换行字节 SHA 仍相同。

有效窗口版本仍 `visibility_grid_v2`，姿态求值实现为 `lazy_target_attitude_v1`：每个细网格点只传播几何，仰角满足时才求 TargetPointing。不增加无界状态缓存；`coarse_step_min` 仍按兼容参数检查，不再用于剪枝。E2 恢复既有可选 `window_boundary_version` 记录；测试注入计算器为 null，未改正式来源准入政策。

## 3. 实际修改文件

| 文件 | 修改及原因 |
|---|---|
| draw/orekit_to_czml.py | UTC 输入边界、保留小数秒、准确闭采样终点；模型/输出字段结构保持 |
| utils/visibility.py | 恢复完整细网格、延迟目标姿态及半开姿态切片；消除截短和粗网格漏检 |
| scripts/recompute_scenario_windows.py | 恢复已验收实现的 window_boundary_version 字段；来源哈希继续绑定实际源码 |
| draw/fixed-payload-state.js | 内部 UTC 微秒比较/索引/时间差；不改线性/SLERP 插值方式 |
| tests/test_e3_e4_time_semantics.py | 17 项纯 Python 根因回归 |
| tests/test_e3_e4_orekit.py | 3 项显式开启的局部物理集成；无完整场景生成 |
| tests/fixed_payload_state.test.cjs | 仅追加微秒窗口/READY 插值/非法时间断言；原 expected 全部保留 |
| docs/phase2/e3_e4_fix_report_2026-10-16.md | 本报告、实际命令、误差与剩余问题 |
| COURSE_SETUP.md | 顶部补修复交接，旧记录保留 |

没有将主目录 `test_czml_time.py`、`test_visibility_boundaries.py` 或另外三份未跟踪文档加入修复分支。

## 4. 窗口、姿态和坐标实测

独立 Orekit 参考不调用生产扫描器：GPM-CORE 原六根数、英文 UTC 历元，EME2000、ITRF/IERS2010/simpleEOP、WGS84、5° 仰角与三轴 45° TargetPointing/ZYX 限制保持一致。每个任务只检查 600 秒，完整 1 秒布尔网格对照后，进入/退出 false↔true 区间二分至 1 微秒；不以两个不可见粗端点断言整区间不可见。

| 任务 | 正确网格起止 UTC | 可见姿态数 | 进入误差上界 s | 退出误差上界 s |
|---|---|---:|---:|---:|
| M009 | 2025-11-18 13:13:33—13:14:32 | 59 | 0.494436 | 0.002538 |
| M020 | 2025-11-19 09:23:10—09:24:16 | 66 | 0.543927 | 0.483987 |

两个进入上界均严格 <1 s，26/49 秒截短不再出现。各 600 个可见性布尔值一致；全部 59/66 个姿态样本角差 ≤1e-8°，E2 内层 time_windows 的起止、agile_data 三轴逐项等于这些样本，静态数据相同。

3 星 × 3 UTC 时刻 × EME2000/ITRF 的 18 项位置/速度对照误差为 0 m / 0 m/s，包含 .123456 秒和等价 +08:00 转换。24 组实际 demo（4 种小数位 × 6 种 duration）全部通过；CZML 节点最大误差 5.036897×10⁻⁹ m（阈值 1e-6 m）。这些是同模型内部一致性，不代表真实星历精度。

小数位：.000000、.123456、.500000、.999999。duration=0、100、300、600、650、900；300 秒采样相应得到 [0]、[0,100]、[0,300]、[0,300,600]、[0,300,600,650]、[0,300,600,900]，无重复终点。

## 5. 真实测试结果与环境对照

先记录 Python 红测试及 Date 微秒红测试，再修代码。未删除失败测试或调整 expected 迁就错误。

| 测试 | 最终结果 |
|---|---|
| 原 5 组专项（epoch/window_recompute/manifest/integrated_replay/scenario_scale） | 131 项：130 passed / 0 failed / 1 可选 skipped；补齐 LFS 后原目录断言通过 |
| 新纯 Python 根因回归 | 17/17 通过 |
| 新局部 Orekit 集成 | 3/3 通过；单独进程 GNU time 6.96 s，RSS 208776 KiB |
| Node 原四组 + 追加微秒断言 | 4/4 通过，0 skipped；最终框架 46.163 ms |
| Controller 原故障组（Linux 本地字节一致副本） | 21/21，通过，32.053 s；未改 2 秒启动测试预算 |
| 最终完整 unittest（含两个 opt-in 环境开关） | **267 passed / 0 failed / 0 skipped**，框架 89.957 s；GNU time 90.79 s、RSS 491808 KiB、退出 0 |

审查时失败有两个可复查的环境原因，不能靠跳过测试解决：

1. 工作树初始为 6 个 LFS pointer。使用本地现有对象 git lfs checkout 填充，六份 SHA 与 main 相同，Git 场景差异仍为零；未下载/生成新场景。
2. DrvFS 路径中的原 Controller 单项仍报 WORKER_STARTUP_TIMEOUT。将相同源码字节放在 Linux 本地后，原 21 项故障测试通过。最初用跨根符号链接共享场景，被原有目录保护正确拒绝；改为同 SHA 普通测试副本后，全量通过。未放宽路径保护、超时、断言或生产逻辑。失败日志均保留。

最终全量来自 Linux 源码快照，逐文件核对本次 7 份代码/测试的字节 SHA 与修复工作树相同；不是在不同实现上取通过结果。运行启动型测试建议使用 WSL 本地代码/数据副本，并保持输入路径满足现有保护规则。原 DrvFS 快速启动限制不能写成已修改生产代码解决。

## 6. Cesium 浏览器验收

**已实际执行，不再标整项 NOT RUN。** 使用现有成功计划→公共 verify_candidate→独立 READY replay→实际 Cesium 页面流程，隔离 3 星/1 任务/650 秒夹具；不是四候选正式实验。共享调度器 0.1 s 预算得到 1 个任务，公共验证器接受；零拍摄时长负向输入被拒绝。测试没有改算法或正式指标定义。

浏览器 CesiumJS 1.136.0：
- 实际页面 READY，显示 3 个本体和 3 个固定载荷标记；点击 M009 后选中 GPM、OBSERVING 和目标坐标同步，控制台 error 为空。
- 用同一 READY CZML 资源进行浏览器 JulianDate/position.getValue 量测。start=2025-11-18T13:11:00.123456Z，stop=13:21:50.123456Z，duration=650。
- 625、649、650 s 均有三颗卫星的位置；节点最大位置差 1.880747×10⁻⁹ m。
- 实际 FixedPayloadState 的 1 微秒前/进入/中点/退出检查 PASS，+08:00 等价输入相同；2 微秒采样区间的中点位置正确。
- 300 s 节点两侧各 1 ms 的位置变化约 7.0–7.6 m，与本夹具轨道运动相符；记录为连续性点测，不替代全时域证明。
- 截图接口两次返回 Unable to capture screenshot；保留 DOM/实际数值 JSON/控制台和服务日志，没有伪造像素截图或宣称完成截图审核。

| 实际浏览器 300 s 区间 | +75 s 误差 m | +150 s 误差 m | +225 s 误差 m |
|---|---:|---:|---:|
| ALOS-2_39766 | 70186.080 | 93591.945 | 70174.993 |
| GPM-CORE_39574 | 68855.784 | 91826.146 | 68857.492 |
| SCD_1_22490 | 58435.117 | 77908.788 | 58409.922 |

**插值精度仍 WARN**：没有已批准的显示容差，本轮没有更换插值、减小 300 秒采样或修正 Cesium 几何。梁兆榮需处理约 58–94 km 的中间点偏差并完成最终显示验收；“连续、可加载”不能替代准确。末端 50 s 现在有数据，但 625 s 的线性插值仍有约 2.2–2.6 km 误差，应区分覆盖缺失已修复与插值精度待处理。

源码热更新中，旧服务曾按原有 guard 拒绝“构建源码已变化”；重启本轮隔离服务加载最终源码后，新身份资源 READY。旧回放和场景均保留。正式部署也需重启有关构建进程，不能绕过 guard。

## 7. 四候选 Manifest / SHA 回归

四份候选、对应 Legacy、完整性侧车和静态 SHA 均重新核验，匹配历史冻结记录，仍 candidate_only，capture_provenance 继续拒绝其直接用于正式实验。过去审查冻结输入的全部 SHA 也再次一致；没有回写验证状态。

| 场景 | 候选 SHA | 静态 SHA |
|---|---|---|
| s1-10s20m | `bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295` |
| s1-20s20m | `86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b` |
| s2-10s20m | `f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68` |
| s2-20s20m | `ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f` |

Manifest 本轮退出 0：PASS=0、WARN=4、FAIL=0，无新增 FAIL。每份三类 WARN 仍为：缺 generator_version/generator_seed/source_dataset/source_group_id，dist 仅文件名证据，Scenario_S1/Scenario_S2 跨规模内部 ID 重复。registered_file_count=4 只是独立报告索引，不是实际 registry 写入。

static_data 范围包括卫星、任务、坐标、sensor、资源和原 ID；没有 resample。已有候选全量物理/调度报告本轮不重跑，继续绑定其原 SHA。当前修复不要求覆盖它们；后续任何重新派生输出必须用新文件/新 SHA，保留旧候选供成对比较。

## 8. 既有连续拍摄政策与来源审核

已有代码/设计给出了离散调度规则，本轮保持：
- ConstraintModel._intervals_overlap 使用半开重叠，end==next start 本身不算重叠；但另有 prev.end+transition_s <= next.start 的姿态转向条件，不能据“不重叠”断言可零间隔连拍。
- 非敏捷默认 10 s，敏捷按 Δg 和 agility profile 分段，Δg≤10° 和缺失角度回退 11.66 s；缺失卫星对象返回 0 属既有分支。未自行新增最小间隔。
- 公共 eos_system.verification 重新匹配来源窗口、时长、角度、顺序和资源，并调用同一 ConstraintModel；Worker 的自述结果不能代替它。4 项原转向模型测试包含在 267 项通过中。
- 现有设计尚未正式决定“1 秒网格退出点与连续物理退出之间，整个曝光应如何保护”。审查中两个 <0.5 s 连续越界探针仍是 Pending review，不能通过擅自收紧模型解决。

正式来源审核不在本次核心修复：不编造 seed、母场景族或外部资料，不修改 released 判定政策、RunConfig/API/数据库快照。window_boundary_version 仅恢复历史已有本地侧车字段，其余来源/版本/SHA 保留。静态 sensor FOV、无地面站 comm=0、亚步长漏检等限制仍在。

## 9. 缓存与兼容性

ORBIT_CACHE_VERSION 保持 2；路径字段/签名不变。已有 propagation_identity 纳入 CZML/visibility 代码，source_bundle_sha 纳入 fixed-payload-state.js，修复自然产生新身份；Node/Python 回归与实际页面热更新保护均验证隔离。没有删除或复用其他实验缓存，也未扩大公共缓存契约。

合法旧场景仍可加载，整秒 UTC 行为保持，naive 入口按历史 UTC。窗口重算派生结果允许变化，原 Legacy 及旧计划按原 SHA 保留。观测网格是 [start,end)，显示轨道样本覆盖 [start,end]；两者用途不同，不应为消除差异而改变拍摄约束。

1 秒内完全夹在两个采样点之间的短窗口仍可能漏检；本轮完整细网格防止粗采样漏检，但不宣称连续时域无漏检。lazy 优化仍保持，未自行启动 10/20/50/100 星完整计算。不能根据局部耗时承诺大场景预算。

## 10. 实际命令与证据位置

执行环境：WSL Ubuntu-22.04，已有 Python/Orekit/JDK/Node；没有安装依赖。临时 Linux 测试副本是字节一致快照，六份内置输入必须是同 SHA 普通文件，不能用跨根 symlink 绕过目录保护。

```bash
# 五组原专项逐个运行；Python 为已有 venv
PY=/home/meteor/eos-course-runtime/venv/bin/python
$PY -B -m unittest discover -s tests -p test_epoch_parsing.py -v
$PY -B -m unittest discover -s tests -p test_window_recompute.py -v
$PY -B -m unittest discover -s tests -p test_scenario_manifest.py -v
$PY -B -m unittest discover -s tests -p test_integrated_replay.py -v
$PY -B -m unittest discover -s tests -p test_scenario_scale.py -v
$PY -B -m unittest discover -s tests -p test_e3_e4_time_semantics.py -v

export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export EOS_OREKIT_DATA=/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-1d-20261016/data/orekit-data.zip
EOS_RUN_E3_E4_OREKIT_TESTS=1 $PY -B -m unittest discover -s tests -p test_e3_e4_orekit.py -v
# 完整回归在 Linux 本地快照中执行，保留原 240 秒上限
EOS_RUN_E3_E4_OREKIT_TESTS=1 EOS_RUN_OREKIT_TESTS=1   /usr/bin/time -v timeout -k 10s 240s $PY -B -m unittest discover -s tests -v
node --test tests/fixed_payload_geometry.test.cjs tests/fixed_payload_state.test.cjs tests/fixed_payload_view.test.cjs tests/replay_acceptance.test.cjs
```

Manifest 实际为同一条命令重复四次 --scenario-dir，值为各 candidate 目录：

```bash
$PY -B scripts/build_scenario_manifest.py  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-grid-v2-lazy-20261016/candidate  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s1-20s20m-grid-v2-lazy-20261016/candidate  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s2-10s20m-grid-v2-lazy-20261016/candidate  --scenario-dir /home/meteor/eos-course-runtime/epoch-acceptance/s2-20s20m-grid-v2-lazy-20261016/candidate  --out-dir /home/meteor/eos-course-runtime/epoch-acceptance/e3-e4-fix-20261016/manifest
```

以上 out-dir 已存在；重跑须另取新目录，不能覆盖本轮证据。新 Orekit 测试有 EOS_E3_E4_EVIDENCE_DIR 可选开关（本轮独立运行使用新的 orekit 子目录），已存在同名结果会拒绝覆盖。它依赖明确 SHA 的本批固定输入，默认不开启，不是完整场景生成器。

证据：
- Linux：`/home/meteor/eos-course-runtime/epoch-acceptance/e3-e4-fix-20261016/`，含最终 full-final 日志、source-sha、Manifest、candidate-checks、隔离浏览器夹具/服务/真值和 READY 资源。
- Windows：`C:\Users\流星\.codex\worktrees\reintegrate-manifest-orbit\e3-e4-fix-evidence-20261016\`，含原工作区快照、红/绿单测、原五组专项日志、局部 Orekit 数值以及浏览器下载 JSON。
- 完整浏览器结果 SHA：`83a8dac153507c61cf73fd5b603c2fa18bac3698115894598686aca395fc7bd6`。
- Orekit ZIP SHA：`1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`。
- 最终代码/测试的运行字节 SHA（Linux 副本与修复工作树核对一致；Git 换行归一化可使 blob SHA 不同）：

| 文件 | SHA-256 |
|---|---|
| draw/orekit_to_czml.py | `f2c6f141b79ac89643e3558f37c4fd2d508d89cc5a01e10ee50bf5607349bd76` |
| utils/visibility.py | `401cf0ae4989af5ac088de9ac9f74dfb58f279018d44b506fa9e61bca0d4aae3` |
| scripts/recompute_scenario_windows.py | `14c2225b6139b3e4a17133506ef0a2ef5553bb6b737a75170fa441fea21628a9` |
| draw/fixed-payload-state.js | `f5065ce53f929b6429443a593fc800609f90a9354850495b1fcda69e74f30c27` |
| tests/fixed_payload_state.test.cjs | `cb3e190be0c3a7029dcd95c494c4c3b7f126c9240f62d1f1dfe35dd819682ec4` |
| tests/test_e3_e4_orekit.py | `0ee21f92838eafc2dd99b9d2a46027763269307cafaa8480a12f4e0fa9aefcc8` |
| tests/test_e3_e4_time_semantics.py | `1cc318f126eab80a0f850af4fd0354e742f8310bb9f83ee9d2e00fe205c2b2e1` |

## 11. Fixed / Remaining blocker / Pending review

| 分类 | 状态 |
|---|---|
| Fixed | M009/M020 粗扫描截短、同步内层姿态；CZML 微秒标时；650 秒末端；aware/naive 混算；显示状态毫秒截断；LFS 工作树测试输入完整性 |
| Remaining blocker | 300 秒显示插值的显著中间点偏差及未批准显示容差；DrvFS 启动预算限制须按实测环境部署和回归，不代表 W2 已改造 |
| Pending review | 连续曝光退出保护、正式来源/分组审核、梁兆榮最终显示验收及截图取证、修复 PR 的独立组员审核 |
| Not run / not authorized | 完整场景重算、正式 A/B/C/D benchmark、候选转正、registry/实际数据库登记、自动 merge |

四项 P0 达到专项标准不等于正式场景可直接发布。先审查/合入修复，再在最终 main 复验；由负责人处理剩余政策/显示项并明确批准发布包/注册，之后才新建正式实验，不复用旧指标。

建议英文 commit / PR 标题：`fix(e3-e4): preserve replay time semantics and CZML precision`。

PR 草稿：

> Restore the accepted fine-grid visibility and lazy target-attitude implementation so GPM/M009 and M020 no longer lose 26/49 seconds at entry. Normalize UTC before CZML arithmetic, retain fractional seconds, include off-grid display endpoints, and preserve microseconds in the private browser state index.
>
> Validation: 267 Python tests passed with bounded Orekit integrations enabled; four Node groups passed; four immutable candidates retained their SHA/static data and Manifest had four WARN and zero FAIL. Real Cesium 1.136 checks passed for fractional timestamps, endpoints and microsecond phase selection. Display interpolation accuracy and formal provenance/continuous-exposure policies remain under owner review. No scene regeneration, algorithm/constraint/metric changes, registry writes or production database changes.
