# IMPORT_AND_VERIFY — 两条交接路线

## 先决条件

建议WSL Ubuntu22.04、Python3.10、Java17及项目既有依赖。真实版本在 generation/tools/artifacts/environment_record.json（Git为scripts/hmt_scene_handoff/artifacts）。先审核平台依赖，再装 requirements-system/course 等；requirements-record.txt是发送方版本记录，不是跨平台一键安装保证。不要安装模型大文件以验证前四算法。

ZIP解压后设定：

```bash
cd /your/path/EOS_Scenarios_Handoff_20261028
export HANDOFF="$PWD"
export PROJECT="$HANDOFF/baseline_runtime"
export SCENES="$HANDOFF/scenarios"
export TOOL="$HANDOFF/generation/tools"
export PY=/path/to/your/python3.10
sha256sum -c SHA256SUMS
"$PY" -B "$TOOL/cli.py" verify --project "$PROJECT" --scenarios "$SCENES" --require-runtime --report /tmp/handoff-loader.json
```

以上离线检查不访问8910，不调用Solver/Controller/Verifier，不重新建库；五份原Bundle分别由原Loader与原Registry读取。校验报告的physical_validation=NOT_EXECUTED_THIS_HANDOFF是正确状态，原采样结果在validation和各Bundle。

## GitHub路线

```bash
git clone --branch feat/hmt-scenes-10-30-20261028 --single-branch https://github.com/TonyLizt/EOS-Course-Project.git
cd EOS-Course-Project
"$PY" -B scripts/hmt_scene_handoff/cli.py verify
```

四份场景可由Git BASE的原Loader结构读取；runtime字段会明确RUNTIME_PREREQUISITE_REQUIRED。**这不是科学运行ready。** 不要跳过此门禁。使用已验收的场景前运行代码，或ZIP中单独标注的baseline_runtime，并显式 `--project /path/to/baseline_runtime`。ZIP里这些216份既有WIP差异未混入场景Git分支，详见BASELINE_AND_DIFF及依赖清单。不要用新分支覆盖正在使用的脏工作树。

## 接入接收方原成熟Web（显式未来操作，本次未启动新服务）

选择接收方**全新**Runtime和空闲端口，例如8920；不连接发送方8910，不复制在线SQLite。保留原UI和factory：

```bash
"$PY" -B "$TOOL/serve_original.py" --project "$PROJECT" --scenarios "$SCENES" --runtime "$HOME/eos-handoff-new" --port 8920 --workers 1
```

在另一个终端显式登记（已有相同root复用，不重复注册）：

```bash
"$PY" -B "$TOOL/cli.py" register --project "$PROJECT" --scenarios "$SCENES" --url http://127.0.0.1:8920
curl http://127.0.0.1:8920/api/health
curl http://127.0.0.1:8920/api/data-sources
```

打开 http://127.0.0.1:8920/ 原工作台；选择新数据源、R30-main-01、FCFS/EDF/RABAS/CAABS；查看实验管理、结果比较、Gantt和导出。发送方现8910已有真实实验，最佳截图见docs/R30_score_comparison.png。若要恢复4Worker，启动参数显式--workers4；默认1更节省接收方资源。停止用该终端Ctrl+C，等待Worker回收；重启需按原系统运行目录恢复流程，便携启动器为防覆写默认只接收新Runtime。

原GUI默认目标不保证等价于历史Score-v2；14条精确请求在results/compare_*/protocol.json，含模型/版本/种子/参数和实际场景SHA。历史receipt路径指向发送方仅作为审计，包内对应原件按run_id提供，不要求访问发送方路径。不要用历史run_id/idempotency key提交新实验。

### 外部依赖与成本

- baseline_runtime/utils/orekit-data.zip是原已有公开轨道数据依赖，SHA见运行要求和SHA256SUMS；不是模型或候选缓存。
- EOS-Bench原175MB文件不随包；source_header提供原真实轨道和城市及源文件SHA，读取现有Bundle无需原文件。
- 不含静态候选证据库。在线缺缓存必须使用原真实物理判定，不可跳过；冷开销会改变搜索覆盖。获取旧缓存需另行交接其原manifest/SHA，不从旧Score推断可凭空复现。
- LAVIS可选真实模型SHA9a2a454f85b41bc948a43ffcc2bbf6d20b7359ec500a81cc8f69841a20ec078d，原出处F:/EOS-Pilot-Work-v1/lzt-models；不随包。没有完整manifest/迁移证明时保持不可用，不阻塞前四算法。
- Cesium需按原依赖配置；不可把缺外部资源显示READY。此包不含99项大型历史库，也不提供发送方旧17/103场景，缺数据源时保留真实WARN。

## 验证与未来生成

Git路径下可运行十项**无Solver**测试：

```bash
"$PY" -B -m unittest discover -s tests -p test_hmt_scene_handoff.py -v
```

生成工具仅供以后显式开发，必须是全新输出；此交接没有重新生成：

```bash
"$PY" -B "$TOOL/cli.py" generate --project "$PROJECT" --id R30-main-01 --output "$HOME/eos-new-generation"
```

它验证六份原脚本SHA，仅重定位ROOT/OUT/WORK/DATA四个顶层路径，复用原OrbitGrid/Orekit/CM与sampling；不调用原脚本init、Web注册或数据库备份。生成侧车含新路径/环境，因此新文件不自动等同原SHA。不要将其产物覆盖本包或冒充原件。此入口未在本次执行物理生成验证，已有交接原件不依赖它重建。
