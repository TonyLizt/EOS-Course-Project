# 连续区间认证设计 v1 — 先决条件审计与禁止虚假通过

本设计在生产实现前提交；算法核心不参与物理证明。状态区分：数学内核可实现/可验证；**当前Orekit完整物理provider尚不能认证**。自动微分、点加速度、事件探测器、稠密输出、1μs出口或更密采样均不提供全区间包含性。

## 1. 精确证明合同

从场景SHA、完整模型/源码/库/数据身份、每任务原始轨道/目标/固定相机/硬件限制及明确UTC/闰秒模型构造真实函数g_j(t)。区间必须覆盖完整曝光闭包[a,b]，比执行半开[a,b)更保守；相邻cell共享端点，不允许1μs空洞。时间为整数微秒、宽度计算为有理数秒，**cell内覆盖所有实数时刻，非仅微秒采样网格**。

对每个cell I，以证明有效的模型provider返回：g_j(c)∈[l_j,u_j]、I上统一Lipschitz界L_j≥0和已包含的输入/数值误差。r=max(|a-c|,|b-c|)，由均值不等式：

`g_j(t) ∈ [l_j-L_j*r, u_j+L_j*r]`，对所有t∈I成立。

内核用Python Fraction精确有理运算，不把最近舍入float当外向区间端点。严格不等式的下界必须>0，非严格下界≥0；上界<0可证明违反；跨0、缺字段、无界、零分母、奇异图、预算耗尽或模型身份变化均INCONCLUSIVE。细分只减少保守界，不能从采样估计L，也不能从经验残差填入数值误差。

## 2. 必须覆盖的物理margin

- opaque WGS84椭球不相交：目标至卫星LOS线段与椭球内域无交点；地表接触端点不算遮挡。地表正法向仰角可作充分条件，地下点不可接受。高程/地形不在当前WGS84模型中，不能冒称地形避障。
- elevation：法向·LOS−sin(min_el)||LOS||>0；min_el取全局、传感器、任务已声明要求的最大值。
- 固定相机body +Z、恒定Rx(pi)安装：z>0及z*tan(FOV/2)±x/y≥0；不增加独立云台。
- R_N→B的每个ZYX轴限幅：必须证明所用Euler图远离奇异与分支切割，并对实际轴函数作区间包含，不用总旋转角代替三个轴约束。
- 整星真实角速率margin：ω_max−||ω_I→B||≥0；加速度/稳定时间等场景若声明，也须覆盖。
- 初始和任务间slew：保存并核验实际姿态轨迹、速率/加速度/稳定区间。仅SO(3)端点角/速率≤空闲时间是必要条件，不等于轨迹存在及跟踪控制已实现。
- 若存在GS：实际下传区间亦须真实LOS/遮挡/通信假设核验；窗口ID/所有权/严格观测后下传和累计资源继续由独立ConstraintModel验证。

## 3. 当前不能闭合的前提（实际源码依据）

1. `visibility.create_visibility_evaluator`只返回Orekit双精度点值；`KeplerianPropagator`没有区间包含合同。瞬时getSpin/getAcceleration不是cell上的上界。
2. EME2000→ITRF使用IERS2010/simpleEOP：当前ZIP绑定身份，但没有对EOP插值、天体系列截断、闰秒/时间映射及全部区间浮点误差传播给出经过验证的界。重复不同精度、和另一个近似相符、经验1e-8都不构成证明。
3. Target/NadirPointing、椭球垂足和Euler分解的全部归一化/奇异性也没有外向舍入包络。Hipparchus Field/自动微分提供计算值，不自动成为区间数或全域误差界。
4. 当前Schedule只存曝光姿态样本和边界四元数，没有实际slew轨迹、执行误差包络和稳定控制模型。不能从离散计划补造轨迹证书。

可选实施路线：对两体Kepler方程用区间Newton/单调根包络，全部基础函数用有证明的有理Taylor界或可靠有向舍入后端，构造帧变换/EOP/姿态的完整区间依赖图；或为每一步建立经过验证的解析导数/舍入界。必须先得到输入误差合同与上述依赖闭包，不能在本轮任意设置“足够小”的角度或米级容差。

依据：[Orekit传播模型](https://www.orekit.org/site-orekit-12.1.3/architecture/propagation.html)说明Keplerian只含μ的两体运动，[FieldKeplerianPropagator](https://www.orekit.org/site-orekit-13.1.1/apidocs/org/orekit/propagation/analytical/FieldKeplerianPropagator.html)并非区间认证API；[MPFR舍入合同](https://mpfr.org/mpfr-current/mpfr.html)区分正确舍入数值与更高层区间运算。缺少当前依赖的整体误差界，不是断言Orekit不能用于将来的验证积分。

## 4. 实施边界与门禁

先实现/测试精确margin包络和覆盖检查内核，返回PROVED_INEQUALITIES仅表示**给定可信包络假设下的数学结论**，不是CONTINUOUS_PASS或CertificationReceipt。没有注册生产Orekit provider，内核的调用者提交字典不能升级为可信物理证据；正式Verifier/Storage/Export继续使用原来的独立重建和发行能力令牌。

未来合格provider须由Verifier从已核验输入独立重建、重新算全证明（不信任Worker的JSON结果）；证书绑定scene/plan/source/model/data/算法和证明版本、每cell/margin及误差合同身份。重新计算失败、缺少slew轨迹或任何适用margin均拒绝。旧模型回执由源码/模型身份拒绝。开发侧车不提升成正式来源；即使未来曝光有证书，正式来源根审核仍是独立门禁。

当前阶段三正式成功/合法正式导出保持BLOCKED。独立可做的GS开发链路、真实预览、物理负例及完整回归继续实施。不能把数学内核合成证明写成真实Orekit认证成功。

## 5. 设计验证与后续实现验收

设计先验证：可见端点间可隐藏负margin；点导数为0不能推定L=0；给定严格证明的L才可做半径外推；0边界严格/非严格不同；浮点nearest可能把负margin舍入为0；无slew轨迹不能从端点时间约束认证；实际Orekit all-visible仍INCONCLUSIVE。

实现再验证：整数微秒和连续实时间覆盖、有理极值、负L/float/NaN输入拒绝、缺margin、额外/重叠/断裂cell、输入身份错配、隐藏间隙及边界不确定时均不可PROVED。正例只使用明确数学多项式，不当作物理来源或正式认证。
