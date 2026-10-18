# R1-02 Rebase 后证据身份兼容修复审计

日期：2026-10-17（Asia/Shanghai）。范围仅为 R1-02 的字节身份与历史证据定位；不实施 R1-03/R1-04，不注册、审批、发布或生成场景。

## 1. 工作树与修复前证据

- 工作目录：`D:/VC/EOS-Course-Project-registry`；分支：`feat/registry-provenance`。
- HEAD：`84dcef4d93e2c523a882568d0e20b5706458bba1`。
- `origin/main`：`f230c3b612cdd582a85fc3c524d9567a77cf7686`；包含于当前 HEAD。
- 开始前已执行 status、branch、log、worktree list、diff --stat；工作树干净，diff --stat 为空。未切换分支或修改其他工作树。
- `core.autocrlf=true`；修复前核心模块与数据库文档均为 Git `i/lf`、工作树 `w/crlf`。
- 指定 WSL 解释器重新执行真实 CLI，得到 **PASS 273 / WARN 28 / FAIL 2，退出码 1**。两个 FAIL 均为 FILE_IDENTITY_MISMATCH，分别绑定 `r1-02-checker-source`、`database-current`。完整输出保存为下述本机审核目录的 `before.json`，未只保存汇总。

## 2. 必须先通过的历史身份核对

修改前使用 Windows Git 子进程直接读取 `git show d0d9325:docs/phase2/database_current_v03.md` 的二进制 stdout，未经过 PowerShell 文本管道重编码。该 blob 为纯 LF、82 个换行；仅将 LF 转为 CRLF 后比较完整字节 SHA 和大小：

| 对象 | 完整 SHA-256 | 字节数 |
|---|---|---:|
| d0d9325 数据库文档 Git blob（LF） | `754ac5227b9d74e394cc2bacc0dae4f5559624863003a7aa43c722fab7cf79bb` | 6009 |
| 上述 blob 的 CRLF 签出字节 | `4b30f69358c610308e23817b35821a79879a18fbfb2388d21202427621408285` | 6091 |
| 原索引 database-current | `4b30f69358c610308e23817b35821a79879a18fbfb2388d21202427621408285` | 6091 |
| 新历史快照（保留 CRLF） | `4b30f69358c610308e23817b35821a79879a18fbfb2388d21202427621408285` | 6091 |
| 新 main/当前 HEAD 的数据库文档 blob（LF） | `b42cd57e22a5c0ada763a0949aa86d876678edf1161feba3f725f26fdceeb51e` | 6041 |
| 当前数据库文档工作树（CRLF；未修改） | `ff73b3d0989dfd1c1ee27d165be7bfc9e6eb275fc4b6433607d9e25615d84394` | 6123 |

**前置条件确实匹配后才修改。** 新 main 文档的更新行由程序 v0.3.2/旧实现分支变为 v0.3.3/fix/cesium-replay-usability，并说明不改变数据库模式。它已有真实版本差异，不能靠统一换行来冒充旧证据，也没有据此推断数据库实际发生迁移。

核心模块独立对照：

| 对象 | 完整 SHA-256 | 字节数 |
|---|---|---:|
| 修复前工作树（CRLF） | `937908feb52a38701a7f33e396dc0d7f31a8bc290c97b344f99f12f828d89b1b` | 21465 |
| HEAD blob / 原索引 / 修复后工作树（LF） | `d426781c03214e281a31cad7457aa50b649d2efca8a1af3acd926c9c9d2f125b` | 21099 |

## 3. 最小修复与身份语义

1. `.gitattributes` 只追加两个精确路径规则：核心模块 `text eol=lf`；历史快照 `-text whitespace=cr-at-eol`。前者固定源代码签出为已索引 LF，后者使历史 CRLF 字节原样进出 Git，空白检查识别其 CRLF 行尾。没有全仓库换行策略更改。
2. 新增 [`evidence/r1_02/d0d9325/database_current_v03.crlf.snapshot.md`](evidence/r1_02/d0d9325/database_current_v03.crlf.snapshot.md)，内容严格为前述旧 blob 的 CRLF 签出字节。没有补写标题、修复相对链接或修改历史内容；文件本身是历史证据，不是当前设计入口。
3. 索引仅改变 `database-current` 一个 evidence 节点：path/normalized_path 指向快照，original_path 仍为旧原始路径；原 id、role、SHA、大小与可靠性等级保持不变。新增 evidence_scope 标注历史范围，historical_source 记录完整旧提交、原路径、LF blob SHA/大小和 CRLF 签出策略。保留旧 id 是为保持既有引用兼容，**其名称不代表“当前版本”**；消费者必须读取历史范围及版本元数据。
4. 核心模块工作树只将 CRLF 还原为 LF，字节与 HEAD blob 相同，因此不产生模块内容的 Git 差异。review_tool_identity 和对应证据 SHA 均不改；生产源码身份、历史 base_git_sha 与当前主线身份没有混用。
5. 未增加“忽略换行后算同一身份”的分支。核验仍比较实际完整 SHA 和大小；历史快照若变为 LF、内容被替换或大小变化，测试要求 FILE_IDENTITY_MISMATCH/FAIL。

索引对象比较确认：除 database-current 的上述定位/历史说明外，其他所有字段保持一致；Raw 30、Scenario Artifact 10（六 Legacy、四 Candidate）、evidence 209、lineage_edges 10 的集合与计数不变。现有 LFS 两行逐行保持原样；真实 Git 属性测试确认 Scenario JSON 仍为 filter/diff/merge=lfs、-text，provenance JSON 仍为 -filter/diff/merge/text，新增路径不触发 LFS。

## 4. 测试与完整核验

WSL 环境：Ubuntu-22.04，用户 meteor，Python 3.10.12，`/home/meteor/eos-course-runtime/venv/bin/python`，ijson 3.6.0。从 `/mnt/d/VC/EOS-Course-Project-registry` 执行：

```bash
PY=/home/meteor/eos-course-runtime/venv/bin/python
"$PY" -B -m unittest discover -s tests -p 'test_scenario_artifact*.py' -v
"$PY" -B -m unittest discover -s tests -p 'test_scenario_manifest.py' -v
"$PY" -B scripts/verify_scenario_artifacts.py \
  --evidence-root epoch_acceptance=/home/meteor/eos-course-runtime/epoch-acceptance \
  --evidence-root e4_audit=/mnt/d/VC/EOS-Course-Project/docs/phase2/e4-review-20261017-124539 \
  --evidence-root reference_docs=/mnt/c/Users/流星/Downloads
```

| 检查 | 实际结果 | 退出码 |
|---|---|---:|
| 专项单测：既有 25 + 新增 6 | 31 PASS，0 FAIL，0 ERROR，0 SKIP | 0 |
| 受保护 Manifest 单测 | 47 PASS，0 FAIL，0 ERROR，0 SKIP | 0 |
| 修复前真实索引 | 273 PASS / 28 WARN / 2 FAIL | 1 |
| 修复后真实索引 | **275 PASS / 28 WARN / 0 FAIL；总体 WARN** | 0 |

新增测试覆盖：实际模块 LF/索引身份、历史快照完整 SHA/大小/旧 blob 版本、主线文档更新或移除不改变旧证据、误指新版同名文档失败、历史内容/换行/大小变动失败、原 LFS 规则。Windows 原生 Git 与 WSL Git 都在独立临时仓库以 core.autocrlf=true/false 执行实际 clean 写入 blob 与 checkout filters 读出，逐字节比较核心模块及快照；不在项目索引 staging，不创建提交。

Windows 补充测试使用 `D:/Anaconda/python.exe -B -m unittest discover -s tests -p test_scenario_artifact_identity.py -v`，最终 6 PASS、0 FAIL、0 SKIP、退出 0。早期运行在 Python 3.13 与 3.12.8 上，两个改写夹具测试曾因现有 stat/fstat ctime 保护得到 INVALID_INDEX，而非预期的 SHA 不符代码；原始失败日志保留。独立不可变负例夹具及明确的宿主时间戳探针用于隔离这一限制：若 stat/fstat 的 ctime 含义不一致，两个依赖核验器的测试显式 SKIP 并要求 WSL，其他字节/Git 属性测试仍执行。最终这次原生运行未发生跳过；它不证明该 Windows 元数据差异已获普遍修复。生产保护逻辑未放宽，真实索引核验仍以指定 WSL 为准。

28 条 WARN 的完整 level/category/code/subject/reason 按顺序比较，修复前后完全一致；scenario_details 也完全一致。分类仍为 HISTORICAL_FIELDS_UNKNOWN 10、DISTRIBUTION_FILENAME_ONLY 10、RAW_ORIGIN_NOT_VERIFIED 6、INTERNAL_ID_REUSE 2；不修改既有 [WARN 处置记录](r1-02_warn_disposition_20261017.md)。275 是具名检查通过数，不是场景数。

## 5. 本机输出与可追溯性

以下均是本机证据路径，不是仓库可移植依赖；测试/JSON/临时日志未放入 Git：

- WSL 审核目录：`/home/meteor/eos-course-runtime/epoch-acceptance/r1-02-rebase-identity-20261017T142904644210Z/`。
- 修复前完整 JSON：`before.json`，SHA `694e65a566da95d01d3c162336628839a2c9d5d9cca4658fc59d1128eca16fa2`，对应 `before.receipt.json` 保存真实命令、解释器、退出码及 FAIL 明细。
- 修复后完整 JSON：`final-verification.json`，SHA `d601f063c98498cb2884c1b3de3ce8b6c4624d01604c799ad488305fac94dce3`；与原 Rebase 前 275/28/0 的输出字节 SHA 相同。`final.receipt.json` 保存最终运行命令、退出码、日志 SHA、WARN/场景明细比较结果；final-artifact-tests / final-manifest-tests 的 stdout/stderr 同目录保存。
- Windows 系统临时目录：`C:/Users/流星/AppData/Local/Temp/eos-r1-02-rebase-kacwll29/`，保留 preflight.json、原索引/属性备份、范围检查、原生测试完整日志和退出码；早期失败未删除或替换为通过记录。

## 6. 变更清单、限制与人工审核

Git 内容修改：`.gitattributes`、`data/registry/scenario_artifacts.v1.json`、`COURSE_SETUP.md`。

新增：历史数据库快照、`tests/test_scenario_artifact_identity.py`、本文。核心模块工作树字节从 CRLF 恢复 LF，与 HEAD 一致，不计为逻辑源码修改；交付时 git status 仍显示该路径 M，但 git diff 对该路径没有内容差异，二进制比较也与 HEAD 完全相同，未用暂存操作刷新此标记。当前数据库设计文档、原索引其他节点、CSV、既有 WARN 文档和受保护 Manifest 源码未改。`git diff --check` 实际退出 0、无诊断；未跟踪新文件另以 no-index/check 检查，无空白错误。该独立比较使用命令级 core.safecrlf=false 关闭未入库普通文本的换行提示，不修改仓库配置或跳过空白检查；快照仍按路径属性保留 CRLF。

剩余限制：

- 历史数据库证据只认证 d0d9325 的指定签出字节；当前/后续主线文档不由该历史节点充当实时身份监控。后续需要引用新版时应明确建立新版身份，不能覆盖旧 SHA。
- Windows 既有 stat/fstat 元数据差异尚未作为生产代码修复；不得根据一次原生测试通过宣称完整核验器已获得所有 Windows 解释器支持。
- 28 WARN 的历史缺失、filename-only 分布/Raw 假设、内部 ID 复用及公共消费规则确认仍按原处置保留。完整 Raw 来源链、生产执行证明、ML lineage、审核签署均没有新增认证。
- 四冻结候选的 JSON/侧车、父场景、Raw、Legacy 与原始来源边未修改。四候选继续 candidate_only、formal_release_eligible=false；80 条原实际曝光继续 INCONCLUSIVE / NO_CONTINUITY_CERTIFICATE。哈希通过不构成连续曝光认证或正式发布批准。
- 本轮仅运行专项、Manifest、真实只读索引和字节策略检查，没有执行全量调度 benchmark、场景求解、重新生成或全仓库测试套件。

建议人工审核两条精确属性、历史字节推导与定位元数据、跨平台测试边界后，按限定范围接受本次身份兼容修复；不代签任何发布或来源完整性结论。未执行 git add、commit、push、merge 或创建 PR，完成后停止等待审核。
