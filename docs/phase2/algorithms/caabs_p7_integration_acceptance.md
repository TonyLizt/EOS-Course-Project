# CAABS P7 集成验收（2026-10-19）

## 版本、环境及证据

目标main为`2d8a808c58334dd5c6c085e9753bbd5aa86eced1`，原备份为`4f6cd37d870d4ef3e0a3767f535c8178f561c07e`；15提交重放完毕于eb3b21e。工作树、分支、原提交映射及三处冲突见[Rebase记录](caabs_p7_rebase_resolution.md)。后续修复ff96a51（来源）、c37285d（Console与真实浏览器）、7c774b7（测试阶段等待）、8b1b3da（正式拒绝可见性）均本地保存，CAABS核心与备份相同。

实际环境：WSL Ubuntu22.04、Python3.10.12，`/home/meteor/eos-course-runtime/venv/bin/python`；Orekit-JPype13.1.5.0/JPype1.5.2。启动前确认ZIP确实存在、19,865,526字节，SHA`1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`。Raw10 SHA`c707ee30417d7e1a0448b644f90d6595235ae4cc8262fa2645f5f85d1fadc241`。Node v22.23.2、隔离安装Playwright1.64.1/Chromium156.0.8078.4，无项目package.json，真实入口为`node --test`和tests/browser下独立smoke脚本。

新证据根`/tmp/caabs-p7-20261019-olusdyus`，Windows归档`D:/VC/caabs-p7-evidence-20261019`。保留中间失败而非覆盖日志；旧240/P6的115项逐SHA复查。工具node-runtime不作为数据交付，生成器含私有分配的总规格留在独立pilot根，不进入公开证据。

## 接口联合审查

- 相对Nadir姿态、固定镜头/FOV、WGS84遮挡、显式最低仰角、真实边界转向、GS几何及下传审计均保留。SafeConflictIndex与Beam Search无重设计；候选先由公共模型核验，独立Verifier重建来源/资源后重传播。
- fresh分支是窗口物理来源指纹，不是缓存。新v2窗口闭包绑定visibility/time/attitude_frames（仅统一换行）；仍调用完整source_identity防加载A/盘上B。gen02.development.v1必须绑定实际Scene/Raw/任务/生成器/源码/ZIP，不能借fresh分支或缺侧车降级。
- 保留main独立preview_audit_process：父进程复制并核对ZIP、限时kill/wait、核对run/scene/plan/任务数，父进程签发预览凭据。Worker JSON、区间数学内核和共享数据SAMPLED_PASS都不能生成正式凭据。
- 保留工程physical_validation及带采样标识的JSON/CSV导出；开发限定来源只能明确planning_preview，正式JSON/CSV返回409，formal/physical请求422。共享新根工程导出与正式认证导出是不同门禁。
- Console维持三工作区、11算法参数、种子模型、比较/调度图。只在有开发限定场景时显示预览选择；保留常规工程默认，明确显示未认证来源与正式失败。

## 实际测试与失败诊断

原632仅为历史基线。本轮首轮最新代码完整发现651项，651通过/0失败/0错误/0跳过，261.333秒、外层262.204秒、1200秒限、退出0。407个跟踪文件原生Linux副本逐SHA一致，无LFS指针，结束时源文件未变；日志p7-full-all-optins及copy/receipt。

最终完整复测结果见本报告末尾收据附录。两轮均使用以下实际命令（完整命令数组也在收据中）：

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

| 定向组/命令范围 | 结果与真实日志 |
|---|---|
| 冲突相关第一层 | continuous16最初2失败，冻结夹具CRLF原因；其余development10/preview5/shared8/identity31/experiments12通过，p7-layer1。未改成假通过。 |
| 来源负例 | 物理闭包1失败；真实development14中版本1失败、数组1error；缺侧车2测试含3失败子项。p7-negative-before、p7-routing-before。 |
| 来源修复定向 | p7-source-fixed：1+14+16+8+5全通过、0跳过；p7-routing-fixed：2+5+8全通过、0跳过，均退出0。 |
| 核心/Registry/旧算法 | p7-core-lifecycle：50/17/7各通过，退出0；来源31在第一层和两轮全量通过。 |
| IPC/group/runtime | 20/15/2各通过，31.111/9.990/1.574秒，退出0；两轮全量也执行。 |
| Controller shutdown | 定向13中1次VERIFYING等待过短失败；采栈3次均复现。只调整该测试阶段等待，修复后3/3（49.600秒、外层52.387）与13/13（外层63.825秒）通过，退出0。生产超时、物理约束未改。 |
| Daemon | 14通过、外层152.779秒、退出0；没有超过240秒模块上限。 |
| Node | node --test：32通过/0失败/0取消/0跳过，571.597ms、外层0.601秒、退出0；node-unit.log/receipt。 |

所有真实物理opt-in在完整运行显式开启，涵盖GEN02、E3/E4、CZML、真实曝光、插值、真实GS、物理负例及来源；不把分组统计加到完整发现数。原13项停机、50项核心、17 Registry、31来源及旧算法7均保留。预期故障注入的Pipe/solver traceback不是失败；faulthandler定时栈是诊断输出，不是实际外层超时。

## 全新真实场景与系统链

| 场景 | 实际SHA-256 | 结果 |
|---|---|---|
| 无GS，3任务/3可信窗 | 426cef705b705ec311f356ad3cc3fcaa83a18b24a6fb041d41851032e91f3722 | CAABS、Completion First各3/3，TP6；同seed42/center/2秒，搜索0.093006/0.006976秒 |
| GS，3任务/3观测窗/1GS/1通信窗 | 2c00006e71789913d5b2cac468b692e0ea950f30de107af99be8b09040c3677d | CAABS2/3、TP4，搜索0.031076秒；独立下传两条各201点PASS，但仍INCONCLUSIVE |
| 共享生成器公开根兼容试验 | dd1b3891534dd83addfcd0cd14427b4a5df753251825499b3c43a38072c3de96 | 10星20任务/1天/10秒网格，373段、20任务有窗；真实HTTP工程模式CAABS20/20 |

前两份都在全新目录由原真实生成器重建，未继承旧侧车。完整源快照SHA`75544183c4e4b7f2bafd42f1d0a5a12367d6f556bb33021779f169bb6bbc62ee`，逐文件/模型/数据身份见e2e-ground/interval-readiness.json和新Sidecar。

实际执行现有validate_caabs_real_integration.py（360秒限、133.996秒退出0）：Registry→Runner→公共模型/来源重建→Verifier；真实Worker/Controller正常和Completion成功、60ms预算TIMED_OUT/SEARCH_BUDGET无计划、取消CANCELLED无候选、崩溃FAILED/IPC_DISCONNECTED exit -9、重启后成功和锁/进程回收。e2e-no-ground完整保留场景、侧车、候选、审计、数据库和各终态。不是mock生命周期。

validate_ground_link_development.py（240秒限、45.751秒退出0）实际重放GS身份、严格观测后下传及资源。真实几何、理想天线模型；没有声称真实RF链路预算/天气损耗/安装标定或连续证明。正式导出拒绝。

## 真实Chromium验收

运行scripts/validate_caabs_p7_http.py，独立runtime/SQLite、真实uvicorn服务和现有生成场景；http-browser-final，51.314秒、360秒限、退出0。两份场景均实际经HTTP→Registry/Worker→Controller→独立Preview进程→Storage→Console/Gantt：无GS3/3、GS2/3；Beam4/branch4/candidates8实际从页面提交，11算法参数组件检查通过。未知/非法参数拒绝；来源、窗口ID、下传ID、当前状态及NOT_CERTIFIED正确；开发限定的formal/physical请求422、JSON/CSV正式导出409。

另用build_shared_dataset.py --limit 1 --step-s 10在独立根实际生成公开根试验（20.038秒退出0，单场景9.730秒），没有生成100份或运行私有测试。shared-http-v4以真实页面默认工程模式提交，完成20/20；JSON/CSV工程导出含SAMPLED_PHYSICAL_PASS和not a continuous标签，仍NOT_CERTIFIED。正式请求实际FAILED/CONTINUOUS_INCONCLUSIVE/NO_CONTINUITY_CERTIFICATE、plan=null，并在Console显示红色FAILED及错误、隐藏导出；截图人工检查通过。整条共享浏览器验收38.392秒退出0。

浏览器统计为2个脚本、3种真实场景流程，不冒称为Node 32项或Python单元项。没有mock网络或注入凭据。初轮脚本等待第二步隐藏控件“可见”而超时，改为等待组件挂载后真实导航；共享工程Gantt使用main的“非严格连续证明”标签，修正过窄文本断言并同时断言不得显示“连续认证通过”。失败日志保留，修复的是测试前提而非物理期望。最终浏览器page_errors均空，3个runtime停机exit0、锁释放、无worker journal。

## 共享数据资格与剩余科学阻断

共享生成/配额、Loader、来源、HTTP、Console及工程导出代码兼容性有真实pilot支持；没有重写experiments/datasets规格或旧80份数据。旧v1物理指纹不含新增姿态实现，**不能继续追认为当前v2可信窗口**。冻结公开80/私有20的整体迁移、发布和人工签收仍未验收，需数据负责人用新版本/新目录生产并审查，不能改旧SHA。此pilot沿用公开EOS-G0001任务根，仅是新模型兼容试验，不是第101个独立来源，也不替换冻结eos-course-v1 artifact。

严格连续认证仍BLOCKED：缺经过验证的Kepler/浮点输入误差界、ITRF/EOP/时间变换包络、姿态归一化/Euler图包络、实际slew执行轨迹/误差/稳定合同。数学有理内核不注册provider；采样、微秒退出括区、工程导出和Controller预览SUCCEEDED均不能代替CONTINUOUS_PASS。新根正式发布资格仍需独立审批。

| P7项目 | 裁决 |
|---|---|
| 当前Rebase/15提交保留/最新main祖先 | PASS |
| 开发来源/非空CAABS/GS/独立Verifier | PASS（开发资格及明确模型范围） |
| 新main Preview进程/Console/HTTP/旧算法 | PASS |
| 最终完整Python/Node/真实浏览器 | PASS（分别记录，不以分组代替全量） |
| 共享生成器及公开pilot工程流程 | PASS WITH CONDITIONS（不等于冻结100份整体迁移） |
| 严格连续认证/正式发布 | BLOCKED |
| Draft PR材料 | PASS；允许提交Draft供独立审查，本轮不创建PR |
| 最终合并批准 | BLOCKED，尚无独立审核和科学证明/正式数据签收；不以本地自验替代 |

最终完整复测及归档信息在收据附录更新；相关PR说明与Reviewer Checklist见[Draft PR正文](caabs_p7_draft_pr.md)。

## 最终收据附录

`p7-full-final-all-optins`：**651通过/0失败/0错误/0跳过，测试259.422秒、外层260.647秒，退出0，1200秒上限未触发**。实际原生目录`/tmp/caabs-final-native-g24vtk0j`，408跟踪文件，源/副本SHA一致，无LFS指针，测试结束源文件未变。相比首轮只增加测试阶段等待与浏览器失败展示断言，没有更改生产物理/来源/Worker实现。两轮全量均为完整discover、全部六组真实opt-in，不能把它们合计当1302个不同测试。

最新共享浏览器为shared-http-v4（38.392秒退出0），除了20/20和工程导出，还用真实导航打开正式失败实验，断言FAILED、NO_CONTINUITY_CERTIFICATE可见、导出隐藏；浏览器page_errors=[]，Gantt及正式拒绝截图已人工检查。首轮共享v3已通过；最终v4增加了正式失败在Console实际可见性，未改认证期望。

`final-integrity.json`独立复查两份开发场景当前部署/ZIP/侧车绑定，以及公开pilot来源；18.029秒退出0。原240项、P6的115项证据逐SHA相同，0失配。归档仅复制pilot的公开development子目录，不复制含私有最终测试分配的顶层规格；不注册final_test，不宣称本次得到新独立任务根或正式数据资格。

最终新归档188个文件，另含`archive_index.json`，索引SHA`fcbbe83bd2753888ec0b58a58d61478c7dbfcbc9c3852c50e945ed1809293849`。源/副本逐SHA核对一致；node-runtime仅工具安装、不归档，工具版本锁另保存。原场景与侧车中的WSL路径未改写；归档是取证副本，不生成新的来源资格。

重放15提交以外新增本地提交：ff96a51（来源闭包/版本/缺侧车降级与LF）、c37285d（开发预览Console及真实浏览器）、7c774b7（阶段等待测试）、8b1b3da（正式失败真实页面可见性）。运行证据HEAD为`8b1b3da40fa5dd27b7a28cbcd8c791cd07b158e3`；最后只有P7报告及COURSE_SETUP文档提交，其SHA以最终Git HEAD为准。原15映射、完整运行提交列表和range-diff均收入归档；最后fetch仍为目标main、ancestor检查退出0，diff及暂存检查退出0。没有源码未提交修改，用户任务书继续未跟踪，未push/创建PR/merge。
