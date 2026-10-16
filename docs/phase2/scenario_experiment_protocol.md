# EOS-Bench 场景审计、注册与成对实验协议

审计日期：2026-10-15。负责人边界：刘懋兴负责数据准备、来源分组和实验协议；公共 API、Controller、数据库及算法注册变更交李泽同或对应负责人确认。

本次只读源码审计基于工作区 `main`、HEAD `7597539ef6a5f25764e6a145b31fa517140f9d83`。这只是**审计代码版本**，不是历史场景生成版本。未打开、扫描或复制 `output/`，未执行生成器、调度器、Benchmark、Orekit/JVM、ML 训练。仅实现独立脚本、合成测试和文档；未建立新分支或 worktree，未提交。

用户指定的 `team_collaboration.md` 在当前 `docs/phase2/` 中不存在。参考现有 [框架交接](framework_handoff.md)、[算法接入](algorithm_integration.md)、[已实现数据库](database_current_v02.md)。交接文档通常要求成员分支；本次按用户明确要求留在当前工作区。`interface_design_target.md`、`database_design_target.md` 的目标设计不能代替当前代码。

## 1. 只读审计结论

以下行号指本次审计时的未修改源码。路径均相对仓库根目录。

### 1.1 已确认事实：输入、场景与时间

| 主题 | 代码证据与结论 |
|---|---|
| 原始卫星输入 | `main_generate.py:125 build_satellites_from_json`；少量只读样本 `input/10_satellites.json`。对象键为卫星 ID，值为 `[轨道类别, a, e, i, argument_of_perigee, RAAN, mean_anomaly, epoch]`；是六根数加历元，不是完整位置/速度/初始姿态状态。 |
| 单位 | `core/models.py:85 OrbitalParameters`、`utils/visibility.py:478 _extract_orbit_params`：a 为 km，e 无量纲，四个角为度；传播前 a×1000 转 m，角转弧度。样本历元为 `18 Nov 2025 12:00:00.000`。 |
| 场景起点 | `main_generate.py:290` 固定 `creation_time=datetime(2025,11,18,12,0,0)`，作为仿真起点，不是实际文件创建时间；duration 单位秒，当前生成 time_step=1 s。工具使用文件实际值，不假设所有历史场景均为 1 s。 |
| 顶层 Schema | `core/scenario.py:338 export_to_json`：`scenario_id`、`scenario_type`、`metadata`、`satellites`、`missions`；有地面站才导出 `ground_stations`，有通信窗口才导出 `communication_windows`；`include_windows=True` 导出 `observation_windows`。`mission_info` 没有被导出。 |
| 静态对象 | `core/models.py:330,402,428`：卫星、任务、地面站均为对象列表，以 `id` 识别；传感器在 `observation_capability.sensors[]`，用 `sensor_id`。卫星还有轨道、平台资源、机动与通信能力；任务含经纬度/高度、priority、`observation_requirement.duration_s`。重复列表 ID 会被调度加载器覆盖，审计工具将其判为 FAIL。 |
| 窗口层级 | `core/scenario.py:363`：观测外层为 `{satellite_id,sensor_id,mission_id,time_windows:[...]}`，通信外层为 `{satellite_id,ground_station_id,time_windows:[...]}`。内层包含起止时间、orbit_number 和可选姿态。一个任务可以有多颗卫星候选，每一对又可有多个时间片段。外层数不等于片段数，更不等于完成任务数。 |
| 加载契约 | `schedulers/scenario_loader.py:202 load_scheduling_problem_from_json` 必须读取 `metadata.creation_time` 与 `metadata.duration`；其他集合缺失按空列表，内部 ID 缺失按文件 stem，time_step 缺失按 1 s。工具不强迫旧场景新增四元数、FOV、初始姿态等字段；缺省信息按 WARN 记录。 |
| 时间约定 | `utils/visibility.py:44 _to_utc` 将 naive datetime 视作 UTC；加载器 `:128 _parse_iso_time` 将 aware 时间转 UTC 再移除 tzinfo，naive 原值不变。工具按加载器比较时间，展示起止时间保留原始时区表示；没有时区的旧场景不擅自加 `Z`。 |

### 1.2 已确认事实：分布、随机性与导出

- `main_generate.py:59 RANDOM_MISSION_INFOS`、`core/scenario.py:393 generate_missions_dict`：dist0 在纬度 [-80,80]、经度 [-180,180] 分别均匀抽样，并不是球面等面积均匀分布。dist1 等概率选择五个经纬度矩形之一，再在矩形内抽样；它是多区域分布，不是按区域面积加权，也不是高斯聚类。纬度区间之一写为 `[10,-30]`，`random.uniform` 允许反向端点。
- 五区分别为纬度/经度：`[20,40]/[70,130]`、`[35,65]/[-10,60]`、`[20,60]/[-125,-60]`、`[10,-30]/[-80,-30]`、`[-30,-10]/[110,155]`。初始坐标保留 6 位小数，重采样保留 4 位。任务优先级在 1–10、时长在 5–15 s 内随机取整数；目标文件模式也随机生成优先级与时长。
- `main_generate.py:365 run_all_scenarios`：随机任务模式启用 `ensure_each_mission_has_window=True`，目标文件模式关闭。`utils/visibility.py:681–784` 为无窗口任务重新采样位置，默认最多尝试 50 次，达到上限仍保留无窗口任务。因此 ensure 是有限重试策略，不保证 100% 覆盖；它也会改变最终任务分布，不能把最终坐标当作未经筛选的原始抽样。
- 生成链使用 Python 全局 `random`；本次查看的生成、任务生成、可见性模块没有 NumPy 随机调用，也没有可用的 `--seed` 参数或每任务种子派生。不能把调度器的稳定种子函数、其他切分脚本的种子或 `PYTHONHASHSEED` 当成生成种子。
- `ProcessPoolExecutor` 的各工作进程有独立缓存与随机状态，未记录或明确初始化任务级随机状态；进程启动方式、工作分配也未冻结。仅在父进程调用一次 `random.seed()` 不足以证明整个多进程生成可复现。
- `main_generate.py:435,464` 从每批计数 1 生成 `Scenario_S{n}`，不仅可能有 S1、S2，批次组合多时还会继续增加；不同规模分开运行可能复用相同内部 ID。`:322` 文件名含内部 ID、星数、任务数、天数和分布/目标标签；同名同参数重跑可能覆盖旧文件。
- `core/scenario.py:384` 直接 `open(filename,"w")` 后 `json.dump`，没有临时文件和原子重命名。正在写入的最终文件不能登记。汇总记录中的耗时在 `export_to_json` 之前计算，不包含最终 JSON 导出耗时，不能当作完整端到端生成时间。

### 1.3 已确认事实：姿态与镜头模型

- `utils/visibility.py:145 _OrekitContext.create`：惯性参考系 EME2000；地固系 ITRF / IERS 2010；WGS84 地球。轨道使用 `KeplerianOrbit` 与 `KeplerianPropagator`，目标地固坐标转到惯性系。
- `compute_visibility_and_attitude(:227)` 使用 Orekit `TargetPointing(ctx.inertial,target_geo,ctx.earth)`，从 `state.getAttitude().getRotation()` 按 `ZYX`、`FRAME_TRANSFORM` 取 yaw/pitch/roll，再转换为度。它们来自目标指向姿态，不是单独冻结的随机初始整星姿态。更细的机体系轴向/正负号语义仍应在后续物理模型设计时明确核实，不能直接等同于“相对天底的独立三个偏转角”。
- `eval_full(:300)` 先检查地面仰角，再检查三个绝对 Euler 角上限；离轴角虽被计算，却没有用传感器 FOV 做视场覆盖判断。`main_generate.py:144` 确实设置 FOV=45°，但可见性调用没有使用它，也没有显式固定安装矩阵或光轴配置。不能描述成“完全没有 FOV 字段”，也不能据此声称已实现固定镜头覆盖。
- `_build_time_windows_from_visible_attitudes(:564)` 生成三个等长数组 `agile_data.*_angles`；`non_agile_data.*_angle` 取每个数组的中间样本，是代表姿态。后者不是另一个轨道传播结果，也不是冻结的初始姿态。
- 细采样步长来自场景 time_step。窗口可能在首个不可见采样点关闭，也可能截到场景末端；构建数组包含末端附近的可见点（容差 1 μs）。因此时长/步长与样本数可能是半开端点或含末点两种口径；工具允许对应数量，不简单强制 `n=duration/step+1`。明显不匹配给 WARN，不凭旧采样差异一律拒绝。
- `schedulers/constraint_model.py:408` 对敏捷候选从选中位置切片 `ceil(duration/step)` 个样本；非敏捷只选窗口中间、按步长对齐的执行片段，携带代表姿态。
- `schedulers/transition_utils.py:81,163` 支持 plural 角数组及旧版 roll/pitch/yaw、gamma/pi/psi、记录列表等形式。`delta_g_between` 使用上一任务末样本和下一任务首样本的 `|Δroll|+|Δpitch|+|Δyaw|`，没有角度 wrap-around 或四元数最短旋转处理。
- `ConstraintModel._transition_time_s(:235)`：非敏捷按配置常量（默认 10 s），敏捷按 Δg 和 agility profile 分段计算；Δg≤10° 为 11.66 s，角度解析失败也回退 11.66 s。该常量不能保证对未知姿态保守可行。`is_feasible_assignment(:288)` 检查已有计划间转向，没有首次任务对冻结初始姿态的检查；实现遍历其他同星任务，不只是注释所称的相邻对。
- `eos_system/verification.py:37 verify_candidate` 另行核对来源哈希、窗口、步长、资源、任务唯一性、共享约束，并在末尾拒绝敏捷相邻转向无法解析的计划。独立注册工具不替代这个核验器。

### 1.4 已识别风险

| 风险 | 代码依据、影响与本次处理 |
|---|---|
| 历元静默回退 | 样本的英文月份历元不匹配 `utils/visibility.py:496 _parse_epoch` 的 ISO 和四种格式；失败后回退 `datetime.now(UTC)`。可能影响轨道位置及同参数重跑结果。未加载正式数据或启动 Orekit 验证其实际影响；不修改运行中的源码。 |
| 粗采样参数命名 | `coarse_step_min` 实际用 `timedelta(seconds=coarse_step)`，默认 60 表示秒。粗扫可能漏掉短几何窗口，边界精度待独立验证，不能从“窗口存在”推出精确物理覆盖。 |
| 内部 ID 与文件名复用 | 跨批次内部 ID 相同合法但有歧义；同名导出覆盖。工具按完整字节哈希登记，跨文件同内部 ID 或同名不同内容给 WARN。 |
| 加载器静默接受/丢弃 | 引用不存在的卫星/任务/地面站时跳过，end≤start 时跳过，重复列表 ID 被覆盖，缺资源值可能默认为无限制/零消耗。工具显式报引用、重复 ID、时间与非法数值问题。零容量仍按兼容含义允许，不擅自改约束。 |
| 旧姿态可解析不等于物理正确 | 缺姿态可能触发固定时间回退；代表姿态的 singular 字段本身不是敏捷转向提取器支持的 plural 数组，但非敏捷转向原本走常量分支。工具审查格式/数值，对缺失与旧表示提示；不宣称完成姿态物理核验。 |
| 历史来源不足 | 导出没有自动保存原始输入路径、生成 seed、生成代码 commit、ensure 设置。文件名分布标签仅是线索，不能证明来源或随机独立性。 |

### 1.5 待验证事项

正式 10/20/50/100 星文件的完整性、实际 Schema、覆盖率、哈希和来源均未在本次读取；用户报告的生成状态不等于工具 PASS。未验证运行中的进程是否使用当前源码版本，也没有检查其进度。Orekit 在固定输入、固定历元、固定数据包和版本下的数值/字节确定性尚未实验确认；不得把数值传播通常可重复推导为整个生成流程完全可复现。

固定光轴方向、机体系定义、安装变换、Euler 奇异点、初始姿态可达性与真实 FOV 覆盖需要后续物理设计和小型验证。本次不实现四元数转向、视锥或新约束。

## 2. 当前已实现的场景登记边界

`eos_system/config.py:41 sha256_file` 已实现 1 MiB 分块哈希。`:73 list_scenarios_in` 只列已登记目录的直接 JSON 子文件，返回 `source_id / scenario_id=filename.stem / name / sha256`，跳过符号链接；`:85 resolve_scenario_in` 按文件 stem 解析真实路径和边界。旧 `main_scheduler.py:95` 则递归发现 `output/Scenario_*.json`，按文件路径加载；载入后 problem.scenario_id 仍是 JSON 内部 ID。

`eos_system/api.py:74,85,122` 已有场景列表、数据源登记和实验提交，并非只有设计稿。SQLite `data_sources` 保存 source_id/name/root_path；`runs` 保存来源 ID、文件名式 scenario_id、sha256，`config_json` 保存 scenario_path 和运行配置（见 `storage.py:247 enqueue`）。没有完整的场景谱系表，也没有本工具 manifest 的导入 API。原有 `source_id` 是数据源目录标识，不能等同于训练独立性分组 `source_group_id`。

本工具只输出文件清单，不写 API、SQLite 或 Controller。交接时保留映射：

```text
registry_id ↔ 完整 sha256 ↔ source_path / filename
                              ↘ API source_id + filename.stem
internal_scenario_id 单独保存，不能作跨批次全局主键
```

## 3. 独立工具使用与统计契约

入口：[build_scenario_manifest.py](../../scripts/build_scenario_manifest.py)。Python 3.10+，不导入生成器、调度器或任何 JVM 模块。用户明确指定专用的**已完成归档目录**，脚本只读直接 `*.json` 子项、不递归；可重复 `--scenario-dir` 合并多处归档。不要把日志或其他 JSON 报告放进待登记目录。

工具一直拒绝项目 `input/`、`output/` 及其后代，也拒绝可能覆盖它们的祖先目录；源文件符号链接拒绝读取。目录路径展开、规范化、解析符号链接后再次检查保护边界。报告目录必须与输入目录互不包含，不能写入保护目录。现存三份同名报告一律拒绝覆盖，重跑请换新报告目录。目录报错/空目录返回 2；单文件 FAIL 返回 1；全部 PASS/WARN 返回 0。WARN 需要人工审核，退出 0 不表示历史来源或物理可行性已获确认。

### 3.1 身份与来源

注册 ID 为 `s<星数>_m<任务数>_t<天数>d_<完整SHA-256>`。分布没有进入主键，因为当前生成器未在 JSON 保存它，仅靠改名不应改变内容身份。完整哈希保存在独立字段，发现同注册 ID 对应不同哈希时对所有冲突项 FAIL，并从成功清单剔除。字节相同的多个文件共享注册 ID，但保留每个来源路径并给重复内容 WARN；`unique_registry_count` 与 `registered_file_count` 分开报告。

同文件名不同内容（多归档目录合并时）给 WARN，两个不同哈希均保留，不用文件名覆盖记录。相同内部 ID 跨规模复用给 WARN，并不自动判非法。格式化空白改变也会改变字节 SHA-256 和注册 ID；这是不可变文件快照身份，不是语义去重。跨多次报告的变化请比较完整哈希；工具没有持久化注册数据库，不宣称发现未提供给本次运行的历史冲突。

`generator_version / generator_seed / source_dataset / source_group_id` 只读取文件已有的 `metadata.extra` 同名声明，并附 `provenance_evidence`。它们是文件内声明，不是工具对历史事实的独立认证。缺失为 JSON null / CSV 空单元格并 WARN，不由当前 HEAD、文件 mtime 或文件名猜测。分布先读取 `metadata.extra.distribution_type` 或顶层同名字段，否则仅提取文件名 dist0/dist1 标签，并标 `filename only; unverified`；无法确定就为空。母场景或原始数据来源由 source_dataset 承载已记录信息，来源家族由 source_group_id 承载；未知必须留空。

### 3.2 字段与口径

| 字段组 | 含义 |
|---|---|
| registry_id、internal_scenario_id、filename、source_path | 分别是内容注册 ID、JSON 内部 ID、文件名、本次来源绝对路径 |
| sha256、file_size_bytes | 两次完整读取一致的字节摘要和大小；读取失败不发布成功身份 |
| satellite_count、mission_count | 实体列表中的唯一有效 ID 数；列表 ID 重复已 FAIL，不能据此当合法场景统计 |
| duration_days、start_time、end_time、time_step_s | metadata.duration / 86400，原始起点及推导终点，场景步长；窗口步长优先于外层步长，再回退场景步长 |
| observation_entry_count | 观测外层列表条目数，包括零片段条目 |
| observation_segment_count | 所有内层 time_windows 元素数；失败报告里的此数可能包含无效片段，不应拿去做实验 |
| missions_with_windows | 至少有一段引用有效、位于场景内、start<end、长度足够容纳正任务时长且步长有效的任务数；按任务去重 |
| window_coverage_ratio | 上述任务数 / 任务总数；空任务集记 0 并 WARN |
| communication_window_count | 内层通信片段数，另有 communication_entry_count 保存外层数 |
| distribution_type、distribution_evidence | 分布声明/文件名线索及其证据级别 |
| validation_status | PASS / WARN / FAIL；只有前两类进入 manifest |
| generator_version、generator_seed、source_dataset、source_group_id | 可提取的来源声明，未记录为空；provenance_evidence 说明声明来源 |
| parser_mode | ijson-outer-item 或 stdlib-bounded，明确实际解析路径 |

覆盖率只表示基础时间机会，不检查多任务竞争、转向、下传、每轨资源或固定镜头视场，不能等同任务可完成率。姿态缺失但时间窗口有效时仍可计入机会覆盖，同时 WARN；不是把它计为已完成任务。

### 3.3 验证等级和读取限制

- PASS：本工具覆盖的当前数据结构、引用、数值与时间检查通过；不是正式计划可行性结论。
- WARN：缺少内部 ID/旧版可选集合/步长记录、来源未记录、姿态部分缺失、旧角度表示、样本数量与时间不吻合、无窗口任务或重复身份线索等。
- FAIL：无法完整解析、重复 JSON 键/实体 ID、列表/对象结构错误、必需 metadata 无效、坏引用、非有限/非法数值、逆序或越界窗口、角数组长度冲突、读取变化、注册 ID 冲突等。

检查记录含 check、level、reason、file、field；窗口 field 含序号和任务/卫星引用。每文件最多保留 1000 条详细问题，剩余条数写 suppressed_checks；最高严重等级不会被截断。失败项保存在 `scenario_validation_report.json.results`，registry_id 为空，不进入两个 manifest。CSV 与 JSON 来自同一 records 列表。未知未来字段不会被要求出现；对未知字段内的非有限 JSON 数字仍拒绝。

每文件进行两次完整顺序读取：第一遍提取小型实体/元数据，第二遍审查窗口，支持顶层字段任意顺序；每遍随读取分块 SHA-256，并比较读取前后的路径 stat、打开描述符 fstat（大小、mtime_ns、ctime_ns、设备和 inode），再比较两遍完整哈希和属性。读取异常、截断或变化均 FAIL。它需要约两遍文件 I/O，不是单遍扫描。

有 `ijson>=3.3` 时按顶层数组的**一个外层条目**构建对象后释放；内存主要为实体索引、最大外层窗口条目（含其姿态数组）、小型统计与有上限的问题列表，不是整文件窗口全集。未知的单个顶层对象、极端巨大的单条窗口仍可能占较多内存；这不是逐角度事件的固定内存保证，未做数百 MB 压测。无 ijson 时只接受不超过 16 MiB 的文件，使用标准库有界整文件解析，存在文本/对象内存开销；超限直接 FAIL，说明需要使用已有含 ijson 的环境，绝不自动安装。当前 WSL 环境已有 ijson。

**两次大小/mtime 一致，甚至两次哈希一致，也不能严格证明生产者已结束。** 生产者可能暂停后续写入，恶意路径并发替换也不属于该脚本的安全隔离保证。使用生成完成后的不可变归档/快照和受控目录权限。三份报告用排他创建防覆盖，但不是跨三文件事务；磁盘写入失败可能留下部分报告，返回 2，保留现场并改用新目录重跑，不把部分文件交接为完整结果。无大文件复制、自动归档或清理行为。

## 4. 场景矩阵与来源记录

以下“当前状态”来自用户任务说明，**未经本次正式文件验证**；每组通常有 dist0、dist1。

| 分组 | 星数 | 任务数 | 跨度 | 用途 | 用户报告状态 |
|---|---:|---:|---:|---|---|
| S0 | 10 | 20 | 1 天 | 系统功能验证 | 已生成 |
| S1 | 20 | 20 | 1 天 | 小规模基线 | 已生成 |
| S2 | 50 | 100 | 3 天 | 中规模主要比较 | 已生成 |
| S3 | 100 | 200 | 3 天 | 规模扩展 | 正在生成 |
| S4 | 200 | 500 | 3 天 | 可选压力测试 | 尚未生成 |

这里 S0–S4 是实验分组，不等于 JSON 的 Scenario_S1/S2。分组登记时同时记录星数、任务数、跨度、两层观测窗口数、机会覆盖率。进一步的难度分析应在生成结束后单独设计：任务时间窗重叠/竞争、候选卫星交集、每任务候选片段数分布、任务时长密度与每轨资源压力。星数增加可能提供更多机会，也可能使组合空间变大；任务数、窗口数或规模不能单独证明场景更难。本工具不执行大规模重叠矩阵计算。

已知当前命令（本次没有执行）：

```bash
python main_generate.py --sat_files 100_satellites --missions 200 --days 3 --workers 2
```

由源码可知它选择 `input/100_satellites.json`、两种随机分布、ensure=True；实际文件、完成日志和最终哈希仍待生成结束后核对。其他规模的准确历史命令、种子、生成版本、机器和耗时若没有日志均为“未记录”，不能由规模倒推成已执行命令。每份归档的外部来源记录至少包括：原始输入文件及其哈希、派生文件及哈希、准确命令、分布/跨度/ensure、生成代码版本及未提交修改、种子策略、开始/结束时间、耗时口径、Python/Java/Orekit 与数据包版本、worker 数。已有 Scenario 不补写这些猜测字段。

## 5. 基线与成对实验协议

### 5.1 算法接入的实际状态

| 算法 | 代码/旧工厂 ID | 当前 HTTP 注册 | 启动、结果与核验状态 |
|---|---|---|---|
| MIP | algorithms/mip.py；`mip`（别名 milp） | 未注册 | 本次不运行；PuLP 和具体 solver 可用性待核实 |
| SA | algorithms/meta_sa.py；`sa` | 未注册 | 本次不运行；不能把源码存在记为启动成功 |
| Profit First | algorithms/heuristics.py；`profit_first` | 未注册 | 本次不运行，旧 CLI 工厂支持 |
| GA | algorithms/meta_ga.py；`ga` | 未注册 | 本次不运行 |
| ACO | algorithms/meta_aco.py；`aco` | 未注册 | 本次不运行 |
| 当前系统基线 | `completion_first`、`adaptive_repair` | 已注册，均为 baseline-1 | COURSE_SETUP 中有历史框架验证记录；不代表当前矩阵全部复现成功 |

依据：`algorithms/factory.py:38 create_algorithm` 与 `eos_system/algorithm_registry.py:106 _SPECS`。旧 CLI 工厂可创建与 HTTP 算法注册是两个概念，新增 HTTP 登记须由负责人集成。本次不调用旧 CLI，因为它会扫描 output。

`main_scheduler.py:621–642` 对 class_id=1 用 `_sat_count_from_scenario_name(:78)` 解析文件名 `Sats(\d+)`，仅当能解析且 >20 时写 SKIP 并不提交 MIP 作业；不是根据实际 JSON 星数进行的全局限制，名字不匹配时不会触发此门槛。`algorithms/mip.py:189 MIPConfig` 默认 solver time_limit_sec=3600，必须记录实际生效配置，不能以默认值冒充同预算实验。

状态按独立阶段保存：SOURCE_PRESENT → REGISTERED（注明旧工厂或 HTTP）→ STARTED → RESULT_PRODUCED → VERIFIED。`[RUN]` 只证明作业尝试开始；`[SKIP]` 是未执行，不是失败，也不能填零指标当成功样本。另分开记录超时有候选、超时无候选、依赖缺失、求解错误、核验拒绝；MIP 有可行结果但未证最优时记录 solver status/gap/预算，不称全局最优。

### 5.2 每次运行必须保存的记录

| 类别 | 必填内容 |
|---|---|
| 算法 | ID、版本、源码 commit、完整配置参数（含默认值和私有参数）、入口（CLI/HTTP） |
| 输入 | registry_id、完整 SHA-256、filename、API source_id（如有）、任务集合及 source_group_id |
| 模型与目标 | 约束版本、agility_profile、placement_mode、非敏捷转向时间、下传比例、资源口径、目标权重及归一化规则 |
| 随机性与预算 | 显式 seed、Python/NumPy/框架种子策略、搜索时间预算、实际 RT、迭代参数、并发度/线程数、超时策略 |
| 环境 | Git commit 和工作区修改摘要、机器 CPU/内存、OS/WSL、Python、依赖与 solver 版本 |
| 结果 | run_id、运行状态、输出路径和 SHA-256、TP/TCR/BD/TM/RT、完成数、solver gap（若有）、核验状态和核验器版本 |

同一次比较固定 Scenario 字节哈希、任务集合、约束、目标、预算、环境和公共核验标准。目标不同必须分组并明确解释；Greedy 类的隐含优先规则也应写清，不能仅因为传入同一权重就称完全相同目标优化。不同预算必须标注，算法预算不支持统一硬限时的旧入口不得隐瞒。

随机算法使用预先约定的多个 seed，在相同场景/seed 对上比较，报告每次结果及均值、离散程度/置信区间；失败、跳过、无结果单列，不混入成功均值的零值样本。多个独立场景也须成对。若某算法的 seed 由文件名派生（旧 CLI `_stable_seed(:89)` 使用场景名和算法名的 MD5），改名会改变种子，应冻结并显式记录实际 seed，不能只说“默认种子相同”。本次只制定协议，不运行全量 Benchmark。

### 5.3 指标公式与比较

设 N 为总任务数、p_i 为 priority、x_i 为是否完成、T 为场景秒数、t_s 为场景开始、L_s 为各卫星观测时长之和、R 为全部任务需求时长之和。

| 指标 | 当前公式/实现 | 比较原则 |
|---|---|---|
| TP | `evaluation_metrics.py:41`：Σ p_i x_i，按任务 ID 去重 | 越大越好；不是完成任务数；ObjectiveModel 的 profit_score 另按总 priority 归一化 |
| TCR | `:56`：已完成的唯一任务数 / N；N=0 返回 0 | 越大越好；不是窗口利用率，也不是本工具的机会覆盖率 |
| BD | `balance_utils.py:33`：clip(1−Σ\|L_s−mean(L)\|/(2R),0,1)；无卫星或 R≤0 返回 0 | 越大表示相对负载更均衡；不是按任务数的 Jain 指数。R>0 时空计划也可能得 1，必须结合 TCR 解读 |
| TM | `timeliness_utils.py:16`：已完成任务累计 max(0,start_i−t_s)，未完成每项累计 T，最后除以 T×N；N≤0 或 T≤0 返回 0 | 越小越好；优化目标里用的是 `1−TM`，不要把二者混为同方向指标 |
| RT | `evaluation_metrics.py:95` 接收运行秒数；旧 CLI `main_scheduler.py:270–315` 包围 engine.run/search；新入口 `eos_system/runner.py:37` 包围 solver.solve | 算法求解计时（适配器可能含初始计划构造），不含加载、核验、导出或轨道生成；不是完整请求延迟 |

指标实现与 `algorithms/objectives.py` 的 BD/TM 共用辅助函数；TP 原始值与目标归一化 profit_score、TM 与 timeliness_score 的含义不同。历史文档中的 RT/成功数值仅代表当时记录，不自动推广到本矩阵。发现其他公式/文档差异应记录并交负责人，不改测评代码。

## 6. ML 数据划分与未来姿态场景

ML D 的训练/验证/测试必须以可证实的来源家族分组。相同母场景的时间切片、不同 seed 的初始姿态变体、相同任务轨迹的派生样本不能随意跨训练/测试集再声称独立泛化；先按 source_group_id 分家族，再在家族层面划分。若来源未知就保留 null，并注明“独立性未证实”，不能仅因 SHA 不同就认定独立。模型权重哈希、训练数据清单哈希、划分 seed 与策略也需冻结；本次不训练。

未来关系（仅需求规划，不创建或修改场景字段）：

```text
原始卫星输入 → Legacy Scenario → 记录母场景 SHA-256
  → 冻结初始姿态快照 → 整星旋转与固定镜头配置
  → Attitude-aware Scenario → 新约束下 Baseline 与 A/B/C/D 成对实验
```

未来增强场景需明确：母场景 registry_id/SHA-256；姿态模型版本；初始姿态快照 ID/SHA-256；姿态随机种子及参考时刻；固定镜头 sensor profile 和安装方向/变换；机体系、光轴、参考系和四元数约定；FOV；最大转向速度与稳定时间；约束模型版本。还应确认单位、相机姿态相对整星姿态的关系、姿态插值与采样规范。

增强文件独立保存并计算新哈希，保留母子关系和同一来源家族，绝不覆盖旧 JSON。一旦新约束改变可行性，所有参与比较的基线须在同一增强场景、同一新约束下重新运行。旧结果可保留为旧模型参考，不能混作同条件比较。谱系字段落在哪个 Scenario 版本或外部注册契约，由物理模型负责人和李泽同共同确定；本次工具没有给旧场景注入这些新字段。

## 7. 生成全部结束后的人工操作指南

**以下是将来由用户执行的步骤，本次未读取 output，也未复制任何正式场景。**

1. 在原生成终端确认命令自然返回 shell 提示符；不要发送停止信号。最终 `All scenario calculations finished` 只表示所有 future 已返回，可能包含失败，不能单凭该行判全部成功。
2. 生成结束后再检查原终端日志及本批 summary：每个预计场景应有 `[OK]` 和汇总表记录，没有未处理的 `[ERR]` / failed；将两个分布逐个与实际命令配对。当前运行的终端和日志不可由本脚本轮询。
3. 此时才确认明确列出的文件为普通文件、生成端不再持有写入、大小/mtime 稳定。完整 JSON 和 Schema 由归档后工具检查；零字节或明显截断不归档为成功。stat 稳定不是生产者结束证明，必须结合终端返回与日志。
4. 选择新的归档目录和精确文件名列表，不使用递归扫描或笼统的 `output/*`。在生成已结束、无写入者时先计算源 SHA-256，再使用禁止覆盖的复制操作复制指定文件，核对归档副本 SHA-256 与源摘要相同。保留源文件及日志，不移动、不删除、不重命名源场景。归档后设置受控只读权限或快照；若有同名不同内容，用独立归档子目录和多次 `--scenario-dir`，不要覆盖。
5. 保留每批日志、实际生成命令及来源记录；历史未记录字段明确空缺。不自动把当前 HEAD 回填为历史生成版本。
6. 使用现有 WSL 环境对已完成归档进行登记，报告写到新的独立目录。下方命令不启动调度或 JVM；必须在归档存在且完成后执行。

```bash
cd /mnt/d/VC/EOS-Course-Project
PY=/home/meteor/eos-course-runtime/venv/bin/python
REPORT_DIR="$(mktemp -d /tmp/eos-scenario-manifest-report.XXXXXX)"
"$PY" -B scripts/build_scenario_manifest.py \
  --scenario-dir experiments/scenarios \
  --out-dir "$REPORT_DIR"
printf 'Report directory: %s\n' "$REPORT_DIR"
```

若归档按批次子目录存放（工具不递归），显式枚举目录：

```bash
"$PY" -B scripts/build_scenario_manifest.py \
  --scenario-dir /absolute/completed/S0 \
  --scenario-dir /absolute/completed/S1 \
  --out-dir /tmp/eos-manifest-new-report
```

7. 先看验证报告中的每文件 status/checks，再看 CSV/JSON。可用下方只读命令汇总；不要只看退出码，WARN 要逐条确认。FAIL 文件不会出现在 manifest 中，不可用缺行当“无需实验”。

```bash
"$PY" -m json.tool "$REPORT_DIR/scenario_validation_report.json"
head -n 3 "$REPORT_DIR/scenario_manifest.csv"
"$PY" -m json.tool "$REPORT_DIR/scenario_manifest.json"
```

8. 将三份报告、来源记录、已完成归档的只读路径及 `registry_id → API source_id/filename.stem` 映射交给 Controller/API 负责人；报告放在归档目录之外，避免现有 API 把报告 JSON 误列为场景。现有 API 可以登记归档数据源，但不会自动导入本 manifest；完整 registry_id、验证报告、生成种子/版本、source_group_id 与母子谱系接入需李泽同确认，不能直接向数据库塞字段。
9. 未来增强场景沿同一内容身份体系登记新 SHA，同时在经确认的谱系契约中关联母场景和姿态快照；所有比较重新冻结场景和约束。

## 8. 本次验收证据与未覆盖范围

只运行新测试文件，输入输出全部由 `tempfile.TemporaryDirectory()` 人工构造；路径保护测试把保护根替换成临时目录，不接触真实 input/output/experiments/scenarios。未执行全量测试。现有 WSL Python 3.10.12 + ijson 的测试命令：

```bash
/home/meteor/eos-course-runtime/venv/bin/python -B -m unittest discover \
  -s tests -p 'test_scenario_manifest.py' -v
```

WSL 验收：47 项通过，0 失败、0 跳过；包含 ijson 流式与标准库有界回退。补充尝试 Windows Anaconda Python 3.13.5（无 ijson）时，沙箱临时目录创建子目录/清理被 ACL 拒绝，47 项均在 fixture 准备阶段报错（含清理错误共 94 条），未验证 Windows 原生运行；不把这次环境阻断记为通过，也不改系统权限或安装依赖。正式验收环境为上述 WSL 虚拟环境。

覆盖正常场景、完整哈希稳定性、两层窗口、任务去重、跨规模内部 ID、内容注册 ID/改名、缺字段、非法/尾随 JSON、时间范围、卫星/任务/传感器/地面站引用、无窗口、姿态缺失/部分缺失/数组长度/非有限值、数值与资源、只读输入、CSV/JSON 一致性、目录隔离及符号链接、读取中/两遍间变化、重复内容、同名不同内容、强制注册冲突、I/O 故障、流式/有界回退一致性、CLI 退出码。详见 [测试文件](../../tests/test_scenario_manifest.py)。

实际 `--help` 输出：

```text
usage: build_scenario_manifest.py [-h] --scenario-dir SCENARIO_DIR --out-dir
                                  OUT_DIR

Audit and register completed EOS scenario archives (read-only, non-recursive).

options:
  -h, --help            show this help message and exit
  --scenario-dir SCENARIO_DIR
                        completed archive directory; reads direct *.json only;
                        repeat for multiple archives
  --out-dir OUT_DIR     separate report directory; refuses protected paths and
                        existing report files

Never scan running output/. No simulator/JVM imports. Exit: 0 PASS/WARN, 1
file FAIL, 2 usage/I/O error.
```

临时演示确实生成了 `scenario_manifest.csv`、`scenario_manifest.json`、`scenario_validation_report.json`，退出后只由该 TemporaryDirectory 清理自身。合成样本关键值如下（来源字段均为明确的测试声明，不是正式实验信息）：

| 字段 | 合成值 |
|---|---|
| internal_scenario_id | Scenario_S1 |
| filename / file_size_bytes | Scenario_synthetic.json / 1414 |
| sha256 | 225baa6a3c4a9898516467677e640ab780e1b524fe08481b43c4743c44253f12 |
| registry_id | s1_m1_t0.000694444d_225baa6a3c4a9898516467677e640ab780e1b524fe08481b43c4743c44253f12 |
| satellite_count / mission_count | 1 / 1 |
| start_time / end_time | 2025-11-18T12:00:00 / 2025-11-18T12:01:00 |
| time_step_s / duration_days | 2 / 0.0006944444444444445 |
| observation_entry_count / observation_segment_count | 1 / 2 |
| missions_with_windows / window_coverage_ratio | 1 / 1.0 |
| communication_entry_count / communication_window_count | 1 / 1 |
| validation_status / parser_mode | PASS / ijson-outer-item |
| generator_version / generator_seed | synthetic-v1 / 7 |
| source_dataset / source_group_id | unit-test-fixture / synthetic-family |

未覆盖：正式文件质量、数百 MB 内存/速度压力、恶意并发路径替换、生产者完成的强证明、轨道/姿态物理准确性、调度计划可行性、API/SQLite 导入、算法启动/结果/全量基线、ML 训练。它们不是本次合成 PASS 的推论。

建议提交信息（本次不提交）：

```text
feat(experiments): add reproducible scenario manifest and validation tooling
```
