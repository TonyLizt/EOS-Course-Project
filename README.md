# 多星观测任务调度实验平台 · EOS-Course-Project

《操作系统课程设计》小组项目。在开源[EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench)的场景模型、调度内核与部分基线基础上，实现可配置、可扩展、可回放的课程实验系统。

**组长：李泽同　｜　组员：何明涛、刘懋兴、梁兆榮**

项目仓库：[TonyLizt/EOS-Course-Project](https://github.com/TonyLizt/EOS-Course-Project)。源码、资源包须使用同一交付版本；安装和验收详情见[发布记录](docs/release/release_plan.md)。

## 背景与课程目标

地面观测请求可类比作业，卫星载荷可类比处理资源；曝光对应服务时间，转向与稳定对应切换开销，可见窗口与存储等限制共同决定任务能否执行。观测不可按CPU时间片任意抢占，卫星轮询也不等同于CPU轮转。

系统实际使用独立进程、IPC、文件锁、队列、超时回收和数据库事务：浏览器提交配置，Controller派发Worker求解，独立核验计划后保存，再查询、比较、导出或回放。一个Worker求解整份卫星计划，不代表一颗卫星。

## 分工

| 成员 | 系统职责 | 算法职责 |
|---|---|---|
| 李泽同（组长） | 总体架构、公共接口、FastAPI、Controller、SQLite、集成与交付 | 主导LAVIS/LAVIS-OC学习排序、模型与验证 |
| 何明涛 | Worker、IPC、同步、取消/超时及进程回收 | DARTIS；参与机器学习协作 |
| 刘懋兴 | 场景、来源谱系、划分/哈希、基线复现与成对实验协议 | CAABS；参与机器学习协作 |
| 梁兆榮 | 前端监控/比较、Cesium/甘特图、Daemon及故障恢复 | RABAS；展示整合 |

## 已有功能

- 课程导览与OS概念对应；配置、管理、比较分区，桌面全屏及内部滚动。
- 登记数据源和输出位置；多算法实验、类型化参数、种子、预算、初始模型、目标和约束配置。
- 1—8个独立Worker，有界队列、事件、PID/尝试记录、取消、超时及回收；实际并发按机器容量配置。
- Controller重放候选，核对来源、任务唯一性、时间、存储/功率预算、姿态转向及Orekit曝光采样与地球遮挡。
- SQLite保存Experiment、Run、配置、计划、指标、事件及回放记录；查询、移除算法、删除实验和相关文件清理。
- 同条件比较、数值表头排序、临时模型对照、单次JSON/CSV及批量统计CSV/ZIP，支持配置目录输出。
- 交互甘特图、Cesium三维轨道/任务回放、载荷视图、时间控制、算法切换及结果联动。
- 独立Daemon监护后端，验证真实身份/心跳，有界退避恢复；独立演示页可结束隔离Worker或后端并观察恢复。

工程采样通过**不等于严格连续区间认证**。Daemon恢复服务及队列处理能力，不恢复中断算法的内存搜索状态。模型仍是课程仿真，不能当作真实航天任务安全认证。

## 环境与交付包

推荐Windows 10/11浏览器＋WSL2 Ubuntu 22.04 LTS，后端为CPython 3.10、Linux x86_64；原生同类Linux也可运行。Windows负责编辑/Git/浏览器，Linux负责Worker、锁、SQLite、物理计算与模型。不要直接用Windows Python启动后端。

| 文件 | 内容 |
|---|---|
| `EOS_课程设计_源码_最终版.zip` | 整理后的源码、测试、部署入口与精简文档，不含虚拟环境、实验数据库或Git内部目录 |
| `EOS_发布资源_v3.zip` | 66份场景、LAVIS模型、Orekit数据、Python离线wheels及逐文件SHA清单 |
| `EOS_公开训练数据_可选.zip` | 仅在重训时使用的公开开发/验证输入，不含最终测试任务 |
| `最终实验_v3_60场景_19算法_seed42_8并行.zip` | 已冻结实验的元数据、原始数据、统计数据；不包含论文说明 |

源码ZIP可替代clone，适合提交与U盘交付；Git获取方式为：

```bash
git clone https://github.com/TonyLizt/EOS-Course-Project.git
```

请先确认远端已包含组长发布的同版本修改；尚未推送的本地成果以配套源码ZIP为准。旧场景LFS样例需要时再`git lfs pull`，运行本次资源包不依赖它们。

## 部署：第一次安装

未安装WSL时在管理员PowerShell执行：

```powershell
wsl --install -d Ubuntu-22.04
wsl -l -v
```

下面在**Ubuntu终端**执行。先准备系统Python的venv支持（一次即可）：

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv
```

将源码包和资源包放到U盘。示例假设U盘是Windows的E盘；按实际盘符修改`/mnt/e`：

```bash
mkdir -p ~/projects
python3 -m zipfile -e /mnt/e/EOS_课程设计_源码_最终版.zip ~/projects
cd ~/projects/EOS-Course-Project
bash eos install --resources /mnt/e/EOS_发布资源_v3.zip --offline
bash eos doctor
bash eos run
```

安装器创建默认`~/eos-course-runtime/.venv`，核对资源SHA后安装场景、模型及Orekit数据，再从组内wheels安装已固定版本的依赖；不同内容的既有文件会报错，不自动覆盖。安装结束执行真实场景来源/模型身份检查。需要修改运行根目录时，**每条命令使用同一个目录**：

```bash
bash eos install --runtime-dir ~/my-eos-runtime --resources /mnt/e/EOS_发布资源_v3.zip --offline
bash eos run --runtime-dir ~/my-eos-runtime --port 8765
```

离线wheels仅覆盖CPython3.10、Linux x86_64。系统包仍需预先安装；浏览器CesiumJS与底图仍需要网络。在线安装可以省略`--offline`，依赖仍受`requirements-release.txt`及完整版本约束控制。不要复制`.venv`到其他机器代替安装。

## 启动、停止及守护

| 操作 | Ubuntu命令 |
|---|---|
| 只读自检 | `bash eos doctor` |
| 前台启动 | `bash eos run`；Ctrl+C正常停止 |
| 后台Daemon启动 | `bash eos daemon-start` |
| 守护状态 | `bash eos daemon-status` |
| 正常停止Daemon | `bash eos daemon-stop` |

先停前台服务再启Daemon，同一运行目录只允许一个Controller；不要删除占用中的锁，也不要用Uvicorn多Web进程或`--reload`实现算法并发。HTTP绑定本机，不提供公网账户认证。

- 工作台：<http://127.0.0.1:8765/>
- API文档：<http://127.0.0.1:8765/docs>
- 健康检查：<http://127.0.0.1:8765/api/health>
- 隔离守护演示：<http://127.0.0.1:8765/daemon-demo>

`config.json`保存相对运行根目录的默认场景/Orekit位置和端口；环境变量`EOS_RUNTIME_DIR`、`EOS_SCENARIO_DIR`、`EOS_OREKIT_DATA`、`EOS_PORT`可覆盖默认值。`EOS_MAX_WORKERS`优先于网页保存值，仅在确需强制固定时设置。

## 使用流程

1. 作业提交：选择联调场景，勾选算法，设置种子和预算；算法预算是求解上限，不是曝光时长或CPU时间片。
2. LAVIS选择`lavis-v4-opportunity`，按实验协议使用`expanded`候选、`multistart`搜索；主测试为完成率目标、earliest放置、无地面站和默认约束。不要改manifest绕过不匹配提示。
3. 运行管理：选择实验、切换其中算法，查看状态、真实尝试PID、事件、配置及计划；需要时取消/删除。
4. 策略比较：在同条件内点表头排序，选择对照，导出统计。综合分为`70×TCR＋20×收益比例＋10×(1−TM)`，RT另列。
5. 构建回放后打开Cesium或甘特图；回放读取已冻结计划，不会再求解。初次构建需要等待。
6. 守护演示：启动→结束Worker→结束隔离后端→停止清理。页面操作不结束正式实验后端，等待作业不产生论文指标；详见[录屏讲稿](docs/release/recording_script.md)。

## 数据、算法与实验

正式60份：小10星20任务、中20星80任务、大50星200任务；每档低冲突/混合/高冲突/资源紧张各5份。15个正式家族各4变体，另3个独立联调家族各2变体；时域1800秒，无地面站。

全新安装默认加载`datasets/eos-final-v1/smoke`的6份**v3**联调场景；v1目录名仅为原安装器兼容槽位，实际dataset_id为eos-final-v3、ID以FINAL3-开头。本机升级环境单独使用datasets/eos-final-v3，不覆盖历史Run输入。正式测试目录`final_test`需明确登记，用于冻结后的统一测量，不用于训练和调参。保留JSON、侧车、验证报告、表征及相对路径计划文件一起复制。

19种就绪方法包括小组DARTIS/RABAS/CAABS/LAVIS、6种OS策略、SA/GA/ACO、4种既有启发式及随机/卫星轮询。MIP/PPO保留历史兼容接口，当前发布环境无可用依赖/制品，不参加主测试。算法来源和实际名称保留，不能把成绩好的开源基线改名成自研算法。

最终采用v3：60×19、seed42、每算法60秒预算，1140次均SUCCEEDED且指标有效，全部记录Worker上限8。完成不表示任务全做完；单种子结果不代表显著领先，RT受并行资源争用影响。原始计划/指标/CSV及19算法汇总已交叉核对，见[实验协议](docs/EXPERIMENTS.md)。v1有地理偏置、v2贴近轨迹，均已停用，旧成绩不混入v3。

## 最终场景与交付版本

v3星座采用独立轨道面/倾角/高度/相位，移除成对近邻构造；任务来自独立球面背景和椭圆区域先验，随后按可达性/负载条件抽样，不沿星下点加扰动铺点。普通组不固定南北等量，高冲突为区域集中的极端组。约5.5%请求无完整窗口，另记可达率，TCR仍为完成数/全部请求数。

新数据使用组长确认的惯性系绝对角范围yaw/roll±180°、pitch±90°，窗口额外限离天底角≤30°；仍用旧课程角度解释、遮挡、曝光、转向和资源规则。算法、模型权重未因此修改。可观测任务最佳角度<5°约20%，20°—30°约26%。实际生成源、独立目标先验、草稿/校准证据随场景包提供；scripts/build_final_dataset.py属于已停用v1生成路径，不用于生成最终v3。

最终交付目录分为01_教师提交、02_组员最终版、03_实验数据与结果、04_历史归档。教师和组员目录各含源码ZIP、配套资源ZIP与说明；提交版本以源码ZIP内SOURCE_MANIFEST.json和交付版本.txt为准。GitHub尚未推送时，以本地交付包为准。

## 目录与文档

```text
eos / ops/           统一安装、自检、启动和资源校验
eos_system/          API、Controller、Worker/IPC、SQLite、Daemon、导出、网页
algorithms/          小组方法、OS迁移策略、开源基线、统一算法合同
core/ schedulers/    场景对象、加载、约束、指标、计划输出
utils/              Orekit、时间解析、姿态及身份核对
draw/ replay/        甘特图、Cesium、冻结回放和载荷视图
scripts/            生成、训练、核验及维护工具；非日常启动入口
tests/              Python/Node机制及集成测试
input/ experiments/  复用输入与兼容样例/研究工具；大测试数据放运行目录
data/registry/       兼容身份索引，不保存新生成的大数据
```

- [系统架构、算法原理、接口与数据库ER图](docs/ARCHITECTURE.md)
- [场景、指标、实验统计与重训](docs/EXPERIMENTS.md)
- [组员协作与分支/PR规范](docs/COLLABORATION.md)
- [发布验收及运行目录](docs/release/release_plan.md)
- [大迭代记录](COURSE_SETUP.md)
- [源码提交说明](说明.txt)

历史小改动文档、旧开发数据和研究输出已单独归档，源码树仅保留测试要求的两份不可变历史证据；它们不是当前接口设计。`main_generate.py`、`main_scheduler.py`、`verify_schedules.py`仍供兼容审计调用，日常使用统一入口`eos`。

## 测试与常见问题

```bash
# 使用同一个已安装环境
PYTHONPATH=tests ~/eos-course-runtime/.venv/bin/python -m unittest discover -s tests -v
# Node可选，仅运行前端回归时需要
node --test tests/*.test.cjs
```

- 缺Python venv：安装`python3-venv`；不要改用Windows解释器。
- 模型未就绪：先`bash eos doctor`，核对资源、数值库版本和源码身份，不重写权重/manifest。
- 端口/Controller锁冲突：正常停止旧实例再启动，不删锁文件。
- Cesium无底图/未加载：检查浏览器网络、服务控制台和回放是否READY；不能把显示异常直接当成物理核验结论。
- 清理磁盘：先导出并核对再通过网页删除实验；历史数据库保留备份，回放缓存不要脱离状态记录盲删。

## 开源来源

复用EOS-Bench的场景结构、部分调度器及可视化基础，小组新增实验框架、接口/数据库、Worker/IPC/Daemon、统一工程核验、算法路线、学习模型、实验协议与交互工作台。保留上游[CITATION.cff](CITATION.cff)及原文件归属；第三方组件见[来源说明](THIRD_PARTY_NOTICES.md)。
