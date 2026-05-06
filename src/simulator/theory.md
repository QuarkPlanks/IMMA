# 注塑模拟原理说明 (Simulation Principles)

> 本文档详细介绍了 `src/simulator` 目录下各模拟模块的物理模型与计算原理。

---

## 1. 热分析模块 (Thermal Module - `thermal.py`)

### 物理模型
采用 **一维不稳定态热传导模型** (1D Transient Heat Conduction)。模拟熔体注入模具后，通过模壁冷却凝固的过程。

### 核心公式
根据 Fourier 导热定律的解析解，对于厚度为 $s$ 的平板：
$$t_{cool} = \frac{s^2}{\pi^2 \alpha} \ln \left[ \frac{8}{\pi^2} \left( \frac{T_{melt} - T_{mold}}{T_{eject} - T_{mold}} \right) \right]$$

- **$\alpha$ (热扩散率)**: $\alpha = \frac{\lambda}{\rho \cdot c_p}$，反映材料传热速度。
- **$T_{eject}$ (顶出温度)**: 通常取材料热变形温度 (HDT) 或维卡软化点。
- **几何校正**: 对于圆柱体或复杂几何，使用等效形状系数进行修正。

### 主要功能
- 计算达到安全顶出刚度所需的 **冷却时间**。
- 结合开合模、保压时间估算 **成型周期**。

---

## 2. 流变分析模块 (Rheology Module - `rheology.py`)

### 物理模型
基于 **非牛顿流体流动动力学**。聚合物熔体通常表现为剪切变稀行为。

### 流变模型
采用 **幂律模型 (Power-law Model)** 描述粘度 $\eta$：
$$\eta = K \cdot \dot{\gamma}^{n-1}$$
其中：
- $K$: 稠度系数 (Consistency index)，受温度影响遵循 Arrhenius 关系。
- $n$: 流动特性指数 (Flow behavior index)，$n < 1$ 表示剪切变稀。
- $\dot{\gamma}$: 剪切速率 (Shear rate)，根据注射速率和流道截面计算。

### 压力与锁模力
- **压力降 ($\Delta P$)**: 基于 Hagen-Poiseuille 方程的变体，计算流道和型腔内的流动阻力。
- **锁模力 ($F$)**: $F = P_{avg} \cdot A_{proj}$。
    - $P_{avg}$: 型腔平均压力。
    - $A_{proj}$: 制品在分型面上的投影面积。

---

## 3. 缺陷评估模块 (Defects Module - `defects.py`)

### 原理
采用 **基于启发式规则的专家系统** (Heuristic Rule-based Expert System)。将物理计算结果与材料工艺窗口进行多维比对。

### 评估机制
每个缺陷（如飞边、欠注）都有一个风险函数 $R \in [0, 1]$：
- **飞边 (Flash)**: 当 $P_{inj}$ 超过锁模力约束，或温度远超材料上限（粘度极低）时触发。
- **欠注 (Short Shot)**: 当计算所需压力超过机器最大注射压力，或熔体温度过低导致提前冻结时触发。
- **缩痕 (Sink Marks)**: 壁厚与冷却时间的非线性耦合，结合保压压力不足进行评估。
- **焦斑 (Burn Marks)**: 评估局部剪切产热或排气不良（基于剪切速率阈值）。

---

## 4. 模拟协调器 (Simulator Orchestrator - `simulator.py`)

### 工作流
1. **数据载入**: 从 RAG 知识库提取牌号 TDS 数据（导热率、比热、粘度指数等）。
2. **几何构建**: 根据用户输入的制品类型（平板、盘状、箱体）建立简化的物理模型。
3. **参数注入**: 将用户设定的温度、压力、时间参数注入各物理模块。
4. **循环计算**: 先进行流动压力计算，再进行热平衡计算，最后进行缺陷耦合判定。
5. **结果封装**: 生成结构化的 `SimulationResult`，供 AI Agent 阅读并生成中文建议。

---

## 技术局限性说明
- 本程序采用的是 **准解析解模型**（Quasi-analytical models），而非三维有限元法 (FEM)。
- **优势**: 计算速度极快（<100ms），适合 LLM 在对话中多次调用。
- **劣势**: 对于极复杂几何形状，计算精度低于专业 CAE 软件（如 Moldflow）。
