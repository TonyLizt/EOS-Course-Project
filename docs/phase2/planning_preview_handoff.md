# 规划预览与正式认证隔离（2026-10-17）

旧启动目录与控制台工作树并存，浏览器还可能缓存旧页面。启动入口现在可明确转入升级工作树，页面禁止缓存并提供 UI build ID。正式实验失败的直接原因是缺少可信连续曝光证明，不能将 `UNTRUSTED_PHYSICAL_SETTINGS` 伪装成认证成功。

经用户确认新增规划预览：UI 默认预览，API 默认仍为正式。预览保留窗口、曝光、资源、姿态转换和地球遮挡检查，使用实际 Orekit 进行曝光区间采样核验；采样通过不等于连续认证。未修改算法目标或评价指标。

## 公共契约

- RunRequest 增加 `execution_mode: formal | planning_preview`，默认 `formal`；场景列表接受同名查询参数。
- 预览返回 `result_kind`、`preview_validation` 和 `NOT_CERTIFIED`。比较条件包含模式，不默认混比正式结果。
- PreviewReceipt / PreviewRecord 与正式认证类型隔离，绑定 Run、场景 SHA 及计划摘要。只生成 `PREVIEW_VALIDATED`，不生成连续认证事件。
- 复用现有 plans、metrics、配置与事件表，无 SQL 模式迁移，不改写历史结果。Schedule / Gantt / Replay 支持明确标记的预览；正式导出仍返回 409，预览禁止服务器目录正式输出。
- health 返回 UI 名称和 build ID；首页、静态资源及 Gantt 禁止缓存。Cesium 和 Gantt 显示预览警告。

## 实际验证与限制

10 项定向 Python 测试通过，涵盖正式门禁、receipt 防伪、计划篡改和历史读取；Node 控制台/时间轴 5 项通过。隔离运行目录中真实 Chromium 提交 completion_first 和 adaptive_repair，10 星 20 任务均完成 20/20，TCR=1；使用实际 Worker 和 Orekit，没有模拟认证。验证正式导出 409、Gantt 提示、比较与无页面异常；真实回放构建 READY，manifest 保留未认证警告。

未做全量测试、大规模 GPU 回放或完整 WCAG 审计。预览不能用于宣称连续认证，既有失败 Run 不自动重跑。

## 启动

原项目目录继续运行 `/home/asus/eos-course-runtime/.venv/bin/python -m eos_system`。本地升级工作树为 `.worktrees/scheduling-console`，保留原数据库和场景目录。其他机器应直接部署包含控制台的分支，不依赖本地桥接。

### 2026-10-18 续作

CLI 加载 API 前只读打开既有锁文件并执行非阻塞 flock 探测。已有 Controller 时以退出码 1 给出网址与原终端 Ctrl+C 重启提示，不打印异常堆栈，不初始化第二个数据库、不删除锁、不停止现有服务。遗留但未被持有的锁不阻止启动；检查与启动之间仍可能有竞争，最终安全边界仍是 Controller.start 的原有排他锁。直接调用 uvicorn 的高级用法不经过此 CLI 提示。

本轮新增 3 项 CLI 测试（无锁不创建文件、遗留锁正常启动、独立进程重复启动不影响持锁者），结合 2 项预览隔离测试共 5 项通过；Node 6 项包含正式/预览及不同预览版本不能混比。一次隔离 Chromium 回归覆盖正式模式的单项/批次提交、拒绝未认证输入、标记的测试历史比较及 Gantt 悬停、键盘、触控和缩放，页面错误为零。本轮未重复真实 Orekit 求解和 GPU 回放，上述真实 20/20 与 READY 是上一轮验证结果，不冒充本轮重测。
