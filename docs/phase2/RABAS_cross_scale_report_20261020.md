# RABAS 跨规模优化与独立验证报告

日期：2026-10-20（Asia/Hong_Kong）。本报告区分算法公共模型测试、真实场景预览核验及正式连续物理认证。**不把未核验候选数、超预算返回或合成 fixture 当作正式合法观测完成数。**

## Git 与交付边界

- 独立克隆目录：`/home/asus/projects/eos-course-runtime-rabas-cross-scale`。
- 从 GitHub 最新 main 克隆并 fetch；基线：`89dff80f881ed4c2a49b43906071ba07012be46c`。
- 分支：`perf/rabas-cross-scale-optimization`；代码负责人边界为算法B/RABAS，注册表仅更新自己的参数/说明。
- 原建议目录 `eos-course-runtime-rabas-opt` 已有另一轮未提交修改，故使用新目录，没有覆盖它或原工作区。
- 只做本地 Commit；没有 Push、PR或合并。代码、算法文档、专题说明、实验脚本和COURSE_SETUP记录一起交付。
- 公共约束、原始场景、其他算法、正式指标、Solver/Worker/Controller/数据库契约均未改动。
- 参数初冻 `b3968a0`，目标边界修复后实现 `4fbaa80`；首轮独立集暴露下传覆盖回归后重新归类，1.1.1 实现第二次冻结 `cfe53ad`。

算法原理、逐个参数的新旧值、公式及汇报流程见 [算法说明](RABAS_algorithm_explanation_20261020.md)。更细的开发阶段记录见 [阶段日志](/home/asus/projects/eos-course-runtime-rabas-cross-scale/docs/phase2/algorithms/rabas_cross_scale.md)。

## 审查结论与实际改动

在最新main重新确认六项问题：每星单贪心路径；原始独占性代替动态稀缺；候选位置和任务覆盖窄；重复完整深复制/公共核验/全量目标；检查上限丢弃当前轮报价；包大小绝对优先。审查覆盖候选池、ConstraintModel、Schedule/Assignment、Solver/SolveContext、Registry、Worker/Controller、ObjectiveModel/EvaluationMetrics、实验可比性检查及RABAS专项。

实际采用：窗口索引和单窗口任务预处理、4096项候选模板缓存、当前轮候选/机会缓存、只复制计划列表、精确可加目标增量及边界回退、入围包的有界动态机会估计、earliest/center/latest/原始网格空隙、按候选量/剩余时间收窄搜索、保留已完成报价的Anytime结束。1.1.1还恢复下传center并增加有界latest/共享资源空隙提案。

可选机制有不同首任务的局部多起点、同星1换2修复、未来机会优先排序。验证没有支持默认开启多起点和修复；最终分别为1和0，未来机会优先排序也回退为false。它们不被写成已经证明有效的默认优势。

最终仍是“局部Bundle构造→卫星报价→全局仲裁→完整重放→中标后重新报价”。真实2/3任务Bundle、任务唯一、转向、存储、累计功率和共享地面站互斥均保留。取消抛异常；Worker硬超时与Controller事务语义不改。全部真实插入及中标使用原始公共约束；仅内部机会估计使用已验证见证的公共离散检查。

没有实现跨星迁移、任意交换、跨轮增量重用报价、精确反事实最优机会损失或在线学习预算模型。仍每轮全星重报，仍有候选截断。缓存保存候选模板而非完整答案，不读取场景名/SHA/Benchmark名，不包含任务或卫星ID特例。

## 数据分离、规模与公平条件

| 阶段 | 来源族/seed | 用途 |
|---|---|---|
| 开发 | uniform / 101及针对性反例 | Profile、正确性、一般机制设计 |
| 验证 | clustered、capacity / 211 | 单因素消融、默认参数取舍 |
| 首轮独立→验证 | hub、downlink / 307 | 发现下传覆盖退化后全体重新归类，原始结果全部保留 |
| 最终独立 | orbit_bands / 409；station_network / 503 | 第二次冻结后一次执行，未用于参数或分支选择 |
| 真实工程核验 | 两个S2小型、一个S2中型、历史500任务实例 | 只读SHA绑定、相同物理版本和Controller核验；来源族隔离不足，不冒充严格独立测试 |

合成每族含20/100/300任务，对应2/5/15星；具体窗口、共享任务、地面站和SHA见结果表。最终新族使用独立生成函数，构造周期机会、多轨资源、星间异构性及双地面站网络，不从已知测试Scene/Schedule派生。它们仍属程序生成的数学测试，不能代替轨道场景物理认证。

真实库存：小型20任务、10/20星、105–355窗口；中型100任务、50星、7259–11251窗口；历史大型500任务、20星、4035窗口。中型的窗口枚举量反而更大，因此“Large”只说明任务维度更大，不意味着每项复杂度都更高。项目正式目录没有同等来源充分的大型认证数据。

比较使用原注册算法和默认参数，目标权重固定完成率1、其余0，原公共指标公式和方向不变。完成数为主要比较项；TP越高、TM越低、BD越高、RT越低作为单独指标报告，不另造综合权重。项目实验比较器负责可比条件，未找到能把全部次级指标自动变成一个新统一字典序的公共规则，因此不伪造“综合总分”。

合成同一2秒Solver墙钟上限；真实补充同一3秒；串行运行，不并发大型Benchmark。初始解构建计入Solver RT。SA/GA/ACO使用completion_first初始解，其他算法空计划或自行重建，明确分组。随机算法使用41/43/47三个预选种子；真实工程核验只用41，不能证明随机稳定性。

环境：WSL2/Linux，Intel Core Ultra 7 155H，约16GB内存，Python3.10.12，NumPy2.2.6、Pydantic2.14.1；同一个既有虚拟环境。MIP缺PuLP/CBC，LAVIS缺sklearn及兼容冻结模型，PPO缺可信模型/统一约束接入；均单列不可用，不算被RABAS击败。

首轮脚本曾使用可被公共辅助函数吞掉的普通TimeoutError。发现后改为BaseException派生的实验截止信号，并在所有结果上复查实际RT。所有超预算返回原样保留、标OVER_BUDGET，不进入等预算成绩；未重跑不利有效样本挑最好结果。最终独立批次从开始就使用修复后的协议。该修改只影响实验工具，不改任何算法预算或内部配置。

## 最终判断：有明显改进，尚未达到三个规模全面领先

- **Small**：最终独立集RABAS平均18/20、90% TCR，与Adaptive Repair及Load Balance并列组均值最高（只比较覆盖全部实例的有效结果）。但station_network只有16，低于部分贪心/负载均衡基线的17；与Adaptive Repair同为16时TP为137对149、BD为0.725对0.925、RT为0.713对0.253秒。没有次级指标全面优势，不能称每个小实例最优。
- **Medium**：平均70.5/100，优于同预算有效返回的旧RABAS21、CAABS43、DARTIS9.5；两个独立实例均胜这三种方法。其他若干算法没有在2秒内返回，属于预算下不可用结果，不是完成数为0，也不是证明其解质量必然较差。
- **Large**：平均98/300，优于有效返回的旧RABAS7、CAABS37、DARTIS2.5；两实例均胜这三种方法。但TCR仍只有32.67%，尤其双地面站族只50/300，搜索质量仍有限。RABAS平均BD低于旧版/CAABS，RT也没有全面优势。
- **真实工程场景**：最新版本小型20/20、中型98/100通过Controller同一预览核验器；中型Completion First同为98且更快。历史500任务输入被物理核验拒绝，不能使用候选14作为合法完成数。实际Controller三个规模formal全部失败，故没有“正式物理成绩三规模领先”的证据。
- **10秒验证补充**：capacity/300中Adaptive Repair完成142，高于RABAS135。这条不利结果也保留，说明2秒结果不能外推成任意预算领先。

最终独立样本只有每规模2个结构族；随机方法最多3种子，确定性方法1次，受墙钟截断影响。没有统计显著性结论，没有把未返回方法的缺失值填0，也没有继续使用最终独立结果调参。

## Profile 与阶段筛选

最初带cProfile的开发集main基线20/100/300任务分别完成20/6/2，纯效率阶段20/8/2；小型RT从1.008降至0.260秒。早期动态机会版本为20/18/6，小型RT反增到0.678秒，说明直接增加机会搜索会抵消收益。随后把机会估计限制在入围项、加入实例压力收缩，并通过验证消融决定默认开关。不同时间的Profile受宿主负载和采样开销影响，不作为正式跨算法RT排名。

冻结后重新串行配对cProfile，输入为同一开发族uniform/101，预算2秒，结果如下。原版深复制次数由外部包裹deepcopy实测，目标调用由pstats读取；优化版不依赖自报的0来证明消除。候选包计数为评价阶段次数，含重定价，不应解释为互不重复的组合数量。

| 任务数 | 版本 | 完成 | RT(s，含Profile) | 构造器调用 | 完整计划深复制 | 公共核验 | 完整目标调用 | 目标增量调用 | 模板命中 | 中标 | 中标/秒 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | baseline | 20 | 0.589 | 1308 | 518 | 1418 | 528 | — | — | 10 | 16.97 |
| 20 | optimized | 20 | 0.240 | 124 | 0 | 1147 | 0 | 758 | 1223 | 10 | 41.70 |
| 100 | baseline | 10 | 1.950 | 12502 | 1038 | 12532 | 1044 | — | — | 5 | 2.56 |
| 100 | optimized | 69 | 0.755 | 441 | 0 | 5876 | 0 | 765 | 4176 | 35 | 46.36 |
| 300 | baseline | 2 | 1.950 | 12759 | 1381 | 12761 | 1382 | — | — | 1 | 0.51 |
| 300 | optimized | 94 | 1.956 | 543 | 0 | 12555 | 0 | 3976 | 9756 | 47 | 24.02 |

缓存/增量方案显著减少构造和复制，最终大型Profile的中标从1增至47；这一配对比较包含全部最终机制，不能把完成数收益完全归因于缓存单项。纯效率阶段大型仍2，正说明效率和候选/预算机制需要配合。未测峰值RSS，不声称已得到内存占用统计；模板缓存上限4096，轮缓存每次中标清空，最多4局部起点，不保留跨轮搜索树。

预算截断修复由专项反例覆盖：检查上限和deadline之间已经完成的报价可在最后重放成功后中标；取消仍抛异常。它的独立跨规模完成数贡献没有单独隔离估计，不把所有提升归功于Anytime修复。

## 消融结论与保留/撤销决定

验证变体说明：`default`是冻结前future_aware_rank=true参考；`no_opportunity`将机会权重置0；`static`关闭动态稀缺；`multi`设2起点；`fixed`关闭自适应；`repair`设8次；`narrow`最多2位置；`old_rank`恢复完成数优先，即最终默认false。

- **动态稀缺**：机制反例能识别共享任务变单星，但验证集中不能证明稳定提高完成率；大型关闭机会成本84→96，同时省去估计，静态近似84→86。保留有界默认估计是兼顾反例保护的取舍，不是宣称其验证收益为正。高压力只探1个保护任务。
- **多起点**：小型13→12且RT增加；中大型自适应强制1起点，因此multi开关未实际增加路径。默认1，可选机制保留但不宣称跨规模收益。
- **修复**：小型/中型没有完成数收益；部分大型只受时间截断波动。默认0；单元反例证明1换2可严格增加完成数，未证明收益覆盖额外成本。
- **候选覆盖**：latest/gap反例及下传回归测试证明确实减少特定遗漏；普通验证small的narrow同为13且更快。不能推断更宽在所有场景都好。首轮downlink退化经通用下传修复后4/4/4→12/36/38，这组已转验证。
- **自适应**：clustered/capacity的100任务固定宽度只有43而自适应46；300任务固定30而自适应84。反映短预算下收窄计算有明显收益；长预算、资源冲突较弱时不保证最优。
- **内部排序**：future-aware true的300任务84/84，恢复count-first为98/94；因此最终future_aware_rank=false。没有为测试排名修改正式目标。
- **资源成本/转向成本**沿用原有默认权重，本轮没有宣称逐项证明最优。最终参数表见说明文档。

## 验证集完整消融（冻结前）

这些是最终默认调整前的同版本机制消融：参考行 `default` 使用 future_aware_rank=true。根据 old_rank 行选择最终默认false。各项为单因素开关；不是完全因子分析，不能将差值直接相加。300任务受墙钟影响，即使不改变实际自适应配置的开关也出现波动，因此不能把每一个差异都归因于机制。

| 族 | 任务 | 变体 | 完成 | RT(s) | 公共核验 | 机会估算检查 | 构造器调用 | 中标 |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| clustered | 20 | default | 13 | 0.098 | 1010 | 241 | 115 | 7 |
| clustered | 20 | no_opportunity | 13 | 0.094 | 1002 | 0 | 116 | 7 |
| clustered | 20 | static | 13 | 0.113 | 1041 | 113 | 118 | 7 |
| clustered | 20 | multi | 12 | 0.166 | 1508 | 434 | 124 | 7 |
| clustered | 20 | fixed | 13 | 0.099 | 1010 | 241 | 115 | 7 |
| clustered | 20 | repair | 13 | 0.115 | 1185 | 241 | 117 | 7 |
| clustered | 20 | narrow | 13 | 0.068 | 755 | 241 | 79 | 7 |
| clustered | 20 | old_rank | 13 | 0.098 | 1010 | 241 | 115 | 7 |
| clustered | 100 | default | 46 | 0.465 | 5922 | 165 | 529 | 24 |
| clustered | 100 | no_opportunity | 46 | 0.418 | 5279 | 0 | 537 | 24 |
| clustered | 100 | static | 46 | 0.468 | 5922 | 165 | 529 | 24 |
| clustered | 100 | multi | 46 | 0.425 | 5922 | 165 | 529 | 24 |
| clustered | 100 | fixed | 43 | 1.953 | 16445 | 1791 | 1009 | 23 |
| clustered | 100 | repair | 46 | 0.480 | 6061 | 165 | 529 | 24 |
| clustered | 100 | narrow | 46 | 0.467 | 5922 | 165 | 529 | 24 |
| clustered | 100 | old_rank | 46 | 0.435 | 5922 | 165 | 529 | 24 |
| clustered | 300 | default | 84 | 1.955 | 18887 | 1367 | 826 | 42 |
| clustered | 300 | no_opportunity | 96 | 1.956 | 19997 | 0 | 1101 | 48 |
| clustered | 300 | static | 86 | 1.957 | 19920 | 1390 | 955 | 43 |
| clustered | 300 | multi | 84 | 1.956 | 19014 | 1375 | 826 | 42 |
| clustered | 300 | fixed | 30 | 1.952 | 16190 | 4548 | 846 | 15 |
| clustered | 300 | repair | 86 | 1.954 | 20094 | 1396 | 955 | 43 |
| clustered | 300 | narrow | 94 | 1.956 | 24195 | 1458 | 1052 | 47 |
| clustered | 300 | old_rank | 98 | 1.957 | 24554 | 1348 | 1068 | 49 |
| capacity | 20 | default | 13 | 0.092 | 1010 | 241 | 115 | 7 |
| capacity | 20 | no_opportunity | 13 | 0.077 | 1049 | 0 | 118 | 7 |
| capacity | 20 | static | 13 | 0.085 | 1041 | 113 | 118 | 7 |
| capacity | 20 | multi | 12 | 0.152 | 1508 | 434 | 124 | 7 |
| capacity | 20 | fixed | 13 | 0.103 | 1010 | 241 | 115 | 7 |
| capacity | 20 | repair | 13 | 0.107 | 1185 | 241 | 117 | 7 |
| capacity | 20 | narrow | 13 | 0.070 | 755 | 241 | 79 | 7 |
| capacity | 20 | old_rank | 13 | 0.100 | 1010 | 241 | 115 | 7 |
| capacity | 100 | default | 46 | 0.487 | 5982 | 166 | 529 | 24 |
| capacity | 100 | no_opportunity | 47 | 0.520 | 6576 | 0 | 562 | 25 |
| capacity | 100 | static | 46 | 0.444 | 5982 | 166 | 529 | 24 |
| capacity | 100 | multi | 46 | 0.394 | 5982 | 166 | 529 | 24 |
| capacity | 100 | fixed | 43 | 1.953 | 17573 | 1675 | 1002 | 23 |
| capacity | 100 | repair | 46 | 0.443 | 6121 | 166 | 529 | 24 |
| capacity | 100 | narrow | 46 | 0.407 | 5982 | 166 | 529 | 24 |
| capacity | 100 | old_rank | 47 | 0.460 | 6807 | 108 | 554 | 25 |
| capacity | 300 | default | 84 | 1.956 | 19286 | 1359 | 938 | 42 |
| capacity | 300 | no_opportunity | 96 | 1.957 | 18061 | 0 | 1016 | 48 |
| capacity | 300 | static | 86 | 1.958 | 19984 | 1376 | 962 | 43 |
| capacity | 300 | multi | 84 | 1.956 | 19090 | 1359 | 938 | 42 |
| capacity | 300 | fixed | 30 | 1.952 | 16043 | 4587 | 816 | 15 |
| capacity | 300 | repair | 84 | 1.956 | 19339 | 1363 | 938 | 42 |
| capacity | 300 | narrow | 92 | 1.956 | 23411 | 1435 | 1049 | 46 |
| capacity | 300 | old_rank | 94 | 1.951 | 18714 | 1046 | 1016 | 47 |

### 下传覆盖修复后验证（1.1.1，2秒）

| 族 | 任务数 | 完成 | RT(s) |
|---|---:|---:|---:|
| uniform | 20 | 20 | 0.076 |
| uniform | 100 | 69 | 0.285 |
| uniform | 300 | 144 | 1.951 |
| clustered | 20 | 13 | 0.070 |
| clustered | 100 | 46 | 0.308 |
| clustered | 300 | 110 | 1.951 |
| capacity | 20 | 13 | 0.063 |
| capacity | 100 | 47 | 0.335 |
| capacity | 300 | 116 | 1.951 |
| hub | 20 | 11 | 0.043 |
| hub | 100 | 39 | 0.182 |
| hub | 300 | 120 | 1.956 |
| downlink | 20 | 12 | 0.546 |
| downlink | 100 | 36 | 1.601 |
| downlink | 300 | 38 | 1.954 |

非下传场景的运行时差异受宿主负载影响，不归因于下传修复。

### 冻结后长预算验证补充（capacity/211，10秒，seed41）

这是验证数据的预算敏感性检查，算法与参数保持冻结；不能当作新独立样本或重新选择参数的依据。

| 任务数 | 算法 | 完成 | RT(s) | 退出/核验 |
|---|---|---:|---:|---|
| 100 | rabas_baseline | 39 | 2.937 | PUBLIC_PASS; no_feasible_bid |
| 100 | rabas | 47 | 1.250 | PUBLIC_PASS; no_feasible_bid |
| 100 | completion_first | 45 | 1.921 | PUBLIC_PASS; 未提供算法终止原因 |
| 100 | adaptive_repair | 46 | 1.682 | PUBLIC_PASS; 未提供算法终止原因 |
| 100 | caabs | 40 | 1.575 | PUBLIC_PASS; 未提供算法终止原因 |
| 300 | rabas_baseline | 30 | 9.951 | PUBLIC_PASS; budget |
| 300 | rabas | 135 | 5.896 | PUBLIC_PASS; no_feasible_bid |
| 300 | completion_first | — | 10.000 | TIMED_OUT; 未提供算法终止原因 |
| 300 | adaptive_repair | 142 | 5.363 | PUBLIC_PASS; 未提供算法终止原因 |
| 300 | caabs | 107 | 9.953 | PUBLIC_PASS; 未提供算法终止原因 |

## 独立合成测试完整结果

注意：以下全部是 **PUBLIC_MODEL_ONLY，非正式物理认证**。每规模预选2个独立采样结构族，确定性算法各1次；Completion First、SA、GA、ACO每实例使用41/43/47三个种子。均值/标准差只对成功返回且公共重放通过的运行计算；分母及所有超时/不可用行完整保留，缺失值不算0完成，也不算被RABAS击败。RT为实际Solver时间。

| 规模 | 算法 | 有效/总运行 | 完成数均值±σ | TCR均值±σ | TP均值±σ | TM均值±σ | BD均值±σ | RT均值±σ(s) | ≥95%预算 | 超时 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Small | rabas_baseline | 2/2 | 17.50±1.50 | 87.50±7.50% | 161.00±7.00 | 0.35±0.03 | 0.97±0.02 | 0.31±0.11 | 0/2 | 0 |
| Small | rabas | 2/2 | 18.00±2.00 | 90.00±10.00% | 157.00±20.00 | 0.35±0.04 | 0.80±0.08 | 0.40±0.31 | 0/2 | 0 |
| Small | completion_first | 6/6 | 17.00±0.82 | 85.00±4.08% | 150.00±11.40 | 0.38±0.03 | 0.91±0.04 | 0.20±0.12 | 0/6 | 0 |
| Small | adaptive_repair | 2/2 | 18.00±2.00 | 90.00±10.00% | 163.00±14.00 | 0.35±0.07 | 0.94±0.02 | 0.19±0.07 | 0/2 | 0 |
| Small | profit_first | 2/2 | 17.50±0.50 | 87.50±2.50% | 158.50±6.50 | 0.38±0.03 | 0.82±0.01 | 0.21±0.13 | 0/2 | 0 |
| Small | timeliness_first | 2/2 | 17.50±0.50 | 87.50±2.50% | 152.50±3.50 | 0.37±0.02 | 0.84±0.10 | 0.20±0.13 | 0/2 | 0 |
| Small | balance_first | 2/2 | 18.00±1.00 | 90.00±5.00% | 154.00±19.00 | 0.35±0.00 | 0.82±0.05 | 0.21±0.09 | 0/2 | 0 |
| Small | pressure_repair | 2/2 | 16.50±2.50 | 82.50±12.50% | 141.50±26.50 | 0.38±0.07 | 0.90±0.08 | 0.29±0.20 | 0/2 | 0 |
| Small | caabs | 2/2 | 16.50±2.50 | 82.50±12.50% | 136.00±33.00 | 0.39±0.07 | 0.92±0.02 | 0.37±0.08 | 0/2 | 0 |
| Small | dartis | 2/2 | 17.00±1.00 | 85.00±5.00% | 156.00±9.00 | 0.38±0.01 | 0.93±0.01 | 0.50±0.33 | 0/2 | 0 |
| Small | sa | 3/6 | 20.00±0.00 | 100.00±0.00% | 177.00±0.00 | 0.32±0.01 | 0.88±0.05 | 1.22±0.02 | 3/6 | 3 |
| Small | ga | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Small | aco | 3/6 | 20.00±0.00 | 100.00±0.00% | 177.00±0.00 | 0.31±0.01 | 0.81±0.05 | 1.63±0.09 | 3/6 | 3 |
| Small | mip | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Small | lavis | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Small | ppo | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Medium | rabas_baseline | 2/2 | 21.00±5.00 | 21.00±5.00% | 340.00±68.00 | 0.86±0.04 | 0.97±0.02 | 1.95±0.00 | 2/2 | 0 |
| Medium | rabas | 2/2 | 70.50±9.50 | 70.50±9.50% | 721.00±109.00 | 0.54±0.05 | 0.94±0.01 | 1.05±0.64 | 0/2 | 0 |
| Medium | completion_first | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Medium | adaptive_repair | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Medium | profit_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Medium | timeliness_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Medium | balance_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Medium | pressure_repair | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Medium | caabs | 2/2 | 43.00±4.00 | 43.00±4.00% | 416.00±18.00 | 0.71±0.02 | 0.93±0.00 | 1.95±0.00 | 2/2 | 0 |
| Medium | dartis | 2/2 | 9.50±5.50 | 9.50±5.50% | 121.00±67.00 | 0.91±0.05 | 0.98±0.01 | 1.95±0.00 | 2/2 | 0 |
| Medium | sa | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Medium | ga | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Medium | aco | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Medium | mip | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Medium | lavis | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Medium | ppo | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Large | rabas_baseline | 2/2 | 7.00±3.00 | 2.33±1.00% | 126.50±55.50 | 0.98±0.01 | 0.99±0.00 | 1.95±0.00 | 2/2 | 0 |
| Large | rabas | 2/2 | 98.00±48.00 | 32.67±16.00% | 965.50±480.50 | 0.77±0.10 | 0.94±0.02 | 1.96±0.00 | 2/2 | 0 |
| Large | completion_first | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Large | adaptive_repair | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | profit_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | timeliness_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | balance_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | pressure_repair | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | caabs | 2/2 | 37.00±6.00 | 12.33±2.00% | 395.00±58.00 | 0.92±0.01 | 0.96±0.01 | 1.95±0.00 | 2/2 | 0 |
| Large | dartis | 2/2 | 2.50±1.50 | 0.83±0.50% | 17.50±12.50 | 0.99±0.00 | 1.00±0.00 | 1.95±0.00 | 2/2 | 0 |
| Large | sa | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Large | ga | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Large | aco | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Large | mip | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Large | lavis | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Large | ppo | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |

初始解分组：SA/GA/ACO消费 completion_first 初始解；其他算法空计划或自行重建。旧Adapter也可能计算随后被算法丢弃的初始解，其时间仍计入预算，未修改基线以消除此项目既有行为。

### 每个预选实例及全部运行

| 族 | 任务 | 算法 | seed:完成数/状态 |
|---|---:|---|---|
| orbit_bands | 20 | rabas_baseline | 41:19/PUBLIC_PASS |
| orbit_bands | 20 | rabas | 41:20/PUBLIC_PASS |
| orbit_bands | 20 | completion_first | 41:18/PUBLIC_PASS; 43:17/PUBLIC_PASS; 47:18/PUBLIC_PASS |
| orbit_bands | 20 | adaptive_repair | 41:20/PUBLIC_PASS |
| orbit_bands | 20 | profit_first | 41:18/PUBLIC_PASS |
| orbit_bands | 20 | timeliness_first | 41:18/PUBLIC_PASS |
| orbit_bands | 20 | balance_first | 41:19/PUBLIC_PASS |
| orbit_bands | 20 | pressure_repair | 41:19/PUBLIC_PASS |
| orbit_bands | 20 | caabs | 41:19/PUBLIC_PASS |
| orbit_bands | 20 | dartis | 41:18/PUBLIC_PASS |
| orbit_bands | 20 | sa | 41:20/PUBLIC_PASS; 43:20/PUBLIC_PASS; 47:20/PUBLIC_PASS |
| orbit_bands | 20 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 20 | aco | 41:20/PUBLIC_PASS; 43:20/PUBLIC_PASS; 47:20/PUBLIC_PASS |
| orbit_bands | 20 | mip | 41:—/UNAVAILABLE |
| orbit_bands | 20 | lavis | 41:—/UNAVAILABLE |
| orbit_bands | 20 | ppo | 41:—/UNAVAILABLE |
| orbit_bands | 100 | rabas_baseline | 41:26/PUBLIC_PASS |
| orbit_bands | 100 | rabas | 41:80/PUBLIC_PASS |
| orbit_bands | 100 | completion_first | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 100 | adaptive_repair | 41:None/TIMED_OUT |
| orbit_bands | 100 | profit_first | 41:None/TIMED_OUT |
| orbit_bands | 100 | timeliness_first | 41:None/TIMED_OUT |
| orbit_bands | 100 | balance_first | 41:None/TIMED_OUT |
| orbit_bands | 100 | pressure_repair | 41:None/TIMED_OUT |
| orbit_bands | 100 | caabs | 41:39/PUBLIC_PASS |
| orbit_bands | 100 | dartis | 41:15/PUBLIC_PASS |
| orbit_bands | 100 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 100 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 100 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 100 | mip | 41:—/UNAVAILABLE |
| orbit_bands | 100 | lavis | 41:—/UNAVAILABLE |
| orbit_bands | 100 | ppo | 41:—/UNAVAILABLE |
| orbit_bands | 300 | rabas_baseline | 41:10/PUBLIC_PASS |
| orbit_bands | 300 | rabas | 41:146/PUBLIC_PASS |
| orbit_bands | 300 | completion_first | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 300 | adaptive_repair | 41:None/TIMED_OUT |
| orbit_bands | 300 | profit_first | 41:None/TIMED_OUT |
| orbit_bands | 300 | timeliness_first | 41:None/TIMED_OUT |
| orbit_bands | 300 | balance_first | 41:None/TIMED_OUT |
| orbit_bands | 300 | pressure_repair | 41:None/TIMED_OUT |
| orbit_bands | 300 | caabs | 41:31/PUBLIC_PASS |
| orbit_bands | 300 | dartis | 41:4/PUBLIC_PASS |
| orbit_bands | 300 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 300 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 300 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| orbit_bands | 300 | mip | 41:—/UNAVAILABLE |
| orbit_bands | 300 | lavis | 41:—/UNAVAILABLE |
| orbit_bands | 300 | ppo | 41:—/UNAVAILABLE |
| station_network | 20 | rabas_baseline | 41:16/PUBLIC_PASS |
| station_network | 20 | rabas | 41:16/PUBLIC_PASS |
| station_network | 20 | completion_first | 41:17/PUBLIC_PASS; 43:16/PUBLIC_PASS; 47:16/PUBLIC_PASS |
| station_network | 20 | adaptive_repair | 41:16/PUBLIC_PASS |
| station_network | 20 | profit_first | 41:17/PUBLIC_PASS |
| station_network | 20 | timeliness_first | 41:17/PUBLIC_PASS |
| station_network | 20 | balance_first | 41:17/PUBLIC_PASS |
| station_network | 20 | pressure_repair | 41:14/PUBLIC_PASS |
| station_network | 20 | caabs | 41:14/PUBLIC_PASS |
| station_network | 20 | dartis | 41:16/PUBLIC_PASS |
| station_network | 20 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 20 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 20 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 20 | mip | 41:—/UNAVAILABLE |
| station_network | 20 | lavis | 41:—/UNAVAILABLE |
| station_network | 20 | ppo | 41:—/UNAVAILABLE |
| station_network | 100 | rabas_baseline | 41:16/PUBLIC_PASS |
| station_network | 100 | rabas | 41:61/PUBLIC_PASS |
| station_network | 100 | completion_first | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 100 | adaptive_repair | 41:None/TIMED_OUT |
| station_network | 100 | profit_first | 41:None/TIMED_OUT |
| station_network | 100 | timeliness_first | 41:None/TIMED_OUT |
| station_network | 100 | balance_first | 41:None/TIMED_OUT |
| station_network | 100 | pressure_repair | 41:None/TIMED_OUT |
| station_network | 100 | caabs | 41:47/PUBLIC_PASS |
| station_network | 100 | dartis | 41:4/PUBLIC_PASS |
| station_network | 100 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 100 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 100 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 100 | mip | 41:—/UNAVAILABLE |
| station_network | 100 | lavis | 41:—/UNAVAILABLE |
| station_network | 100 | ppo | 41:—/UNAVAILABLE |
| station_network | 300 | rabas_baseline | 41:4/PUBLIC_PASS |
| station_network | 300 | rabas | 41:50/PUBLIC_PASS |
| station_network | 300 | completion_first | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 300 | adaptive_repair | 41:None/TIMED_OUT |
| station_network | 300 | profit_first | 41:None/TIMED_OUT |
| station_network | 300 | timeliness_first | 41:None/TIMED_OUT |
| station_network | 300 | balance_first | 41:None/TIMED_OUT |
| station_network | 300 | pressure_repair | 41:None/TIMED_OUT |
| station_network | 300 | caabs | 41:43/PUBLIC_PASS |
| station_network | 300 | dartis | 41:1/PUBLIC_PASS |
| station_network | 300 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 300 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 300 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| station_network | 300 | mip | 41:—/UNAVAILABLE |
| station_network | 300 | lavis | 41:—/UNAVAILABLE |
| station_network | 300 | ppo | 41:—/UNAVAILABLE |

### RABAS对各算法的完成数胜/平/负（按实例、先平均种子）

只有该实例双方所有预定种子都有效时才计比较；否则记不可比。共2实例/规模，样本很少，不宣称统计显著。

| 算法 | Small 胜/平/负/不可比 | Medium | Large |
|---|---|---|---|
| rabas_baseline | 1/1/0/0 | 2/0/0/0 | 2/0/0/0 |
| completion_first | 1/0/1/0 | 0/0/0/2 | 0/0/0/2 |
| adaptive_repair | 0/2/0/0 | 0/0/0/2 | 0/0/0/2 |
| profit_first | 1/0/1/0 | 0/0/0/2 | 0/0/0/2 |
| timeliness_first | 1/0/1/0 | 0/0/0/2 | 0/0/0/2 |
| balance_first | 1/0/1/0 | 0/0/0/2 | 0/0/0/2 |
| pressure_repair | 2/0/0/0 | 0/0/0/2 | 0/0/0/2 |
| caabs | 2/0/0/0 | 2/0/0/0 | 2/0/0/0 |
| dartis | 1/1/0/0 | 2/0/0/0 | 2/0/0/0 |
| sa | 0/1/0/1 | 0/0/0/2 | 0/0/0/2 |
| ga | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |
| aco | 0/1/0/1 | 0/0/0/2 | 0/0/0/2 |
| mip | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |
| lavis | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |
| ppo | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |

### 场景身份与结构

| 族/任务数 | 星数 | 窗口数 | 共享任务数 | 地面站 | SHA-256 |
|---|---:|---:|---:|---:|---|
| orbit_bands/20 | 2 | 64 | 15 | 0 | `066ade83c0340401691b332d954e3dba42592401c6a8366d4213cfbebf0cceab` |
| orbit_bands/100 | 5 | 529 | 75 | 0 | `7e9534d18bbfbe284920f32961c84d63932405b65ebcd2a6740af3aa5bac90e6` |
| orbit_bands/300 | 15 | 1639 | 225 | 0 | `9e54b89240221ce0d4c5555ee91827d7b50e484fcad4b45fd302dad6d96dc35a` |
| station_network/20 | 2 | 71 | 15 | 2 | `20cdade69a735bd030e74d49d243a36b057488a730212ad1c9b69c045992a4de` |
| station_network/100 | 5 | 580 | 75 | 2 | `a1f9bae4ddea78eba14c7b18eb7f73161c796a67858f86c2fbf80be3e097828e` |
| station_network/300 | 15 | 1770 | 225 | 2 | `7b28b1b57c0ea4628afcebf0853fe8262cd9feb89bf181ebcd1cdab4ee262373` |

### 最终RABAS退出原因与实际计算量

| 族 | 任务数 | 退出原因 | RT(s) | 搜索宽度最小–最大 | 构造器调用 | 公共核验 | 机会离散估计 | 中标 |
|---|---:|---|---:|---|---:|---:|---:|---:|
| orbit_bands | 20 | completed | 0.086 | 8–8 | 112 | 1108 | 308 | 10 |
| orbit_bands | 100 | no_feasible_bid | 0.400 | 1–1 | 444 | 5879 | 291 | 41 |
| orbit_bands | 300 | budget | 1.956 | 1–1 | 666 | 23687 | 1621 | 73 |
| station_network | 20 | no_feasible_bid | 0.713 | 4–8 | 893 | 12249 | 405 | 9 |
| station_network | 100 | no_feasible_bid | 1.690 | 1–1 | 1561 | 25523 | 403 | 31 |
| station_network | 300 | budget | 1.954 | 1–1 | 1868 | 21325 | 1030 | 25 |

所有RABAS最终独立返回均公共重放通过，6/6；最大包均为2，确实构造多任务Bundle。其他算法的内部停止原因若未提供，不从“提前返回”猜测为收敛；超时代表外部2秒Solver预算截止，进程失败和不可用另列。RV按原指标为None，没有伪造稳定性分数。各随机种子结果完整列于上表。

## 真实场景统一预览核验对照

3秒预算，seed41；RABAS使用最新1.1.1四次结果，其他八算法使用前轮已执行且实现/参数/场景/公共物理版本未变的结果，没有多次运行取最好值。前轮RABAS1.1.0的原始四行仍存档，不计入此表。输入来源族相近，仅工程核验，不是严格held-out。有效指标由原Controller核验器重算。

### 分组均值

| 规模 | 算法 | 有效/预选 | 平均完成 | TCR | TP | TM | BD | Solver RT(s) | 核验结果 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Small | rabas | 2/2 | 20.000 | 1.000 | 119.500 | 0.455 | 0.522 | 0.390 | CONTROLLER_VERIFIER_PASS |
| Small | completion_first | 2/2 | 20.000 | 1.000 | 119.500 | 0.200 | 0.466 | 0.114 | CONTROLLER_VERIFIER_PASS |
| Small | adaptive_repair | 2/2 | 20.000 | 1.000 | 119.500 | 0.116 | 0.477 | 0.441 | CONTROLLER_VERIFIER_PASS |
| Small | profit_first | 2/2 | 20.000 | 1.000 | 119.500 | 0.229 | 0.437 | 0.183 | CONTROLLER_VERIFIER_PASS |
| Small | timeliness_first | 2/2 | 20.000 | 1.000 | 119.500 | 0.194 | 0.402 | 0.212 | CONTROLLER_VERIFIER_PASS |
| Small | balance_first | 2/2 | 20.000 | 1.000 | 119.500 | 0.196 | 0.442 | 0.186 | CONTROLLER_VERIFIER_PASS |
| Small | pressure_repair | 2/2 | 20.000 | 1.000 | 119.500 | 0.116 | 0.477 | 0.180 | CONTROLLER_VERIFIER_PASS |
| Small | caabs | 2/2 | 20.000 | 1.000 | 119.500 | 0.400 | 0.223 | 1.535 | CONTROLLER_VERIFIER_PASS |
| Small | dartis | 2/2 | 20.000 | 1.000 | 119.500 | 0.469 | 0.515 | 2.259 | CONTROLLER_VERIFIER_PASS |
| Medium | rabas | 1/1 | 98.000 | 0.980 | 476.000 | 0.448 | 0.643 | 2.703 | CONTROLLER_VERIFIER_PASS |
| Medium | completion_first | 1/1 | 98.000 | 0.980 | 476.000 | 0.055 | 0.476 | 1.382 | CONTROLLER_VERIFIER_PASS |
| Medium | adaptive_repair | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Medium | profit_first | 1/1 | 98.000 | 0.980 | 476.000 | 0.057 | 0.491 | 1.813 | CONTROLLER_VERIFIER_PASS |
| Medium | timeliness_first | 1/1 | 98.000 | 0.980 | 476.000 | 0.054 | 0.434 | 1.862 | CONTROLLER_VERIFIER_PASS |
| Medium | balance_first | 1/1 | 98.000 | 0.980 | 476.000 | 0.053 | 0.460 | 1.900 | CONTROLLER_VERIFIER_PASS |
| Medium | pressure_repair | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Medium | caabs | 1/1 | 24.000 | 0.240 | 113.000 | 0.799 | 0.766 | 2.985 | CONTROLLER_VERIFIER_PASS |
| Medium | dartis | 1/1 | 1.000 | 0.010 | 10.000 | 0.991 | 0.991 | 2.955 | CONTROLLER_VERIFIER_PASS |
| Large | rabas | 0/1 | — | — | — | — | — | — | VERIFICATION_REJECTED |
| Large | completion_first | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Large | adaptive_repair | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Large | profit_first | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Large | timeliness_first | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Large | balance_first | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Large | pressure_repair | 0/1 | — | — | — | — | — | — | TIMED_OUT |
| Large | caabs | 0/1 | — | — | — | — | — | — | VERIFICATION_REJECTED |
| Large | dartis | 1/1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 2.951 | CONTROLLER_VERIFIER_PASS |

### 每个预选真实输入

| 规模/星数/任务数 | 算法 | 合法预览完成 | Solver RT(s) | 核验RT(s) | 状态 |
|---|---|---:|---:|---:|---|
| Large/20/500 | adaptive_repair | — | — | — | TIMED_OUT |
| Large/20/500 | balance_first | — | — | — | TIMED_OUT |
| Large/20/500 | caabs | — | 2.952 | 8.105 | VERIFICATION_REJECTED |
| Large/20/500 | completion_first | — | — | — | TIMED_OUT |
| Large/20/500 | dartis | 0 | 2.951 | 1.130 | CONTROLLER_VERIFIER_PASS |
| Large/20/500 | pressure_repair | — | — | — | TIMED_OUT |
| Large/20/500 | profit_first | — | — | — | TIMED_OUT |
| Large/20/500 | rabas | — | 2.956 | 8.299 | VERIFICATION_REJECTED |
| Large/20/500 | timeliness_first | — | — | — | TIMED_OUT |
| Medium/50/100 | adaptive_repair | — | — | — | TIMED_OUT |
| Medium/50/100 | balance_first | 98 | 1.900 | 18.088 | CONTROLLER_VERIFIER_PASS |
| Medium/50/100 | caabs | 24 | 2.985 | 13.902 | CONTROLLER_VERIFIER_PASS |
| Medium/50/100 | completion_first | 98 | 1.382 | 16.518 | CONTROLLER_VERIFIER_PASS |
| Medium/50/100 | dartis | 1 | 2.955 | 12.473 | CONTROLLER_VERIFIER_PASS |
| Medium/50/100 | pressure_repair | — | — | — | TIMED_OUT |
| Medium/50/100 | profit_first | 98 | 1.813 | 16.676 | CONTROLLER_VERIFIER_PASS |
| Medium/50/100 | rabas | 98 | 2.703 | 17.339 | CONTROLLER_VERIFIER_PASS |
| Medium/50/100 | timeliness_first | 98 | 1.862 | 16.921 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | adaptive_repair | 20 | 0.337 | 6.383 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | balance_first | 20 | 0.170 | 6.306 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | caabs | 20 | 1.461 | 6.574 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | completion_first | 20 | 0.115 | 6.373 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | dartis | 20 | 2.097 | 6.287 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | pressure_repair | 20 | 0.149 | 6.306 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | profit_first | 20 | 0.168 | 6.374 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | rabas | 20 | 0.277 | 6.383 | CONTROLLER_VERIFIER_PASS |
| Small/10/20 | timeliness_first | 20 | 0.183 | 6.319 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | adaptive_repair | 20 | 0.545 | 6.568 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | balance_first | 20 | 0.202 | 6.772 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | caabs | 20 | 1.610 | 6.457 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | completion_first | 20 | 0.114 | 6.506 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | dartis | 20 | 2.421 | 6.592 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | pressure_repair | 20 | 0.211 | 6.525 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | profit_first | 20 | 0.198 | 6.467 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | rabas | 20 | 0.502 | 6.440 | CONTROLLER_VERIFIER_PASS |
| Small/20/20 | timeliness_first | 20 | 0.240 | 7.002 | CONTROLLER_VERIFIER_PASS |

全部真实场景SHA：Small/10=`bc9f47038a114dff1658b8f5d6c88417a2d438a193a2f4b560cdc695fdd3bbf7`；Small/20=`eeafada8b6901f2fed2b6c1f4eb850110a571b4b0c1bdd3f25a6ba8a03f10c2b`；Medium/50=`d8ca6e8f71585e216ca5c39f55b2dbab439d717ddf50e485f7dd38928e5ca7c5`；Large/20=`1ee36edc00612eb2ef1bd67972e064b565cab813c0b6a5448818b118be5a2724`。文件只读未改。

Large的RABAS候选14、CAABS候选40都因PREVIEW_PHYSICS_CHECK_FAILED被拒绝，**不计入完成数、TCR或TP**；DARTIS空计划0通过预览也不是有用的非空观测认证。超时没有指标，不填0。Medium预览RABAS与Completion First/Profit/Timeliness/Balance同为98，RABAS的Solver RT更高。验证RT单列，不混入Solver RT，也不把较长认证成本隐藏掉。

## 实际HTTP → Worker → Controller → SQLite

使用原API、真实spawn Worker、Controller和独立临时SQLite，没有替换物理认证器或公共约束。每规模一个预选输入，分别提交planning_preview及formal。只有成功的预览事务有指标；失败事务metrics为空，形式认证门禁未放宽。

| 规模 | 模式 | 状态 | 完成 | RT(s) | 原错误码 | Run ID |
|---|---|---|---:|---:|---|---|
| Small | planning_preview | SUCCEEDED | 20 | 0.290 | — | `45fdccaa-7dc6-4801-ae88-ab7418388b47` |
| Small | formal | FAILED | — | — | CONTINUOUS_INCONCLUSIVE | `e669008d-ea55-415f-bf88-bf074ccdc4c7` |
| Medium | planning_preview | SUCCEEDED | 98 | 2.888 | — | `ce6b3ab5-124b-49ff-b68b-b40b3b17642e` |
| Medium | formal | FAILED | — | — | CONTINUOUS_INCONCLUSIVE | `876073c0-ca90-4330-a7ba-9ec69463e087` |
| Large | planning_preview | FAILED | — | — | PREVIEW_REJECTED | `dbc0ec4b-d947-4f81-a914-cbba816bdd09` |
| Large | formal | FAILED | — | — | CONTINUOUS_INCONCLUSIVE | `d0069841-dc2b-4de9-884b-7db102a31f68` |

三个formal均为CONTINUOUS_INCONCLUSIVE / UNTRUSTED_PHYSICAL_SETTINGS。需要数据与物理认证负责人提供当前版本可信来源的正式场景，再评估正式非空调度性能；不通过修改原JSON、放松遮挡或虚构证书来绕过此限制。

## 测试交付、边界及后续方向

最新完整测试：`python -m unittest discover -s tests -v`，718项、50项跳过、无失败，173.184秒。跳过仍按项目现有依赖/opt-in条件，不称718项全部实际执行。原22项RABAS专项、10项新增机制/回归、2项预算实验协议测试及原集成测试均通过。早期全套曾因两项参数schema缺说明失败，已修复并完整重跑；失败日志保留。

新增反例覆盖动态共享变单星、目标增量与BD/负优先级截断、latest/原始网格gap、缓存对新计划和自定义约束重新检查、不同首任务/真实Bundle、1换2严格改善、最后重放预算、共享地面站center/latest/gap、身份改名。原测试继续覆盖任务唯一、转向、资源、地球遮挡拒绝、过期报价、取消和上限。

仍需改进：高压力宽度1易陷入早期局部选择；多起点/修复尚无默认收益；动态稀缺样本有限且有成本；仍全星重报；地面站竞争场景小型耗时和收益不够好；真实大型来源/物理认证不满足验收。正式性能目标未全部达到。下一轮如用最终orbit_bands/station_network结果指导优化，必须将其转验证并重新预留独立来源；本轮没有这样做。

## 本地提交与复现

本轮无Push、PR或main修改。代码冻结后只补实验脚本与文档。提交列表（最后文档提交可用下面命令查看，避免在文档中自引用其SHA）：

```text
49a14af perf(rabas): reduce candidate evaluation overhead
6809f32 fix(rabas): preserve feasible bids on search limits
075ec1f feat(rabas): add bounded adaptive bundle auction search
b3968a0 perf(rabas): freeze validation-selected search defaults
df42a76 fix(rabas): describe new parameters in registry schema
4fbaa80 fix(rabas): preserve clipped objective edge-case semantics
0fabfcb fix(rabas): reject over-budget benchmark returns
cd76718 test(rabas): reserve new held-out families after coverage regression
cfe53ad fix(rabas): restore diversified downlink placement and bounded gaps
7e2ea6a test(rabas): add reproducible profiling and controller checks
```

```bash
cd /home/asus/projects/eos-course-runtime-rabas-cross-scale
export PYTHONDONTWRITEBYTECODE=1
export EOS_OREKIT_DATA="$PWD/utils/orekit-data.zip"
RABAS_PY=/home/asus/eos-course-runtime/.venv/bin/python
"$RABAS_PY" -m unittest discover -s tests -v
# 输出目录必须不存在；完整套件串行，不要并发竞争CPU。
"$RABAS_PY" scripts/benchmark_rabas_cross_scale.py --split heldout --budget 2 --output /tmp/rabas-reproduce-heldout
"$RABAS_PY" scripts/benchmark_rabas_cross_scale.py --split validation --budget 10 --algorithms rabas completion_first adaptive_repair caabs --output /tmp/rabas-reproduce-validation
"$RABAS_PY" scripts/benchmark_rabas_real.py --budget 3 --output /tmp/rabas-reproduce-real
"$RABAS_PY" scripts/verify_rabas_controller.py --output /tmp/rabas-reproduce-controller
"$RABAS_PY" scripts/profile_rabas_cross_scale.py --output /tmp/rabas-reproduce-profile
git log --oneline 89dff80..HEAD
git status --short
```

上面长预算命令覆盖完整验证划分，本文10秒补充实际只执行capacity/100、300及五算法，精确job JSON在证据目录。首轮消融记录的是冻结前配置；复现时需要显式future_aware_rank=true作为参考，再改单个开关。当前1.1.1重跑同一配置不能冒充历史1.1.0结果。

原始证据保存在独立克隆的 `output/rabas-cross-scale-20261020/`（Git已忽略的运行输出目录），原始临时副本为 `/tmp/rabas-cross-scale-evidence/`。含两轮全部144+144运行、原始及纠正预算分类、40次真实核验记录、6次Controller运行、48行最终消融及早期阶段数据、Profile与全量测试日志。原始失败行未删除。SHA索引为 `evidence-sha256.json`，不将数据库/大日志/临时实验结果加入Git。关键内容完整转录于本报告，避免只交一个临时链接。

说明文档及本报告另复制至用户指定原工作区 `docs/phase2/`，只增加这两个新文件，不提交或覆盖原工作区其他成员改动。交付检查口径：文档本地提交后以`git status --short`确认为干净；运行输出保持ignored。最终文档提交标题为`docs(rabas): report cross-scale evidence and optimization guide`，其SHA见交付时的Git回执。

## 附录：首轮独立测试，现已全部转为验证

以下保留1.1.0首轮所有预选实例及失败结果，**不得作为本轮最终独立结论**。识别downlink回归后整批转验证，而非只移走不利实例；后续参数默认不变，通用下传覆盖修复后另用新族作最终测试。超预算返回经复查排除，原始JSON也保留。

### 首轮已转验证的完整结果

注意：以下全部是 **PUBLIC_MODEL_ONLY，非正式物理认证**。每规模预选2个结构族（本批现已转验证），确定性算法各1次；Completion First、SA、GA、ACO每实例使用41/43/47三个种子。均值/标准差只对成功返回且公共重放通过的运行计算；分母及所有超时/不可用行完整保留，缺失值不算0完成，也不算被RABAS击败。RT为实际Solver时间。

| 规模 | 算法 | 有效/总运行 | 完成数均值±σ | TCR均值±σ | TP均值±σ | TM均值±σ | BD均值±σ | RT均值±σ(s) | ≥95%预算 | 超时 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Small | rabas_baseline | 2/2 | 11.00±0.00 | 55.00±0.00% | 75.00±1.00 | 0.54±0.00 | 0.91±0.02 | 0.25±0.12 | 0/2 | 0 |
| Small | rabas | 2/2 | 7.50±3.50 | 37.50±17.50% | 51.00±23.00 | 0.68±0.15 | 0.95±0.01 | 0.05±0.01 | 0/2 | 0 |
| Small | completion_first | 6/6 | 12.33±0.75 | 61.67±3.73% | 74.33±7.27 | 0.49±0.03 | 0.96±0.04 | 0.20±0.19 | 0/6 | 0 |
| Small | adaptive_repair | 2/2 | 13.00±0.00 | 65.00±0.00% | 91.00±4.00 | 0.46±0.00 | 0.97±0.01 | 0.18±0.11 | 0/2 | 0 |
| Small | profit_first | 2/2 | 11.50±0.50 | 57.50±2.50% | 77.00±5.00 | 0.52±0.02 | 0.98±0.01 | 0.24±0.20 | 0/2 | 0 |
| Small | timeliness_first | 2/2 | 12.00±0.00 | 60.00±0.00% | 71.50±2.50 | 0.51±0.01 | 0.98±0.02 | 0.26±0.23 | 0/2 | 0 |
| Small | balance_first | 2/2 | 12.00±1.00 | 60.00±5.00% | 66.50±12.50 | 0.50±0.05 | 0.93±0.02 | 0.26±0.21 | 0/2 | 0 |
| Small | pressure_repair | 2/2 | 11.00±1.00 | 55.00±5.00% | 67.50±5.50 | 0.54±0.04 | 0.99±0.00 | 0.28±0.23 | 0/2 | 0 |
| Small | caabs | 2/2 | 10.50±0.50 | 52.50±2.50% | 67.00±2.00 | 0.57±0.02 | 0.95±0.03 | 0.12±0.00 | 0/2 | 0 |
| Small | dartis | 2/2 | 11.50±0.50 | 57.50±2.50% | 63.50±1.50 | 0.52±0.02 | 0.99±0.00 | 0.33±0.27 | 0/2 | 0 |
| Small | sa | 3/6 | 13.67±0.47 | 68.33±2.36% | 80.00±6.38 | 0.44±0.02 | 0.98±0.01 | 1.35±0.02 | 3/6 | 3 |
| Small | ga | 0/6 | — | —% | — | — | — | — | 6/6 | 5 |
| Small | aco | 3/6 | 11.33±0.47 | 56.67±2.36% | 61.33±2.62 | 0.53±0.01 | 0.95±0.04 | 0.89±0.02 | 3/6 | 3 |
| Small | mip | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Small | lavis | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Small | ppo | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Medium | rabas_baseline | 2/2 | 17.00±5.00 | 17.00±5.00% | 133.50±34.50 | 0.86±0.04 | 0.98±0.00 | 1.95±0.00 | 2/2 | 0 |
| Medium | rabas | 2/2 | 21.50±17.50 | 21.50±17.50% | 107.00±87.00 | 0.82±0.14 | 0.98±0.00 | 0.14±0.05 | 0/2 | 0 |
| Medium | completion_first | 3/6 | 41.00±2.16 | 41.00±2.16% | 203.00±4.32 | 0.66±0.02 | 0.98±0.00 | 1.30±0.05 | 3/6 | 3 |
| Medium | adaptive_repair | 2/2 | 36.00±7.00 | 36.00±7.00% | 215.00±31.00 | 0.70±0.06 | 0.97±0.00 | 1.43±0.22 | 0/2 | 0 |
| Medium | profit_first | 1/2 | 42.00±0.00 | 42.00±0.00% | 303.00±0.00 | 0.66±0.00 | 0.98±0.00 | 1.46±0.00 | 1/2 | 1 |
| Medium | timeliness_first | 1/2 | 39.00±0.00 | 39.00±0.00% | 206.00±0.00 | 0.68±0.00 | 0.98±0.00 | 1.59±0.00 | 1/2 | 1 |
| Medium | balance_first | 1/2 | 42.00±0.00 | 42.00±0.00% | 199.00±0.00 | 0.65±0.00 | 0.97±0.00 | 1.05±0.00 | 1/2 | 0 |
| Medium | pressure_repair | 1/2 | 44.00±0.00 | 44.00±0.00% | 238.00±0.00 | 0.64±0.00 | 0.98±0.00 | 1.82±0.00 | 1/2 | 0 |
| Medium | caabs | 2/2 | 25.50±13.50 | 25.50±13.50% | 143.50±64.50 | 0.79±0.11 | 0.97±0.01 | 0.93±0.39 | 0/2 | 0 |
| Medium | dartis | 2/2 | 19.00±15.00 | 19.00±15.00% | 105.00±83.00 | 0.84±0.13 | 0.99±0.00 | 1.95±0.00 | 2/2 | 0 |
| Medium | sa | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Medium | ga | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Medium | aco | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Medium | mip | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Medium | lavis | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Medium | ppo | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Large | rabas_baseline | 2/2 | 3.00±3.00 | 1.00±1.00% | 26.50±26.50 | 0.99±0.01 | 1.00±0.00 | 1.44±0.51 | 1/2 | 0 |
| Large | rabas | 2/2 | 61.00±57.00 | 20.33±19.00% | 350.50±319.50 | 0.83±0.16 | 0.98±0.01 | 1.10±0.85 | 1/2 | 0 |
| Large | completion_first | 0/6 | — | —% | — | — | — | — | 6/6 | 5 |
| Large | adaptive_repair | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | profit_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | timeliness_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | balance_first | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | pressure_repair | 0/2 | — | —% | — | — | — | — | 2/2 | 2 |
| Large | caabs | 2/2 | 28.50±12.50 | 9.50±4.17% | 142.50±71.50 | 0.92±0.04 | 0.97±0.01 | 1.89±0.06 | 1/2 | 0 |
| Large | dartis | 2/2 | 4.50±3.50 | 1.50±1.17% | 19.00±18.00 | 0.99±0.01 | 1.00±0.00 | 1.95±0.00 | 2/2 | 0 |
| Large | sa | 0/6 | — | —% | — | — | — | — | 5/6 | 5 |
| Large | ga | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Large | aco | 0/6 | — | —% | — | — | — | — | 6/6 | 6 |
| Large | mip | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Large | lavis | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |
| Large | ppo | 0/2 | — | —% | — | — | — | — | 0/2 | 0 |

初始解分组：SA/GA/ACO消费 completion_first 初始解；其他算法空计划或自行重建。旧Adapter也可能计算随后被算法丢弃的初始解，其时间仍计入预算，未修改基线以消除此项目既有行为。

### 每个预选实例及全部运行

| 族 | 任务 | 算法 | seed:完成数/状态 |
|---|---:|---|---|
| hub | 20 | rabas_baseline | 41:11/PUBLIC_PASS |
| hub | 20 | rabas | 41:11/PUBLIC_PASS |
| hub | 20 | completion_first | 41:11/PUBLIC_PASS; 43:13/PUBLIC_PASS; 47:13/PUBLIC_PASS |
| hub | 20 | adaptive_repair | 41:13/PUBLIC_PASS |
| hub | 20 | profit_first | 41:12/PUBLIC_PASS |
| hub | 20 | timeliness_first | 41:12/PUBLIC_PASS |
| hub | 20 | balance_first | 41:11/PUBLIC_PASS |
| hub | 20 | pressure_repair | 41:12/PUBLIC_PASS |
| hub | 20 | caabs | 41:11/PUBLIC_PASS |
| hub | 20 | dartis | 41:11/PUBLIC_PASS |
| hub | 20 | sa | 41:14/PUBLIC_PASS; 43:14/PUBLIC_PASS; 47:13/PUBLIC_PASS |
| hub | 20 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| hub | 20 | aco | 41:11/PUBLIC_PASS; 43:11/PUBLIC_PASS; 47:12/PUBLIC_PASS |
| hub | 20 | mip | 41:—/UNAVAILABLE |
| hub | 20 | lavis | 41:—/UNAVAILABLE |
| hub | 20 | ppo | 41:—/UNAVAILABLE |
| hub | 100 | rabas_baseline | 41:22/PUBLIC_PASS |
| hub | 100 | rabas | 41:39/PUBLIC_PASS |
| hub | 100 | completion_first | 41:38/PUBLIC_PASS; 43:43/PUBLIC_PASS; 47:42/PUBLIC_PASS |
| hub | 100 | adaptive_repair | 41:43/PUBLIC_PASS |
| hub | 100 | profit_first | 41:42/PUBLIC_PASS |
| hub | 100 | timeliness_first | 41:39/PUBLIC_PASS |
| hub | 100 | balance_first | 41:42/PUBLIC_PASS |
| hub | 100 | pressure_repair | 41:44/PUBLIC_PASS |
| hub | 100 | caabs | 41:39/PUBLIC_PASS |
| hub | 100 | dartis | 41:34/PUBLIC_PASS |
| hub | 100 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| hub | 100 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| hub | 100 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| hub | 100 | mip | 41:—/UNAVAILABLE |
| hub | 100 | lavis | 41:—/UNAVAILABLE |
| hub | 100 | ppo | 41:—/UNAVAILABLE |
| hub | 300 | rabas_baseline | 41:6/PUBLIC_PASS |
| hub | 300 | rabas | 41:118/PUBLIC_PASS |
| hub | 300 | completion_first | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/OVER_BUDGET |
| hub | 300 | adaptive_repair | 41:None/TIMED_OUT |
| hub | 300 | profit_first | 41:None/TIMED_OUT |
| hub | 300 | timeliness_first | 41:None/TIMED_OUT |
| hub | 300 | balance_first | 41:None/TIMED_OUT |
| hub | 300 | pressure_repair | 41:None/TIMED_OUT |
| hub | 300 | caabs | 41:41/PUBLIC_PASS |
| hub | 300 | dartis | 41:8/PUBLIC_PASS |
| hub | 300 | sa | 41:None/TIMED_OUT; 43:None/PROCESS_FAILED; 47:None/TIMED_OUT |
| hub | 300 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| hub | 300 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| hub | 300 | mip | 41:—/UNAVAILABLE |
| hub | 300 | lavis | 41:—/UNAVAILABLE |
| hub | 300 | ppo | 41:—/UNAVAILABLE |
| downlink | 20 | rabas_baseline | 41:11/PUBLIC_PASS |
| downlink | 20 | rabas | 41:4/PUBLIC_PASS |
| downlink | 20 | completion_first | 41:13/PUBLIC_PASS; 43:12/PUBLIC_PASS; 47:12/PUBLIC_PASS |
| downlink | 20 | adaptive_repair | 41:13/PUBLIC_PASS |
| downlink | 20 | profit_first | 41:11/PUBLIC_PASS |
| downlink | 20 | timeliness_first | 41:12/PUBLIC_PASS |
| downlink | 20 | balance_first | 41:13/PUBLIC_PASS |
| downlink | 20 | pressure_repair | 41:10/PUBLIC_PASS |
| downlink | 20 | caabs | 41:10/PUBLIC_PASS |
| downlink | 20 | dartis | 41:12/PUBLIC_PASS |
| downlink | 20 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 20 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/OVER_BUDGET |
| downlink | 20 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 20 | mip | 41:—/UNAVAILABLE |
| downlink | 20 | lavis | 41:—/UNAVAILABLE |
| downlink | 20 | ppo | 41:—/UNAVAILABLE |
| downlink | 100 | rabas_baseline | 41:12/PUBLIC_PASS |
| downlink | 100 | rabas | 41:4/PUBLIC_PASS |
| downlink | 100 | completion_first | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 100 | adaptive_repair | 41:29/PUBLIC_PASS |
| downlink | 100 | profit_first | 41:None/TIMED_OUT |
| downlink | 100 | timeliness_first | 41:None/TIMED_OUT |
| downlink | 100 | balance_first | 41:None/OVER_BUDGET |
| downlink | 100 | pressure_repair | 41:None/OVER_BUDGET |
| downlink | 100 | caabs | 41:12/PUBLIC_PASS |
| downlink | 100 | dartis | 41:4/PUBLIC_PASS |
| downlink | 100 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 100 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 100 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 100 | mip | 41:—/UNAVAILABLE |
| downlink | 100 | lavis | 41:—/UNAVAILABLE |
| downlink | 100 | ppo | 41:—/UNAVAILABLE |
| downlink | 300 | rabas_baseline | 41:0/PUBLIC_PASS |
| downlink | 300 | rabas | 41:4/PUBLIC_PASS |
| downlink | 300 | completion_first | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 300 | adaptive_repair | 41:None/TIMED_OUT |
| downlink | 300 | profit_first | 41:None/TIMED_OUT |
| downlink | 300 | timeliness_first | 41:None/TIMED_OUT |
| downlink | 300 | balance_first | 41:None/TIMED_OUT |
| downlink | 300 | pressure_repair | 41:None/TIMED_OUT |
| downlink | 300 | caabs | 41:16/PUBLIC_PASS |
| downlink | 300 | dartis | 41:1/PUBLIC_PASS |
| downlink | 300 | sa | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 300 | ga | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 300 | aco | 41:None/TIMED_OUT; 43:None/TIMED_OUT; 47:None/TIMED_OUT |
| downlink | 300 | mip | 41:—/UNAVAILABLE |
| downlink | 300 | lavis | 41:—/UNAVAILABLE |
| downlink | 300 | ppo | 41:—/UNAVAILABLE |

### RABAS对各算法的完成数胜/平/负（按实例、先平均种子）

只有该实例双方所有预定种子都有效时才计比较；否则记不可比。共2实例/规模，样本很少，不宣称统计显著。

| 算法 | Small 胜/平/负/不可比 | Medium | Large |
|---|---|---|---|
| rabas_baseline | 0/1/1/0 | 1/0/1/0 | 2/0/0/0 |
| completion_first | 0/0/2/0 | 0/0/1/1 | 0/0/0/2 |
| adaptive_repair | 0/0/2/0 | 0/0/2/0 | 0/0/0/2 |
| profit_first | 0/0/2/0 | 0/0/1/1 | 0/0/0/2 |
| timeliness_first | 0/0/2/0 | 0/1/0/1 | 0/0/0/2 |
| balance_first | 0/1/1/0 | 0/0/1/1 | 0/0/0/2 |
| pressure_repair | 0/0/2/0 | 0/0/1/1 | 0/0/0/2 |
| caabs | 0/1/1/0 | 0/1/1/0 | 1/0/1/0 |
| dartis | 0/1/1/0 | 1/1/0/0 | 2/0/0/0 |
| sa | 0/0/1/1 | 0/0/0/2 | 0/0/0/2 |
| ga | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |
| aco | 0/0/1/1 | 0/0/0/2 | 0/0/0/2 |
| mip | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |
| lavis | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |
| ppo | 0/0/0/2 | 0/0/0/2 | 0/0/0/2 |

### 场景身份与结构

| 族/任务数 | 星数 | 窗口数 | 共享任务数 | 地面站 | SHA-256 |
|---|---:|---:|---:|---:|---|
| hub/20 | 2 | 56 | 8 | 0 | `6073d38c826e4023931b0bda8ade3bb618c2d32a9881cc730ce6c955f310e7df` |
| hub/100 | 5 | 421 | 60 | 0 | `f83ec73d09f6c43dfb9c23a4201169d960033eed6d2ca59fd1742e4bcb7e1d00` |
| hub/300 | 15 | 1388 | 187 | 0 | `4ddf6b4bea8eeb28cd7361a1d43c313e52fdf91d731b37ff82654c0f29e44e5b` |
| downlink/20 | 2 | 71 | 15 | 1 | `e2e6900a5008ac9fa5155dc3fa74d22c121483f8473801130fa32c56c3b3e60d` |
| downlink/100 | 5 | 448 | 63 | 1 | `6e84b2739e6528dd225dabc9b128c94f15897de9e01f7277c355d6cbdb28e67a` |
| downlink/300 | 15 | 1367 | 191 | 1 | `5e98a51272186601a46289d175caa2b7172f68ebc76251a31c6981db9567e7f0` |
