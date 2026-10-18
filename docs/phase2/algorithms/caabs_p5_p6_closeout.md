# CAABS P5/P6 阻断收口（2026-10-18）

起点`c5090ba72819493c5f91ce8c1aa0a6a26e8cf58d`，唯一工作树`EOS-Course-Project-caabs-latest`，分支`feat/caabs-hardening-20261018`。原归档`D:/VC/caabs-final-evidence-20261018`的240文件逐SHA复查全部相同，未覆盖。新日志独立位于`/tmp/caabs-p6-20261018-2y6h8qpd`。原任务书未跟踪保留，不更改CAABS核心。

## 阶段一：物理基准版本迁移

先在原源码实际复现：RABAS4项1失败（29.151秒）、曝光15项2个失败子项（7.281秒）、E3/E4三项1失败（6.438秒），各退出1。命令为现有WSL Python3.10.12的`-B -m unittest discover -s tests -p MODULE.py -v`，开启GEN02/EXPOSURE/E3_E4真实物理opt-in，固定hashseed0、Agg、真实Orekit ZIP；每模块240秒上限。日志`baseline/`，没有依赖上一轮报告推定结果。

迁移不是把失败码直接改成实际值：新增独立`tests/physical_reference_v2.py`从原轨道字段直接构建Orekit轨道/地球/姿态，不调用生产visibility、姿态工具、规划窗口或证据；以显式矩阵乘积`R_BI R_NI^T`和手工被动ZYX公式求角，以ITRF地表法向点积求仰角，以固定相机半空间`z>0,|x|<=z*tan(FOV/2),|y|<=z*tan(FOV/2)`核对LOS，联合原始硬件速率。数值交叉验证不是区间证明，1e-8度/1e-12矩阵回归公差不用于认证。

独立脚本`tests/freeze_physical_reference_v2.py`只读历史轨道/任务，在扫描前冻结真实ALOS/GPM轨道第100秒的WGS84地表垂足作为新可达目标；不移动旧任务。由独立oracle求得：

| 星 | 新窗口首采样UTC | 可见侧出口UTC | 不可见侧出口UTC |
|---|---|---|---|
| ALOS-2_39766 | 2025-11-18T12:00:02 | 12:03:19.173844 | 12:03:19.173845 |
| GPM-CORE_39574 | 2025-11-18T12:00:33 | 12:02:46.923712 | 12:02:46.923713 |

冻结文件`tests/fixtures/nadir_relative_v2.json` SHA`edbb4787169b47834a3b4ad70de140210c8e4e120fdc61fed43b27f2c1369b51`，明确NUMERICAL_TEST_REFERENCE_ONLY_NOT_PROVENANCE_OR_CERTIFICATION；固定输入、原始场景/数据SHA、oracle函数源码SHA及历史反例。写入exclusive xb，不覆盖原夹具/证据。测试每次复查自身摘要和oracle公式身份。

旧GPM M009/M020在旧绝对姿态参考中可见，在相对Nadir中轴限幅拒绝；保留原输入及独立旧/新数值。旧SKYSAT/SCD曝光在起点即违反当前姿态/速率联合条件；保留原场景和原plan字节SHA，先独立计算拒绝原因再调用public verifier，另外使用上表新可达目标验证正曝光INCONCLUSIVE与中途退出1μs夹逼，未删除中途超限负例。旧RABAS M008/CARTOSAT在12:46:43的独立物理拒绝先于Controller断言；保留旧文件及SHA，另加全新当前生成场景上的真实RABAS Worker/Controller非空正例、201点独立重放和开发来源不得正式消费的负例。没有修改RABAS/CAABS策略、公共约束或正式发布资格。

新的E3/E4 GPM正例检查全部600采样与独立参考一致、非空窗口、所有姿态、真实出口、重新计算序列化及静态输入不变；原微秒CZML和EME2000/ITRF回归保留。原历史根值仍保存在测试常量、原Git历史及原运行归档，不能把它们冒认成新模型根。

阶段一最终命令/统计见`migration-final/`：E3/E4 4项/7.256秒、曝光16项/7.162秒、RABAS5项/57.192秒，合计25项全部通过、0跳过、各退出0。不将中间浮点全字典相等断言失败记为生产缺陷。

## 阶段二及后续

设计和7项验证测试先提交于78d07c4，再于11de4ce实现Fraction精确条件区间内核（11项测试通过）。内核只证明给定可信包络假设下的margin，不注册生产provider或发行正式回执。详见[数学设计和阻断前提](continuous_interval_certification_design.md)。真实Orekit的全链误差包络和执行slew轨迹仍缺失，正式认证保持BLOCKED；后续真实readiness审计另存证据。

审查新增实际缺陷：地下1km的目标曾可见；生成和独立曝光审计只用全局5°，忽略传感器85°/任务80°显式要求。先加真实负例，3项全部失败（退出1/6.305秒），再修复：opaque WGS84地表模型拒绝内部目标、要求正地表法向仰角；最低角取全局/传感器/任务声明最大值，拒绝非法数字。模型身份predicate升为v2，旧证书不沿用。没有改任务/FOV/硬件轴限幅。实际修复后3项、GEN02物理13、真实来源/HTTP10、曝光16、E3/E4 4项，合计46通过/0跳过，各退出0；日志`physical-negatives-before`与`physical-negatives-fixed`。

## 独立完成的真实地面站开发链路

生成入口新增`--with-ground-station`：沿原真实轨道330秒的WGS84垂足预先冻结GS坐标，明确10Mbps理想天线配置，再逐时传播求真实通信窗口。不是复制观测窗口或放宽光学角限。原通信生成曾借用光学TargetPointing/宽松180°Euler，改为独立真实地面链路elevation/opaque WGS84几何，不虚构光学姿态，消除光学奇异性对RF窗口的误影响。当前无RF链路预算、天线安装标定、天气或传播损耗证明，只验收公开的理想天线几何模型。

独立Verifier的PlanExposureAuditor新增实际下传全时段重传播（此前仅核验通信来源ID/离散区间），不会以ID存在代替物理检查。真实几何不符、缺物理字段或超预算不能保留sample PASS；即使观测有区间证明，下传没有也不能CONTINUOUS_PASS。源码/模型身份显式记录通信模型和interval provider unavailable，开发来源/正式来源门禁未改。

实际命令：`PYTHONHASHSEED=0 MPLBACKEND=Agg python -B scripts/validate_ground_link_development.py --output /tmp/caabs-p6-20261018-2y6h8qpd/ground-final --orekit-data /tmp/eos-gen02-itrf-eVCxbe/orekit-data.zip`。外层240秒，28.311秒退出0。场景SHA **`0e2210cc56dc0d3a6f9cba93c04d50ff93d9ce7cf81a35b3dcd8f3a0f7cee278`**，3任务/3可信规划窗/1个GS/1个真实通信窗口，CAABS完成2/3、TP4，真实Spawn Worker→Controller为planning_preview SUCCEEDED。完整配置、场景及Sidecar、源码/数据身份、独立Verifier、201点下传、Controller记录保存于`ground-final/`。正式JSON/CSV导出拒绝；连续认证仍INCONCLUSIVE。

`ground-final-tests`真实专项8项77.094秒、真实曝光16项8.504秒、真实重计算45项11.798秒，合计69通过/0跳过/三个进程退出0。负例包括GS ID/归属/严格观测后边界/短下传、真实公共模型存储及功率上限、两个各自可行请求争用同GS、地面站移到地球对面后的实际下传拒绝。没有用mock替代物理结果。新只读`audit_continuous_proof_readiness.py`实际检查三组卫星-目标，生产interval provider均不存在，记录五项明确证明缺口；不会消费JSON声明或将数学内核结果提升为正式资格。

## 2026-10-19：真实非GS复验与全量问题诊断

当前环境为Ubuntu-22.04/WSL2（Linux 6.18.33.2）、Python3.10.12、orekit-jpype13.1.5.0、JPype1.5.2、pydantic2.14.1、numpy2.2.6。实际Orekit数据ZIP SHA`1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`；原始10星文件SHA`c707ee30417d7e1a0448b644f90d6595235ae4cc8262fa2645f5f85d1fadc241`。新场景源快照SHA`841cb5ef77caf240cbb55c5931d6a3066dcb715bcee328ce5b55397f99078479`，逐文件身份见`final-independent-replay.json`和GS的`interval-readiness.json`。本轮不改CAABS核心，与`c5090ba`及`8cf282b`均无差异。

实际执行：`PYTHONHASHSEED=0 MPLBACKEND=Agg /home/meteor/eos-course-runtime/venv/bin/python -B scripts/validate_caabs_real_integration.py --output /tmp/caabs-p6-20261018-2y6h8qpd/no-ground-final --orekit-data /tmp/eos-gen02-itrf-eVCxbe/orekit-data.zip`，300秒外限，75.330秒退出0。新场景SHA **`55243347e49c07856edab6dac0f71b051c567acaef3e962952289dd37ee56f1b`**，3任务/3可信规划窗。相同seed42、center、2秒预算下，CAABS和Completion各3/3、TP6；Runner搜索分别0.050362/0.006906秒。仅一个小开发场景，不说明统计显著性或优于基线。

真实Controller正常及Completion均SUCCEEDED/planning_preview；运行中取消为CANCELLED、ACK一次、无候选提交；强制杀死本次受控Worker后FAILED/IPC_DISCONNECTED、exit -9；重启后再次SUCCEEDED。60ms极短预算为TIMED_OUT/SEARCH_BUDGET，Worker exit0、未发布计划，属于明确边界结果，未伪装成功。Runner协作取消0.157358秒返回内部incumbent；Controller取消不发布该候选。全套JSON、隔离SQLite、进程回收记录见`no-ground-final/`。

在独立新进程中再次初始化真实JVM、重新核对两份场景/Sidecar/原始输入/源快照/数据身份，并调用`verify_candidate`；非GS3项、GS2项再次通过独立重建和物理采样，原字节不变。正式来源入口都拒绝开发Sidecar；认证仍INCONCLUSIVE，18.149秒退出0。旧证据归档240项再次逐SHA核对无变化。此结果只证明开发来源和离散/采样核验，不能签发正式连续证书。

首轮全量真实opt-in在`9336aae`运行631项，630通过/1失败/0跳过/0error，测试183.258秒、外层184.423秒、退出1。日志`p6-full-all-optins.log`完整保留。唯一失败为Daemon旧测试用UTC日志推算0.6秒退避得到0.076514秒；源码实际使用Event.wait的单调计时。额外隔离重复4次全部通过（合计68.256秒），但不能据此把首轮失败改成通过。原日志未保存该测试临时目录，不能确证当时发生了WSL时钟校正。

确定的可观测性缺陷是UTC不适合测量退避，且按UTC大小寻找后续事件不可靠。修复事件增加`monotonic_ns`、按日志顺序配对并严格断言完整单调退避时间（移除旧20ms宽容）；新增UTC倒退1秒的受控回归，生产重启策略不变。后续全量以这一修复的新源码重新完整执行，首轮失败证据保留。

## 最终完整回归

运行代码提交`37cbaf6`（其后的修改仅验收文档），Daemon专项14项通过/0跳过，测试122.937秒、外层124.076秒、退出0，见`daemon-monotonic/`。本轮最终完整发现 **632项全部成功，0失败/0错误/0跳过**；测试194.085秒、外层195.552秒、退出0，上限1200秒。不是分组汇总冒充全量。

命令在`/tmp/caabs-final-native-h7uh4h1i`运行：

```bash
PYTHONHASHSEED=0 MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1 \
EOS_RUN_GEN02_PHYSICS=1 EOS_RUN_CAABS_REAL_E2E=1 \
EOS_RUN_OREKIT_TESTS=1 EOS_RUN_EXPOSURE_OREKIT_TESTS=1 \
EOS_RUN_E3_E4_OREKIT_TESTS=1 EOS_RUN_ORBIT_INTERPOLATION_TESTS=1 \
EOS_OREKIT_DATA=/tmp/eos-gen02-itrf-eVCxbe/orekit-data.zip \
/home/meteor/eos-course-runtime/venv/bin/python -B -c \
"import faulthandler,runpy;faulthandler.dump_traceback_later(120,repeat=True);runpy.run_module('unittest',run_name='__main__')" \
discover -s tests -p 'test_*.py' -v
```

385个跟踪文件复制清单及逐字节SHA在`p6-full-final-all-optins-copy.json`，无LFS指针，复制前后及测试结束时源文件全部相同；未复制或改变Git数据库。完整日志和退出收据为`p6-full-final-all-optins.log`、`.receipt.json`，都单独保留。六组opt-in实际开启，包括原来未在全量运行的GPM、CZML和轨道插值。故障注入中预期的Pipe EOF/BrokenPipe/身份拒绝/solver exception会输出traceback，其对应测试均ok；不是吞异常或忽略失败。faulthandler定时堆栈是诊断输出，未达到1200秒超时。

另在原DrvFS工作树按原专项命令独立复测，均为`python -B -m unittest discover -s tests -p MODULE.py -v`（外包faulthandler60秒及每模块240秒上限，hashseed0/Agg）。`final-core-lifecycle/`与`final-worker-runtime/`记录真实命令和退出收据：

| 模块 | 通过/失败/跳过 | 外层秒 | 退出码 |
|---|---|---:|---:|
| test_algorithm_conflict_beam | 50/0/0 | 3.421 | 0 |
| test_algorithm_registry_i1 | 17/0/0 | 12.898 | 0 |
| test_source_window_identity | 31/0/0 | 81.241 | 0 |
| test_nine_algorithms | 7/0/0 | 6.067 | 0 |
| test_worker_ipc | 20/0/0 | 18.167 | 0 |
| test_worker_process_group | 15/0/0 | 9.350 | 0 |
| test_controller_shutdown | 13/0/0 | 46.646 | 0 |
| test_worker_runtime | 2/0/0 | 1.992 | 0 |

原四组105/105、生命周期50/50均保留通过，合计独立复测155次、0跳过。nine_algorithms的7项包含其已有导入AdaptiveRepairTests的3项，沿用原unittest发现行为，不能冒称105项全为CAABS独有测试。完整632项也包含这些用例；此表不与全量相加当作独立覆盖量。

新原始证据已以exclusive创建归档到 **`D:/VC/caabs-p6-evidence-20261018`**：115文件全部逐字节核对源/副本，另有`archive_index.json`，其SHA为`bf0785637be5f056a18313c00d69b52e016b0f683a686d7ec713c9f16ce6a343`。其中包括基线/中间失败、两次全量、定向收据、两份新场景及Sidecar、隔离SQLite、数学/物理诊断、源码复制清单与运行辅助脚本。归档不编辑场景中的原WSL绝对路径或来源哈希；它是取证副本，不是新来源场景。核心文件原字节SHA`424cd755c683e08ee94fe15c1e3a1e70db5f498bc4b94f33af9aecddf8b8bd52`与原归档相同。

## 提交与独立审核边界

| 本地提交 | 内容 |
|---|---|
| f1a8432 | 历史物理基准版本迁移、独立相对Nadir数值oracle和冻结正负例 |
| 78d07c4 | 先提交连续证明数学设计及7项反例测试 |
| 11de4ce | 精确有理条件区间内核及11项测试，不发行物理证书 |
| 4d2ff79 | 修复地下目标与显式仰角要求，真实负例先失败后通过 |
| 9336aae | 真实GS生成与独立全下传重传播、源身份及8项真实验收 |
| 37cbaf6 | Daemon单调计时证据及UTC回拨回归，不更改重启策略 |

所有代码提交前运行对应测试、`git diff --check`和`git diff --cached --check`。最后文档提交收录本表、版本记录和历史报告附录；其SHA以Git日志为准。不push/merge/创建PR，不更改其他worktree。`CAABS_CODEX_TASK.md`继续未跟踪保留。

| 验收项 | 当前裁决 | 有效性边界 |
|---|---|---|
| 历史曝光/RABAS/GPM迁移 | PASS | 原始SHA/失配证据保留，新模型可达和不可达数值冻结 |
| 物理生成与显式约束 | PASS WITH CONDITIONS | 仓库两体/WGS84/固定相机模型；没有卫星硬件实测标定 |
| CAABS/Completion非空开发对照 | PASS | 同场景3/3，公共约束、来源重建、实际曝光采样 |
| Worker/Controller生命周期 | PASS | 正常、取消、短预算、崩溃、重启与回收；预览不冒认正式 |
| GS开发链路 | PASS WITH CONDITIONS | 真实几何窗口、归属ID/资源/严格边界和下传采样；不是RF链路预算 |
| 完整回归 | PASS | 本轮632/632、全部相关物理opt-in、0跳过、未超时 |
| 条件区间数学内核 | PASS | 仅给定可信包络假设下的数学结论 |
| 真实连续物理认证 | BLOCKED | 缺生产provider及全链误差/姿态执行轨迹合同 |
| 正式来源/成功闭环/合格正式导出 | BLOCKED | 开发根未获正式资格，且无连续证书；正式负例严格拒绝 |

后续必须先闭合Kepler输入/浮点、ITRF/EOP/时间、姿态归一化/Euler图的经验证包络，以及实际slew轨迹/执行误差/稳定合同，再由独立Verifier从可信输入重建证明；不能用经验误差、自动微分点值或高频采样补空。GS还需真实天线安装/指向、RF链路预算与适用资源连续模型。物理/认证模块负责人应审核这些科学合同；系统负责人审核单调计时证据、IPC/重启和正式门禁；算法负责人审核未变核心及候选兼容。

可进入Draft代码审查，**不能据此批准“最终正式认证完成”或正式发布**。本实现和本地自验仍需独立人员审核，632项通过不替代数学证明、硬件标定或正式来源批准；本轮不声称完成正式正例成功闭环。
