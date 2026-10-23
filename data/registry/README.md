# 场景登记

`raw_input_manifest.csv`、`scenario_artifacts.v1.json`是既有索引，保持原位。

新建eos-v1使用`scenario_manifest.json`和`scenario_manifest.csv`记录可用Canonical实例的相对路径、SHA、规模、难度、来源及开发状态；`dataset_manifest.json`记录目标数量和未生成项。索引不复制场景。`eos-v1-asset-audit-20261023.json`是建设前92份公开场景的只读结构审计，WARN不是物理通过，也不等于物理失败。

矩阵结果与数据库位于`experiments/runs/eos-v1/`，不写入原始场景。运行`python scripts/validate_scenarios.py index`会核对来源镜像、SHA、公共Loader和结构后更新此次新增的登记文件。
