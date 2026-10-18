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

全部计划内测试已实际执行，P5完整回归未绿，正式连续认证BLOCKED；详见最终裁决。不以非空预览声称正式系统成功。

## P5发现的适配缺陷与历史边界

额外开启`EOS_RUN_OREKIT_TESTS=1`后，真实recompute的SimpleNamespace传递了JSON的`field_of_view_deg`，新物理计算器读取core模型的`field_of_view`，导致AttributeError。硬件slew_rate也需相同显式投影；已在`calculator_inputs`映射原值、严格拒绝缺失/非法值，无默认替换，新增纯测试并完成真实Orekit重计算45项全通过（10.160秒/退出0）。重计算工具加入source_identity闭包，因为它是物理参数/窗口序列化/来源发布实际依赖。此变更使P4中间场景按设计失效，最终在新目录再生成，不能改侧车SHA。

完整发现首次：`full-native.log/.receipt.json`，原生目录`/tmp/caabs-final-native-dg56qucu`，373个实际文件逐字节SHA核对、无LFS指针，同Python/依赖/随机种子，1200秒上限，171.722秒完成，597项/587通过/2失败/8跳过/0错误/退出1。实际命令 `python -B -c "import faulthandler,runpy;faulthandler.dump_traceback_later(120,repeat=True);runpy.run_module('unittest',run_name='__main__')" discover -s tests -p 'test_*.py' -v`。启用GEN02真实物理和CAABS真实E2E，其他原有opt-in在首次命令中未开，不能把它们算通过。复制时全部一致；运行期间在原目录继续写报告，完成后的全文件一致标记false，副本未改。后续适配修复另行提交并用新最终快照完整重跑。

- `test_experiments.test_http_add_to_pre_ui_and_inline_metadata_experiments`硬编码当前执行SHA须等于两个历史UI-only版本之一，真实物理源码变化必然不满足。已迁移测试：保持历史两SHA兼容正例，当前同版正例，新增历史→新物理版本HTTP409负例；**生产兼容白名单未改**，12项通过/退出0/25.495秒。不把新物理版本谎称仅UI变化。
- `test_rabas_integration.test_unchanged_real_scene_preview_and_formal_gate`要求旧epoch-fixed场景在预览中20/20，但新真实固定镜头/整星姿态核验在CARTOSAT-2C/M008曝光开始即不可见，正确给出PREVIEW_REJECTED而不是放行。未改RABAS实现、旧场景或期望，保留失败供公共历史fixture迁移审查；新场景的CAABS/Completion真实正例单独通过。
- 显式开启旧`EOS_RUN_EXPOSURE_OREKIT_TESTS=1`时，历史冻结曝光案例两子项原期待NONVISIBLE_EXPOSURE_POINT及旧绝对姿态的出口，现在曝光起点已NONVISIBLE_EXPOSURE_START。仍是拒绝，未改期望或追认历史角。新增当前物理模型真实正起点→中途超限负例，验证NONVISIBLE_EXPOSURE_POINT、真实可见/不可见夹逼及≤1μs边界，13项物理测试通过。旧物理基准必须重新生成并独立冻结，不能仅把断言改成实际错误码。

这些历史fixture失配和未具备连续区间证书分别记录，不能以分组通过掩盖完整回归未绿。

## 最终源码、真实产物及可复现命令

所有240份原始日志/收据、开发场景/Sidecar、隔离数据库与完整文件SHA清单已按字节核对归档到 **`D:/VC/caabs-final-evidence-20261018`**（WSL `/mnt/d/VC/caabs-final-evidence-20261018`），`archive_index.json`记录每份实际SHA；不纳入Git、不覆盖原文件。下列`/tmp`证据相对路径可在该归档中找到同字节副本，避免临时目录回收后丢失审查材料。

运行源码为`0b9f48d41b2880e353b3621477fe769f508df3cb`（最后文档提交只修改说明，不改变运行代码）。WSL Ubuntu22.04/Python3.10.12；NumPy2.2.6/Pydantic2.14.1，Orekit-JPype13.1.5.0/JPype1.5.2/JDK25.0.2.1。未安装新依赖；FastAPI TestClient缺httpx2，实际HTTP测试改用已有Uvicorn+标准库loopback，不跳过HTTP验收。

重生及系统验收命令（已执行，300秒外层上限，退出0/69.751秒）：

```bash
cd /mnt/d/VC/EOS-Course-Project-caabs-latest
PYTHONHASHSEED=0 MPLBACKEND=Agg \
  /home/meteor/eos-course-runtime/venv/bin/python -B \
  scripts/validate_caabs_real_integration.py \
  --output /tmp/caabs-final-20261018/p5-repro \
  --orekit-data /tmp/eos-gen02-itrf-eVCxbe/orekit-data.zip
```

重跑必须换全新输出目录；禁止覆盖成功产物。入口导入无JVM/目录副作用。真实服务启动须先在主线程初始化JVM，或给Controller设`EOS_PREINITIALIZE_OREKIT=1 EOS_OREKIT_DATA=...`；不预初始化的后台首次物理认证明确报OREKIT_MAIN_THREAD_INITIALIZATION_REQUIRED，避免进程退出永久卡住。空/合成纯工程测试不要求JVM。

最终场景路径 `/tmp/caabs-final-20261018/p5-repro/small/scene.json`，SHA **`a2ec9d89b2610eba6633a2b637b6d391eda95fde9baa20ad6859d359d177d10a`**；与前一轮p5-final重新生成结果相同。3任务/3可信planning窗口，真实Sidecar在`small/provenance/scene.json.provenance.json`。24任务压力SHA `43e5dee448d4c0ba9edc68bfdc43f23a6470d040f322d3e1ea35fcae9e175e2c`。不提交这些运行数据或SQLite到Git。P2/P4旧中间产物保留原SHA，但当前身份核验会拒绝，最终验收以p5-repro为准。

同SHA/seed42/2秒预算/center/默认约束与目标权重，**进程启动前固定PYTHONHASHSEED=0**（旧Completion内部有set迭代，光设算法seed不能消除进程哈希差异；未修改其他算法策略）：

| 最终Runner | 完成 | TCR | TP | TM | RT秒 | stop |
|---|---:|---:|---:|---:|---:|---|
| CAABS | 3/3 | 1.0 | 6 | 0.487963 | 0.059138 | completed |
| Completion First | 3/3 | 1.0 | 6 | 0.660185 | 0.007028 | 基线无该遥测字段 |

再次独立Python进程重复两算法，与保存的Runner候选、实际Worker→Controller计划比较（按任务排序消除Verifier时间排序），所有Assignment字段一致，证据`reproducible-comparison.json`及`reproducible-comparison-final.receipt.json`（退出0/10.267秒）。这是单个受控开发几何，不能推出统计优势或跨星座/私有测试泛化。

CAABS正式来源ID/实际曝光（均ALOS-2_39766、真实`sensor_id=ALOS-2_39766_sensor`，UTC）：

| task | sat_window_id | 开始 | 结束 |
|---|---:|---|---|
| DEV01-00 | 1 | 2025-11-18T12:01:25 | 12:01:35 |
| DEV02-00 | 2 | 2025-11-18T12:02:56 | 12:03:06 |
| DEV03-00 | 3 | 2025-11-18T12:04:26 | 12:04:36 |

无GS场景不伪造gs_window_id或下传；真实通信物理没有在这个小场景验收，I2相关31项包含公共GS身份/归属/严格边界负例。独立重放在新实例ConstraintModel中按时间逐条先检查父计划再加入，3条均通过；固定输入重复结果相同，SchedulingProblem及原ConstraintModel属性前后不变。篡改source ID/卫星/传感器/orbit/微秒曝光5负例均拒绝，见`p5-independent-replay.json/.log/.receipt.json`（退出0/27.959秒）。

最终六次真实Controller结果：normal/Completion/restart为非空开发预览SUCCEEDED；60ms预算在0.057185秒返回2任务incumbent预览；cancel为CANCELLED/退出0/一个ACK/无候选；当前自有pidfd崩溃注入为FAILED/IPC_DISCONNECTED/退出-9/无候选。六次WORKER_REAP均identity_confirmed=true/alive=false/live_members=0，最终worker-lease不存在、flock可重新取得。同数据库重启成功；未触碰正式数据库或用户其他进程。

## 最终测试汇总

单模块实际命令模板：`PYTHONHASHSEED=0 MPLBACKEND=Agg [各实际opt-in环境] /home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover -s tests -p 'test_MODULE.py' -v`。收据的实际测试包装只额外开启faulthandler；每模块240秒上限、完整发现1200秒、真实E2E300秒。以下数字不重复相加冒充不同测试总数。

| 证据目录/命令范围 | 执行数 | 成功/失败/跳过 | 退出码/墙钟 |
|---|---:|---|---|
| p4-tests：CAABS/Registry/I2/旧算法四组 | 105 | 105/0/0 | 均0，2.857/9.258/58.027/5.240秒 |
| p3-round2，runtime/IPC/group/shutdown | 50 | 50/0/0 | 均0，累计71.262秒 |
| p3-round3，同上稳定性复测 | 50 | 50/0/0 | 均0，累计75.606秒 |
| p5-final-physics，实际物理13+来源/真实HTTP10 | 23 | 23/0/0 | 均0，6.134/47.550秒 |
| p5-adapter，重计算45+实验12 | 57 | 57/0/0 | 均0，10.160/25.495秒 |
| p4-http-final，transition/continuous_pipeline/preview | 23 | 23/0/0 | 均0，1.387/53.760/1.995秒 |
| p5-orekit，真实UTC CZML | 1 | 1/0/0 | 0，6.816秒 |
| full-native-final，最终完整发现 | 599 | 592成功；2个失败测试含3条failure；5跳过；0error | 1，测试172.066/外层173.266秒 |
| p5-geometry，E3/E4真实几何 | 3 | 2/1/0 | 1，6.562秒 |
| p5-geometry，真实轨道/Node消费者插值 | 7 | 7/0/0 | 0，7.053秒 |

最终全量使用同一环境、全部当前实际源码的原生Linux副本`/tmp/caabs-final-native-rzxvzlgt`；373文件复制清单及SHA在`full-native-final-copy.json`，**源与副本复制前后字节一致、无LFS指针、源在运行结束时未变**。Git库不复制/不改，运行代码对应0b9f48d。原worktree已通过上表DrvFS定向运行。env开启`EOS_RUN_GEN02_PHYSICS=1 EOS_RUN_CAABS_REAL_E2E=1 EOS_RUN_OREKIT_TESTS=1 EOS_RUN_EXPOSURE_OREKIT_TESTS=1`及真实EOS_OREKIT_DATA；完整命令见收据。105/IPC20/group15/shutdown13及真实CAABS E2E均在全量中再次通过。全量没有超时或卡死；预期故障注入的stderr traceback不算测试失败。

最终全量3条failure是上文历史曝光两个子项与RABAS历史场景一项。5个skip是原E3/E4三个、插值两个opt-in；之后**实际开启** `EOS_RUN_E3_E4_OREKIT_TESTS=1 EOS_RUN_ORBIT_INTERPOLATION_TESTS=1`独立运行：微秒CZML的所有结点/首末端、UTC EME2000/ITRF状态及7项插值通过，GPM旧窗口测试失败（旧test_e3_e4_orekit.py:160仍用绝对惯性Euler作参考，期望1窗/实际0窗）。保留原断言与数据，不改成0窗“通过”。分组结果不反写全量的skip/失败。

## 最终裁决、剩余工作及PR审核材料

| 阶段/门禁 | 裁决 | 证据范围 |
|---|---|---|
| P0 故障复现 | PASS | 真实基线、死锁栈、Spawn分布、历史来源拒绝 |
| P1 GEN02物理模型 | PASS WITH CONDITIONS | 相对姿态/固定镜头/硬件速率/真实负例正确；保留Keplerian与方形FOV建模假设及硬件标定未证实 |
| P2 可信非空开发来源 | PASS | 新生成真实数据、原子不替换、严格SHA/sidecar链；仅开发资格 |
| P3 Worker/Controller | PASS | 连续两轮50项及两次全量；真实取消/崩溃/重启/资源回收 |
| P4 非空开发全链路 | PASS | Registry/Runner/真实Worker/Controller/独立Verifier/开发JSON预览；正式导出拒绝 |
| P5 全量回归 | FAIL | 最终3条failure及额外1个GPM旧物理基准；未skip或改期望掩盖 |
| 连续认证/正式发布 | BLOCKED | 真值采样通过仍缺经验证的解析/区间证书；不是Orekit缺失或I2失败 |
| 同预算开发比较 | PASS WITH CONDITIONS | 单几何、相同SHA/权重/seed/hashseed可复现；不是正式Benchmark分数 |

剩余阻断与责任：

1. 物理/连续认证实现及独立审核：当前真实evaluator没有可信`certify_interval`，缺已验证的导数/误差界或等效区间证明。不得用更密采样替代。正式成功/正式JSON CSV导出仍BLOCKED；不得复用Legacy/C6证书。硬件安装轴/FOV定义和真实卫星硬件参数仍须独立规格确认，当前仅证明仓库显式模型的一致性。
2. 公共物理测试/场景维护：对旧绝对姿态GPM/曝光固定探针和旧RABAS正例建立新模型下可达、不可达的独立冻结fixture并审查。现有历史数据保持原SHA和失败证据，不修改算法或约束来迁就它们。上述失败未被解决，不建议合并。
3. 部署：必须主线程预初始化JVM、固定PYTHONHASHSEED；普通Solve预算是best-effort，不可中断构造可能超极小预算，Controller严格终态裁决已验证。源码升级会使开发侧车失效，须新目录重生，不能原地改hash。
4. 仍未做完整一天100场景生成、大规模Benchmark/私有final或真实地面站链路的端到端物理验收；既有累计W资源模型不是完整电池/热力学/燃料仿真，未在本任务中虚构这些保证。

本地提交清单（均实际测试、diff --check及cached检查后提交）：7025151(P0报告)、ee7d0e2(物理参考系/刚体转向)、be92f1d(真实开发生成/来源)、3f2cff0(IPC/停机/JVM)、aa7a9b7(真实非空全链路/公共候选四元数兼容)、0b9f48d(物理配置适配及历史版本隔离测试)。随后文档提交只保存本最终验收和版本说明；CAABS核心与8cf282b无差异。未push/建PR/merge、未改变其他worktree，根目录用户任务书仍未跟踪保留。

建议Draft PR标题：`fix(caabs): restore real pointing windows and validate worker lifecycle integration`。

可复制PR摘要：修复GEN02把惯性绝对Euler误用为整星倾斜的缺陷，以Nadir相对姿态、固定相机与真实转向边界生成当前源码可信开发窗口；修复Worker握手前重导入、重复取消ACK、JVM后台初始化退出卡死及测试清理同步；接通显式开发来源HTTP入口，保留正式认证拒绝。CAABS v0.2.0核心不变，真实3/3非空计划通过独立公共约束/来源及实际曝光采样；真实取消、崩溃和重启通过。最终完整599项仍有历史物理fixture相关3条failure/5skip，额外GPM旧物理基准失败，未取得连续区间证书，**Draft可供独立审查，当前不可批准合并或正式发布**。

Reviewer检查表：旋转复合/相机轴与FOV语义；精确末端四元数和初始/任务间转向；新根开发来源防篡改/正式隔离；Worker身份/ACK/重收锁与主线程JVM；预算超限拒绝；所有非空出参的来源/资源独立重放；历史fixture迁移证据及连续区间证明缺口。物理与公共Verifier负责人审物理/认证，系统负责人审IPC/Controller/SQLite事件兼容，算法负责人审候选兼容/105回归与实验复现。不擅自邀请或联系组员。
