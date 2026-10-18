# 全组场景数据：U盘交付与本地接入

日期：2026-10-18。适用于支持 physical_validation 与新版场景来源校验的代码版本。

## 1. 李泽同交付什么

发全组的U盘目录建议如下（无需把整个运行目录复制过去）：

```text
EOS场景数据/
├─ eos-course-v1-development.zip   # 80份：60训练/开发、20验证
├─ SHA256SUMS.txt                 # 压缩包校验值
├─ 使用说明.md
└─ U盘交付与接入说明.md           # 本文
```

公开包约24.6MB，内含完整场景、provenance来源侧车、生成配置、源码快照、划分及检查报告。请复制整个压缩包，不能只挑场景JSON。

`eos-course-v1-final_test.zip`约6.5MB，含20份冻结测试：**仅单独交刘懋兴保管**。算法、参数和模型冻结后由数据负责人统一测试；不要放入全组公开文件夹，也不要登记日常后端。SHA256SUMS列出两包校验值不代表两包都应发全组。

## 2. 组员先核验、再解压

先将development压缩包从U盘复制到本机，保留原包。PowerShell进入所在文件夹后执行：

```powershell
Get-FileHash .\eos-course-v1-development.zip -Algorithm SHA256
```

预期SHA-256（大小写无关）：

```text
3c012d2050358e58fde8e40a0799d252ef11ad5030bf884ca2b8f2d5c8df4fa2
```

优先解压到运行后端的WSL Linux文件系统，避免直接从U盘运行。若U盘为E盘，公开文件夹名为EOS场景数据，可在Ubuntu中执行以下示例；盘符不同请替换 `/mnt/e`：

```bash
mkdir -p "$HOME/eos-course-runtime/datasets"
python3 -m zipfile -e /mnt/e/EOS场景数据/eos-course-v1-development.zip "$HOME/eos-course-runtime/datasets"
```

第一次解压后应得到：

```text
eos-course-runtime/datasets/eos-course-v1/
├─ development/
│  ├─ scenarios/                  # 80份场景JSON
│  │  └─ provenance/              # 必须与场景一起保留
│  ├─ generation_configs/
│  ├─ generation_source/
│  ├─ delivery_manifest.csv
│  ├─ lineage_manifest.json
│  └─ checks/
└─ splits/                        # 60开发/20验证白名单
```

不要对已有修改的数据目录直接重复解压；先选新的目录。不要改场景或侧车中的时间、坐标、SHA或PASS字段；新派生数据写另一个目录。共享包是原始输入，不承载每个人的数据库或输出。

## 3. 网页接入

1. 同步本次PR合并后的代码；若PR尚未合并，可使用已推送的feat/console-layout-polish分支。在本机已有环境中按README启动后端。
2. Ubuntu执行 `echo "$HOME/eos-course-runtime/datasets/eos-course-v1/development/scenarios"`，复制输出的完整绝对路径。
3. 控制台 → 新建实验 → 目录管理：新增数据源，名称填“全组统一开发集 eos-course-v1（80份）”，目录粘贴第2步路径。
4. 只登记 `development/scenarios`，不要登记整个datasets或development目录。来源ID由各自数据库生成，不要硬编码李泽同本机的source_id。
5. 返回选择场景，选择刚登记的数据源；应显示80个场景。先选EOS-G0001，用收益优先启发式和默认参数试跑。
6. 成功后在实验管理查看计划与指标，试下载JSON/CSV，再打开Gantt和Cesium。示例成功只证明接入，不要求所有算法得到相同任务数。

无场景时先检查路径及解压层级；来源错误时检查provenance是否完整及代码是否同步。不要手改证据绕过核验。物理采样通过不是严格连续区间证明，旧formal API仍可能因缺少连续证明拒绝。

## 4. 全组统一使用规则

- 传统算法：共同使用这批原始输入与约束，报告相同场景、种子、预算及代码版本。
- 机器学习：仅从splits中的train_development白名单生成训练特征/标签；validation用于选择模型及调参，不混入训练，不递归读取整个datasets。
- 最终测试：20份仅刘懋兴保管，冻结后统一评估，不用于开发调参。
- 各自实验数据库、模型、缓存与导出写各自运行目录，不提交Git，不发给其他组员冒充原始场景。
- 接入验收反馈：代码提交号、数据包SHA、显示的场景数量、一个成功实验ID及导出结果；出错保留错误码，不直接修改原数据。

详细来源、规模及精度限制见同仓库shared_scenario_data_delivery_report.md。
