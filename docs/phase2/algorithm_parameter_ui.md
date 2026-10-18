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

- `algorithm_registry.parameter_schema()` 只补公共 Schema 的中文 title/description；算法已有专属 description 优先。原 Pydantic 模型、默认值、数值限制、参数 ID 与额外字段禁令不变。
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
