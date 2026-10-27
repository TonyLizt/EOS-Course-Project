# EOS 10/30星场景交接（2026-10-28）

一分钟：本次新增四份10/30星机制开发场景，使用原 Canonical Bundle、Loader、Registry、成熟工作台；ZIP额外含50星展示附件。没有重写UI或科学算法。

已完成14项真实运行，均为 SUCCEEDED / SAMPLED_PHYSICAL_PASS / NOT_CERTIFIED。R30-main-01的CAABS为106/144、Score71.155511，比FCFS/EDF高4.430845；RABAS93/144落后。其余负结果、持平与单项展示均保留。

**先读 BASELINE_AND_DIFF.md 和 IMPORT_AND_VERIFY.md。** Git分支是场景增量，不包含开发前已经存在但未提交的216份运行代码差异。ZIP的 baseline_runtime 是独立标注的既有运行依赖快照，不是本次场景贡献。直接克隆Git分支能读取场景，不能据此宣称已具备当前统一物理/预算执行合同。

Git：data/scenarios/hmt-web-10-30-v1（四份）；scripts/hmt_scene_handoff（便携校验/显式注册/可选生成）；docs/hmt-scenes-20261028。
ZIP：scenarios（五份原件）、generation（原生成版本与便携入口）、validation、results（14项原始证据）、docs、baseline_runtime。

不含模型权重、物理候选缓存、在线SQLite、虚拟环境、凭据和99项历史数据库。无需连接发送方8910即可完成离线读取。没有新建性能实验，没有创建PR，没有修改main/master。
