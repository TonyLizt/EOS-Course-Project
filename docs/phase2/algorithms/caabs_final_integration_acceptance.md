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

## 后续阶段状态

P2/P3/P4/P5尚在执行，以下任何最终结论必须等待实际场景及独立验证。当前不宣称正式连续认证通过，不宣称完整系统成功集成，不以空计划代替非空验收。
