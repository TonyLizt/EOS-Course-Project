# R2-C / I2：Assignment 来源窗口消歧与公共 Verifier 修复

日期：2026-10-18（Asia/Shanghai）。工作树 `D:/VC/EOS-Course-Project-i2`，分支 `fix/source-window-i2`，基线 `0a1a9418659be9d7b9e4dad90484ac2cd087c593`（CAABS Core PR #17）。开始前 status --short、diff --stat、staged diff 均空，branch/HEAD/log/worktree list已记录。未切分支，不修改其他工作树，不执行git add、commit、push、merge、rebase或创建PR。

本修复服务公共调度链路；I2专项及WSL本地等字节源码副本的默认完整回归通过，待人工审核。原Windows挂载路径的全量时序限制单独保留，不能声称该路径全量通过。来源一致性不等于连续曝光认证或发布批准。

独立审核P2的后续修复见第6节；第1–5节保留首轮实现及原始测试历史。第6节说明Loader必要的步长解析修正，首轮“Loader仅说明/逻辑不改”不再描述当前最终差异。

## 1. 实际根因与数据流

已阅读 Loader、Assignment/ConstraintModel、Candidate Pool、CAABS候选接线、schedule_output、Worker/Runner、两个Verifier、exporting、Storage和回放/前端消费代码，以及R1 I2反例和协作规范。

```text
Scenario JSON → Loader TaskWindow / CommWindow（分命名空间顺序编号）
  → 公共构造器 / Candidate Pool → Assignment（原本已有两类来源ID）
  → schedule_to_dict → Worker JSON / CLI JSON → Controller Verifier
  → 官方plan_json + assignment_json → JSON/CSV Export
  → JSON加载 → Verifier重新读取可信Scenario并恢复来源
```

原 schedule_output 不输出 sat_window_id/gs_window_id；两个Verifier均按卫星、传感器和时间包含过滤后取首项。Controller随后按首项窗口检查中心/姿态，合法窄窗口可被错误拒绝。CLI不使用显式ID，不检查来源轨道/姿态等完整语义，并丢失通信来源ID。原公共规划模型也没有完整检查圈号及通信引用。

## 2. 修复前后真实反例

合成非敏捷任务时长10秒，真实Loader产生窗口1 `[0,100)`、窗口2 `[10,20)`。公共构造器指定窗口2，公共模型接受，实际sat_window_id=2。没有调用四冻结候选或大型求解器。

| 观察项 | 修复前真实结果 | 修复后 |
|---|---|---|
| 观测输出 | sat_window_id缺失 | 保留2 |
| Controller来源重建 | 错选1，报“非敏捷卫星任务不在窗口中心：M” | 正确通过来源检查，到达原认证调用边界 |
| CLI普通核验 | 合法任务通过，但忽略来源身份 | 合法来源通过，仍标为DISCRETE_ONLY |
| 伪造sat_window_id=999999 | CLI接受1条 | UNKNOWN_SAT_WINDOW_ID，拒绝 |
| 历史无ID、完整语义唯一 | 取宽窗口导致错误拒绝 | 依据中心/姿态等唯一恢复来源2 |
| 同时间、同属性、不同ID，无显式来源 | 默取首项 | 歧义拒绝 |

Windows独立证据目录：`C:/Users/流星/AppData/Local/Temp/eos-i2-20261018-359047ceed9b4b60b25b99988ca5f97c/`；WSL对应 `/mnt/c/Users/流星/AppData/Local/Temp/eos-i2-20261018-359047ceed9b4b60b25b99988ca5f97c/`。

`repro-before/result.json` 保存未修改代码的实际现象。原始合成Scenario完整SHA为 `db5c46b77d267f6c8901de6d233134e84abf733d166a4cfc72cd0d16f29d917c`，计划SHA为 `cf6e220878e9fba14c52044273b46fbd5d15e6fe72485795b9f4403f45beffb7`；输入未覆盖。after使用相同几何的独立新夹具，生成记录绑定新部署，SHA与before不同，不冒充同一字节身份。

`unchanged-original-replay.json` 另外读取原before文件：结构来源正确恢复为2，原三份文件SHA全部保持；原规划证据绑定旧源码，正式核验保留 INCONCLUSIVE / UNTRUSTED_WINDOW_PROVENANCE，不把历史证据重标为当前部署认证。

`baseline-python/` 是Git HEAD原Python源码的独立副本，叠加两项新回归断言。baseline-tests.json记录真实退出1、1 FAIL/1 ERROR：CLI没有拒绝伪造ID；输出缺失sat_window_id。修复后的对应测试通过。不是修改当前基线制造循环或来源故障。

after诊断仅把最终certify_schedule调用替换为明确INCONCLUSIVE哨兵，以证明已通过来源检查且没有运行真实物理认证；没有替换Loader、来源匹配或共享约束。正向Storage/导出单测的最终证书注入均明确标为UNIT_TEST_INJECTION_ONLY。

## 3. 身份契约与最小实现

完整定义见 [公共来源契约审查稿](../assignment_source_window_contract_v1.md)。采用已有字段，不扩展Assignment dataclass：编号只在可信Scenario快照及各自命名空间内唯一。原JSON的自报窗口ID不作为Loader身份。

- 新增 `schedulers/source_windows.py`：一次核验建立来源索引；显式正整数ID必须存在且唯一，核对归属、执行范围、轨道、对齐、非敏捷中心、姿态和资源；通信同样核对来源及配置长度。
- 两个Verifier调用同一重建逻辑。显式无效ID不退回时间搜索；历史字段缺失才允许完整语义下的唯一匹配，歧义拒绝。
- `schedule_output.py` 保留两类ID；`exporting.py` 的CSV增加ID及圈号，JSON自然保留完整计划。没有新增CSV计划导入器。
- 公共ConstraintModel补齐来源中心/对齐、圈号及通信身份检查，保留既有姿态/转向解析约定；正式Verifier仍独立比较来源姿态和传感器归属。
- Loader仅增加真实编号语义说明，不改变计数、过滤或时间解析实现。
- `certification_identity.SOURCE_NAMES` 纳入新模块；CLI审计源码摘要也纳入该文件。连续认证函数、证据等级、Controller门禁和正式入库条件不改。

未知/伪造/错归属/越界、重复加载身份、历史歧义有明确错误原因。两来源所有可核验属性相同时，合法显式引用可指向任一真实记录；不能由自报JSON证明生成器当初的内部选择。完整来源认证、生成历史与连续物理证明仍是不同命题。

## 4. 回归和环境证据

解释器 `/home/meteor/eos-course-runtime/venv/bin/python`，Ubuntu-22.04 / WSL，Python3.10.12、Pydantic2.14.1；工作目录 `/mnt/d/VC/EOS-Course-Project-i2`，禁写pyc、MPLBACKEND=Agg。

实际执行由审核目录run_tests.py逐模块使用独立Python `-B -c` 进程，调用unittest discover/TextTestRunner并保存完整argv、环境、stdout/stderr、真实退出码和结构化数量。完整默认套件由full_suite.py执行同一发现入口，所有测试日志外置，不加入Git。脚本完整命令及结果在对应receipt JSON中。

先行专项：I2新增31/31、Core48/48、连续流水线17/17、认证身份P1回归40/40，各退出0；最终源码的完整套件再次覆盖并通过这些方法。新增测试覆盖任务/卫星/传感器错引、圈号及类型、窗口ID交换/伪造、同时间双ID、微秒越界、中心/步长/姿态、地面站来源/时长、历史唯一/歧义、JSON→SQLite→Export→Import→Verifier、CSV身份、实际Completion/Adaptive/CAABS及Candidate Pool输出。

中间失败原样保留：首轮I2测试26/27，1微秒对齐负例落在旧索引容差内，已将负例改为2微秒，生产规则没有因此收紧。首轮连续流水线16/17，诊断记录显示原3秒认证预算超时。测试改用独立WSL本地ZIP副本后17/17通过，未更改任何期限、Controller或证书规则。

数据副本 `/home/meteor/eos-course-runtime/audits/i2-validation-20261018-woyie6cm/orekit-data.zip`，与原ZIP完整SHA同为 `1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`，大小19,865,526字节。代码仍来自实际Windows工作树；没有换用另一份源码。此为测试I/O配置，不是实际物理认证。

完整默认回归结果如下，不删除失败尝试：

| 实际运行 | RUN | PASS | FAIL | ERROR | SKIP | 退出码 |
|---|---:|---:|---:|---:|---:|---:|
| 原Windows挂载代码路径首轮 | 465 | 429 | 28 | 0 | 8 | 1 |
| 最终源码等字节WSL本地副本 | 465 | 457 | 0 | 0 | 8 | 0 |

首轮两项Adaptive失败是本次规划层提前要求SensorSpec引入的兼容回归，已去掉该过度限制；没有更改旧算法或旧测试夹具，Verifier仍完整检查真实传感器归属。其余26项停机/IPC失败包含WORKER_STARTUP_TIMEOUT、未到达预期子进程/消息路径等；没有修改Controller、时限或测试断言来规避。

最终运行目录 `/home/meteor/eos-course-runtime/audits/i2-reviewed-source-20261018-0hev7xa2`，native-snapshot.json对278个复制文件逐一校验完整SHA和大小，生产及测试Python与最终实际工作树等字节。Scenario目录只读引用原目录，没有复制、生成或改写冻结场景。代码副本、原ZIP及测试期限均未做放宽；native-final.json保留完整输出、真实退出0及138.38秒用时。源码路径变化使不同运行的部署路径/数据身份不能混称同一实例；该结果证明同字节程序在此环境通过，不把原路径失败改标为通过。26项路径相关时序限制未逐项以未修改基线证明为历史问题，保留供系统负责人处置。

8个SKIP均为原有真实Orekit opt-in：曝光1项、E3/E4 3项、轨道导出1项、轨道插值2项、重算集成1项。本轮未启用这些物理验收。

原工作树最终专项：I2 31/31、Core48/48、Adaptive3/3，共82/82，各退出0，见mounted-final-summary.json。该结果也直接确认规划兼容修正，没有修改旧测试。源码、差异及保护范围最终回执见delivery-check.json和包含全部未跟踪文件的review.diff；git diff --check退出0，五个新增文件独立空白检查无诊断。15份保护源码/属性文件核对通过，Assignment/Schedule/TimePlacementStrategy的AST未变，Loader逻辑AST未变，认证身份模块只新增来源依赖项。

## 5. 影响与审核边界

修改生产文件：schedule_output.py、constraint_model.py、scenario_loader.py（仅说明）、eos_system/verification.py、eos_system/exporting.py、utils/certification_identity.py、verify_schedules.py；新增source_windows.py和test_source_window_identity.py。同步公共算法接入、框架、接口目标说明、COURSE_SETUP和本文，新增来源契约及独立PR草稿。

Assignment字段和solve签名不改；Worker/Controller协议、API路由/请求、SQLite结构、I1 Registry、CAABS全部搜索源码及冻结Scenario/Raw/Legacy/Candidate/Sidecar不改。计划JSON增加已有来源键，CSV增列；严格外部消费端需确认。SQLite已有plan_json/assignment_json保存额外字段，不做数据迁移或历史回写。计划摘要包含新增字段，不能重用旧签署或缓存身份。

审核期间远端main前进到 `5e37ba720a9222a70d834d84e96c740601a3d236`，为I1 PR #18的合并提交，父提交0a1a941和1d5306f。本轮只读取该不可变对象，没有更新本地origin/main或当前HEAD，没有Merge/Rebase。远端相对本基线的9项变更包含I1契约/登记、测试和文档；与本次待提交路径交集为COURSE_SETUP.md和algorithm_integration.md，生产代码没有双方修改同文件。整合时仍须人工处理文档语义，不能直接覆盖I1记录。

在独立临时副本 `/home/meteor/eos-course-runtime/audits/i2-with-main-5e37-20261018-*` 中，直接读取该main的4份Python原文件（CAABS、共用Solver契约、Registry、I1测试）与I2源码组合测试，**没有执行Git merge**。combo-summary.json保存来源提交、逐文件SHA及运行位置：Registry17/17、I2 31/31、Core48/48、Adaptive3/3，共99/99、各退出0。此有限组合检查不是新main上的全量验收，不自动更新本分支基线。

I1/I2正式整合后须重新验证实际提交的完整链路；本分支本身没有登记CAABS，直接构造Solver的单测不冒充I1登记证据。CLI保留默认约束配置，非默认配置用可信RunConfig核验。本轮没有启动真实Orekit opt-in、大场景重算、全调度benchmark或正式发布。

待李泽同确认公共契约、兼容拒绝策略、CSV消费端及源码身份部署/重启影响；何明涛确认Worker来源字段往返。人工审核与实际物理认证未完成，所有冻结候选原状态不变。独立 [PR草稿](caabs_i2_source_window_pr_draft_20261018.md) 尚未创建。

## 6. 独立审核两项P2修复（2026-10-18）

本轮继续使用原工作树、fix/source-window-i2、HEAD `0a1a9418659be9d7b9e4dad90484ac2cd087c593`；保留已有未提交I2变更，不暂存、提交、推送、Merge/Rebase或创建PR。独立审核报告在 `C:/Users/流星/AppData/Local/Temp/eos-i2-independent-review-20261018-11484c2db7ff483b891c3cf380c433e1/i2_independent_review_20261018.md`。

本轮独立证据目录为 `C:/Users/流星/AppData/Local/Temp/eos-i2-p2-20261018-23c33b97e58f4bb9ad2468810d27ff2b/`，WSL对应 `/mnt/c/Users/流星/AppData/Local/Temp/eos-i2-p2-20261018-23c33b97e58f4bb9ad2468810d27ff2b/`。initial.json及before-source保留起始branch/HEAD/status/log/worktree/stat/staged、原Python文件SHA和全部已有未提交文件原文，不以HEAD覆盖既有修改。

### 6.1 修复前后反例

| 项目 | 本轮修复前实际结果 | 修复后实际结果 |
|---|---|---|
| P2-1：同一直接aware UTC Assignment | `TypeError: can't compare offset-naive and offset-aware datetimes`，未捕获的诊断子进程退出1。 | 同一输入文件字节，返回feasible=true，诊断子进程退出0。 |
| P2-2：窗口显式time_step=0 | CLI返回1；正式Verifier报 `ExposureStatus.ERROR: INVALID_OR_MISMATCHED_SCAN_STEP`。 | 两入口均报 `SAT_WINDOW_SOURCE_MISMATCH`，在原认证调用前拒绝。 |
| 同类全局配置time_step=0 | Loader吞成1秒，CLI接受；正式路径直到后续物理检查才拒绝。 | Loader保留0，来源解析拒绝；两个入口均在来源阶段拒绝。 |

`capture.py before/after`分别在独立子进程调用p2_probe.py，before/after-reproduction.json保存完整argv、实际cwd/解释器、stdout、stderr、堆栈与真实退出码。各probe目录保留完整输入、Scenario、计划、配置和结果。两个zero诊断的包装进程退出0表示成功记录两个入口的返回/异常，不表示该非法计划通过；aware诊断保留真实未捕获异常退出1及修复后退出0。

额外global-zero修复前探针确实触及原认证器，实际为 `REJECTED / NONVISIBLE_EXPOSURE_START`，没有证书；其原输出中的统一NOT_RUN标签不准确，另存diagnostic-label-clarification.json校正，未改写原始日志。窗口级zero及修复后zero均在认证前拒绝。本轮没有用该诊断签发物理证书或验收真实候选。

aware输入前后完全相同；zero计划内容前后相同，但新合成Scenario的生成记录绑定当前部署，源码变化使Scenario完整SHA不同。不得将其说成历史文件被重标；原始输入均保留，各完整SHA由最终证据清单记录。

### 6.2 最小实现和不变量

- `schedulers/constraint_model.py`：增加私有 `_normalize_assignment_times`，复用 `utils.time_parsing.parse_orbit_epoch`，先转换UTC再移除tzinfo。仅对带时区值用dataclasses.replace构造局部副本；原本naive路径不复制。公共可行性、离散检查入口及参与卫星/地面站冲突比较的既有Assignment均归一，不改写调用方对象。
- `schedulers/source_windows.py`：删除step的真假值缺省；已解析来源必须为有限正数、整数微秒。此为既有planning_window步长条件在共同来源层的落实，不更改连续物理规则、中心算法、`1e-6`索引容差或半开区间。
- `schedulers/scenario_loader.py`：全局缺失/None的原1秒缺省改为显式None判断，显式0保留用于拒绝；避免bool经float变成有效步长，对窗口/分组未解析null明确报错。保留原窗口/分组键缺失继承和原UTC解析、窗口遍历、过滤及编号行为。首轮“Loader仅文档”范围因此有必要修正。
- 新增 `tests/test_source_window_p2.py`，不修改旧测试夹具或放宽旧断言。不改Assignment dataclass、Solver/Registry、CAABS核心、Controller、SQLite、连续认证或冻结场景。

来源身份仍为 `(可信Scenario SHA, observation/communication, Loader ordinal)`；显式无效ID不回退，历史无ID仍须唯一，时间与资源仍由可信Scenario独立核对。新增UTC归一和非法步长拒绝没有产生新的来源身份或历史认证例外。全局缺失/None默认1秒与已解析TaskWindow为None的非法状态明确区分。

### 6.3 回归覆盖与原始证据

新15项方法覆盖：naive/aware UTC、+08/-05等价时间和错误丢偏移反例；混合端点、原调用方对象不变；来源/Scenario时域的微秒越界、反向/零/短曝光；旧1e-6对齐容差；同星既有计划混合时区、半开端点相接及1微秒重叠；跨星同地面站通信冲突、下传严格晚于观测和来源边界。

步长覆盖全局/分组/窗口三级0、负数、NaN/±Inf、非整数微秒、布尔；历史无ID不能回退；缺省和全局None仍通过，已解析None/非法文本拒绝；合法0.5/1/2秒均经两个入口通过。正向正式导出/认证生命周期仍仅使用原有UNIT_TEST_INJECTION_ONLY最终签署注入；负向测试断言原认证函数未被调用。

修复前新增15项的实际退出码1：12个失败方法、3个通过方法，包含11个FAIL条目和11个ERROR条目（子测试可重复归属同一方法）。初始采集器直接减去子项条数导致不正确的负通过数，原回执不删除，p2-before-corrected-counts.json按父方法去重校正。之后采集器同时记录失败方法数与断言/异常条数；未放宽测试，另补布尔子项。修复后实际挂载路径15/15通过、退出0。

解释器仍为 `/home/meteor/eos-course-runtime/venv/bin/python`，Ubuntu-22.04/WSL2、Python3.10.12、Pydantic2.14.1，`-B` / PYTHONDONTWRITEBYTECODE=1、MPLBACKEND=Agg；EOS_OREKIT_DATA使用前述同SHA的WSL独立数据副本。原始ZIP保持只读。

每组命令通过 `run_tests.py <label> <实际运行目录> <test_pattern>`执行；内部argv使用独立Python `-B -c`、unittest discover('tests',pattern=...)及TextTestRunner(verbosity=2)。完整argv、环境、运行目录、数量、耗时和退出码在每个label.json，完整stdout/stderr另外保留。原始挂载路径28条失败和8项opt-in跳过证据保持第4节原状，不以本轮WSL副本结果替代其结论。

### 6.4 本轮实际最终结果

| 运行位置及范围 | RUN | PASS | FAIL/ERROR | SKIP | 退出码 |
|---|---:|---:|---:|---:|---:|
| 实际Windows挂载工作树，新P2 | 15 | 15 | 0/0 | 0 | 0 |
| 同一工作树，原I2来源专项 | 31 | 31 | 0/0 | 0 | 0 |
| 同一工作树，CAABS Core | 48 | 48 | 0/0 | 0 | 0 |
| 同一工作树，Adaptive | 3 | 3 | 0/0 | 0 | 0 |
| 同一工作树，连续曝光边界 | 15 | 14 | 0/0 | 1 | 0 |
| 同一工作树，连续流水线 | 17 | 17 | 0/0 | 0 | 0 |
| 同一工作树，认证身份P1回归 | 40 | 40 | 0/0 | 0 | 0 |
| 等字节WSL本地副本，完整默认套件 | 480 | 472 | 0/0 | 8 | 0 |
| 独立main/I1文件组合，Registry | 17 | 17 | 0/0 | 0 | 0 |
| 同一文件组合，I2及P2 | 46 | 46 | 0/0 | 0 | 0 |
| 同一文件组合，Core | 48 | 48 | 0/0 | 0 | 0 |
| 同一文件组合，Adaptive | 3 | 3 | 0/0 | 0 | 0 |

默认完整套件实际运行目录 `/home/meteor/eos-course-runtime/audits/i2-p2-source-20261018-szez81bd`，耗时142.99秒，包含原47项Manifest及其他公共/HTTP/进程/数据库回归。native-source-snapshot.json保存逐文件SHA及大小、只读场景链接和数据SHA，validation-final.json确认实际工作树Python与测试副本仍一致，数据ZIP未改。8项SKIP仍为真实Orekit opt-in（曝光1、E3/E4 3、轨道导出1、插值2、重算1），完整方法名和原因在native-full.json，不算通过。本轮未重跑挂载路径的完整480项，不能宣称该路径26条未决进程/时序失败已经消失。

命令示例（WSL中执行，完整argv以各JSON回执为准）：

```bash
/home/meteor/eos-course-runtime/venv/bin/python -B /mnt/c/Users/流星/AppData/Local/Temp/eos-i2-p2-20261018-23c33b97e58f4bb9ad2468810d27ff2b/run_tests.py p2-after-tests /mnt/d/VC/EOS-Course-Project-i2 test_source_window_p2.py
/home/meteor/eos-course-runtime/venv/bin/python -B /mnt/c/Users/流星/AppData/Local/Temp/eos-i2-p2-20261018-23c33b97e58f4bb9ad2468810d27ff2b/run_tests.py native-full /home/meteor/eos-course-runtime/audits/i2-p2-source-20261018-szez81bd 'test*.py'
```

上述为本轮已执行命令的引用；回执标签及路径属于本机证据，不是可移植输入路径，勿覆盖现有日志。validate.py记录完整分组执行顺序与源码副本建立方式。

### 6.5 交付范围及集成评估

本轮相对原未提交I2状态只改8个文件：

| 文件 | 本轮原因/位置 |
|---|---|
| `schedulers/constraint_model.py:292` | UTC副本归一；入口302/343行、既有计划比较369/412行。 |
| `schedulers/source_windows.py:37` | 来源有效步长，不再真假值回退。 |
| `schedulers/scenario_loader.py:214` | 步长数值解析；245行显式None缺省、338行窗口解析。 |
| `tests/test_source_window_p2.py:28` | UTC直接Assignment 8项；138行起步长7项。 |
| `docs/phase2/assignment_source_window_contract_v1.md` | 说明UTC副本及None/0/分辨率语义。 |
| 本报告 | 第6节保留复现、实际结果及历史限制。 |
| `caabs_i2_source_window_pr_draft_20261018.md` | 更新最终修复行为与当前验证。 |
| `COURSE_SETUP.md` | 本轮版本记录，保留首轮记录。 |

delivery-check.json和p2-only.diff记录相对开始时已有未提交代码的真实差异，不把全部I2历史改动误称本轮新增。Assignment/Schedule/TimePlacementStrategy AST未变；公共可行性和离散约束方法去除新增归一调用后，其判断逻辑AST与修复前相同；SourceWindowIndex类本身及原31项测试未变。其他起始已跟踪Python、.gitattributes和受保护范围保持原字节。git diff --check退出0，新文件无行尾空白。

多次 `git ls-remote origin refs/heads/main` 均为 `5e37ba720a9222a70d834d84e96c740601a3d236`；本地origin/main仍0a1a941，不混为最新远端。与新main共同修改仍只有COURSE_SETUP和algorithm_integration，两者集成时保留I1中立Solver契约说明及I2记录；生产文件无共同改动。没有自动Merge/Rebase。

临时组合目录 `/home/meteor/eos-course-runtime/audits/i2-p2-main-overlay-7aqf_68q` 取新main的CAABS、solver_contracts、Registry和I1测试四份原始blob，main-overlay.json保存完整SHA。114/114通过，包含独立进程registry-first/algorithm-first、参数校验、真实公共Solver构造及来源回放；这不是正式Git集成版本的完整回归。正式整理分支后，仍需在实际提交上重跑完整HTTP→Worker→Verifier→SQLite→Export与认证/取消/超时回归。

**P2-1 RESOLVED；P2-2 RESOLVED，等待人工复审。** 未修改连续物理规则、证据等级或发布门禁；来源一致、离散通过、严格连续认证、正式发布资格仍分别判断。原28条失败、物理opt-in未运行、公共契约/CSV消费端确认和实际集成验收仍保留为限制，不能用两个P2修复冒充其完成。所有候选及实际曝光认证状态保持原状。
