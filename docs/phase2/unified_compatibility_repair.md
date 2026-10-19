# 统一场景与四算法兼容修复交接

日期：2026-10-19。基线：main `e53a6a3`。修复分支：`fix/unified-scenario-algorithm-compatibility`。2026-10-20 已获李泽同授权提交、推送并向 main 创建 PR；不自动合并。

## 1. 小组已确认的范围

优先恢复既有成果。默认不批量生成场景、不重训、不改写旧模型或侧车、不删除旧数据库。李泽同已明确确认：恢复旧版课程仿真姿态规则，保留地球遮挡核验；新增规则是否作为后续正式模型另行决定。

旧数据按旧合同解释，新数据按新合同解释；同一个成对比较必须使用同一份场景与合同。工程采样通过不等于连续区间证明，也不能声称采样间隙绝对没有不可见片段。

## 2. 真实原因与历史版本

原权重推理源码 SHA 与 `50660f3` 相同。`ab1fc4d` 的父提交已是 `7fcc77d`，不是物理变化前版本；只撤回 `88f369d` 的指纹扩展不能恢复原权重。

实测中型场景 `M093 → Sa103` 在 `2025-11-18T12:00:27Z`：

| 项目 | 原课程定义 | PR25 相对天底定义 |
| --- | ---: | ---: |
| 仰角 | 11.5082° | 11.5082° |
| 俯仰角 | -40.8202° | 59.6032° |
| 45° 轴限结果 | 通过 | 拒绝 |
| 地球遮挡 | 无 | 无 |

这一例不是前端错误，也不是卫星在地平线以下，而是把旧窗口按新增姿态定义重新核验。另一个问题是 CAABS 独有的 `planning_window` 预筛选早于公共工程候选策略，导致同一旧场景在不同算法间准入不一致。

## 3. 本轮修改

- `algorithms/conflict_beam.py`：预筛选调用现有 `candidate_exposure`，正式模式仍由该入口执行严格来源策略；候选构造、共享约束和独立核验继续执行。未改 Beam 搜索策略、预算或 IPC。
- `utils/course_compatibility.py`：集中声明旧生成源码身份、旧姿态名和模型/场景兼容边界，拒绝未知历史生成合同。六个历元修复场景仅识别明确的历史来源实现。
- `utils/visibility.py`：新增内部姿态合同参数。默认新版 Nadir 语义不变；旧合同复用原 TargetPointing 绝对 Euler 轴限，保留正确 Epoch、实际轨道传播和地球遮挡。旧合同不追溯套用新增 Nadir/FOV/跟踪限制，其结果明确属于课程仿真假设。
- `utils/continuous_exposure.py`、`eos_system/provenance.py`：接纳已知 v1 生成指纹并冻结真实侧车 SHA、采样与姿态版本。不修改侧车，不把它伪装成 v2 来源。
- `eos_system/planning_preview.py`：Controller 子进程按已冻结来源选择姿态解释，逐段真实采样核验；结果增加 `attitude_model_version`，JSON 导出可追溯。
- `algorithms/lavis/model.py`：保留原权重、原 manifest 和训练指纹。仅为已知 v1 协议建立显式运行兼容记录，额外冻结当前运行代码 SHA；特征顺序、域、依赖、权重 SHA 和运行后替换检查保留。
- `eos_system/api.py`、`runner.py`：API 与 Worker 共用模型/场景域判断。旧权重不能混用于新版 Nadir 场景；仍限制 earliest、完成率、默认约束和无地面站。
- `utils/certification_identity.py`：新增兼容模块纳入进程源码身份；代码运行中变化仍要求重启。

没有修改数据库模式，没有新增网页配置项，没有回退整个 PR25，也没有移除进程恢复、来源重建、下传及其他已有功能。

## 4. 保留的限制

- 正式连续认证仍须独立连续证据；不能把工程 SUCCEEDED 冒称连续认证。
- 卫星遮挡、曝光时长、时间/资源冲突、旧合同中的转向与姿态限制仍检查。若实际不符合所选合同，允许失败，不能靠删除核验变成功。
- 新版四元数边界、初始姿态、固定相机与跟踪约束仍用于明确采用新版合同的场景。
- MIP 本机缺少 PuLP/CBC，PPO 尚未接入可信模型；这两项不在本轮恢复生产可用性的声明内。
- 完成率优先和自适应修复是初始模型选项，不能直接作为 `/api/runs` 的比较算法；直接提交 422 为既有设计。
- 重用原模型不代表取得新训练成果或证明泛化提升。历史报告保留适用范围；本轮新增结果是兼容性验收。

## 5. 验证状态

最终证据以 `experiments/reports/unified_compatibility_acceptance.json` 为准。包含全部公开来源检查、真实 HTTP/Worker/Controller/导出结果、原权重未变检查及运行目录清理结果。

已完成专项：163 项中 161 通过、2 跳过，启用 `EOS_RUN_GEN02_PHYSICS=1` 和 `EOS_RUN_CAABS_REAL_E2E=1`；覆盖旧/新姿态隔离、原模型快照、CAABS/DARTIS/RABAS、来源、独立核验进程和 Controller 集成。不是全仓库全量测试。

验证工具首次通过 stdin 直接启动 unittest，导致 spawn 无法恢复 `<stdin>`；已改用 `python -m unittest` 模块入口复跑。CAABS 首轮缺少 timedelta 导入和旧注入点引用已修复，最终专项 51/51 通过。不能把这些前次失败当成生产故障，也不隐去其原因。

### 5.1 本机真实运行结果

原 80 份统一开发场景与 96 份高冲突开发场景，176/176 完成来源接入检查；没有读取冻结测试场景内容。这不等于跑过全部“场景 × 算法”组合。

| 同场景工程核验 | CAABS | RABAS | DARTIS | 原 LAVIS v3 |
| --- | ---: | ---: | ---: | ---: |
| EOS-G0001（20任务） | 16 | 16 | 16 | 16 |
| HC-F033-V1（64任务） | 23 | 17 | 23 | 15 |

七种可用传统比较基线（收益、时效、均衡、压力修复、SA、GA、ACO）在 EOS-G0001 均成功，JSON/CSV、调度数据与甘特图入口通过。主要验收共 18 次真实 HTTP/独立 Worker/Controller 成功。SA/GA/ACO 使用小规模显式迭代参数及 30 秒预算，详情见报告；这是可用性验收，不作公平性能排名。

原来失败的 50 星 100 任务中型场景：收益优先 94/100、SA 96/100、LAVIS 98/100；补验压力修复 82/100。均通过真实采样，不是把 FAILED 状态直接改成成功。另一次 SA 使用 adaptive_repair 初始模型成功 16/20；完成率优先初始模型已由其他运行使用。

原 LAVIS 权重与 manifest 文件 SHA 均未变化，三份模型恢复登记。补验 LAVIS 回放 READY，5种资源内容与 manifest SHA 相符，Cesium HTML 正常返回；未声称实际操作浏览器验证全部交互。原失败点恢复 true，同时独立取样仰角 -28.6934° 时 `earth_unoccluded=false`、`visible=false`，遮挡检查仍生效。

18 次主验收外，还有 3 次补充运行和 1 次真实回放运行，报告分开记录，避免重复统计。两次直接提交初始模型的 422 作为预期请求拒绝保留；首次回放脚本遗漏必填 replay_config_id 返回422，修正请求后已真实通过，未修改回放 API。

测试服务独立运行，没有往原 SQLite 写入实验；测试后发送 SIGTERM 并 wait，实际信号退出码保留，不冒称退出0。运行目录、模型复制件、Orekit副本和回放资产均由临时目录上下文清理。保留的只有小型验收 JSON，未留下大包或训练缓存。

## 6. 组员如何继续使用

1. 审核合并后拉取代码，正常停止旧后端并等待退出，再启动；不要删除锁或继续用旧进程。
2. 继续登记原统一开发场景目录，不需要复制新场景覆盖旧数据。LAVIS 还需原模型完整目录，保持 manifest 与 model.joblib 配对。
3. 网页日常运行用工程物理核验；选择同一来源、场景、seed、目标、预算进行算法比较。
4. LAVIS 选择完成率目标、earliest、默认约束与无地面站场景；模型 ID 可选原 `lavis-v3-ranking`。
5. 导出查看 `preview_validation.attitude_model_version` 和模型的 `runtime_compatibility`，说明采用的是旧课程合同。
6. 旧失败实验保留，修复后重新创建实验，不改历史状态。新旧合同结果不放在同一行冒充同条件对照。
7. 每次算法改动另开 branch，更新对应算法文档，PR 合并；若改变公共物理合同，应先协调全组，避免再次通过单算法 PR 隐式改变全组验收条件。

## 7. Git 操作

本轮新建分支与检查命令：

```powershell
git status --short --branch
git switch -c fix/unified-scenario-algorithm-compatibility
git diff --check
git diff --stat
```

历史只读取证还执行了 `git show 50660f3:utils/continuous_exposure.py`、`git show 50660f3:utils/visibility.py`、`git show 50660f3:utils/time_parsing.py`；WSL 使用相同命令并增加 `-c safe.directory=/mnt/d/Code/EOS-Course-Project`。只读取源码，不切换/运行整个旧工作树。2026-10-20 李泽同已确认提交、推送与 PR，执行结果以 Git/GitHub 回执为准。

最终只读检查还执行：

```powershell
git diff --numstat
git diff -- algorithms/lavis/model.py eos_system/runner.py eos_system/provenance.py utils/course_compatibility.py utils/visibility.py
git diff --check
git status --short --branch
```

`git diff --check` 通过。LF/CRLF 提示来自原仓库的换行设置，未对项目执行批量换行重写。

## 8. 2026-10-20 提交审核

提交前重新 fetch：origin/main 仍为 `e53a6a3`，修复分支与其提交差为 0/0，全部修复当时尚在工作区，因此无需 rebase。文档、交接和验收报告随代码一起提交。PR 内容见 [PR 说明](unified_compatibility_pr.md)；不自动 merge main。

界面“算法预算/秒”限制求解搜索时间，场景加载、独立核验、入库和回放不包含在内；支持收尾的算法返回最后可行计划，超过系统硬期限则明确超时。比较算法时保持相同预算并披露迭代参数，不能把网页总等待时间作为纯搜索耗时。
