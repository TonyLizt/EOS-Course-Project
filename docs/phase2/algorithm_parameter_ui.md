# 算法简介与参数表单统一修复（2026-10-18）

## 范围与根因

基线为 main `3e9413d`（已合并 RABAS PR #22），分支 `fix/algorithm-parameter-ui`。未修改算法求解、指标、Controller/Worker、数据库或物理约束。

原 `console.js.catalog()` 对全部算法无条件渲染 `JSON.stringify(a.parameters)` 的 `<pre>`，因此 MIP 的 `anyOf`、`additionalProperties` 等直接出现在普通配置区。它并非 MIP 特有缺陷：所有有参数算法都受影响，空参数算法也出现空 Schema/JSON 编辑器。Cesium 则只显示运行参数 JSON，详情弹窗又把说明与整份 Run 配置串联；三处呈现职责不一致。多数参数缺少描述、自动英文 title，RABAS 的部分参数已有描述，但旧页面并未使用它们生成表单。重复的 description/strategy 也会重复显示。

## 实际注册清单（不是凭文档推断）

| 条目 | 参数类型 / 检查结果 |
| --- | --- |
| MIP | 可空候选上限、布尔日志；保留 PuLP/CBC 可用性提示 |
| 收益优先、时效优先、负载均衡、冲突压力修复 | 可空候选上限 |
| SA | 可空整数、浮点数，含开闭区间范围 |
| GA | 可空候选上限、种群/代数、交叉/变异概率 |
| ACO | 可空候选上限、蚂蚁/轮数、信息素与启发因子权重、挥发率 |
| PPO | 空参数对象；保留可信模型/依赖未接入的禁用状态 |
| CAABS | 整数上限、布尔冲突预筛 |
| RABAS | 整数、浮点成本权重、单值 `const` 重新竞价方式 |
| 完成率优先（初始模型） | 无额外参数 |
| 自适应修复（初始模型） | 可空候选上限、可空重建轮数 |

Registry 共 13 条，其中 11 条进入算法比较，另 2 条用于初始模型。Factory 有旧算法别名，但不是独立算法，CAABS/RABAS 走已存在的直接 Solver 注册入口。当前没有 DARTIS 注册项，不添加虚构简介。检查全部 13 条，无需执行 13 次调度。

## 公共实现

- `algorithm_presentation.parameter_schema()` 在算法列表 API 输出层补中文 title/description；算法已有专属 description 优先。展示元数据与执行 Registry 分离，原 Pydantic 模型、默认值、数值限制、参数 ID 与额外字段禁令不变。
- `algorithm-parameters.js` 为共享组件，渲染整数/浮点输入、布尔复选框、enum/const 下拉、字符串、闭合嵌套对象分组；数组及开放字典使用局部结构化 JSON 输入，保留其内容。支持本地 `$ref`、Nullable、`anyOf`/`oneOf` 与类型数组。
- 每个参数明确区分“不提交字段”“显式 null”“自定义值”。默认配置保持 `{}`，不会把 null 强行替换为 0，不会把字符串 `"false"` 转成布尔值，不会悄悄填充必填值。Schema 的 null 默认值如实显示；旧适配器如何解释 null 仍由后端既有契约决定。
- 可选高级入口只编辑参数值，不展示 Schema；点击应用后校验并同步回表单。未应用的修改会阻止提交并提示，不会静默丢弃。额外字段、非法类型、范围与必填错误定位到字段；后端仍是最终权威。
- `ExperimentUI.description()` 统一为简介、机制、目标、限制、可用性，去除相同简介/机制的重复段落；依赖提示不再覆盖算法限制。
- 复用现有三角按钮，勾选与展开独立；收起不销毁表单，参数保留。错误可自动展开相关算法卡片，支持键盘、焦点及 alert 提示。新增紧凑共享 CSS，防止标识符溢出。

## 页面分工

| 页面 | 行为 |
| --- | --- |
| 首页/新建实验 | 共享简介与可编辑表单；最终仍提交原有 `algorithm_params` 对象 |
| 实验详情“算法详情”弹窗 | 相同简介及只读实际运行参数，不再混入整份 Run 配置 |
| Cesium 已添加算法 | 相同简介与只读实际参数；主布局、Metrics、Fixed Payload View、比较与回放不变 |
| 实验详情/Cesium“新增算法” | 保留此前只勾选、默认参数添加的产品约束，不新加展开或表单 |

只读模式区分记录中的 null、false 和未显式设置；不会修改历史 Run。原有独立的运行配置诊断区域仍保留。API 仍返回 Schema 供组件使用，但普通页面不打印 Schema；无 API 字段或路径变更。

## 定向验证与实际结果

```bash
node tests/algorithm_parameters.test.cjs
PYTHONPATH=tests /home/asus/eos-course-runtime/.venv/bin/python -m unittest \
  test_algorithm_parameter_metadata test_console_catalog \
  test_algorithm_registry_i1 test_nine_algorithms -v
```

- JavaScript：6 项通过，覆盖类型、范围、空对象、必填、null、联合类型、字典、嵌套、只读及说明去重。
- Python：28 项通过。遍历全部注册项，比较去除呈现字段后的 Schema 与原模型相等；默认解析一致，额外字段仍拒绝；同一目录还保留 Registry/Worker 兼容定向验证。
- Chromium：使用现有隔离合成夹具，只运行一次双算法单实验。11 个算法卡片全部检查展开/收起、不改变勾选、字段数匹配、不暴露 Schema。MIP 检查整数、null、缺省、布尔、非法范围和高级 JSON；泛型 DOM 夹具检查嵌套、数值、字符串联合、枚举、单值及数组。
- RABAS 与收益优先一起提交，仍为一个实验；3/3 任务、比较、3 条 Gantt 任务及 Tooltip、Cesium 3 条观测/2 个模型、当前回放高亮通过。实验详情只读参数、245px 窄侧栏无控件溢出、无 pageerror。该夹具认证明确为 `SYNTHETIC_UNIT_TEST_ONLY`，不代表实际物理认证。

浏览器复现（两个终端，coord 必须不存在）：

```bash
/home/asus/eos-course-runtime/.venv/bin/python tests/browser/serve_rabas_fixture.py \
  --coord /tmp/algorithm-params-ui-test.json
```

```bash
PLAYWRIGHT_MODULE=/tmp/eos-browser/node_modules/playwright \
EOS_BROWSER_EXECUTABLE=/tmp/eos-browser/browsers/chromium-1248/chrome-linux64/chrome \
EOS_RABAS_COORD=/tmp/algorithm-params-ui-test.json node tests/browser/rabas-smoke.cjs
```

测试只使用随机端口、临时 SQLite/输入/运行目录，结束回收，不停止或替换用户服务器；未运行全量测试或大型算法 Benchmark。

## 限制

组件不是通用 JSON Schema 完整解释器：不支持远程引用、递归表单、条件 Schema 等当前注册表未使用的扩展。当前全部实际模型已覆盖；将来引入新结构时须补测试，不能把前端预检当成后端校验。数组/开放字典仍采用局部 JSON，而非无限动态列表编辑。新增算法区按既有要求仍使用默认参数；本次不改变它的产品行为。真实场景正式认证门禁不受本次 UI 修复影响。

## 追加修复：旧实验新增算法被展示变更错误阻挡

用户反馈新增失败、删除正常。检查发现 `algorithm_source_sha256()` 对算法、共享约束及整个 Registry 文件取摘要；UI 提交 `63b35a1` 在 Registry 内加入中文参数元数据，使指纹变化。`Experiments.add()` 对完整公共配置严格比较，因此旧实验会被409拒绝；删除无需新增配置，不触发这项比较。

已将展示元数据移到独立 `algorithm_presentation.py`，`/api/algorithms` 仍返回相同的增强数据。执行 Registry 恢复到 main `3e9413d` 的逐字节内容，今后这类展示说明修改不再扰动算法执行摘要；未把 Registry 整体排除出摘要，真实 builder/校验变化仍能被检测。

为了兼容在短暂回归版本创建的实验，`experiment_compatibility.py` 只允许以下完整源码指纹对的展示兼容，不接受任意版本差异：

- 展示修复前及本次分离后：`382612be7cac60c70c16272fcf34a9289d1365c0e336ab775e7322c76a8967f4`
- `63b35a1` 内联展示元数据版：`149dd9bb3e87cb227cc1bb72d3356cd73d76c30376ad3f01f81dffc064cdc602`

验证方式：`git diff 3e9413d 63b35a1 -- algorithms schedulers core utils eos_system/verification.py eos_system/algorithm_registry.py` 在指纹覆盖的文件中仅 Registry 有展示元数据差异；测试中仅将 Registry 读取字节替换为该提交原字节重新计算全摘要，得到上述第二个值，其他源文件不变。

兼容只在差异字段恰好为 `algorithm_code_sha` 且恰好命中这对完整摘要时生效。原实验/历史Run不改写，新Run记录其真实当前指纹，同一事务写 `EXPERIMENT_PRESENTATION_ONLY_COMPATIBILITY` 事件，包含原实验及新Run指纹。场景/路径/预算/种子变化或其他源码摘要仍被拒绝，错误现在指明差异字段。无数据库迁移，不扩大其他跨实验比较规则。

新增直接API端点和数据库定向回归：旧版实验添加、回归版本实验添加、实验总数不增加、保留历史、新增审计事件、真实源码/场景/种子变化拒绝，以及原有删除/取消/重新添加均通过。

```bash
MPLCONFIGDIR=/tmp/eos-params-mpl PYTHONPATH=tests \
  /home/asus/eos-course-runtime/.venv/bin/python -m unittest \
  test_algorithm_parameter_metadata test_experiments -v
node tests/algorithm_parameters.test.cjs
```

追加验证结果：Python 14项、JavaScript 6项全部通过。本次未执行真实浏览器或Worker调度重跑；无法连接用户8765服务、默认运行数据库亦未能只读打开，因而没有声称已确认用户具体实验的响应。修复后须由用户重启现有服务加载。本轮暂停Push/PR。
