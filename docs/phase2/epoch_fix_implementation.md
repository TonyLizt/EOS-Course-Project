# Change E：轨道历元 E1–E2 实现与验收记录

实施日期：2026-10-15 至 2026-10-16（Asia/Shanghai）。分支：`fix/orbit-epoch-parsing`。审计基线：`753d2677f51965121006829475e775f95c1a4a44`。本轮不提交、不推送、不登记正式场景、不运行大型生成或调度实验。

## 1. 依据与当前实现差异

已按内容版本核对项目实际源码、README、COURSE_SETUP、实验协议、framework_handoff、algorithm_integration。最新版设计材料位于 `D:\学习\大三上\操作系统课设`：

- `第二阶段实施计划说明书_审核稿 (1)(1).md`：v0.9，2026-10-15，第 12 节 E1–E5。
- `第二阶段_接口设计文档_审核稿 (1)(1).md`：v0.3，2026-10-15，第 10 节。
- `第二阶段_数据库设计文档_审核稿 (1)(1).md`：v0.3，2026-10-15，第 8 节。
- `team_collaboration.md`：分支与顶部运行记录规范。
- `W2 WorkerIPC 与 Controller 协作实施说明 v1.0.md`：2026-10-14，W2 实施方案。

这些最新版尚未全部入本仓库；其中部分文档链接仍指向较旧的 `(1)` 文件。按文档内版本选择 `(1)(1)`，没有自动拉取、合并或覆盖仓库文档。设计稿中的 provenance/API/cache 字段、W2 状态机不视为当前 HEAD 已实现的能力。

开始时工作区干净，但在 main；遵照任务停止编辑，用户手动切换至修复分支后才开始实现。修改前和继续工作时均用只读 pgrep 检查，未匹配 main_generate/main_scheduler/系统服务进程。没有发送进程信号。LFS 清单有 6 个历史场景条目；本轮未打开其内容，未访问 output/。

## 2. 当前 HEAD 审计：逐文件、逐函数

以下描述指修复前 HEAD；当前工作区已按第 3 节修复解析入口。

| 文件 / 函数 | 已确认事实、影响及边界 |
|---|---|
| `utils/visibility.py::_parse_epoch` | 英文 `18 Nov 2025 12:00:00.000` 不匹配 ISO/四种旧数字格式，最终返回执行时 datetime.now(UTC)。同一输入可能得到不同的轨道历元。 |
| `_extract_orbit_params` | 从 `Satellite.orbital_params.initial_representation_Epoch` 读取历元；a 的 km 转 m，其他四角保持度，e 无量纲。原始输入顺序是类型、a、e、i、argp、RAAN、M、epoch。只读样本 input/1_satellites.json 使用上述英文日期，没有时区标记；旧契约解释为 UTC。 |
| `_build_keplerian_orbit` | UTC-aware 历元交给 datetime_to_absolutedate，再构造 EME2000 / PositionAngleType.MEAN 的 KeplerianOrbit。缓存键包含解析后的 epoch ISO。错误不是给窗口简单整体加一个时间偏移，而是在错误日期定义了同样的根数，改变指定仿真时刻的传播相位。 |
| `calculate_windows_orekit` | ensure_orekit 后逐星提取参数，预建/缓存轨道并求周期；按任务、卫星传播和扫描。窗口 sensor_id 硬编码 `{sat_id}_sensor`。ensure=True 时可原地改任务坐标；False 的无窗口路径立即结束，不调用随机坐标函数。 |
| `compute_visibility_and_attitude` | TargetPointing；EME2000 与 ITRF/IERS2010(simpleEOP=True)、WGS84；ZYX / FRAME_TRANSFORM Euler 度。仰角和三轴绝对角上限影响可见性。默认粗步长 60 秒，细步长来自场景。FOV 虽有静态字段但未进入窗口判定。E 不改变这些公式。 |
| `_build_time_windows_from_visible_attitudes` | 重新从可见样本构造 agile_data 三轴数组，代表姿态取中间样本。orbit_number 是从场景起点按开普勒周期计数，非升交点轨道编号。 |
| `core/scenario.py::calculate_visibility_windows` | 传递原有卫星、任务、地面站、mission_info、起止时刻、步长和扫描参数；接收 updated_missions。ensure=True 的对象修改会进入导出。 |
| `Scenario.export_to_json` | 重建已知顶层结构，会丢掉未知字段；无地面站时删除 satellite.communication_capability。不能用其完整序列化路径实现静态冻结重建。 |
| `core/models.py` | 旧导出具有轨道、资源、传感器、机动等静态配置，足以构建当前窗口计算所消费的投影。不能断言每个未检查历史文件都完整；E2 缺必需字段会失败，不回填默认卫星。 |
| `main_generate.py::run_all_scenarios` | 原来父进程读卫星文件仅计数，无历元预校验；本轮在已有读取点校验全部历元后才提交池。模块本身导入会创建 output 目录，因此测试不导入或执行该入口。 |
| `main_generate.py` 默认配置 | metadata.creation_time 是 naive 2025-11-18 12:00，duration 秒、time_step 1 秒；默认 ground_stations_dict={}，直接导致通信计算被跳过。comm=0 在该配置下是 no_ground_station_configured，不是物理上没有通信机会。 |
| `draw/orekit_to_czml.py::demo` | 场景开始时间 fromisoformat(...).replace(tzinfo=UTC) 会错误重新标记已有偏移；轨道英文日期另用 locale 敏感 %b 解析。与 visibility 的入口不同，造成回放/调度可分离。需要 E3 统一解析，未经授权本轮不修改。 |
| `eos_system/orbit_generate.py` / `visualization.py` | 前者调用 CZML demo，后者轨道缓存未纳入解析器和传播版本。需要 E3/E5；本轮不改回放、缓存或服务。 |
| `schedulers/scenario_loader.py` | aware 时间转 UTC 后移除 tzinfo，naive 按既有 UTC 比较；该加载器只保留调度子集，不能作为 E2 全量静态序列化器。 |
| `scripts/build_scenario_manifest.py` | FIELDS 固定，未实现物理版本/parent 关系传播。E2 复用 Validator 和 registry_id，另存 provenance 子目录；不把 sidecar 放进场景目录的直接 *.json 扫描集合。47 项现有测试保持通过。 |

场景开始时间、轨道历元是独立字段，允许不同；必须保持各自同一绝对时刻的 UTC 语义，不能将历元改成场景起点。错误历元影响 PV、地固目标相对几何、可见窗口、姿态及调度的派生特征。Cesium 可能使用正确英文历元却显示另一条轨道，因此“看起来正常”不证明旧调度数据正确。

本轮能独立修改解析及数据工具。自定义/多传感器、注册/API/RunConfig、回放缓存、Worker/IPC、数据库和 UI 属于公共契约，交李泽同及对应负责人确认；不扩展核心模型。Change P（初始姿态、固定镜头 FOV、四元数可行性）未实施。

## 3. E1 实现

`utils/time_parsing.py::parse_orbit_epoch` 使用标准库，版本 `epoch_parser_v1`。支持固定英文月份、ISO、Z、明确偏移、旧 slash 格式、datetime 和有限 Unix 秒。naive 按 UTC，aware 用 astimezone(UTC)。布尔、空串、未知类型、NaN/Inf、越界日期明确 ValueError，包含 satellite_id、field、value 和原因。无 locale 全局操作，无当前时间回退。

`visibility._parse_epoch` 保留兼容函数名并委托统一入口；`_extract_orbit_params` 加卫星 ID 上下文。`main_generate.run_all_scenarios` 只增加原数据读取后的预校验；没有重构池、随机分布、生成输出或物理计算。

E1 23 项纯 Python 测试实际通过，随后才开始 E2 正式实现。生成器测试用 AST 核查预校验位置，不触发模块导入的 output 副作用。

## 4. E2 重建与安全边界

`scripts/recompute_scenario_windows.py` 的 CLI 和函数接口独立于生成入口：

1. 只读加载调用方已冻结的 JSON，拒绝重复键/非有限数值、过大文件和可选的预冻结 SHA 不一致。默认输入上限 64 MiB，可显式提高；这是多副本的内存实现，未宣称支持大型场景流式重建。解析完整 JSON 并不能证明源文件已由生产者完成，冻结仍由调用方负责。
2. `static_data` 仅排除两个顶层派生字段 observation_windows、communication_windows，所有其他已知/未知配置、原 epoch 字符串、数组顺序和 ID 全部进入规范化静态 SHA-256。JSON 空白与对象键序不进入静态身份，数值/字符串/数组内容保留。
3. 计算器输入为完整静态对象的临时属性投影，补充现有低层 API 需要的单位别名；不用会重置能力的构造器。计算前后比对对象，任务被替换、删除或坐标被修改都会报具体字段差异并失败。场景 JSON 只替换两个派生集合。
4. 明确传 `ensure_each_mission_has_window=False`、`mission_info=None`；无随机分布参数，无重新抽样入口。零窗口任务保留并进入完成率分母。
5. 当前只支持每星恰好一个、ID 为 `{sat_id}_sensor` 的既有配置；自定义或多传感器明确拒绝，停止该部分功能。没有静默改名或把多传感器复制成相同窗口。提案：由公共 API 接收显式 sensor_id 和选择策略；团队确定各传感器几何/模式语义后补多传感器测试。
6. 使用当前 low-level Orekit 函数重新生成片段、姿态、代表姿态和轨道编号；有地面站则重算通信，无地面站通信为空。观测片段缺姿态、任何片段缺轨道编号、错误引用/时段/数值等拒绝发布。复用现有 Manifest Validator；其 WARN（例如零覆盖）保留为证据，不当作物理 PASS。
7. 仿真区间/步长来自源 metadata；扫描缺省仍为当前生成器 5° 仰角、60 秒粗步长。可读取显式 metadata.extra.visibility_settings 中同名两参数；未知扫描参数拒绝。若旧文件没有记录其实际生成时的覆盖参数，必须在后续确认；本工具不能恢复未知历史参数。
8. 拒绝同文件、已有文件/sidecar、受保护目录、同一输入目录和未带 epoch_fixed_v1 的输出名。input/output 禁止读写，experiments/scenarios 和 .git 禁止作为输出；不修改 LFS。
9. 在目标文件系统创建独占临时文件，flush/fsync，校验 SHA，然后 os.link 原子创建最终名称且不替换已有名称。无 hardlink 能力时直接失败，不退回覆盖式 rename。先场景、后 provenance；后者是完成标记。第二步失败仅撤回与自己临时文件同一 inode 的产物，不删除竞争生产者文件。
10. 两个文件不能作为一个文件系统事务同时出现。进程崩溃可能留无 sidecar 的孤立候选；该文件不算完成，不得送注册工具。当前 Manifest 不识别这个闸门，因此不能自动扫描重算进行中的候选目录。E4 人工核实匹配 SHA 与完成标记后再登记。

只重算当前 API 定义的轨道派生字段；遇到额外未知的派生缓存不擅自删除，需先确认契约。保留原任务、资源不意味着当前物理模型使用了每个参数。

## 5. Provenance 与注册契约

输出结构示意（不是本轮生成的正式历史场景）：

```text
<独立候选目录>/Scenario_S1_epoch_fixed_v1.json
<独立候选目录>/provenance/Scenario_S1_epoch_fixed_v1.json.provenance.json
```

场景内部 scenario_id 保持源值 `Scenario_S1`。sidecar 包含由实际字节计算的 parent_scenario_sha256、scenario_sha256、legacy_static_sha256、static_data_sha256，原内部 source_scenario_id，以及复用原 Manifest 算法计算的 proposed registry_id（`s<星数>_m<任务数>_t<天数>d_<完整SHA>`）。physics 字段为 epoch_fixed_v1，解析器为 epoch_parser_v1；propagation_version 记录已安装 wrapper 版本，无法可靠获取时 null。注入假计算器必有 calculator_kind 标记且传播版本为 null。

base_git_sha 只记录基线 HEAD；仅当所有工具源码被 Git 跟踪且与 HEAD 一致时才填写 recompute_tool_git_sha。未提交/修改中的实现把该字段留 null，用 working-tree 文件 SHA 描述实际源码，不能伪称实现已在 HEAD 内。记录 Orekit 数据包 SHA，并在计算前后复核输入、源码、数据身份。结果 SHA 存在外部 sidecar，场景无自哈希循环。

核心字段示意（尖括号值必须由实际执行替换，不可照抄）：

```json
{
  "source_scenario_id": "Scenario_S1",
  "registry_id": "s1_m2_t0.00694444d_<full-sha>",
  "registry_id_status": "proposed_not_registered",
  "scenario_physics_version": "epoch_fixed_v1",
  "epoch_parser_version": "epoch_parser_v1",
  "propagation_version": "orekit-keplerian/orekit_jpype-13.1.5.0",
  "parent_scenario_sha256": "<sha-of-legacy-bytes>",
  "scenario_sha256": "<sha-of-candidate-bytes>",
  "legacy_static_sha256": "<same-static-sha>",
  "static_data_sha256": "<same-static-sha>",
  "provenance_status": "verified",
  "completion_status": "complete",
  "publication_status": "candidate_only",
  "formal_release_eligible": false,
  "physical_validation": {"status": "NOT_RUN", "reason": "requires independent E3 acceptance"},
  "scheduling_validation": {"status": "NOT_RUN"},
  "ground_station_status": "no_ground_station_configured"
}
```

verified 仅指本次重算的来源哈希关系、静态一致性及完成记录；不声称历史生成 provenance 已知。E2 每次输出仍为 candidate_only，独立小型测试通过不会自动将任意场景的 physical_validation 改成 PASS。真实场景仍须 E3/E4 按具体 SHA 验收，不能直接送正式 API。

## 6. 测试与实际命令

已执行：E1 23 项通过；E2 默认发现 44 项，43 项合成测试通过、1 项 Orekit 测试按默认策略跳过；原 Manifest 47 项通过。合成测试在独立临时目录验证输入字节/mtime/权限不变、全部静态字段不变、任务分母、通信、异常撤回、竞争文件不覆盖和来源哈希，并检查完成时间在场景发布及哈希核验后才生成、未提交工具不伪称基线 Git 版本。纯 Python 合计 113 项通过。没有全量 benchmark、真实调度或数据库操作。

小型 Orekit 测试已实际通过，含真实 E2 临时 bundle 重算/发布验证，不是空窗口比较：

| 项目 | 实际结果 |
|---|---|
| 数据 | tests/test_window_recompute.py 的固定合成 fixture；1 星，a=7000 km，e=0.001，i=28°，RAAN/argp/M=0；2 固定目标 (5°,125°)、(8°,135°) |
| 区间/参数 | 2025-11-18 12:00:00 UTC 起 600 秒；细步长 10 秒、粗步长 60 秒、仰角 5°；合成卫星三轴上限 180°。这些是测试静态输入，不改变生产默认模型。 |
| 日期 | 英文、2025-11-18T12:00:00Z、2025-11-18T20:00:00+08:00 |
| 参考系 | EME2000；ITRF / IERS2010 / simpleEOP=True；WGS84 |
| PV 比较点 | 起点后 0、300、600 秒，两参考系均比较；位置容差 1e-6 m、速度 1e-9 m/s；实际最大差 0 m、0 m/s |
| 窗口/姿态 | 2 个片段、102 个姿态样本；窗口时间与三轴姿态精确相等，容差/实际差均为 0 秒、0° |
| 环境 | Ubuntu 22.04 / Python 3.10.12；orekit_jpype 13.1.5.0；Java 25.0.2；Java 包 ImplementationVersion 返回 null，未猜测核心版本 |
| 耗时/数据加载 | 首次直接读取 DrvFS 数据包 303.357 秒；随后对相同 SHA 数据包的 Linux 临时副本测试 6.014 秒；最终源码身份记录调整后的复测 6.626 秒。无下载/安装，临时数据和 bundle 自动清理。 |
| 范围 | 等价日期、现有传播链和小型 E2 的一致性 PASS；Cesium、真实星历准确性、真实场景、调度计划及完整 E3/E4：NOT RUN |

实际固定数据 SHA（均由测试计算，未生成永久场景）：

```text
synthetic_source_sha256 = 79b1d29eb9f006755d321019260a19596f22f3a1a78f3e0de6cd064c09d6c9aa
synthetic_candidate_sha256 = c7bed3a3fb0970f4dd35faaa971c69e966eac39c224a49c78e0dd3ff13ee31c4
synthetic_static_sha256 = 2e7c52c046069dbfa6fc6058f16f8fcbf8948be4e405871321b934e8a5798eeb
orekit_data_sha256 = 1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985
```

可选测试打印 OREKIT_EPOCH_EVIDENCE JSON，包含 UTC 完成时间、容差、实际误差、参考系、版本与上述 SHA。第一次完成于 2026-10-15T16:52:22.039386+00:00；同数据临时副本复测完成于 2026-10-15T16:54:58.670521+00:00；最终复测完成于 2026-10-15T16:57:50.870592+00:00（北京时间均为 2026-10-16），均 PASS 且场景/静态 SHA 相同。Java 原生访问警告未导致失败；没有为消除警告修改现有环境。

```bash
cd /mnt/d/VC/EOS-Course-Project
/home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover -s tests -p 'test_epoch_parsing.py' -v
/home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover -s tests -p 'test_window_recompute.py' -v
/home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover -s tests -p 'test_scenario_manifest.py' -v
EOS_RUN_OREKIT_TESTS=1 /home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover -s tests -p 'test_window_recompute.py' -k OrekitEpochIntegrationTests -v
/home/meteor/eos-course-runtime/venv/bin/python -B scripts/recompute_scenario_windows.py --help
```

以下为实现后的调用示例，**本轮未对历史场景执行**。先由负责人冻结源文件并计算 SHA；独立候选目录和报告目录不得已有同名产物：

```bash
/home/meteor/eos-course-runtime/venv/bin/python -B scripts/recompute_scenario_windows.py \
  --scenario /mnt/d/eos-frozen/legacy/Scenario_S1.json \
  --out /mnt/d/eos-candidates/epoch_fixed_v1/Scenario_S1_epoch_fixed_v1.json \
  --preserve-static-data --no-resample \
  --expected-source-sha256 <实际冻结文件的64位SHA256> \
  --orekit-data /mnt/d/VC/EOS-Course-Project/utils/orekit-data.zip
```

内存评估通过后才可增加 `--max-input-mib`。正式候选登记前人工核对 sidecar 的字节 SHA、静态一致性、完成状态、实际物理与调度验收。后续人工调用（本轮未执行）：

```bash
/home/meteor/eos-course-runtime/venv/bin/python -B scripts/build_scenario_manifest.py \
  --scenario-dir /mnt/d/eos-candidates/epoch_fixed_v1 \
  --out-dir /mnt/d/eos-reports/epoch_fixed_v1
```

当前 Manifest 不传播 sidecar 新字段；保持 sidecar 与原注册报告并存，李泽同确认扩展后再接 API/RunConfig。不能把普通 Manifest 的 PASS/WARN 当成 E3 完成。

实际 `--help` 输出：

```text
usage: recompute_scenario_windows.py [-h] --scenario SCENARIO --out OUT
                                     --preserve-static-data --no-resample
                                     [--expected-source-sha256 EXPECTED_SOURCE_SHA256]
                                     [--orekit-data OREKIT_DATA]
                                     [--max-input-mib MAX_INPUT_MIB]

Recompute a frozen legacy scenario into an unpublished E2 candidate bundle.
Only observation_windows and communication_windows are replaced. The JSON is
the source of truth; calculator objects are disposable projections, not
default Satellite constructors or Scenario.export_to_json round trips. A
provenance sidecar is the final completion marker. E3/E4 acceptance remains
external.

options:
  -h, --help            show this help message and exit
  --scenario SCENARIO   completed, frozen legacy JSON (read only)
  --out OUT             new epoch_fixed_v1.json in an independent directory
  --preserve-static-data
                        require exact static JSON invariance
  --no-resample         keep zero-window tasks and their coordinates
  --expected-source-sha256 EXPECTED_SOURCE_SHA256
                        optional externally frozen input SHA-256
  --orekit-data OREKIT_DATA
                        existing orekit-data.zip; never downloaded
  --max-input-mib MAX_INPUT_MIB
                        in-memory input size limit (default: 64 MiB)
```

## 7. E3–E5 验收与成员交接

| 工作包 / 负责人 | 具体文件、契约、验证 |
|---|---|
| E3 梁兆榮 / 系统集成 | `draw/orekit_to_czml.py::demo` 接共享时间解析，偏移用 astimezone；`eos_system/orbit_generate.py` 与 `visualization.py` 冻结同一时间、参考系、数据版本。用相同 SHA 场景在至少三个 UTC 时刻比较传播/Cesium 位置，记录 m、m/s、角度及窗口边界容差。缓存键需包含场景 SHA、epoch_parser_version、propagation_version 和步长，旧缓存隔离。 |
| E4 刘懋兴 / 李泽同 | 冻结完整 Legacy；按源 SHA 识别 affected/unknown，重建至新目录；登记完整 SHA、静态哈希、覆盖率/窗口变化及 provenance。当前工具未扩展 Manifest 字段，需审核兼容方案。新基线、A/B/C/D 使用同一修复场景/约束/指标版本/预算，全部创建新 run，不复用旧指标。 |
| E4 机器学习 D | 受旧窗口/角度影响的特征和标签重新生成、审查训练来源；按独立母场景分训练/验证/测试，Legacy/修复对必须同组，不能泄漏。未受影响也需证据，不能假定。 |
| E5 李泽同 / 何明涛 / 梁兆榮 | Controller 启动、Worker 加载及核验前绑定新 registry_id、SHA；历史 run/plan/metrics 保持原 SHA。现有 IPC 不扩展 run_id/attempt/seq、双 Pipe、取消/超时或回收状态机；按 W2 独立分支回归。设计 v0.3 默认无业务表迁移，所需配置快照与 UI 来源展示由负责人实现并测试。 |

当前模型验证的是既有开普勒传播、地面仰角阈值、TargetPointing Euler 限制及离散窗口；调度核验另属 verification。未验证真实星历精度、摄像机固定安装/FOV、首次任务初始姿态、四元数最短转向、真实射频链路/天气/地面站资源等。comm=0 且无地面站只代表未配置。不得把 Change P 混入修复。

历史场景若由缺陷解析器读入英文日期产生，其派生窗口应重建；未知生成版本/数据不足的文件先标 unknown，不伪装可恢复。旧随机 ensure 已改变过的最终任务坐标作为冻结实验输入保留，本工具不能恢复当年的首次随机抽样。所有参与新物理数据比较的调度结果必须重跑；旧结果作为 legacy 保留。

## 8. 修改范围、提交与 PR 草稿

本轮仅修改/新增以下 9 个允许文件：utils/time_parsing.py、utils/visibility.py、main_generate.py、scripts/recompute_scenario_windows.py、tests/test_epoch_parsing.py、tests/test_window_recompute.py、docs/phase2/epoch_fix_implementation.md、docs/phase2/scenario_experiment_protocol.md、COURSE_SETUP.md。现有文件局部修改；COURSE_SETUP 顶部插入记录。原始 input 与 Legacy 场景未写入，未重建真实档案。合成输入有前后字节证据；真实档案未打开，不能声称本轮逐文件完成了新的哈希核验，Git 受保护路径无修改。

建议人工拆分提交，Codex 未执行 add/commit/push：

```text
fix(orbit): parse satellite epochs deterministically
feat(scenarios): recompute visibility windows from immutable inputs
```

PR 1 标题：`fix(orbit): parse satellite epochs deterministically`

> Legacy English-month epochs previously fell back to wall-clock UTC and changed orbital phase. Add a locale-independent UTC parser, preserve existing valid timestamp formats, fail with satellite context, and validate epochs before generator pool submission. Validation: 23 pure Python tests; no propagation model or scanning changes.

PR 2 标题：`feat(scenarios): recompute visibility windows from immutable inputs`

> Add a standalone frozen-scenario recomputation tool with resampling disabled, full static-data hashes, immutable legacy inputs, and no-overwrite candidate publication with provenance. Reject unsupported custom/multiple sensors instead of changing identities. Validation: 43 synthetic tests, 47 manifest regressions, and one opt-in Orekit integration test. Formal scenario registration, E3/Cesium acceptance and scheduling reruns remain follow-up work.

最终只读检查命令为 git status --short、git diff --stat、git diff --check；新增文件另列，因为未暂存文件不会进入普通 diff --stat。未改变 Git 分支、索引、提交或 LFS 配置。

最终工作区检查：仅下列 9 个允许文件，范围校验 PASS；新增文件尾空白检查 PASS；git diff --check 无输出；受保护 input / experiments/scenarios 的 git diff --name-only 无输出。旧文件中未修改行的原有空白没有批量整理。

```text
 M COURSE_SETUP.md
 M docs/phase2/scenario_experiment_protocol.md
 M main_generate.py
 M utils/visibility.py
?? docs/phase2/epoch_fix_implementation.md
?? scripts/recompute_scenario_windows.py
?? tests/test_epoch_parsing.py
?? tests/test_window_recompute.py
?? utils/time_parsing.py

 COURSE_SETUP.md                             | 10 +++++++
 docs/phase2/scenario_experiment_protocol.md | 19 +++++++++++++
 main_generate.py                            |  8 ++++--
 utils/visibility.py                         | 42 +++++------------------------
 4 files changed, 41 insertions(+), 38 deletions(-)
```
