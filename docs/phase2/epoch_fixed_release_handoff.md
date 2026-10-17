# 历元修正场景发布与 TCR 恢复交接

日期：2026-10-17（Asia/Hong_Kong）
分支：`fix/cesium-300s-consistency`

## 1. 根因与处理边界

旧场景的 observation windows 由错误的轨道历元语义产生。统一约束层加入完整曝光 Earth-occlusion 检查后，这些 stale windows 会被正确拒绝；若仍把 legacy 窗口送给调度器，TCR 会从原有约 92%～100% 降至约 45%～60%。不能通过删除遮挡约束恢复指标。

本次只替换 `observation_windows` 与 `communication_windows`，卫星、任务、坐标、资源、ID、轨道根数、时间范围和所有未知静态字段保持不变。legacy 文件不删除、不覆盖，历史 run 仍可按原 ID 与 SHA 解析。

## 2. 发布门禁

`scripts/recompute_scenario_windows_parallel.py` 按 mission 分片，每个 spawned worker 使用自己的 Orekit JVM。worker 输入排除旧的大型动态窗口，避免将 82–157 MB legacy 数组复制十份。发布前复查：

- 源 SHA、静态数据 SHA、重算源码和 wrapper SHA 未变化；
- 所有 worker 使用同一个 Orekit ZIP，SHA 为 `1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985`；
- 输出结构完整，并以同文件系统 hard-link 原子发布且不覆盖；
- 候选阶段允许如实保留零窗口任务，不因非 100% 覆盖丢弃已完成的昂贵计算。

`scripts/release_epoch_fixed_scenario.py` 再验证静态谱系、结构、每个任务的完整曝光 1 秒地球遮挡、三 seed completion-first 计划及共享约束重放。只有达到 92% TCR 才原子写入 release sidecar。场景目录只列出能通过既有 `capture_provenance` 门禁的修正版；candidate-only 文件既不出现，也不隐藏 legacy sibling。

## 3. 六场景结果

| 场景 | 修正版 SHA-256 | 物理候选覆盖 | 片段 | seed 1 / 42 / 99 TCR |
|---|---|---:|---:|---:|
| S1 10×20 dist1 | `1357bd9802aae6cc2bb21e992e65f432fb3cda24702f1dff4340ec68cc8bccc9` | 20/20 | 105 | 100% / 100% / 100% |
| S1 20×20 dist1 | `5e7a7702d60d194f403c30b157089243135b4287bef48b4114af5c83899addda` | 20/20 | 204 | 100% / 100% / 100% |
| S2 10×20 dist0 | `bc9f47038a114dff1658b8f5d6c88417a2d438a193a2f4b560cdc695fdd3bbf7` | 20/20 | 127 | 100% / 100% / 100% |
| S2 20×20 dist0 | `eeafada8b6901f2fed2b6c1f4eb850110a571b4b0c1bdd3f25a6ba8a03f10c2b` | 20/20 | 355 | 100% / 100% / 100% |
| S1 50×100 dist1 | `b960601535c6545a556f41a8c297ed813e0bda981eae5e3d5f312265a4e648f4` | 98/100 | 7,259 | 95% / 94% / 95% |
| S2 50×100 dist0 | `d8ca6e8f71585e216ca5c39f55b2dbab439d717ddf50e485f7dd38928e5ca7c5` | 98/100 | 11,251 | 98% / 98% / 98% |

中型 S1 的 `M048`、`M064`，以及 S2 的 `M018`、`M047` 没有足够长的物理窗口。这是修正后的输入事实，不应随机搬移目标或放宽地球遮挡来强制达到 100%。

## 4. 重算证据与性能

命令使用 `/tmp/eos-test-venv/bin/python`、`orekit_jpype 13.1.5.0`、10 workers：

```bash
python scripts/recompute_scenario_windows_parallel.py \
  --scenario <legacy.json> --out <independent-candidate.json> \
  --workers 10 --max-input-mib <100-or-180>
python scripts/release_epoch_fixed_scenario.py \
  --legacy <legacy.json> --scenario <candidate.json> --minimum-tcr 0.92
```

S1 双批竞争环境耗时 24:08.56、最大父进程 RSS 428,948 KiB；S2 耗时 28:41.86、最大父进程 RSS 783,340 KiB。这里的 RSS 不包含所有 Java 子进程总和；运行期间系统未使用 swap。输出大小分别为 45,779,564 与 87,585,325 bytes。先前单批 S1 计算为 11:48.49，但因过严的 100% 覆盖闸门未发布；该失败促成 candidate 与 release 门禁分离。

## 5. 验证与限制

- 定向自动化为 Python 56 PASS、1 个 opt-in Orekit SKIP；Node 7 组 PASS。Python 组合执行在既有服务线程类测试停滞 90 秒后人工中止，因此没有宣称完整 suite 通过。
- 修正版不会自动篡改既有 run、计划或指标；须新建实验才会使用新 SHA。
- release sidecar 是项目内验收证据，不是密码学签署；`metadata.extra` 中历史 generator seed/source dataset 仍未记录，因此结构报告保留 WARN。
- completion-first 的具体完成数可能受进程 hash iteration 顺序影响，但所有实际发布与回归结果均不低于 92%；正式比较应继续冻结运行环境与保存每次 run 配置。
- 回放 30 秒采样、LAGRANGE degree 5 与相机稳定性属于前序提交，不由场景发布工具回写物理窗口。
- 没有创建 PR；由至少一名未编写改动的组员审核后再合并。
