# CAABS 第一轮：阶段0只读审计与基线

日期：2026-10-21。基线 `origin/main=f344af9704d5839578b69caed4534a74374cab90`（已fetch）。
独立分支 `perf/caabs-round1`，worktree为原仓库的 `output/caabs-round1-worktree`。
原工作区HEAD为 `0aff177`，其未跟踪文件和其他算法未修改。阶段0没有修改算法。

## 实现与接口

真实入口为 `algorithms/conflict_beam.py:ConflictBeamScheduler.solve`，Registry中的 `caabs` 直接构造该Solver，非旧CLI算法工厂。当前版本0.2.0。
Runner计时仅包围solve；场景加载、独立核验和导出不计Solver RT。默认公共目标为profit权重1；排序首先按完成数，再按ObjectiveModel，最后按完整规范键，不调整权重。
公共构造器实际支持earliest、center、latest；CAABS及现有专项已有latest回归，本轮不新增放置模式。

## 搜索审计

1. 任务按ID固定排序，每层一次，skip后不再处理。时间耗尽时偏向前缀任务。
2. 窗口先经过公共曝光准入，按卫星分组、时域分散采样。选定窗口上限为 `min(max_windows_per_task,max_candidates_per_task)`。
3. 空计划上按earliest整轮、center整轮、latest整轮生成候选，总候选默认16；前一轮可填满容量。下传只取公共构造器首个可行组合。
4. 搜索再取 `candidates[:branch_limit]`。历史branch_limit的实际语义为“每父状态最多检查的候选数”，不是可行子节点数。默认8，因此最多一半已生成候选进入检查。此次用户明确要求分离两个预算，需要版本和参数说明更新。
5. 每个skip深复制Schedule；每次接受插入深复制整个父计划，再复制候选；每次incumbent改善再复制。assignment和姿态均可变，不能未经证明改为共享引用。
6. 每个子节点完整计算四项目标（包括权重为0的项），完整递归冻结所有assignment并排序生成canonical key。键保留全部字段、容器类型、UTC和微秒。
7. 去重键为 `(task_index, canonical_key)`。所有状态共享同一固定任务顺序，所以游标加已分配集合已隐含skip集合，当前不存在漏掉游标的错误。若未来动态改序必须扩充身份。
8. 每父状态建立稀疏同星观测索引，只安全拒绝重复任务与严格半开观测重叠；其他约束仍交公共模型。没有全候选两两冲突图。
9. 每层含skip，去重后按固定rank取Top-B。最优可行解在剪枝前保存。Beam默认8，最大256；branch默认8最大64；候选默认16最大128；窗口默认32最大256。
10. checkpoint检查当前SolveContext取消及单调时钟，返回预留 `min(0.05,0.05*budget)`。公共原生调用不是硬实时保证，外层Controller仍须拒绝超预算结果。
11. levels_completed只在去重、剪枝结束后增加，符合完整层定义；accepted_insertions是约束接受次数，可能在子节点构造中断前增加，不能当已生成子节点数。stop_phase在incumbent复制时仍沿用canonicalization，正常完成沿用pruning，阶段诊断有改进空间。

## 实测基线

Windows 11 26200、Python3.13.5、Anaconda；numpy/pydantic/psutil版本、完整参数、seed、场景哈希、原始指标见 [baseline.json](caabs_round1/baseline.json)。seed41、PYTHONHASHSEED=0、单线程BLAS、串行新子进程、每实例2秒、重复2次。
沿用 `scripts/rabas_study_fixtures.py` 的uniform/clustered/downlink三族，各20/100/300任务。它们是既有公共模型合成压力测试，不是dist0/dist1真实轨道数据，不是物理认证；没有读取最终测试集。
全部18个返回计划通过独立重新生成场景、重建ConstraintModel、按开始时间回放和任务唯一性核验；输入未变、RT均未超2秒。

| 任务数 | 平均完成（三族×两次） | 平均Solver RT(s) |
|---|---:|---:|
|20|14.33|0.213|
|100|31.33|1.329|
|300|29.00|1.886|

另行cProfile（不能与正常RT混排）：uniform20/100/300的clone_schedule累计为0.586/0.834/0.756秒，canonical_state_key为0.499/0.743/0.748秒，完整ObjectiveModel.score为0.034/0.081/0.161秒。对应分析运行总时1.337/1.951/1.952秒。各组存在嵌套调用，不能相加累计时间。复制和规范键是首要瓶颈；完整目标次之；候选构造仅约0.04–0.06秒。
单独tracemalloc运行Python分配峰值为6,130,781 / 9,209,702 / 8,882,202字节；其约4倍的仪器开销影响完成数，只作内存诊断，不列入性能胜负。

原有 `python -B -m unittest discover -s tests -p test_algorithm_conflict_beam.py -v`：51/51通过，0跳过，unittest3.803秒。

## 后续实验决定

先独立比较候选预算分离、候选多样性、静态机会排序、贪心incumbent，再组合。排序机会由经过公共构造检查的有限候选估计，明确为采样下界，不当作全部可行性证明。
第二阶段允许增量精确规范键及有一致性回归/回退路径的增量目标计算。安全复制保留，不引入可变assignment共享。没有必要在首轮同时重写资源模型或改变评分。

Windows缺少orekit_jpype/jpype；已只读找到WSL Ubuntu22.04 Python3.10.12现有Orekit环境，需进一步确认外部数据包位置。真实场景只使用公开开发/验证白名单；Controller物理核验结果必须与公共模型回放分列。
既有3星200任务24h研究脚本依赖外部7天母场景，原CLI列表未含CAABS；本地常规input/experiments中尚未找到这两份母场景，不能声称复现。

## 复现

```powershell
$env:PYTHONHASHSEED='0'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
python -B scripts/benchmark_caabs.py --output output/caabs/baseline --budget 2 --repeats 2
python -B scripts/benchmark_caabs.py --output output/caabs/baseline-profile --budget 2 --repeats 1 --families uniform --instrument profile
python -B scripts/benchmark_caabs.py --output output/caabs/baseline-memory --budget 2 --repeats 1 --families uniform --instrument memory
```

输出目录必须不存在，避免覆盖证据。每个job保留参数、计划、日志、结果及可选prof；独立子进程有超时回收。合成场景SHA为dataclass完整内容的稳定JSON摘要，真实场景另记原文件SHA。
