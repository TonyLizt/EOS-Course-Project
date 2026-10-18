# 统一控制台 PR：最新 main / PR #19 集成交接

日期：2026-10-18。功能分支：`feat/unified-experiment-interactions`。

## 实际基线与冲突处理

重新 fetch 并从 GitHub 核实 PR #19（fix/source-window-i2）已合并，最新基线为 `22299b4ffaa1b928ea3ce449f3e6aedd0eeb044e`，不是此前 PR #18 的 `5e37ba7`。遵循 team_collaboration.md 的 merge 流程，不 rebase/强推历史，不改 main，不触碰原始目录内其他成员的脏工作区。

先保存已完成的 #18 合并处理，再继续 merge 最新 #19；保留双方 COURSE_SETUP/README 记录，复用中立 Solver 契约、保留 Registry 的同类型重导出。schedule_model 作为共享 SolveContext 中的默认字段追加在原取消回调之后，兼容既有位置参数。

保留 main 的 CAABS 注册/真实实现和参数；控制台比较清单成为原九种加 CAABS 的十种（其中 MIP/PPO 按环境禁用）。两个初始模型仍独立选择、历史 ID 仍可查询。添加元数据说明只依据已有 CAABS 文档，不改核心机制；实验/临时对照容量契约相应支持十种。

保留 #19 的 SourceWindowIndex.restore、显式 sat/gs_window_id、唯一旧来源恢复、场景 SHA/历元、姿态、资源及通信窗口检查，移除旧的“取第一个包含时间的窗口”逻辑。规划预览只使用自己的曝光窗口判定，不能绕过上述来源检查；formal 仍使用原 planning_exposure 和独立连续认证。未放宽 Earth Occlusion、来源或正式存储/导出门禁。

## PR 功能边界

- 一个持久 Experiment 包含多个独立算法 Run；schema v4 升级前在线备份，不覆盖旧备份。
- 注册驱动的算法配置、独立参数、规划预览及正式认证隔离、运行/取消/错误和原 Replay/导出。
- 比较以当前实验为单位；仅初始模型不同的临时对照使用同一 Controller 执行槽与字典内存，不创建持久 Run。
- 轻量筛选与完整指标表；原 Cesium 布局增量管理算法，比较在 Intervals 下方；仅持久结果可回放。
- 交互 Gantt 共用时间轴/缩放/吸附/键盘；临时 Gantt 用最小内存任务数据和独立 API，删除/过期后清空，不能进入 Cesium。

完整专题：[实验管理](experiment_management_handoff.md)、[临时 Gantt](temporary_gantt_handoff.md)、[I2 来源契约](assignment_source_window_contract_v1.md)。

## 验证与可复现命令

```bash
PYTHONPATH=tests MPLCONFIGDIR=/tmp/eos-console-mpl \
/home/asus/eos-course-runtime/.venv/bin/python -B -m unittest discover -s tests -v
node --test tests/*.test.cjs
```

最新 main 整合后默认 Python 总计 525 项，517 通过、8 项 opt-in 跳过，零失败/错误，退出 0（129.188 秒）。覆盖 CAABS core/Registry、新来源窗口身份、正式/临时实验、迁移、独立核验、Worker 取消/超时/回收及默认 HTTP 路径。Node 的 12 个测试文件全部通过，退出 0。

第一次在 #18 整合中运行时有 6 failure / 13 error：包括未展开的 LFS 输入、旧 HTTP 测试把初始模型作为算法提交、CAABS 新增元数据未补齐。随后仅从本地 LFS 缓存恢复原对象（不改字节/侧车），将相关 HTTP fixture 改用 profit_first，补齐真实 CAABS 说明，再在 #19 基线上完整复测取得上述结果。大场景没有重算或重新生成，数据没有纳入新提交。

最新 #19 整合代码的真实 Chromium/Cesium 两星夹具回归通过（UNIFIED_INTERACTIONS_OK，页面错误为空）：注册清单、一个实验多算法、临时创建/删除且正式数量不增、原 Cesium 布局与 Run 切换、Metrics/Intervals/Gantt、高亮、新增/移除、宫格开关及任务吸附。夹具为明确的测试认证注入，不冒充真实连续曝光认证。此前临时 Gantt 定向检查已验证正式记录数不增、删除后旧图清空。8 项 Orekit opt-in 未在本次开启，未做大型 Benchmark、完整 WCAG 或长时 GPU 测试。

## 审核要求

公共接口、Controller 和 schema v4 需由李泽同确认集成影响，至少一名未编写本改动的组员审核后才可合并。作者不自行合并或开启绕过审核的自动合并。PR 仅包含功能分支提交，不包含原始工作目录未提交内容、数据库、虚拟环境、LFS 数据本体或临时日志。
