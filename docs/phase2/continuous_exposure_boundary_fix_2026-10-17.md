# 连续曝光边界保护与离散窗口误接受修复（2026-10-17）

本轮完成已检测退出事件的可见侧微秒细化、复用原 Orekit 判定的独立曝光审查器、真实负向探针及完整回归。**未完成严格连续曝光认证：四份真实计划均 INCONCLUSIVE，不能正式发布。**未修改候选或计划，没有对四场景运行求解器，没有提交或推送。

## 1. Git 与保护范围

- 工作树：`D:/VC/EOS-Course-Project-boundary-guard`；分支 `fix/continuous-exposure-boundary`。
- 修改前 HEAD `0af4f61ee76828eaa806ce8fca7dd1e8c7c00204`；祖先检查确认包含 `12f8849597ce9a4f1d7875eed832082b87c1682f` 和 `0af4f61`。工作树起初干净。
- 本轮不切换 main、不重置、不合并 main、不 rebase、不创建提交或推送。上游跟踪仍为 origin/fix/e3-e4-time-semantics，后续人工提交时须明确推送目标。
- 插值的五份实现文件及测试原字节不变；时间解析模块、调度器、Controller、Worker、数据库、registry、Cesium 均未修改。
- `preflight.json` 冻结 187 份候选和历史证据；四 Legacy 的 SHA/全部静态字段另行与候选核对。历史文件及原有报告保留。

## 2. 根因及实现

原 `_scan_visibility_grid` 使用首次不可见采样点作为窗口终点；候选和公共验证器再把该离散区间当作曝光可用区间。半开 `[ws,we)` 仍包含真实退出到 we 之间的正时长不可见尾段。不能靠把 <= 改成 < 或统一扣任意秒数解决。

本轮修改：

| 文件 | 修改与边界 |
|---|---|
| `utils/visibility.py` | 新 `_refine_visibility_exit`；下界已评估可见，上界已评估不可见，二分到区间宽度不超过 **1 µs**，返回可见侧。整数 datetime 运算及中点进展检查避免无限循环。 |
| 同上 `_scan_visibility_grid` | 遇到已检测退出时细化；时域末端也实际评估，若不可见则对最后可见点至末端细化。若末端可见则按已检查端点裁剪；仍不保证端点之间无隐藏事件。零长度保守片段不导出。 |
| 同上 `create_visibility_evaluator` | 从既有函数提取原 Keplerian/TargetPointing 判定；生成和独立审查共用，不再维护第二套阈值、参考系或姿态定义。姿态计算失败显式带 evaluation_error，审查器不将其当作有效物理证据。 |
| 同上缓存 | 轨道参数缓存键改用完整 float.hex，避免近似参数舍入串扰；同 JVM 的 Orekit 数据绑定 SHA，换数据必须使用新进程。轨道传播公式和参考系不变。 |
| `utils/continuous_exposure.py`（新增） | 实际曝光时间及整数微秒时长检查；读取原始轨道、历元、目标和姿态约束重建求值器；不以 observation_windows 的终点作为物理真值。三态结果及有界实例缓存。 |
| `verify_schedules.py` | 新 `verify_continuous` 及 `--continuous` CLI；保留离散模式并明确标识 PASS_DISCRETE_ONLY。统一历史 naive UTC / aware 时间；已有不带 metrics 的 verified_plan 可复核，有 metrics 时仍检查 TCR。 |
| `tests/test_continuous_exposure.py`（新增） | 15 项（含真实 Orekit 探针）及公共序列化门禁测试，覆盖合法、越界、非法时间、缓存、隐藏间隙、端点姿态和缺证据。 |
| `tests/test_e3_e4_time_semantics.py` | 旧“29 秒首次不可见点”断言改为真实可见侧 28.999999 秒；起点、原网格样本数、姿态数保持原断言。 |
| `tests/test_e3_e4_orekit.py` | GPM 退出终点对照独立 eager Orekit 二分下界，且检查该点可见、再加 1 µs 不可见；保留原进入边界和姿态精度检查。 |
| 本报告、README、COURSE_SETUP | 使用方法、测试证据、版本及发布阻断说明。 |

现有 `compute_visibility_and_attitude` 的参数和三元组返回结构不变。原网格 samples 与 visible_attitudes 不插入细化求值点，时间和索引保持一致；`_build_time_windows_from_visible_attitudes` 已有 `ws <= t < we` 筛选，无需修改，新增测试确认终点上的原始可见样本也不会混入导出姿态。

新的派生窗口标识是 **visibility_exit_refined_v3**，边界精度常量 `EXIT_BOUNDARY_PRECISION_US=1`。既有四候选仍是旧窗口版本，不能改侧车冒认 v3。未来如批准重算，必须使用新输出文件、新 SHA 和新验收证据；本轮未启动任何整场重算。

## 3. 独立验证与明确的保证范围

四候选保留：六根数（km/deg）、轨道历元、目标 latitude/longitude/altitude_km、三轴角度限制、卫星/任务/传感器身份、creation_time 和 duration。当前实际数据中这些字段完整，没有自动补默认轨道或默认姿态界限。

仰角阈值通过 CLI 显式传入；本批 5° 与原 provenance.calculation_settings.min_elevation_deg 核对一致。模型保持 EME2000 / ITRF IERS2010 simpleEOP / WGS84 / Orekit Keplerian / TargetPointing，谓词为 el > 5° 与原三轴界限。没有新增传感器 FOV、遮挡、光照或真实电池模型的物理保证。

独立门禁先验证原计划的离散约束，再从静态输入重建实际任务的物理求值器，对实际曝光区间以 **0.05 s** 步长复核，包含曝光起止检查；遇到已确认可见→不可见的退出使用同一回调细化，并输出可见侧下界/不可见侧上界与越界量。不从待审查 JSON 的窗口终点推断物理退出。

- **FAIL**：明确不可见点、保守退出超界、无效时间/时长、离散约束不合法或 SHA 不匹配等。
- **INCONCLUSIVE**：必要物理输入/环境/预算不足，或者采样全可见但没有连续区间证书。不能映射为通过。
- **PASS**：还必须有可信代码内的连续区间证书覆盖各区间；CLI 不读取 JSON 的自称证书字段。本轮只有解析性合成测试提供可证明的恒真区间证书，**真实 Orekit 求值器没有实现该证书**。

因此 50 ms 复核无违规，只能得到 sampled_boundaries_status=PASS，整体仍为 INCONCLUSIVE。二分仅收敛到括区中检测到的退出，不证明不存在更早的隐藏事件，也不发现所有完全夹在两次采样之间的不可见间隙。进入点保持首次可见网格点；没有擅自向来源窗口之前移动起点。

物理层求值失败与缺字段不能冒充可见。首任务初始姿态、曝光结束时刻的精确转向姿态及连续转向动力学也未因此获认证。新的严格门禁是独立验收 CLI；**现有 Controller 的离散验证路径没有自动改为连续认证**，调用方必须检查严格结果和退出码。

## 4. 两个已知误接受案例：实际重建结果

原证据根为 `/home/meteor/eos-course-runtime/epoch-acceptance/s2-20s20m-grid-v2-lazy-20261016/independent-e3-20261016/`。
`continuous_duration_probe_report.json` SHA 为 `a1629ddaf3ab7fb730ccf38fdc6c169f67089ebcdb4cb9d13bd15fe1158a7026`；其参考括区精度为 1 µs。这些数值只用于本地案例，不是所有场景的固定物理常数。

| 任务 / 卫星 | 原曝光 UTC | 所需 s | 新重建退出可见侧 / 不可见侧 UTC | 越界范围 s | 实际 CLI |
|---|---|---:|---|---|---|
| M001 / SKYSAT-C2_41773 | 2025-11-18 15:06:44–15:06:55 | 11 | 15:06:54.513645 / .513646 | 0.486354–0.486355 | FAIL，拒绝 |
| M007 / SCD_1_22490 | 2025-11-19 04:46:29–04:46:42 | 13 | 04:46:41.801176 / .801177 | 0.198823–0.198824 | FAIL，拒绝 |

这两个是原有单任务负向探针，不是本批四份已接受的 20 任务计划。本轮实际调用公共 `verify_continuous` 和 CLI，不只是断言辅助函数返回值。新证据 `known-probes.cli.json` 保留每份原计划 SHA、模型源码 SHA、重建括区和拒绝原因 NONVISIBLE_EXPOSURE_POINT；CLI 退出码 **1 为预期拒绝**。

## 5. 四份候选与实际计划：最终代码重验

逐个校验原 config.scenario_path/SHA、候选来源侧车及 Legacy；重新计算候选所有非窗口静态字段的规范 SHA，并与 Legacy 的静态对象逐字段比较相等。没有改动原始 ID、传感器、资源或任务坐标。

| 场景 | 候选 SHA-256 | 实际调度计划 SHA-256 |
|---|---|---|
| s1-10s20m-grid-v2-lazy-20261016 | `bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `23afb113ecf269c05c673e9f0e48ff2493f13a80a4471c0818f7d84fc58e6c77` |
| s1-20s20m-grid-v2-lazy-20261016 | `86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `221da06c568f6ee0884bff32d623aea2c22ff007eb1a08bd6dac8572f9f8858a` |
| s2-10s20m-grid-v2-lazy-20261016 | `f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `85eb29839d8cb0cd5aa28cc9db47ba8c431832e55a38cd4086772d5b1b52c2b5` |
| s2-20s20m-grid-v2-lazy-20261016 | `ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `6e14284bccd42a280719532748f3c5be77f952560ec02c59733d9b0d9bfa6f97` |

准确路径来自原配置及证据索引，场景 JSON 与计划 JSON 明确分开：

- **s1-10s20m-grid-v2-lazy-20261016**
  - 场景：`/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-grid-v2-lazy-20261016/candidate/Scenario_S1_Sats10_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json`
  - 计划：`/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-grid-v2-lazy-20261016/independent-e3-20261016/scheduling/verified_plan.json`
- **s1-20s20m-grid-v2-lazy-20261016**
  - 场景：`/home/meteor/eos-course-runtime/epoch-acceptance/s1-20s20m-grid-v2-lazy-20261016/candidate/Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1_grid_v2_lazy.json`
  - 计划：`/home/meteor/eos-course-runtime/epoch-acceptance/s1-20s20m-grid-v2-lazy-20261016/independent-e3-20261016/scheduling/verified_plan.json`
- **s2-10s20m-grid-v2-lazy-20261016**
  - 场景：`/home/meteor/eos-course-runtime/epoch-acceptance/s2-10s20m-grid-v2-lazy-20261016/candidate/Scenario_S2_Sats10_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json`
  - 计划：`/home/meteor/eos-course-runtime/epoch-acceptance/s2-10s20m-grid-v2-lazy-20261016/independent-e3-20261016/scheduling/verified_plan.json`
- **s2-20s20m-grid-v2-lazy-20261016**
  - 场景：`/home/meteor/eos-course-runtime/epoch-acceptance/s2-20s20m-grid-v2-lazy-20261016/candidate/Scenario_S2_Sats20_M20_T1.0d_dist0_epoch_fixed_v1_grid_v2_lazy.json`
  - 计划：`/home/meteor/eos-course-runtime/epoch-acceptance/s2-20s20m-grid-v2-lazy-20261016/independent-e3-20261016/scheduling/verified_plan.json`

| 场景 | 任务数 | 严格通过 | 已发现连续违规 | 无法判定 | 最终状态 | 求值次数 | 审查器墙钟 s | CLI 总墙钟 | RSS KiB |
|---|---:|---:|---:|---:|---|---:|---:|---|---:|
| s1-10s20m-grid-v2-lazy-20261016 | 20 | 0 | 0 | 20 | **INCONCLUSIVE** | 3920 | 5.405 | 0:06.15 | 234736 |
| s1-20s20m-grid-v2-lazy-20261016 | 20 | 0 | 0 | 20 | **INCONCLUSIVE** | 3900 | 4.976 | 0:05.76 | 223716 |
| s2-10s20m-grid-v2-lazy-20261016 | 20 | 0 | 0 | 20 | **INCONCLUSIVE** | 4280 | 5.075 | 0:05.77 | 239696 |
| s2-20s20m-grid-v2-lazy-20261016 | 20 | 0 | 0 | 20 | **INCONCLUSIVE** | 4360 | 5.055 | 0:05.80 | 253812 |

80 条均无采样到的不可见点，离散约束也通过，但理由均为 **NO_CONTINUITY_CERTIFICATE**，严格 CLI 均退出 **2**。没有把旧验证器 PASS 或旧物理报告复用为本轮严格 PASS。完整逐任务结果见本轮 `final-audits/*.json`，每份含实际曝光、要求时长、采样检查状态和无法判定理由。

原公共 `eos_system.verification.verify_candidate` 另外对四旧计划做了只读内存复核，返回对象与原 verified_plan 完全一致；记录为 **PASS_DISCRETE_ONLY**，没有导出或持久化返回对象，没有运行真实调度求解器。证据为 `public-discrete-recheck.json`。

静态 SHA：

| 场景 | 静态 SHA-256 |
|---|---|
| s1-10s20m-grid-v2-lazy-20261016 | `c4b1404bd4e6c6ba71b0597bd90cbb03f179559c3a35f91e8d911d19e7f62295` |
| s1-20s20m-grid-v2-lazy-20261016 | `180426a5794b48755520c032cd4824f61bb82a555a6d7e9184af1553a8c8e18b` |
| s2-10s20m-grid-v2-lazy-20261016 | `2caa8648e7800fc8fd746ea5d5564c0d274352e16ec83d88859cfc0891e94f68` |
| s2-20s20m-grid-v2-lazy-20261016 | `1875ce02713c0f9f0dae90099db0068f8983e8ecf7ec1ec761b95685df98d56f` |

## 6. 测试、失败记录与环境

- **完整 Python：289 passed / 0 failed / 0 skipped**，unittest 90.428 s，GNU time 墙钟 91.40 s，峰值 RSS 483300 KiB，退出 0。
- 新曝光测试最终 **15/15** 在完整回归中通过。早期专项 13/13（增加两项姿态/伪证书测试前）5.506 s、墙钟 6.72 s、RSS 240468 KiB，日志保留。
- P0 时间/真实 Orekit 专项 **20/20**，6.533 s、墙钟 7.96 s、RSS 242408 KiB。
- 原插值专项 **7/7**（含真实 Orekit），5.941 s、墙钟 7.45 s、RSS 254576 KiB；五份插值实现文件和插值测试字节不变。
- Node **5/5**：fixed_payload_geometry、fixed_payload_state、fixed_payload_view、orbit_interpolation、replay_acceptance。
- 两原探针实际 CLI：退出 1（预期拒绝），墙钟 5.70 s，RSS 203632 KiB。
- 初始原 P0 测试有 **1 项失败**：它要求不可见的整数终点 29 秒，与新约束冲突。`contract-transition-red.*.log` 保留原失败。没有降低精度或删除测试，改为 28.999999 秒严格可见侧断言；GPM 终点与独立 eager Orekit 下界严格相等，而不是简单替换成另一个手填期望值。最终失败数为 0。
- 测试只使用临时合成 fixture / 原项目隔离测试库。完整套件含原有合成求解器单测，但没有对四真实候选运行调度或生成其计划。

环境：WSL Ubuntu 22.04；Python `3.10.12`；orekit_jpype `13.1.5.0`；JPype `1.5.2`；`JAVA_VERSION="25.0.2"`，JDK 路径 `/home/meteor/eos-course-runtime/venv/lib/python3.10/site-packages/jdk4py/java-runtime`。实际记录在 `environment.json`。

测试在 Linux 原生新副本运行，避免 /mnt/d I/O 放大。234 份文件逐项 SHA 验证；五份大数据仅对旧隔离测试副本建立只读硬链接，测试前后哈希不变，避免额外重复占盘。真实候选/正式库不与该测试副本混用。没有清理历史证据。

## 7. 可复现命令

以下默认当前目录是本工作树在 WSL 下的路径。真实检查不会调用求解器；--report 以排他创建模式写入新文件，不能覆盖旧报告。

```bash
cd /mnt/d/VC/EOS-Course-Project-boundary-guard
PY=/home/meteor/eos-course-runtime/venv/bin/python
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export EOS_OREKIT_DATA=/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-1d-20261016/data/orekit-data.zip
export EOS_RUN_EXPOSURE_OREKIT_TESTS=1
export EOS_RUN_E3_E4_OREKIT_TESTS=1
export EOS_RUN_ORBIT_INTERPOLATION_TESTS=1
export EOS_RUN_OREKIT_TESTS=1

"$PY" -B -m unittest discover -s tests -p test_continuous_exposure.py -v
"$PY" -B -m unittest discover -s tests -p 'test_e3_e4*.py' -v
"$PY" -B -m unittest discover -s tests -p test_orbit_interpolation.py -v
/usr/bin/time -v timeout -k 10s 240s "$PY" -B -m unittest discover -s tests -v
for test in tests/*.test.cjs; do node "$test" || break; done

# 将下面的实际路径、SHA换成第5节同一行对应值，NEW_REPORT必须尚不存在。
"$PY" -B verify_schedules.py "$SCENE" "$PLAN"   --continuous --orekit-data "$EOS_OREKIT_DATA"   --min-elevation-deg 5 --scan-step-s 0.05   --expected-scenario-sha "$SCENE_SHA" --expected-plan-sha "$PLAN_SHA"   --report "$NEW_REPORT"
```

四计划最终实际 argv（含所有准确路径、SHA、超时和报告路径）保存在 `final-audits/summary.json`，可直接复核，不能把路径占位符当作已执行命令。CLI 状态码：PASS=0，FAIL=1，INCONCLUSIVE=2。2 是严格门禁不放行，不能当作运行异常重试到变为 0。

Orekit ZIP SHA：`1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`。

## 8. 缓存、开销及兼容性

审查器实例最多缓存 8 个卫星/任务/目标求值器，每个求值器最多 256 个时刻，默认最多 100000 次真实求值；键含场景内容摘要、精确物理参数、目标/姿态/阈值、数据 SHA 和审查版本，不复用其他实例的审查结果。预算耗尽明确 INCONCLUSIVE。基础模块原有进程级 Orbit 缓存保持同一模型，改为无舍入身份以防输入串扰；长驻批量模式资源上界未在本轮认证。

每个已检测退出增加约 log2(步长/1µs) 的判定，1 秒括区约 20 次，再加端点核实。没有全场景性能测量，不承诺原 10/20/50 星生成预算。末端两点均可见也仍可能隐藏事件，检查了末端不等于证明整个尾区间。

旧场景和旧计划继续可读，数据本体不改。新生成的退出边界/极短片段可能与 v2 不同，必须新版本、新文件与新 SHA；不能覆盖已有候选。原调度算法及公共 JSON Schema 不变，新增的是 CLI/工具函数与内部求值回调。没有扩展公共数据库或缓存键契约，既有源码 SHA 身份会区分变更。

## 9. 发布结论与交接

**仍有发布阻断：现有物理实现没有可验证的连续区间界限/证书，80 条任务只能 INCONCLUSIVE。**严格连续曝光认证在此停止，不能靠继续缩小扫描步长、放宽断言或把 sampled PASS 改名解决。

后续若要求真实计划 PASS，需要在相同可见性模型上提供可审查的连续区间证明或严格事件隔离保证，并重新运行独立门禁；必要时另行批准接口/证据协议。Controller 默认离散验证尚不构成该门禁。传感器 FOV、遮挡、照明、硬件时钟/控制误差与连续姿态动力学等额外物理约束仍未建模。

本轮不提交、不推送、不创建 PR，等待人工审查；并未声称正式发布完成。

## 10. 新证据位置

`/home/meteor/eos-course-runtime/epoch-acceptance/continuous-exposure-20261017/`：preflight.json、environment.json、test-source-final-sha256.json、full.*.log、node.json、known-probes.cli.json、public-discrete-recheck.json、final-audits/summary.json 和逐任务报告。初次四计划报告及旧断言失败日志保留。大型证据不入 Git。

本次核心源码 SHA（与最终审查结果绑定）：

- `utils/visibility.py`: `6e5416cb8d459fc16b87d4c90b4abb7569a5a9887687098cabb5a1540a6a09cf`
- `utils/continuous_exposure.py`: `7356774239437cfdb0bcde933b7e48ce1345190a5bb71cbe60cbf6cebb7df9f6`
- `verify_schedules.py`: `87603d783485bed9d973c5d27fb36acc89aa64b367624783e395af322cc3df86`
- `tests/test_continuous_exposure.py`: `4e6b719fd0919440bd6ec0d70893d1492867ba3f7fb95b79b4a3463dc73b2aa7`
- `tests/test_e3_e4_time_semantics.py`: `7743a9e4bffa3fc970a35c59261b186cdefb2b80ac5160e83d4bad4985766658`
- `tests/test_e3_e4_orekit.py`: `069631dc623e1bab121951e6ee238b78aa68cb2b7c315fff7e92703bddfde08e`


---

## 11. P1 正式链路接入：本轮最终结论

本节及后续为 2026-10-17 的 P1 实施；第 1–10 节保留此前独立工具阶段的历史数据（289 项测试、audit_v1），不能将其“Controller 未接入”的描述当作当前状态。本轮保留全部原有修改，未提交、推送或创建 PR。

**P1 接入已完成，可交人工代码审查；正式发布仍阻断。** 新增链路专项 **17/17**；最终完整 Python **306 passed / 0 failed / 0 skipped**；Node **5/5**。四份真实计划共 80 条任务是 **PLANNING_FEASIBLE 80，但严格认证 PASS 0 / FAIL 0 / INCONCLUSIVE 80**。规划可行绝不等于连续物理认证。

- 工作树 `D:/VC/EOS-Course-Project-boundary-guard`，分支 `fix/continuous-exposure-boundary`，HEAD 仍为 `0af4f61ee76828eaa806ce8fca7dd1e8c7c00204`；包含 `12f8849`、`0af4f61`。没有 reset、rebase、checkout、合并 main 或修改上游跟踪。
- 实际代码身份是未提交工作树文件 SHA，不能将该基础 HEAD 冒充本轮实现提交。最终 Python 源码摘要为 `gate-final-source-sha256.json`，待审文件摘要为 `working-files-sha256.json`。
- 新审查版本为 `continuous_exposure_audit_v2`；窗口算法沿用 `visibility_exit_refined_v3`。本轮没有再次修改原边界算法、原连续曝光专项和两份 E3/E4 测试文件的字节。
- 新证据 RUN_DIR：`/home/meteor/eos-course-runtime/epoch-acceptance/continuous-exposure-p1-20261017T024314Z`。原证据目录 `continuous-exposure-20261017` 的文件保持原样，新证据不覆盖旧证据。

### 11.1 统一五态契约和规划依据

| 共享状态 | 含义 | 能否成为正式成功 |
|---|---|---|
| REJECTED | 已知越界、物理不可见或无正时长保守区间 | 否 |
| PLANNING_FEASIBLE | 通过有来源依据的保守规划规则，未证明连续性 | 否 |
| CONTINUOUS_PASS | 真实审查结果完整、每条曝光具有可信连续证明，并与输入身份绑定 | 还须通过其他共享约束 |
| INCONCLUSIVE | 未发现违规，但来源或连续性证据不足 | 否 |
| ERROR | 输入、执行、证据或超时错误 | 否 |

所有曝光比较复用 `parse_orbit_epoch` 和 `exposure_times`，按绝对 UTC、整数微秒及半开区间处理。历史 naive UTC 按原契约解释；拍摄时长必须精确匹配，不能使用 1 微秒容差接受短时长。窗口之间不得拼接曝光。

候选池与 ConstraintModel 共用 `planning_exposure`，不是复制两套规则：

1. v2 必须同时具备匹配场景 SHA、完成侧车、Orekit 来源、经审计的实现 SHA、真实且匹配的扫描步长。历史 v2 实现白名单 SHA 为 `401cf0ae4989af5ac088de9ac9f74dfb58f279018d44b506fa9e61bca0d4aae3`。
2. v2 终点是首次不可见点或未证明的时域截断。规划终点扣除 **一个实际采样步长**，回到/早于最后可见样本。这里的 1 秒来自四候选实际步长，不是任意固定余量；其他步长按自身配置计算。此规则仍不证明采样点之间连续可见。
3. v3 已采用可见侧退出边界，不重复扣减 1 秒或 1 微秒预算。已检测退出的括区精度与连续区间证明分开记录。
4. 来源缺失、陈旧、矛盾、符号链接、过大侧车或步长不匹配均不默认零保护。JSON 中单条窗口自报的 trusted/certified 字段无效。
5. 正式物理阈值取自同一份已核实的来源；不能优先使用与侧车不一致的嵌入元数据。来源确认建立在可信本机文件与安装源码上，尚不是面向恶意文件系统的签名供应链。

原有姿态切片、非敏捷卫星中心、转向时间及资源计算保留。旧离散约束主体改名 `check_discrete_assignment`，只用于历史诊断和独立物理探针；所有正常规划入口调用带保护的 `is_feasible_assignment`。CLI 不带 --continuous 的 PASS_DISCRETE_ONLY 不能用于正式接收。

### 11.2 正式执行链路及接口变化

| 文件:行号 / 函数 | 接入内容 |
|---|---|
| `utils/continuous_exposure.py:342` / `planning_exposure` | 五态契约、同一规划判定 |
| `schedulers/scenario_loader.py:204` / `load_scheduling_problem_from_json` | 核实来源并附加内部 planning_evidence |
| `algorithms/candidate_pool.py:83` / `enumerate_task_candidates` | 候选插入前执行共享保护 |
| `schedulers/constraint_model.py:289` / `is_feasible_assignment` | 所有共享安排先检查安全区间 |
| `eos_system/verification.py:42` / `verify_candidate` | 共享约束和独立连续认证，返回三元组 |
| `eos_system/controller.py:120` / `_verify_with_deadline` | 后台认证、超时和可信凭证门禁 |
| `eos_system/storage.py:409` / `finish_success` | 成功事务必须有匹配凭证 |
| `eos_system/storage.py:480` / `get_run` | 历史记录、源码和计划 SHA 核验 |
| `eos_system/storage.py:536` / `get_replay_source` | 回放/可视化来源不绕过认证 |
| `eos_system/storage.py:682` / `record_export` | 直接导出记录也检查认证 |
| `eos_system/exporting.py:18` / `require_certified_record` | JSON/CSV/目录只接受 Storage 可信记录 |
| `eos_system/api.py:225` / `export_run` | 沿用 HTTP_409 错误格式并校验认证 |
| `core/scenario.py:234` / `calculate_visibility_windows` | 普通生成写入版本、精度和 NOT_RUN |
| `scripts/recompute_scenario_windows.py:325` / `recompute_file` | 外部侧车记录相同语义，静态字段不补写 |
| `eos_system/config.py:129` / `algorithm_source_sha256` | 将共享物理/时间代码纳入运行代码身份 |

链路为：场景加载并核实来源 → 候选池/共享约束保守规划 → 原 Engine/Worker 返回未认证候选 → Controller 进入 VERIFYING → 正式验证器独立重建共享约束、资源、姿态和 UTC 时间 → `certify_schedule` 复用原 Orekit 审查器 → Controller 校验内部认证凭证 → Storage 在同一事务内校验并保存凭证事件、计划、任务和指标 → SUCCEEDED → 读取/导出再次核验。

Engine、参考 Worker 的实现无需改变；它们返回的仍是候选，不具备成功持久化权。Worker 自报 continuous_verified 或伪造的 continuous_certification 字段不会被纳入 Controller 重建的正式计划。

`verify_candidate` 现在返回 `(plan, metrics, CertificationReceipt)`，Controller 为唯一正式调用方。`finish_success` 新增必需通过的 keyword-only `certification` 参数；未提供或提供 JSON 字典会失败。凭证是带进程内来源能力的对象，不能经 Worker JSON 伪造。读取后的 CertifiedRecord 也携带不参与 JSON 序列化的能力；复制一份看似有效的字典不能直接正式导出。

认证证据绑定 run_id、场景文件 SHA、规范计划 SHA、audit_v2、六份相关源码 SHA、Orekit 数据 SHA、阈值、采样配置、精度、完整审查摘要及认证任务数。不同计划、场景、审查版本或源码的旧凭证不能复用。原始计划不嵌入补写证据，不改变冻结计划 SHA。

### 11.3 状态迁移、事务及导出防绕过

- 仍使用原 QUEUED → RUNNING → VERIFYING 状态机。只有共享约束全部通过且 CONTINUOUS_PASS 才进入 SUCCEEDED。
- REJECTED / INCONCLUSIVE / ERROR 分别记录为 FAILED，认证错误码为 CONTINUOUS_REJECTED / CONTINUOUS_INCONCLUSIVE / CONTINUOUS_ERROR。其余未包装异常由原队列保护记录对应异常类型，仍是 FAILED、无正式计划。停机保持原 CONTROLLER_STOP；取消与算法超时维持原事务裁决。
- **不新增数据库枚举、不修改 schema、不做真实数据库迁移。** CONTINUOUS_CERTIFIED 记录在既有 run_events 表，与 plans/assignments/metrics 及 SUCCEEDED 位于同一事务。诊断接口禁止伪造该保留事件。
- 无凭证、身份不符或后续指标写入失败时事务回滚；没有部分计划、悬空指标或“先成功后认证”的窗口。负向 Controller 测试直接检查 finish_success 未被调用，且三张结果表为空。
- 认证在 Controller 后台线程中执行，不在 HTTP 请求线程运行。默认截止 30 秒；单次物理求值间也检查期限。超时后迟到 PASS 无权提交；同一 Controller 最多有一个在途认证线程，防止积累。
- 停机等待认证线程；若原生调用没有退出则保留实例锁并显式报错，不能静默释放锁。永久阻塞的 JVM/native 调用仍可能需要人工恢复服务，属于可用性剩余风险。
- Storage 写入、get_run、get_replay_source、record_export，JSON/CSV 渲染、目录导出和 API 正式导出均设置校验。读取核对存储计划字节 SHA、规范计划身份、场景身份、审查版本与当前源码。
- 历史 SUCCEEDED 保留原数据库状态和归档证据，列表/详情额外给出连续认证状态。无当前有效证据时不返回正式 plan；API JSON/CSV/可视化计划请求返回原格式 HTTP_409，目录导出不创建文件。现有离线历史文件不删除，也不能被重新解释为已连续认证。

当前成功状态承担正式认证结果语义；本轮没有新增“仅实验成功”发布通道。算法可能完成搜索，但认证证据不足仍会停在 FAILED / CONTINUOUS_INCONCLUSIVE，不能为维持成功率将其改为 PASS。

### 11.4 负向测试与正确的正向注入

`tests/test_continuous_pipeline.py` 共 17 项，覆盖：

- M001/M007 在原离散约束主体实际返回 True；新候选池返回空、新共享约束返回 False、新共享构造器拒绝。
- v3 不重复扣预算、UTC 等价时间、1 微秒越界、步长不匹配、未核实来源与不连续窗口。
- 普通场景生成记录退出精度与 NOT_RUN，而不是伪造连续 PASS；陈旧、超大及符号链接侧车不能回退；v2 阈值由已核实来源而非嵌入声明决定。
- 使用真实 spawn/IPC 的 Controller 接收流程，在连续 FAIL、INCONCLUSIVE、异常、超时及 Worker 伪造字段下不调用成功持久化；迟到 PASS 也不能提交。
- Storage 拒绝缺失/字典伪造/其他计划的凭证，事务无残留；历史 SUCCEEDED 在 Storage/API/JSON/CSV/目录导出均被挡住。
- 一个**明确标记 UNIT_TEST_INJECTION_ONLY** 的模拟完整认证通过，走过真实 Controller、Storage 成功事务及导出；随后篡改计划便无法再次读取/导出。

模拟能力只在测试夹具或 unittest.mock 中注入，实际场景 CLI 从不安装这些模拟器；没有 HTTP/Worker JSON/环境变量开关能启用模拟认证。不能把临时测试库中的 PASS 或模拟凭证用于四份真实场景。

原 lifecycle、事务和 replay 正向夹具显式使用测试凭证，以保留原取消、进程回收、回滚、导出和回放断言；没有删除失败断言或将全体分支无条件拒绝。原 E3/E4、插值及连续曝光专项保持原测试内容。

真实探针继续通过公共 CLI，并返回 NONVISIBLE_EXPOSURE_POINT：

| 案例 | 曝光 UTC | 重建退出括区 UTC | 超出区间秒数 | CLI |
|---|---|---|---|---|
| M001 / SKYSAT-C2_41773 | 2025-11-18 15:06:44–15:06:55，11 s | 15:06:54.513645–.513646 | 0.486354–0.486355 | FAIL / exit 1 |
| M007 / SCD_1_22490 | 2025-11-19 04:46:29–04:46:42，13 s | 04:46:41.801176–.801177 | 0.198823–0.198824 | FAIL / exit 1 |

原参考文件 SHA/精度见第 4 节；这些数值仅是两个已知案例，不是全局常数。两个新 CLI 结果保存在 gate-final-audits/known-probe-1.json、known-probe-2.json。

### 11.5 四冻结候选与计划：最终代码只读复核

| 场景 | 候选 SHA-256 | 实际计划 SHA-256 |
|---|---|---|
| s1-10s20m | `bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `23afb113ecf269c05c673e9f0e48ff2493f13a80a4471c0818f7d84fc58e6c77` |
| s1-20s20m | `86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `221da06c568f6ee0884bff32d623aea2c22ff007eb1a08bd6dac8572f9f8858a` |
| s2-10s20m | `f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `85eb29839d8cb0cd5aa28cc9db47ba8c431832e55a38cd4086772d5b1b52c2b5` |
| s2-20s20m | `ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `6e14284bccd42a280719532748f3c5be77f952560ec02c59733d9b0d9bfa6f97` |

| 场景 | 任务 | PASS | FAIL | INCONCLUSIVE | 本轮 CLI 墙钟 s | 峰值 RSS KiB |
|---|---:|---:|---:|---:|---:|---:|
| s1-10s20m | 20 | 0 | 0 | 20 | 4.951 | 228840 |
| s1-20s20m | 20 | 0 | 0 | 20 | 5.014 | 231576 |
| s2-10s20m | 20 | 0 | 0 | 20 | 4.787 | 195848 |
| s2-20s20m | 20 | 0 | 0 | 20 | 4.935 | 236696 |

80 条全部为 INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE，sampled_boundaries_status 全为 PASS。文件缺失、Orekit 初始化失败、任务窗口不匹配、时间解析错误和内部异常导致的 INCONCLUSIVE 均为 0。额外的共享规划检查为 80 条 PLANNING_FEASIBLE；它不会被映射为认证通过。

准确候选与计划路径保持第 5 节所列路径，均由原证据读取，未重新运行求解器。完整文件 SHA 相同，卫星、任务、坐标、传感器、资源、原始 ID 及窗口内容均未被补写。187 份受保护候选/Legacy/历史证据全部复核一致；原轨道插值相关七文件与前次 preflight SHA 一致，E3/E4 修复未回退。

### 11.6 测试、资源与可复现命令

- 新增链路专项 **17/17**，墙钟 6.323 s，RSS 88408 KiB。
- 完整 Python **306/306，0 failed / 0 skipped**，墙钟 96.939 s，RSS 471016 KiB，退出 0。
- 完整套件含原连续曝光 15、E3/E4 20（时间 17 + Orekit 3）、轨道插值 7、新链路 17，原 Controller 停机 13 等测试。
- Node **5/5**，全部退出 0；未修改其实现或期望。

最终日志 gate-full.stderr.log、gate-pipeline.stderr.log、gate-node.json 和 gate-final-summary.json；所有 Orekit 可选测试开关实际开启，未以跳过替代通过。最终测试副本 Python 源码逐字节匹配工作树（gate-final-source-sha256.json）。测试副本复用已校验的只读输入硬链接，测试使用临时库，不初始化或修改实际运行库。

保留早期失败证据：pipeline-first 有 4 fail / 1 error，来自新增夹具缺失 SolveContext 和环境没有可选 httpx；修正夹具并复用标准 ASGI 调用后通过。full-first 的停机错误码/认证线程等待回归也保留，已通过实现修复恢复原断言。中间 304/305 项成功记录为阶段证据，最终以 306 项和 gate-* 文件为准。

环境沿用 WSL Ubuntu 22.04、Python 3.10.12、orekit_jpype 13.1.5.0、JPype 1.5.2、JDK 25.0.2。Orekit ZIP SHA `1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`。

实际 cwd 为 RUN_DIR/source，最终完整命令如下；也可切换至字节一致的 WSL 工作树执行：

```bash
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export EOS_OREKIT_DATA=/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-1d-20261016/data/orekit-data.zip
export EOS_RUN_EXPOSURE_OREKIT_TESTS=1 EOS_RUN_E3_E4_OREKIT_TESTS=1
export EOS_RUN_ORBIT_INTERPOLATION_TESTS=1 EOS_RUN_OREKIT_TESTS=1
/usr/bin/time -v timeout -k 10s 240s /home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover -s tests -p test_continuous_pipeline.py -v
/usr/bin/time -v timeout -k 10s 240s /home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v
```

Node 实际逐份执行 tests/*.test.cjs；五个文件及 stdout/stderr/退出码见 gate-node.json。真实六次 CLI 的完整 argv、候选/计划 SHA、新报告路径、计时和退出码在 gate-final-audits/summary.json，不能把历史报告路径再次作为 --report 覆盖。重现时必须指定新的报告名。CLI 0=PASS、1=FAIL、2=INCONCLUSIVE；后二者都不得正式放行。

### 11.7 全部待审文件清单与保护范围

全工作树共 **31 文件**（26 个 tracked 修改、5 个 untracked）；其中 9 文件为先前未提交修复，P1 另触及 22 文件。以下为相对于 `D:/VC/EOS-Course-Project-boundary-guard` 的精确路径：

- `COURSE_SETUP.md`
- `README.md`
- `algorithms/candidate_pool.py`
- `core/scenario.py`
- `eos_system/api.py`
- `eos_system/config.py`
- `eos_system/controller.py`
- `eos_system/exporting.py`
- `eos_system/storage.py`
- `eos_system/verification.py`
- `schedulers/constraint_model.py`
- `schedulers/scenario_loader.py`
- `scripts/recompute_scenario_windows.py`
- `tests/test_adaptive_repair.py`
- `tests/test_controller_cancel.py`
- `tests/test_controller_shutdown.py`
- `tests/test_controller_timeouts.py`
- `tests/test_e3_e4_orekit.py`
- `tests/test_e3_e4_time_semantics.py`
- `tests/test_integrated_replay.py`
- `tests/test_replay_backend.py`
- `tests/test_replay_delivery.py`
- `tests/test_system_storage.py`
- `tests/test_system_v02.py`
- `utils/visibility.py`
- `verify_schedules.py`
- `docs/phase2/continuous_exposure_boundary_fix_2026-10-17.md`
- `tests/certification_fixtures.py`
- `tests/test_continuous_exposure.py`
- `tests/test_continuous_pipeline.py`
- `utils/continuous_exposure.py`

原 utils/visibility.py、tests/test_continuous_exposure.py、两份 test_e3_e4 测试的既有修改完整保留，本轮未再次改写。没有修改 Controller 以外的 Worker 实现、三种新算法、SQLite schema/枚举、原始场景、正式候选、正式计划、registry、Cesium 或轨道插值实现。algorithms/candidate_pool.py 是本轮明确授权的共享候选入口。

### 11.8 发布判断与剩余风险

| 优先级 | 剩余事项 | 当前处理 |
|---|---|---|
| 发布阻断 | 现有 Orekit 点采样/退出二分没有连续区间证明；完全隐藏的不可见间隙仍不能排除 | 四计划 80 条继续 INCONCLUSIVE；正式门禁关闭，不发布、不注册、不重新生成 |
| P2 | JVM/native 单次调用永久阻塞，Python 不能安全强制结束线程 | 30 秒后不提交、限制一个在途认证、保留实例锁；仍需人工恢复或后续独立进程隔离设计 |
| P2 | 新版来源核验依赖可信本机源码/侧车；非白名单历史来源不可恢复 | 不补写历史来源、不默认零预算；需要独立核实后才能扩充来源支持 |
| P2 | 当前源码变化会使旧认证失效 | 明确拒绝陈旧证据，需对同一计划重新认证，不能直接沿用旧 PASS |
| 模型限制 | FOV、遮挡、光照、硬件控制误差和连续姿态动力学等尚未完整建模 | 不将本模型认证描述为全部真实工程约束保证 |
| 独立验收 | Cesium 浏览器内实际插值验收不属于本轮 | 保留原修复和 Node 回归，不以本轮通过替代浏览器物理验收 |

P1 的“拒绝不合格正式结果”已完成；“为真实任务提供连续物理证明”仍未完成。下一步应人工审查本批代码和来源契约，再单独设计可验证的连续区间证据；没有放宽阈值、缩短任务时长、任意扣固定秒数或降低采样步长来制造认证通过。

本轮最终停止在实现、测试、文档和审计完成阶段。未自动 commit、push、merge、创建 PR、发布或登记场景。

最终 Git 核验：`git diff --check` 退出 0；分支、HEAD、两基础提交祖先关系保持不变；未发现纯换行符污染或数据/缓存进入待审清单。

---

## 12. 最终四项 P1 认证链路缺陷修复（本轮生效记录）

本节覆盖第 11 节之后的最终修复，不能沿用此前 306 项测试作为本轮结论。**本轮四项 P1 已在可信本机部署模型下关闭；可以交人工审核并准备统一 Draft PR，尚未创建 PR。正式场景及计划发布仍阻断：四计划 80 条曝光均没有连续区间证书。**

### 12.1 基线、精确范围及保护

开始时核实工作树 `D:/VC/EOS-Course-Project-boundary-guard`、分支 `fix/continuous-exposure-boundary`、HEAD `0af4f61ee76828eaa806ce8fca7dd1e8c7c00204`。祖先检查确认 `12f8849` 和 `0af4f61` 均包含在当前历史中。31 份已有修改先冻结字节 SHA；未 reset、checkout、rebase、merge、commit 或 push。

本轮仅修改以下 **9 份文件**（含新增 2 份）；其余原有修改完整保留。第 11.7 节的 31 文件清单加上这两份新文件，组成现在的 **33 文件**待审工作区（26 tracked 修改、7 untracked）。

| 文件 | 本轮实际修改及函数位置 |
|---|---|
| `eos_system/controller.py` | `_verify_with_deadline:120` 冻结同一绝对 deadline/可信上下文；`_execute:161`，最终裁决段 `:416`，传递期限到成功事务 |
| `eos_system/storage.py` | `Database.__init__:217` 冻结预期上下文；`expected_certification_context:245`；`write:264` 增加提交前回调；`finish_success:424`；`finish_failure:463`；`get_run:513` |
| `eos_system/exporting.py` | `require_certified_record:18` 复用 Storage 绑定的可信上下文，读取与导出采用相同身份规则 |
| `utils/continuous_exposure.py` | `certification_runtime:387`；`check_deadline:396`；`certification_context:401`；`validate_certification:409`；`certify_schedule:439`，认证版本升为 `continuous_exposure_audit_v3` |
| `utils/certification_identity.py`（新增） | `_code_key:38`、`_capture_sources:61`、`assert_code_current:118`、`CertificationContext:136`、`trusted_context:168`，进程/部署/数据集冻结身份 |
| `tests/certification_fixtures.py` | `unit_receipt:12`、`unit_certify:27`、`storage_receipt:31`：提供完整、明确标识为 UNIT_TEST_INJECTION_ONLY 的测试上下文和凭证 |
| `tests/test_continuous_pipeline.py` | `_AuditFixture` 回报实际传入数据路径的 SHA，去掉旧的全零数据 SHA；既有正负向断言保留 |
| `tests/test_certification_final_p1.py`（新增） | 四组 **40 项**专项，真实 SQLite 事务、可控时钟/Queue、隔离部署副本及真实子进程身份测试 |
| 本报告 | 本第 12 节；第 1–11 节历史证据保留 |

未修改 visibility、UTC 解析、E3/E4 测试、轨道插值实现及其测试的原字节；未修改 Worker、Controller 协议、SQLite schema/枚举、算法、registry、四份候选或原始计划。只在独立测试临时库中测试状态机，未打开正式数据库进行写入。

### 12.2 P1-1：一个绝对截止时间贯穿成功裁决

原实现在线程启动之后才创建相对时限，Queue 返回及凭证校验后没有再次检查，最终事务也不知道认证期限，存在迟到 PASS 被接受的窗口。

现在 `_verify_with_deadline` 在认证开始时只创建一次 `time.monotonic() + VERIFICATION_TIMEOUT_S`，通过线程本地 `certification_runtime` 传入真实验证器/签发器，结果同时返回原 deadline。原 Worker 三参数验证入口不变。检查点为：

1. 可信上下文核验后、等待 Queue 前。
2. Queue 取出结果后，包括已经排队的结果。
3. 凭证完成核验后。
4. `_execute` 最终成功裁决、调用 Storage 前。
5. Storage 获得写锁并核验凭证之后、写 SUCCEEDED 前，以及实际执行 COMMIT 之前。

Storage 使用 Controller deadline 与凭证原期限的较早者，不能延长时限。`monotonic() >= deadline` 即超时；不使用 UTC 墙钟作期限比较。提交前回调异常会回滚认证事件、计划、assignments、metrics 和 SUCCEEDED 更新。超时后迟到线程只有内存 Queue 写权限；已提交终态不可再改。

这是“最后一个事务裁决点必须未过期”的软件契约，不声称 Python 能在最终检查与 SQLite 原生 COMMIT 指令之间提供零时间原子硬实时保证。原算法搜索预算、停机、取消和一个在途认证线程的限制保留。

### 12.3 P1-2：取消与认证失败在事务内裁决

原 `finish_failure` 不读取 `cancel_requested_at`，所以 Controller 在事务外读取消状态后，仍可能用后到的认证失败覆盖已接受取消。

现在 `BEGIN IMMEDIATE` 内读取 status、attempt 和持久取消字段：VERIFYING 阶段已接受取消且随后普通认证失败时，终态为 **CANCELLED / CANCELLED_DURING_VERIFY**；原失败诊断另存 `CERTIFICATION_FAILURE_AFTER_CANCEL`，不会丢失 INCONCLUSIVE、REJECTED、ERROR 或 TIMEOUT 原因。

- 取消事务先提交：随后认证失败得到 CANCELLED。
- 认证失败事务先提交：FAILED 已为终态，随后取消返回 `(FAILED, false)`，不会谎称取消已被接受。
- 已取消、已失败、已成功或其他已提交终态均不被迟到结果覆盖。
- 原 `CONTROLLER_STOP` / `CONTROLLER_RESTART` 优先级与已经裁决的算法 TIMED_OUT 保留；没有把所有失败无条件改成取消。
- 成功事务仍在同一写锁下拒绝已有取消，计划/指标/认证事件继续保持单事务原子性。

测试通过两个独立 Database 实例、真实 SQLite 写事务与 Event 控制两种锁/提交顺序；没有只 mock Controller 返回值。原搜索超时后迟到取消、原 Controller 停机和 flock 等测试也在完整回归中重新通过。

### 12.4 P1-3：完整 Orekit 数据身份及凭证 schema

新凭证采用 `receipt_schema_version=3` 与 `continuous_exposure_audit_v3`。必须包含并核验：

- run_id、场景文件 SHA、规范计划 SHA、审查版本。
- `orekit_data_sha256`：64 位小写十六进制字符串；`orekit_data_source`：可信配置解析后数据文件的绝对 URI。
- 冻结源码逐文件 SHA、部署摘要、进程代际。
- 模型参数：Orekit Keplerian、EME2000、ITRF IERS2010 simpleEOP、WGS84、TargetPointing、UTC 和既有仰角/存储三轴约束谓词。
- 扫描步长 0.05 s、边界精度 1 µs、有效仰角阈值、谓词说明及其设置摘要。
- 完整审查结果 SHA、与实际 assignments 数量严格一致的认证任务数、签发时的原绝对 deadline。

预期身份来自 **Database/Controller 启动的可信运行上下文**，不是从待验凭证取一个 SHA 当作“预期 SHA”。数据路径显式配置于 `EOS_OREKIT_DATA`，未配置时使用仓库既有 `utils/orekit-data.zip`；配置须先于可信初始化。运行时改环境变量不会替换已冻结的 Controller 上下文；不匹配的数据路径会被拒绝。

签发前后、凭证校验、Storage 提交及正式读取/导出均核对实际文件。实际 Orekit 审查器仍通过 `ensure_orekit` 的 JVM 已加载数据 SHA 保护，不能在同 JVM 换一个 ZIP 冒充当前模型。任何缺字段、格式不符、错误 SHA、来源不符、数据变化或不可读均 fail closed；检测到某路径变化后，在该进程中记录数据撤销，即使恢复原字节也需重启。

允许显式冻结另一个数据路径/数据版本，但必须使用它自己的可信上下文并重新认证；不静默接受任何 ZIP。历史 v2/不完整凭证保持历史记录，只是不再可作为当前认证成功结果读取或导出。

本轮实际数据 SHA 保持 `1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`。

### 12.5 P1-4：执行进程身份、初始化及失效策略

原签发器在认证完成时重新读取磁盘源码，可能让已导入的 A 执行结果被标记为磁盘 B。

现在身份模块在可信启动导入阶段冻结 **20 份核心源文件**的 SHA，并形成不可变部署摘要、随机进程代际和 PID 约束。清单涵盖物理求值、时间解析、模型数据结构、共享约束、来源核验、正式验证、Controller、Storage 和导出等；完整清单在模块 `SOURCE_NAMES`，本轮源码字节清单另存证据。

冻结阶段还比对已加载函数/源文件定义的方法的执行字节码；正在初始化的模块（含身份模块及 continuous_exposure 自身）比对实际模块执行帧，避免初始化期间已编译 A、磁盘变 B 的身份重标记。字节码常量规范化处理 frozenset/tuple，避免集合展示顺序造成同源误拒绝；不会放宽真正代码变化的判定。

认证开始、结束、签发、Controller 凭证校验、Storage 最终提交与读取时，必须同时匹配冻结身份、当前磁盘、可信部署及进程代际。观察到源码变化或无法读取即撤销当前进程认证能力；恢复文件也不会解除撤销。**修改认证核心源码或数据集后必须重启认证进程并重新认证。** 新进程代际不同，因此上一进程的旧凭证也不能用于当前正式读取/导出；原 SUCCEEDED 归档状态不被自动改写，但正式 plan 被隐藏。

保证边界：这是可信本机、不可变部署约定下的进程身份和防误用机制，不是针对恶意 Python 代码、任意 monkeypatch、恶意文件系统或供应链替换的远程证明。仅在核验点做哈希，不能发现完全位于检查间隔之间、且从未被观察到的 A→B→A 临时改动；已观察到的改动会锁定失效。Python/Java 依赖安装需随部署保持不变，本轮记录依赖版本但未实现第三方 wheel/JAR 全量签名。没有声称两次磁盘哈希构成不可绕过的篡改证明。

源码 OSError 通过身份错误规范化，Storage 读取保留历史状态但隐藏失效计划；JSON/CSV/API/目录导出继续走原认证失效/HTTP_409 门禁，不向上泄漏未规范化源码读取异常。

### 12.6 本轮实际回归及中间失败记录

最终源码测试结果如下；全部为本轮亲自执行，测试副本与工作树源码逐字节匹配。最终依据是 `*-release-review*`，不能用此前通过的 306 项或本轮中间版本代替。

| 验证 | 实际结果 | unittest 耗时 | 总墙钟 | 峰值 RSS KiB |
|---|---|---:|---:|---:|
| 新增四组 P1 专项 | **40 passed / 0 failed / 0 skipped** | 6.522 s | 7.031 s | 104336 |
| Python 完整回归 | **346 passed / 0 failed / 0 skipped** | 109.712 s | 110.317 s | 607624 |
| Node 全部 5 份 `*.test.cjs` | **5/5，均 exit 0** | 见逐文件记录 | 见逐文件记录 | 未单独测量 |

完整套件包含原连续曝光 15、正式链路 17、E3/E4 20（含真实 Orekit 3）、轨道插值 7，以及原 Controller/Worker/Storage/API/导出/Manifest/重算工具回归；四个 Orekit 可选开关全部开启，没有以跳过替代通过。新增测试覆盖 Queue 已有 PASS 但过期、凭证校验跨期限、事务内到期回滚、迟到 PASS、四种取消后失败、两种实际提交顺序、完整数据身份正反例、源码不可读、恢复后仍撤销、旧/异进程凭证及两种启动源码不一致。

测试正向凭证及模拟审查器均标明 **UNIT_TEST_INJECTION_ONLY**，带完整上下文和实际传入数据 SHA；真实场景 CLI 从不安装这些模拟。完整空计划测试凭证允许认证任务数为 0，但必须与空 assignments 严格匹配；不能用于非空计划。生产签发器原有“实际返回经过认证的非空 rows”要求没有放宽。

中间失败完整保留：

- `full-current.*`：343 项，5 failure / 1 error，来自新增 schema 错误拒绝原有空计划正向夹具。修正完整零计数凭证的 schema 兼容性，并增加匹配/不匹配回归；没有改原 lifecycle 成功断言。
- `full-final.*`：344 项，7 failure / 65 error，来自相同 transition_utils 源码的 frozenset 常量顺序导致启动身份误拒绝。改为集合内容规范化，并新增提前导入 transition_utils 的回归。未绕过启动校验。
- `p1-first`（34 项）、`p1-final`（37 项）、`p1-final-v2`（38 项）为中间阶段记录；最终新增专项以 40 项为准。
- 最终 `discovery-identity.log` 确认全量导入身份一致、346 项；`full-release-review.*` 和 `node-release-review.json` 全部通过。

环境：WSL Ubuntu 22.04，Python 3.10.12，orekit_jpype 13.1.5.0，JPype 1.5.2，JDK 25.0.2，Node v22.23.2。测试使用 Linux 原生隔离副本，避免 /mnt/d I/O 开销；原有大输入只对此前隔离副本复用硬链接，未链接正式候选用于写入。没有对四真实场景调用求解器或完整重算。

### 12.7 四候选与计划：本轮 SHA 及真实复核

准确原路径继续使用第 5 节清单，命令从既有证据读取后改用新源码和新报告路径，不猜测计划文件名，不覆盖旧报告。

| 场景 | 候选 SHA-256（重新计算） | 实际计划 SHA-256（重新计算） |
|---|---|---|
| S1 / 10 | `bb29994f5b2d0e2e6b22481f5c01c5b37e33ba9da0b98427c70536f276ef644e` | `23afb113ecf269c05c673e9f0e48ff2493f13a80a4471c0818f7d84fc58e6c77` |
| S1 / 20 | `86909deb21bdbc6f8f77051b50e483fed8151bd225aa8b2c8ef65410e8b90779` | `221da06c568f6ee0884bff32d623aea2c22ff007eb1a08bd6dac8572f9f8858a` |
| S2 / 10 | `f44bb789f6bbe1623b2adf119980e502c69c0764cab7080b43b226e6f19c89d4` | `85eb29839d8cb0cd5aa28cc9db47ba8c431832e55a38cd4086772d5b1b52c2b5` |
| S2 / 20 | `ae4d75699239b250aa064db099a8619e50678bd9ee821a812d0fef5330edd575` | `6e14284bccd42a280719532748f3c5be77f952560ec02c59733d9b0d9bfa6f97` |

| 场景 | PASS / FAIL / INCONCLUSIVE | 原因 | 本轮 CLI 墙钟 s | RSS KiB |
|---|---|---|---:|---:|
| S1 / 10 | 0 / 0 / 20 | NO_CONTINUITY_CERTIFICATE ×20 | 4.857 | 239472 |
| S1 / 20 | 0 / 0 / 20 | NO_CONTINUITY_CERTIFICATE ×20 | 4.903 | 194848 |
| S2 / 10 | 0 / 0 / 20 | NO_CONTINUITY_CERTIFICATE ×20 | 4.836 | 235148 |
| S2 / 20 | 0 / 0 / 20 | NO_CONTINUITY_CERTIFICATE ×20 | 4.895 | 267936 |

四计划公共连续 CLI 均 exit 2；80 条采样检查均 PASS，但连续认证均 INCONCLUSIVE。由于文件缺失、初始化失败、时间错误或内部异常导致的 INCONCLUSIVE 为 0。

M001/M007 原始探针均通过同一公共 CLI 被拒绝（exit 1 / NONVISIBLE_EXPOSURE_POINT）；墙钟分别 4.610/4.726 s，RSS 234408/230244 KiB，精细退出括区仍与第 4 节一致。不能把探针拒绝或 80 条采样无违规解释成真实连续认证通过。

187 份受保护场景/计划/历史证据重新哈希，无变化；前轮 83 份索引历史证据也全部一致。完整文件 SHA 相同，静态字段、原始 ID、传感器与资源没有补写。本轮真实审查与完整测试存在并行运行时段，墙钟仅作为本次运行记录，不用于推导独占资源性能提升。

### 12.8 证据目录与可复现命令

本轮新 RUN_DIR：

`/home/meteor/eos-course-runtime/epoch-acceptance/continuous-exposure-final-p1-20261017T035340Z/`

主要证据：

- `preflight.json`：初始 31 份文件 SHA 与 187 份受保护输入。
- `release-review-python-source-sha256.json`：最终源码字节清单。
- `p1-release-review.command.json`、`p1-release-review.*.log`：40 项专项实际命令、环境、结果及资源。
- `full-release-review.command.json`、`full-release-review.*.log`：346 项完整回归。
- `node-release-review.json`：5 份 Node 实际 stdout/stderr/exit。
- `audits/summary-verified.json`：6 次真实 CLI 的完整 argv、所有输入 SHA、新报告路径、耗时、RSS、正确展开的任务原因分类。原 `audits/summary.json` 仅为运行器初始状态记录，任务行位于 reports 数组，原因分类以 verified 文件为准。
- `audits/*.json`：四计划及两探针逐任务证据。
- `protection-final.json`、`scope-check.json`、`environment.json`：保护范围、历史证据及环境。

```bash
cd /mnt/d/VC/EOS-Course-Project-boundary-guard
PY=/home/meteor/eos-course-runtime/venv/bin/python
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export EOS_OREKIT_DATA=/home/meteor/eos-course-runtime/epoch-acceptance/s1-10s20m-1d-20261016/data/orekit-data.zip
export EOS_RUN_EXPOSURE_OREKIT_TESTS=1 EOS_RUN_E3_E4_OREKIT_TESTS=1
export EOS_RUN_ORBIT_INTERPOLATION_TESTS=1 EOS_RUN_OREKIT_TESTS=1
"$PY" -B -m unittest discover -s tests -p test_certification_final_p1.py -v
/usr/bin/time -v timeout -k 10s 240s "$PY" -B -m unittest discover -s tests -p 'test_*.py' -v
for test in tests/*.test.cjs; do node "$test" || break; done
```

上述为可复现工作树命令；本轮实际 cwd 是 SHA 匹配的 RUN_DIR/source，准确 argv 见 command.json。真实 CLI 使用第 7 节相同参数与新的 --report 名称；不要把已存在的报告路径再次作为输出。

### 12.9 最终裁决与剩余项

| 事项 | 当前结论 |
|---|---|
| P1-1 认证截止竞态 | 关闭：同一绝对期限，Queue/凭证/最终事务/提交前均检查，迟到结果无持久化权 |
| P1-2 已接受取消被认证失败覆盖 | 关闭：实际 SQLite 写事务内裁决；两种提交顺序及原停机/算法超时回归通过 |
| P1-3 数据身份不完整 | 关闭：schema v3 + 独立可信数据上下文 + 全路径复核 + 检测后撤销 |
| P1-4 执行代码与磁盘身份混淆 | 关闭：启动快照/执行代码核验/部署摘要/进程代际/多阶段复核；保证边界见 12.5 |
| 创建统一 Draft PR 条件 | 具备，可供人工审查；本轮没有创建、提交或推送 |
| 是否发现仍阻断本批防护代码合并的 P0/P1 | 在本轮测试及上述可信部署范围内未发现；最终合并仍需独立人工代码审查 |
| 正式场景/计划发布 | **不允许**：四计划 80 条仍 INCONCLUSIVE，缺少连续区间证明 |
| P2：窗口生成身份与正式认证身份拆分 | 保留后续任务；当前核心认证源码变化仍可能使旧 v3 来源不匹配，不补写历史候选 |
| P2：永久阻塞 JVM 调用隔离 | 保留后续独立进程设计；本轮只保证期限后拒绝提交、限制在途线程与停机保留锁 |
| 其他边界 | 无法排除未观测的亚采样间隙/临时 A→B→A；第三方依赖须固定部署；Cesium 插值验收仍是独立工作 |

最终停止在实现、测试、文档和审计完成阶段，等待人工审核。没有注册、发布、修改正式输入/输出或真实数据库，没有自动创建提交或 PR。
最终核验：git diff --check 退出 0，含未跟踪文件的尾随空白检查也为 0；当前仍是原分支/HEAD，33 份待审文件。本轮仅 7 份既有文件发生变化、另新增 2 份。最终 97 份 Python 源码在工作树及隔离测试副本逐项 SHA 相同；原报告第 1–11 节字节前缀验证不变。完整 Git 状态及清单保存在 final-review-summary.json。
