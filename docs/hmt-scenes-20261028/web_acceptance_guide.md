# 网页验收：先看已经完成的真实结果

入口：**http://127.0.0.1:8910/**。原成熟工作台、原接口、实际4 Worker持续运行，没有替换页面。

## 最值得截图的一组

1. 点击“实验管理”，打开 **实验 7b86d94d**，场景 **R30-main-01**，内含4种算法。
2. 点击“结果比较”，保持FCFS、EDF、RABAS、CAABS全部勾选。
3. 点击“综合分/100”降序排序。表格内部可纵向、横向滚动，查看全部四行。

| 算法 | 完成任务 | 综合分 | TP |
| --- | ---: | ---: | ---: |
| CAABS | 106/144 | **71.155511** | 570 |
| FCFS | 101/144 | 66.724666 | 495 |
| EDF | 101/144 | 66.724666 | 495 |
| RABAS | 93/144 | 62.041442 | 483 |

CAABS当次领先最强OS **4.430845分**，完成数、收益、时效三项均改善。RABAS这组落后，截图或报告不能改称RABAS胜利。每行均是真实SUCCEEDED/工程物理采样通过，不是旧99项结果复用。

**推荐截图保留场景/实验ID、四算法、完成数、综合分、TP、TM、核验状态。** 当前内置浏览器已停在此真实比较页；原生Windows Chrome可自行打开同一网址验收。有限采样不是严格连续认证。

## 新建实验时怎样找到新场景

“新建实验” → 数据源 **新机制开发场景 · S10/S30/S50**。

这些是原EOS-Bench轨道与城市坐标上的受控开发请求：包含重复观测、请求卫星资格和合成资源配置。144/240个任务不等于144/240个独立城市，也不宣称这些容量是真实卫星硬件测量值。

- R30-main-01：30星/144任务，主展示，已完成4算法。
- C30-main-01：30星/144任务，成本/价值分支对照，已完成4算法；CAABS没有获胜，保留负结果。
- R30-main-02：30星/144任务，固定位置资源对照，已完成4算法、最终同分；不是优势图。
- R10-show-01：10星/48任务，RABAS真实单项31/48。
- R50-show-01：50星/240任务，FCFS真实单项167/240。

首轮只勾FCFS、EDF、RABAS、CAABS。初始模型选“完成率优先”，Solver预算60秒，保持公共物理设置。不要勾未配置好模型的算法来阻断整个实验。

## 手动表单与精确复现的区别

普通数据源的原工作台表单默认objective-v1；已有主展示实验使用冻结的 **objective-score-v2 / score-search-v2-hard-budget-r1**、70/20/10、29.5秒原生上限及140000公共硬检查上限。两者都可真实运行，但不能把不同协议结果当成同条件复现。`完成率优先`是初始模型名称，不等于纯TCR目标协议。

本轮没有修改成熟UI或加入隐藏协议切换。看展示无需重新求解，直接打开已完成实验即可。若需要精确重做本轮配置，可由用户在PowerShell运行下列命令，创建全新实验后回到网页查看；本交付阶段没有替用户再次执行：

```powershell
$protocol = Get-Content -Raw -LiteralPath '\\wsl.localhost\Ubuntu-22.04\home\mint\eos-course-runtime\f-pilot-v25-web-scenes\compare_R30-main-01\protocol.json' | ConvertFrom-Json
$payload = @{runs=$protocol.requests} | ConvertTo-Json -Depth 100
$validation = Invoke-RestMethod 'http://127.0.0.1:8910/api/experiments/validate' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($payload))
if (-not $validation.valid) { throw '预校验未通过，不提交' }
Invoke-RestMethod 'http://127.0.0.1:8910/api/experiments' -Method Post -ContentType 'application/json; charset=utf-8' -Headers @{'Idempotency-Key'=('manual-web-scenes-'+[guid]::NewGuid().ToString())} -Body ([Text.Encoding]::UTF8.GetBytes($payload))
```

新请求有新的运行身份和真实物理核验；墙钟搜索可能产生不同结果，不保证逐次完全复现分数。不要把本轮开发胜例当作统计独立泛化证明。

## 规模演示与维护

S10/S50两项证明各自规模已实际经过Controller/Worker/Solver/独立Verifier/SQLite，不代表50星所有算法或4路完整压力均通过。Score最后10%是TM时效，RT不计分；共享离线准备成本不为零。

服务沿用Stage24-R6入口，数据库/data-source登记持久保留：

```powershell
& 'D:\大学学习\大三\大三上\OS课设\stage24r6-web.ps1' health
& 'D:\大学学习\大三\大三上\OS课设\stage24r6-web.ps1' start
# 无活动任务时才停止或重启
& 'D:\大学学习\大三\大三上\OS课设\stage24r6-web.ps1' stop
```

WSL或Windows关闭后需重新start，确认健康及4 Worker。原17场景、19算法、旧99项只读入口和用户记录均保留。
