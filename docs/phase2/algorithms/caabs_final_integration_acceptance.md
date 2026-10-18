# CAABS 全链路修复与验收（2026-10-18）

## 版本及执行边界

唯一源码工作树 `D:/VC/EOS-Course-Project-caabs-latest`，分支 `feat/caabs-hardening-20261018`；保留起点 `8cf282b556fa97b3d9867913c5a2edfdef500d81` 的CAABS v0.2.0/latest修复。origin/main核验为ba114dd，未重置/merge/push其他工作树，用户任务书未纳入提交。所有运行场景、数据库、日志使用 `/tmp/caabs-final-20261018` 下独立目录。

## P0：基线与根因

见 [P0实际报告](caabs_P0_report.md)。105项算法/Registry/来源/旧算法回归及IPC19、进程组15通过；shutdown原命令240秒超时，不能记为13通过。原生Linux同字节副本shutdown13通过。首次物理反例和证据链区分均已实际复现。

## P1：相对姿态、固定相机与转向

已确认并修复：EME2000绝对Euler角不是整星相对名义天底的倾斜角。姿态链为轨道EME2000→ITRF/WGS84地表→Nadir名义body N与TargetPointing实际body B；Orekit R_I_B为被动惯性到body变换，限幅采用 `R_N_B=R_I_B*transpose(R_I_N)` 的ZYX/FRAME_TRANSFORM角。独立矩阵乘法和真实LOS验证复合顺序，误差见P0报告。公式依据：[Orekit NadirPointing](https://www.orekit.org/site-orekit-11.3/apidocs/org/orekit/attitudes/NadirPointing.html)、[Hipparchus Rotation](https://www.hipparchus.org/apidocs/org/hipparchus/geometry/euclidean/threed/Rotation.html)。

物理模型版本 `nadir_relative_fixed_camera_v1` 单独记录，窗口出口精化算法仍为v3。固定镜头光轴body +Z，不增加云台自由度；使用camera -Z的消费者须采用恒定Rx(pi)安装矩阵。FOV显式采用项目当前显示合同的方形完整角；敏捷卫星由整星转向追踪目标，非敏捷卫星保持名义Nadir，由真实body LOS与FOV判断。该模型不是实物卫星仪器安装的在轨标定，实际设备安装资料不足时不得声称硬件已认证。

仰角、遮挡、三个相对轴限幅、固定FOV及可声明的硬件tracking rate联合判断；真实TargetPointing spin超硬件速率仍拒绝。未降低45°/5°默认限。仍使用真实UTC/轨道历元和半开窗口，可见侧出口重求值，未凭首末采样证明连续性。

新增可选 `boundary_quaternions_xyzw`，保存网格状态及精确可见侧末端；旧三轴数组及旧数据类型保持兼容。公共源核验/候选切片同取n+1边界状态，对不支持的非网格曝光末端拒绝而不插值造姿态。新姿态候选由公共ConstraintModel核对完整来源角/四元数；首次执行须有场景起点实际初始姿态和转向/稳定时间；任务间转向取原公共经验模型与 `SO(3)角/硬件速率+稳定时间` 的较大值。没有重写CAABS核心或降低公共约束。新受控场景必须保存初始姿态；缺少该证据时拒绝安排。

真实物理11项（4纯数值/公共约束+7真实Orekit）通过，含天底、偏轴、遮挡、矩阵/LOS、非敏捷FOV、tracking速率、UTC/时域偏移。实际5秒曝光0.05秒含端点共101次点求值全部可见，仍返回INCONCLUSIVE/NO_CONTINUITY_CERTIFICATE；未添加或假造certify_interval。

P1命令：`EOS_RUN_GEN02_PHYSICS=1 EOS_OREKIT_DATA=/tmp/eos-gen02-itrf-eVCxbe/orekit-data.zip python -B -m unittest discover -s tests -p MODULE.py -v`。模块 gen02_attitude(11)、algorithm_conflict_beam(50)、source_window_identity(31)、window_recompute(44)、e3_e4_time_semantics(17)、continuous_exposure(15)，共168项166通过/2个既有真实Orekit opt-in跳过/0失败错误，六进程均退出0，外层各240秒无超时。日志及逐模块命令/墙钟为 `/tmp/caabs-final-20261018/p1/`。尚未用该阶段替代全量回归。

## P2：真实新生窗口与开发来源合同

新增 `scripts/generate_caabs_development_scene.py`：Raw10的ALOS-2真实轨道/真实历元，预先选择80/180/280秒处WGS84垂足作为3个地面开发目标，完整要求各10秒、1秒网格、5°仰角、45°机动/FOV、1°/秒/10秒稳定，无GS，360秒时域。目标是受控物理开发几何，不是随机共享数据集，不计100份来源或私有final，未为成功临时降低曝光或放大硬限。保存实际初始Nadir姿态，显式ensure=false并比较计算前后任务字节。

P2实际命令：`python -B scripts/generate_caabs_development_scene.py --output /tmp/caabs-final-20261018/p2-verified-scene --orekit-data /tmp/eos-gen02-itrf-eVCxbe/orekit-data.zip`；退出0/9.916秒，窗口计算0.557秒。新场景SHA `c1bb391a87977dbca43add990cae75cfd364552b5aa6a22f83c3a85b5eb4a053`，Raw10 SHA `c707ee30417d7e1a0448b644f90d6595235ae4cc8262fa2645f5f85d1fadc241`，3任务/3窗口/3个PLANNING_FEASIBLE。后续公共代码变化会使此中间产物失效，必须新目录重生，不能改这个SHA或追认旧C6。命令/原始输出在 `p2-generation.log/.receipt.json`。

新侧车合同 `gen02.development.v1` 绑定真实Scene字节、原始卫星文件SHA、冻结任务摘要、真实计算器/源码/数据SHA、生成器SHA、完整窗口生成记录。原子不替换发布，完成标记在场景后；新根parent=null，标记development_only/formal_release_eligible=false/NOT_CERTIFIED。没有套用Legacy父SHA，也没有放宽 `capture_provenance` 正式门禁。只有明确planning_preview配置可以使用 `capture_development_provenance`；正式模式拒绝这个来源快照。新合同要求侧车，删除侧车不能回退到内嵌声明。

没有缩小原source_identity依赖闭包以迁就旧数据，反而把新物理工具和生成器加入实际文件身份；旧C6/Legacy仍拒绝。威胁模型延续可信本地部署/受控生产者：防误配、部署漂移和场景/窗口/记录篡改，不冒称对恶意同用户文件所有者的数字签名。跨版本认证仍须重生/复验，不能将相同物理源文件以外的不同SHA强行视同。

8项真实来源测试全通过：实际非空求解、开发来源不得正式消费、删侧车、改窗口/姿态、改源码哈希、改Raw身份、伪造Source ID、独立Verifier真实预览。该Verifier重建公共模型和来源再传播采样，得到SAMPLED_PREVIEW，audit仍INCONCLUSIVE/NO_CONTINUITY_CERTIFICATE。另Registry17、旧算法7及continuous_exposure15（1跳过）通过；本阶段47项46通过/1跳过、4进程退出0，无超时。详见 `/tmp/caabs-final-20261018/p2/`。

## P3：真实启动、取消与停机

原生Linux/DrvFS同字节对照及6次实际Spawn表明，started耗时2.811–4.239秒，固定3秒测试等待和测试Controller的2秒启动预算不足。worker模块此前在身份握手前导入Runner/算法；现在握手前不导入Runner/Registry/JPype，收到身份绑定Start后才加载。生产startup默认30秒未增大；仅测试首次启动使用可配置、有限的8秒，其余IPC消息仍3秒，Controller测试按实际阶段里程碑计时且有总上界。未删除身份、pidfd或进程组检查。

另一个独立根因：后台线程首次启动JPype JVM后，业务线程已经结束，进程却在`jpype._core._JTerminate`卡住；35.044秒诊断超时，见`p3-background-jvm-before.log/.receipt.json`。现在首次ensure_orekit必须主线程调用，未初始化时后台线程明确失败；真实Controller可通过`EOS_PREINITIALIZE_OREKIT=1 EOS_OREKIT_DATA=...`在启动线程前初始化，避免悄悄卡死，后台Verifier使用已初始化的同一数据。Worker无物理计算时不启动JVM。

取消现在对重复有效Cancel序列也只发一个ACK，并保留取消后不提交Candidate。异常在stderr保留traceback。测试中的可被SIGKILL Worker不再持有multiprocessing.Event信号量；改用隔离临时目录中的有界文件门闩，避免进程被杀后测试清理死锁。blocked-verification负例仍断言锁保留及stop失败，但释放门闩后须先等实际线程结束，不能边删除SQLite边让Controller运行。

三轮日志保留于`p3-round1/2/3`：第一轮暴露清理和分阶段测试等待问题（13项shutdown中1失败2错误），针对性修复后连续两轮全部通过，分别runtime2、IPC20、process_group15、shutdown13，共50项/轮、0跳过、4进程退出0。第二轮各模块墙钟1.379/18.728/9.723/41.432秒；第三轮0.884/19.881/8.935/45.905秒。所有结果是/mnt/d真实Spawn运行；没有把分组通过等同全量回归。

## P4：真实非空全链路与对照

入口 `scripts/validate_caabs_real_integration.py --output NEW_ABSOLUTE_DIRECTORY --orekit-data REAL_ZIP`，目录必须全新且在仓库外。实际命令前缀为 `/home/meteor/eos-course-runtime/venv/bin/python -B`，运行输出 `/tmp/caabs-final-20261018/p4-final`；300秒外层上限，退出0，墙钟75.647秒。脚本用真实Registry、真实公共候选/约束、真实Spawn Worker、真实SQLite Controller及独立Verifier，无替换Worker或注入认证。

最终小场景 `p4-final/small/scene.json` SHA **`9f444fddf9a9b4635fe5d8f6a56f6552dfa324cdf1ef5f58171a95e76f0c0c32`**，3任务/3真实窗口/3可信planning窗口。Raw10及Orekit ZIP SHA见P0/P2，输入未改。真实侧车在同目录provenance，冻结的任务和源码/数据身份全部绑定。另生成24任务压力场景，3个相同物理目标各8项独立请求，逐项重新实际计算窗口；明确不算24个独立数据集根，仅用于取消/预算负载。

两算法统一场景SHA、seed42、center放置、公共默认约束、利润权重1（其余0）、2秒名义搜索预算：

| Runner | 完成/TCR | TP | TM | 搜索RT秒 |
|---|---:|---:|---:|---:|
| caabs v0.2.0 | 3/3，1.0 | 6.0 | 0.487963 | 0.053682 |
| completion_first baseline-1 | 3/3，1.0 | 6.0 | 0.348148 | 0.007248 |

CAABS使用默认8/8/16，9次公共候选构造、28次扩展约束核验、7次安全预筛拒绝，实际前沿8、23次接受插入、3层、stop_reason=completed。Solver报告作为`untrusted_solver_diagnostics`事件保留，独立Verifier丢弃这些遥测并重新装载来源/实例化公共约束及计算指标；没有以遥测替代核验。Completion曾因公共candidate_pool遗漏n+1四元数末端而返回空，已最小修正该字段切片，不改任何旧算法排序，真实来源回归覆盖此反例。

24任务真实Runner协作取消：0.159975秒返回，stop_reason=cancelled，保留3任务incumbent（TP5/TCR0.125），独立公共约束/来源及真实采样重放通过。Controller真实流程6次：CAABS正常、Completion正常、60ms短预算、运行中取消、当前身份pidfd注入Worker SIGKILL、同SQLite/目录Controller重新启动后再次CAABS。正常与重启均非空开发预览SUCCEEDED；取消CANCELLED/退出0/无Candidate，崩溃FAILED/IPC_DISCONNECTED/退出-9/无Candidate；全部进程回收、Worker日志清除、flock释放。状态按真实源码为QUEUED→RUNNING（started/LOADING/SEARCHING/SERIALIZING事件）→VERIFYING→终态，不虚构STARTING数据库状态。

60ms是best-effort而非硬实时：第一次压力运行单次不可中断候选构造导致0.067257秒，Controller严格TIMED_OUT/SEARCH_BUDGET且不存计划（`p4-third`，脚本原先误期待必成功的断言失败已保留）；最终运行0.058809秒正常停止并返回结构性空fallback，被明确保存为开发预览，**不算非空验收或认证**。未提高Controller预算、不伪造RT。

HTTP/API和场景目录现在只在显式planning_preview时消费新开发合同，正式请求仍422。独立真实loopback HTTP测试使用独立端口/进程/数据库/来源根，核验CAABS版本、参数传递、非空结果、事件和JSON可视化；正式JSON/CSV导出均409。原窗口导出还修复agile-only时遗漏四元数边界的条件，添加纯单元回归。未重写CAABS算法核心。

正式`certify_schedule`在同一真实计划上再次传播得到 **INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE**。每条10秒曝光含端点201点均由真实Orekit检查；采样再密也不构成区间证明。正式开发来源门禁和正式导出门禁均维持拒绝。`SUCCEEDED`仅对应已有planning_preview结果类型，Storage发PreviewRecord而非CertifiedRecord，continuous_certification明确NOT_CERTIFIED。

## 后续阶段状态

P5首次完整发现已完成（见下），最终版本复测正在执行。正式连续认证没有通过，不能据非空预览声称正式系统成功。

## P5发现的适配缺陷与历史边界

额外开启`EOS_RUN_OREKIT_TESTS=1`后，真实recompute的SimpleNamespace传递了JSON的`field_of_view_deg`，新物理计算器读取core模型的`field_of_view`，导致AttributeError。硬件slew_rate也需相同显式投影；已在`calculator_inputs`映射原值、严格拒绝缺失/非法值，无默认替换，新增纯测试并完成真实Orekit重计算45项全通过（10.160秒/退出0）。重计算工具加入source_identity闭包，因为它是物理参数/窗口序列化/来源发布实际依赖。此变更使P4中间场景按设计失效，最终在新目录再生成，不能改侧车SHA。

完整发现首次：`full-native.log/.receipt.json`，原生目录`/tmp/caabs-final-native-dg56qucu`，373个实际文件逐字节SHA核对、无LFS指针，同Python/依赖/随机种子，1200秒上限，171.722秒完成，597项/587通过/2失败/8跳过/0错误/退出1。实际命令 `python -B -c "import faulthandler,runpy;faulthandler.dump_traceback_later(120,repeat=True);runpy.run_module('unittest',run_name='__main__')" discover -s tests -p 'test_*.py' -v`。启用GEN02真实物理和CAABS真实E2E，其他原有opt-in在首次命令中未开，不能把它们算通过。复制时全部一致；运行期间仅在原目录继续写报告，完成后的全文件一致标记false，实际运行副本未改，后续最终快照另行记录。

- `test_experiments.test_http_add_to_pre_ui_and_inline_metadata_experiments`硬编码当前执行SHA须等于两个历史UI-only版本之一，真实物理源码变化必然不满足。已迁移测试：保持历史两SHA兼容正例，当前同版正例，新增历史→新物理版本HTTP409负例；**生产兼容白名单未改**，12项通过/退出0/25.495秒。不把新物理版本谎称仅UI变化。
- `test_rabas_integration.test_unchanged_real_scene_preview_and_formal_gate`要求旧epoch-fixed场景在预览中20/20，但新真实固定镜头/整星姿态核验在CARTOSAT-2C/M008曝光开始即不可见，正确给出PREVIEW_REJECTED而不是放行。未改RABAS实现、旧场景或期望，保留失败供公共历史fixture迁移审查；新场景的CAABS/Completion真实正例单独通过。
- 显式开启旧`EOS_RUN_EXPOSURE_OREKIT_TESTS=1`时，历史冻结曝光案例两子项原期待NONVISIBLE_EXPOSURE_POINT及旧绝对姿态的出口，现在曝光起点已NONVISIBLE_EXPOSURE_START。仍是拒绝，未改期望或追认历史角。新增当前物理模型真实正起点→中途超限负例，验证NONVISIBLE_EXPOSURE_POINT、真实可见/不可见夹逼及≤1μs边界，13项物理测试通过。旧物理基准必须重新生成并独立冻结，不能仅把断言改成实际错误码。

这些历史fixture失配和未具备连续区间证书分别记录，不能以分组通过掩盖完整回归未绿。
