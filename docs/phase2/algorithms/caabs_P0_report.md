# CAABS P0：真实基线与故障分流（2026-10-18）

起点 `8cf282b556fa97b3d9867913c5a2edfdef500d81`，分支 `feat/caabs-hardening-20261018`；fetch后 origin/main=`ba114dd4e58936445222499e0325e33f1c2fe489`。仅用户任务书未跟踪，未更改其他工作树。

## 实际基线

WSL Python3.10.12，orekit_jpype13.1.5.0/JPype1.5.2/jdk4py25.0.2.1。命令：`python -B -m unittest discover -s tests -p MODULE.py -v`，外层240秒，测试进程每60秒faulthandler栈；固定PYTHONHASHSEED=0/MPLBACKEND=Agg。

| 模块 | Run | 结果/退出码 | 外层秒 |
|---|---:|---|---:|
| algorithm_conflict_beam | 50 | 50通过，0 | 3.788 |
| algorithm_registry_i1 | 17 | 17通过，0 | 12.288 |
| source_window_identity | 31 | 31通过，0 | 64.875 |
| nine_algorithms | 7 | 7通过，0 | 4.648 |
| worker_ipc | 19 | 19通过，0 | 19.729 |
| worker_process_group | 15 | 15通过，0 | 8.564 |
| controller_shutdown | 未完成 | 首项失败，第二项清理死锁；TIMEOUT，不能计13通过 | 240.018 |

保留的日志/逐命令收据：`/tmp/caabs-final-20261018/`。139项有完成统计，无跳过；shutdown余项未知，不能继承旧报告中的9失败为本次准确统计。

## 假设—证据—排除

- Legacy10：SHA `d01e91232fde765cc69534b8334610a062042e3d321b37d7d89dffa68ef1e3fc`；20任务/100窗口全部 `INCONCLUSIVE:UNTRUSTED_WINDOW_PROVENANCE`，无generation record或sidecar。这是缺来源，不是证实物理不可达。
- C6：SHA `bf4dcb78b568c3a4f6c1ef0779076e01bc7fa5a2ab4afa2aeaa3f13e7f8a89a9`；2任务/2窗口同样拒绝。真实v3记录与当前部署的7个文件不同（config/contracts/controller/runner/storage/verification/constraint_model）。边界/可见性代码相同，不足以把差异解释为物理bug；保留严格拒绝，优先新生数据。
- 追踪链：Loader → `planning_evidence`（记录/sidecar+完整source_identity）→ TaskWindow.planning_evidence → `planning_window` → 公共候选构造/ConstraintModel；没有将INCONCLUSIVE改为可规划。
- Spawn导入测量：当前DrvFS两轮1.641/1.285秒；原生Linux相同字节副本0.559/0.504秒；都没有导入JPype/Orekit。副本仅为诊断临时目录 `/tmp/caabs-native-baseline-9d15109n`，不是其他Git工作树，复制清单/所有实际SHA保留。其IPC19/shutdown13全通过（6.717/18.915秒）。说明2秒测试启动+加载总预算接近导入成本，不能把所有错误归因JVM；还需P3逐事件测量。
- shutdown停滞栈明确位于 `multiprocessing.synchronize.notify_all → Event.set → unittest._callCleanup`。测试先tearDown强制回收子进程，再清理release Event；被强杀共享同步状态可能遗留锁。不能用无限延长测试隐藏，P3将修正可被强杀的测试同步和保留有界启动/身份语义。

## 真实物理反例

仓库和既有临时Orekit ZIP均真实存在，19,865,526字节，SHA `1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`。本轮主线程真实初始化5.288秒，进程正常退出0（总6.870秒），没有声称旧GEN-02运行时已自动解决。

2025-11-18T12:00:00Z，a=7000km/e=.001/i=98°/RAAN=20°的Keplerian轨道：地表垂足约(0.137306°,142.546123°)。TargetPointing与NadirPointing的旋转距离 `5.025e-13°`；惯性绝对ZYX却约(-70.006,-82,90.006)°。固定45°限幅误拒天底，确认参考系语义错误。东偏1°/10°的相对旋转约10.246°/57.378°；对跖目标即使目标指向可求也必须由仰角/遮挡拒绝。

旋转 `R_target * transpose(R_nadir)` 独立矩阵乘积与Hipparchus `compose(..., VECTOR_OPERATOR)` 最大误差4.44e-16；将真实LOS乘以R_target得到+Z，误差约6.36e-15°。这证明Orekit姿态是惯性到body，被限幅的应是相对名义姿态，不能把相机当独立云台。公式与API依据：[Orekit NadirPointing](https://www.orekit.org/site-orekit-11.3/apidocs/org/orekit/attitudes/NadirPointing.html)、[Hipparchus Rotation](https://www.hipparchus.org/apidocs/org/hipparchus/geometry/euclidean/threed/Rotation.html)。

P1将据此修复并补真实/负例回归；FOV、非敏捷姿态、初始姿态/转向和连续证书分别核对，绝不以有限点采样代替连续证书。P0只完成定位，没有把系统验收标为通过。
