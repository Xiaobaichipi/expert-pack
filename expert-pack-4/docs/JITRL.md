# JitRL → expert-pack：逐条对应

论文：*Just-In-Time Reinforcement Learning: Continual Learning in LLM Agents Without
Gradient Updates*（ICML 2026 Spotlight，arXiv 2601.18510），本地副本 `JitRL-Paper/`；
代码副本 `JitRL-master/`。

本文只记录**真的被借用并且落到了代码里**的东西，以及**刻意偏离**的地方。

## 三条流

| 论文 | 本实现 | 位置 |
|---|---|---|
| 记忆库 `M = {(s_i, a_i, G_i)}` | SQLite `transitions` 表 | `jitrl/memory.py` |
| 推理流：检索 `N(s)` → `V/Q/A` → 修正输出 | `retrieve → advantage → policy.decide` | `jitrl/retrieval.py`、`advantage.py`、`policy.py` |
| 记忆更新流：评测器给 `r_t` → 折扣回报 `G_t` → 写回 | `evaluator.evaluate → agent._returns → store.write_episode` | `agent.py`、`jitrl/evaluator.py` |

## 公式对应

| 论文 | 实现 | 说明 |
|---|---|---|
| 式 (1) `G_t = Σ γ^{u-t} r_u` | `ExpertAgent._returns` | `γ` 来自 `AdvantageConfig.gamma`，默认 0.5（与参考实现 CLI 默认一致） |
| 式 (2) `V̂(s) = mean G_i` | `advantage.estimate` | 邻居平均回报 |
| 式 (3) `Q̂(s,a) = mean_{N(s,a)} G_j` | 同上 | 只看邻居中同一 `action_id` 的子集 |
| 式 (4) 未见动作 `Q̂ = V̂(s) + α/|N(s)|` | 同上 | 以概率 `λ` 生效；否则 `Q=0`（与 Algorithm 1 一致） |
| 式 (5) `Â = Q̂ − V̂` | 同上 | 返回 `raw` |
| 式 (6)/(7) KL 约束下 `π* ∝ π_θ exp(βA)`，logit `z' = z + βÂ` | `policy.JitrlPolicy.decide` | **离散候选上的同形式**：`score = base + β·Ã`，`base = ln(confidence)` |
| 归一化 `Ã = A / max\|A\|`（论文 Algorithm 1 正文） | `advantage.normalize`，`normalization="signed"`（默认） | 见下方"两处版本差异" |
| 每回合权重 `1.0 → 1.5`（论文 Algorithm 1 没有，代码里有） | `episode_weight` | 采用代码版本，因为它是被实验验证过的那一版 |

## 与参考实现的四处对齐（论文正文没有写、代码里才有）

1. **自适应探索概率。** 论文写固定 `λ`。`Jericho/src/jitrl_agent.py`
   的 `calculate_exploration_probability` 用"均值 × 稳定性(1/(1+CV)) × 样本量置信"
   算出一个 confidence，再取 `λ = clamp(1/(1+confidence), 0.05, 0.8)`。
   本实现 `advantage.adaptive_exploration` 照抄该公式，默认开启
   （`adaptive_exploration: true`），并可用 `lambda_explore` 退回固定值。
   理由：固定 `λ` 在只有 1–2 条经验时会把探索概率抬得过高，实测会让智能体反复试错。

2. **有符号归一化。** 论文 Algorithm 1 的注释版用 `max|A|`；`update_scores`
   实际逻辑是：若存在正优势，除以**最大正优势**；否则除以最小负优势的绝对值。
   本实现默认 `signed`，并把 `max_abs` 保留为可选项（两者都有测试）。

3. **回合权重。** 参考实现 `weight = min(1.0 + (episode/50)·0.5, 1.5)`，
   第 1 回合是 1.01 而不是 1.00。本实现保留该细节并在测试里固定住
   （`test_episode_weight_ramps_to_one_and_a_half`、`test_advantage_is_normalized_then_episode_weighted`）。

4. **记忆里"只有记忆才有的动作" logit 置 0。** 论文 Algorithm 1 Step 3 明确；
   `agent._augment_with_memory` 用 `base_score=0.0, source="memory"` 实现。

## 刻意偏离（以及为什么）

### 1. 修正对象：候选分数，不是 token logits

论文在 `π_θ` 的输出 logits `z(s,a)` 上加 `βÂ`；参考代码在 Jericho 里对**候选动作的
`normalized_prob`** 做同样的事（`options_with_logits` → `corrected_logprob`），
WebArena 里则把候选动作排序后交给执行器。也就是说，参考实现本身就是
"有限候选集上的 log 概率修正"，不是真的改神经网络。

本实现面对的是只经 API 调用的模型，**没有任何办法**拿到或改写 token logits。
因此我们把它做成离散闭式解：

```
π(a) = softmax_a( base(a) + β·Ã(a) ),   base(a) = ln confidence(a)
```

`temperature=0` 时取 argmax（等价于把 exp 的温度压到 0）。这不是近似掉包：
在有限动作集上，它对式 (7) 是精确的；差别只在于"候选从哪来"（模型提议 + 记忆补全）。
文档和 README 都明确写了这一点，不宣称"改变了模型权重"。

### 2. 检索：结构相容 + 精确键，而不是纯 Jaccard

论文用 Jaccard / 向量最近邻。直接照搬到工具智能体会坏：短状态的公共样板词
（`family=… | obs=tool | ok=true`）会主导相似度，把"回答步"的经验污染到"工具步"。

本实现的检索先做**结构相容**（`family`、观察类型、成功标记必须一致），再比文本；
命中同一 `state.key` 时相似度直接记 1.0。这既保留了论文"功能等价状态映射到相近表示"
的**设计原则**，又避免了一个会实际毁掉结果的检索缺陷。可关：
`retriever: {require_structural_match: false}`。

### 3. 记忆回放：参数必须可移植

论文/代码里经验是"状态 + 动作"，动作参数随任务实例而变（`alpha` vs `beta`）。
无脑回放会把上一个任务的参数硬搬到下一个任务（早期版本实测：`17*3` 被复用到
"alpha × 3" 的任务，直接把成功率打崩）。本实现要求参数字符串出现在当前任务或当前状态里，
否则不回放该动作。这是**对参考实现没有覆盖的场景的必要补强**，不是算法改动。

### 4. 存储：SQLite，不是 FAISS

参考实现用 FAISS 双索引（history + state 向量），依赖嵌入模型。
本框架的目标是"在别的电脑上一条命令跑起来"，所以默认是零依赖的 SQLite；
`transitions` 直接存 token 元组，检索是纯函数。
`retriever` 与 `store` 都是 seam，想要向量检索就实现一个 `Retriever`，不需要动存储格式。

### 5. 评测器：启发式默认 + LLM 可选

论文用 LLM 评测器做逐步打分（`evaluate_step_scores_with_llm`）。
本实现默认 `heuristic`（看工具失败、重复动作、最终答案与期望是否一致），因为它
**确定性、离线、可测试**；开放任务可装配 `evaluator: {type: builtin, target: llm}`，
它优先用模型打分，长度/数值不合法时自动回退启发式，并把原因写进 `rationale`。
`answers_match` 的最高优先级是 `task.context["expect"]`：模型说"成功"不算成功。

### 6. 中文/CJK 状态（本仓库补强）

原始实现对状态文本只做 ASCII 词级 tokenization（`_TOKEN = [a-z0-9_]`）。实测
`tokenize("查询郑州变电站1号主变套管缺陷")` 只返回 `['1']`，中文问数的检索会退化成
“只有 state_key 完全一致才算邻居”，跨问法/跨站经验基本无法命中。

现已改为：

- ASCII 词 + 词 n-gram（英文/工具名/单位，行为不变）；
- CJK 字符 unigram + 字符 bigram（无需分词器/词典，零依赖）；
- 数字（含 `1号主变` 这类中文相邻数字）归一为 `__num__`，同型设备问法可跨实例迁移。

注意：`Task.family` 仍参与结构相容检查，**中文问数应把 `family` 设为“意图”**
（如 `缺陷查询` / `台账查询`），不要用整句 `goal` 当 family，否则跨站的不同问法不会成为邻居。
对应测试见 `tests/test_state.py` 与 `tests/test_retrieval.py`。

## 理论：借用了什么、没有验证什么

论文给出三个结论：

- **Thm 4.1（闭式解最优性）**：KL 约束下 `π* ∝ π_θ exp(βA)` 是精确解。
  我们在候选集上直接使用该形式，因此这一步的推导是站得住的（附录证明未复现）。
- **Thm 4.2（V̂/Q̂/Â 的一致性）**：要求邻居数量增长、采样条件、非平稳策略下的追踪条件。
  **我们没有验证这些假设**，也不声称满足。短任务的邻居数常常是 1–3。
- **Thm 4.3（策略更新一致性）**：由 4.1+4.2 复合而来，因此同样取决于 4.2 的条件。

还有一个参考实现层面的事实：论文的 `G_t` 来自**事后**评测器的完整轨迹回报，
所以记忆永远滞后一回合。本实现保留了这个语义（`write_episode` 在回合结束才写），
并把它写成不变量，避免"半步记录"导致的自污染。

## 与论文实验的差异

- 论文环境是 WebArena / Jericho；这里是通用工具智能体，没有复现两个 benchmark。
- 论文报告"比 WebRL 省钱 30×"；这里没有成本对比，只有离线演示与单元/集成测试。
- 离线演示的"模型"是脚本规划器（固定习惯：先算后查），只用于**证明记忆能翻转决策**。
  它不能说明语言能力，也不代表论文的绝对分数。

## 想进一步贴近论文时可做的三件事

1. **向量检索**：实现 `Retriever` 用嵌入 + 结构分面过滤；`store` 不动。
2. **LLM 逐步评测**：装配 `evaluator: llm`，用真实模型做 credit assignment。
3. **多候选采样 + 温度**：把 `temperature` 调到 0.3–0.7，让 `exp(βÂ)` 真正按分布采样，
   而不是只在 argmax 上体现优势。
