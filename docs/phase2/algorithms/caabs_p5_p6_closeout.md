# CAABS P5/P6 阻断收口（2026-10-18）

起点`c5090ba72819493c5f91ce8c1aa0a6a26e8cf58d`，唯一工作树`EOS-Course-Project-caabs-latest`，分支`feat/caabs-hardening-20261018`。原归档`D:/VC/caabs-final-evidence-20261018`的240文件逐SHA复查全部相同，未覆盖。新日志独立位于`/tmp/caabs-p6-20261018-2y6h8qpd`。原任务书未跟踪保留，不更改CAABS核心。

## 阶段一：物理基准版本迁移

先在原源码实际复现：RABAS4项1失败（29.151秒）、曝光15项2个失败子项（7.281秒）、E3/E4三项1失败（6.438秒），各退出1。命令为现有WSL Python3.10.12的`-B -m unittest discover -s tests -p MODULE.py -v`，开启GEN02/EXPOSURE/E3_E4真实物理opt-in，固定hashseed0、Agg、真实Orekit ZIP；每模块240秒上限。日志`baseline/`，没有依赖上一轮报告推定结果。

迁移不是把失败码直接改成实际值：新增独立`tests/physical_reference_v2.py`从原轨道字段直接构建Orekit轨道/地球/姿态，不调用生产visibility、姿态工具、规划窗口或证据；以显式矩阵乘积`R_BI R_NI^T`和手工被动ZYX公式求角，以ITRF地表法向点积求仰角，以固定相机半空间`z>0,|x|<=z*tan(FOV/2),|y|<=z*tan(FOV/2)`核对LOS，联合原始硬件速率。数值交叉验证不是区间证明，1e-8度/1e-12矩阵回归公差不用于认证。

独立脚本`tests/freeze_physical_reference_v2.py`只读历史轨道/任务，在扫描前冻结真实ALOS/GPM轨道第100秒的WGS84地表垂足作为新可达目标；不移动旧任务。由独立oracle求得：

| 星 | 新窗口首采样UTC | 可见侧出口UTC | 不可见侧出口UTC |
|---|---|---|---|
| ALOS-2_39766 | 2025-11-18T12:00:02 | 12:03:19.173844 | 12:03:19.173845 |
| GPM-CORE_39574 | 2025-11-18T12:00:33 | 12:02:46.923712 | 12:02:46.923713 |

冻结文件`tests/fixtures/nadir_relative_v2.json` SHA`edbb4787169b47834a3b4ad70de140210c8e4e120fdc61fed43b27f2c1369b51`，明确NUMERICAL_TEST_REFERENCE_ONLY_NOT_PROVENANCE_OR_CERTIFICATION；固定输入、原始场景/数据SHA、oracle函数源码SHA及历史反例。写入exclusive xb，不覆盖原夹具/证据。测试每次复查自身摘要和oracle公式身份。

旧GPM M009/M020在旧绝对姿态参考中可见，在相对Nadir中轴限幅拒绝；保留原输入及独立旧/新数值。旧SKYSAT/SCD曝光在起点即违反当前姿态/速率联合条件；保留原场景和原plan字节SHA，先独立计算拒绝原因再调用public verifier，另外使用上表新可达目标验证正曝光INCONCLUSIVE与中途退出1μs夹逼，未删除中途超限负例。旧RABAS M008/CARTOSAT在12:46:43的独立物理拒绝先于Controller断言；保留旧文件及SHA，另加全新当前生成场景上的真实RABAS Worker/Controller非空正例、201点独立重放和开发来源不得正式消费的负例。没有修改RABAS/CAABS策略、公共约束或正式发布资格。

新的E3/E4 GPM正例检查全部600采样与独立参考一致、非空窗口、所有姿态、真实出口、重新计算序列化及静态输入不变；原微秒CZML和EME2000/ITRF回归保留。原历史根值仍保存在测试常量、原Git历史及原运行归档，不能把它们冒认成新模型根。

阶段一最终命令/统计见`migration-final/`：E3/E4 4项/7.256秒、曝光16项/7.162秒、RABAS5项/57.192秒，合计25项全部通过、0跳过、各退出0。不将中间浮点全字典相等断言失败记为生产缺陷。

## 阶段二及后续

设计和7项验证测试先提交于78d07c4，再于11de4ce实现Fraction精确条件区间内核（11项测试通过）。内核只证明给定可信包络假设下的margin，不注册生产provider或发行正式回执。详见[数学设计和阻断前提](continuous_interval_certification_design.md)。真实Orekit的全链误差包络和执行slew轨迹仍缺失，正式认证保持BLOCKED；后续真实readiness审计另存证据。

审查新增实际缺陷：地下1km的目标曾可见；生成和独立曝光审计只用全局5°，忽略传感器85°/任务80°显式要求。先加真实负例，3项全部失败（退出1/6.305秒），再修复：opaque WGS84地表模型拒绝内部目标、要求正地表法向仰角；最低角取全局/传感器/任务声明最大值，拒绝非法数字。模型身份predicate升为v2，旧证书不沿用。没有改任务/FOV/硬件轴限幅。实际修复后3项、GEN02物理13、真实来源/HTTP10、曝光16、E3/E4 4项，合计46通过/0跳过，各退出0；日志`physical-negatives-before`与`physical-negatives-fixed`。
