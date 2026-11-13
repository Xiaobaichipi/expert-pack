# JitRL 作为插件：Harness 集成设计（讨论稿）

> 问题：JitRL 能否从 `expert-pack-4` 抽象出来，做成一个插件，用来优化 Harness 的性能？
>
> 结论：**可以抽象，但要限定在“策略层插件”，不是把整个智能体塞进 Harness。**
> 只有在 Harness 能提供「候选动作集合 + 任务结果/奖励 + 状态观察」三个钩子时，
> 才能做真正的 JitRL 打分；否则只能退化为 prompt 记忆注入。

## 一、可抽象的部分

JitRL 的本质是四段纯函数 + 一个存储，不依赖具体 Agent 循环：

| 组件 | 输入 | 输出 | 是否可插件化 |
|---|---|---|---|
| `StateAbstractor` | task/observation/step | `State(key,text,tokens,facets)` | ✅ 需按领域定制 |
| `ExperienceStore` | episode/transitions | 持久化 | ✅ SQLite/向量库均可 |
| `Retriever` | state + transitions | `Neighbor[]` | ✅ |
| `AdvantagePolicy` | candidates + neighbors | `ScoreDecision` | ✅ **核心** |
| `Evaluator` | trajectory | step rewards + success | ✅ 最依赖领域 |

**不能抽象的部分**：Harness 的控制流（什么时候调模型、怎么执行工具、怎么重试）、
模型权重本身、以及 `max_steps/并发/权限` 等宿主策略。

## 二、三种插件形态（按 Harness 能力选择）

### 形态 A：进程内 Python 插件（推荐给 Python Harness）

```python
class JitrlPlugin:
    def __init__(self, store, abstractor, retriever, policy, evaluator, gate): ...
    def recall(self, task, observation, step, previous_action) -> list[Neighbor]: ...
    def shape(self, candidates, neighbors, episode_index, temperature) -> PolicyDecision: ...
    def observe(self, task, trajectory) -> ObserveResult: ...
```

Harness 在三个位置调用：

1. **模型给候选之后、执行之前**：`shape()` 把 `score = base + βÂ` 应用到候选排序；
2. **每步开始**：`recall()` 返回经过门控的邻居，可同时用于候选补全/prompt 注入；
3. **任务结束**：`observe()` 调评测器 → `G_t` → 写回记忆。

优点：低延迟、可直接改候选分数；缺点：Harness 必须是 Python 且能拦截候选。

### 形态 B：Sidecar（MCP/HTTP 服务，推荐跨语言 Harness）

```
Harness ──POST /retrieve──► JitRL sidecar ── SQLite
        ──POST /shape─────►
        ──POST /observe───►
```

- sidecar 暴露 `retrieve / shape / observe / stats` 四个接口；
- Harness 只需在“选下一步动作前”和“任务结束后”各调一次；
- 优点：不侵入 Harness 代码、可独立重启/回滚、可多 Harness 共享经验；
- 缺点：多一次本地网络往返（通常 <10ms，可缓存）。

### 形态 C：Prompt-only（降级方案）

只把检索到的经验拼进上下文，不改候选分数。这不是严格 JitRL（没有 `βÂ`），
但在“只开放 prompt”的 Harness 里可用；效果上限低，且最容易出现负迁移。

## 三、Harness 必须提供的钩子

| 钩子 | 用途 | 没有时的降级 |
|---|---|---|
| 候选动作列表（工具/命令/子智能体） | `shape` 打分、memory-only 候选 | 只能 prompt 注入 |
| 每步观察（工具输出/错误/成功） | 状态抽象 | 只能用任务级状态 |
| 任务终局 + 可计算奖励 | `G_t`、写记忆 | 无法在线学习 |
| 任务族/意图 | 检索结构相容 | 用文本相似度替代，污染风险高 |

**关键：没有可靠奖励就没有 JitRL。** Harness 需要把“测试通过 / 构建成功 / 用户接受”
映射成 evaluator 的 step reward。

## 四、如何优化 Harness 性能（可测指标）

| 指标 | 定义 | 期望方向 |
|---|---|---|
| 任务成功率 | 评测器/人工验收 | ↑ |
| 步数 | 工具调用/模型轮次 | ↓ |
| 工具错误率 | schema/权限/参数错误 | ↓ |
| token/时延 | 模型与工具开销 | ↓ |
| 记忆命中率 | 有效邻居/检索次数 | 仅观察 |
| 负迁移率 | 有记忆比无记忆更差的 family 占比 | ↓ |

必须做 **A/B 同任务集、同种子/同模型** 对比；否则无法判断插件是帮忙还是添乱。

## 五、从 P1/P2 得到的教训（直接决定插件设计）

1. **强模型上记忆会负迁移**：真实模型 A=92.9% → B=85.7%（P1）；
   记忆门控后 B=88.1%，仍低于 A（P2-1）。
   → 插件必须默认 **门控**（邻居数/相似度/回报方差），不能默认全量注入。
2. **工具契约错误比记忆错误更致命**：P1 真实失败大量来自参数名幻觉；
   → 插件不能替代 Harness 的 schema 校验，二者应叠加。
3. **Skill 会抢占步数**：真实模型会先激活技能再查询；
   → 插件应支持 `max_steps` 与技能裁剪策略，或把技能作为候选而非固定前置。
4. **小样本不可学**：邻居 1–3 条时优势估计不可靠；
   → 默认 `min_neighbors >= 2`，并按任务族统计成功率后再启用。

## 六、建议的落地路线

**第一步（低风险）**：把当前 `expert-pack-4/jitrl/` 抽成独立 Python 包 `jitrl_core`：

```
jitrl_core/
  state.py memory.py retrieval.py advantage.py policy.py evaluator.py gate.py
  plugin.py   # JitrlPlugin facade
```

零第三方依赖、SQLite 存储，配置化门控；`expert-pack-4` 只作为参考 Adapter。

**第二步**：为 Harness 做一个 `HarnessAdapter`（形态 A 或 B），先只开：
- `recall`（只读记忆）+ prompt 注入；
- `observe`（只记录，不更新策略）；
跑 2 周影子模式，收集“记忆是否有用”的证据，不动线上策略。

**第三步**：影子模式确认正收益后，才开启 `shape`（真正改候选分数），
并保留门控、灰度、回滚和一键关闭。

## 七、直接回答“能不能优化 Harness”

- **能**，但优化的是“重复性动作选择/路由/参数复用”，不是模型推理能力本身；
- 对 **高频、同族、可判分** 的任务收益最大（如固定仓库的构建/测试/检索流程）；
- 对 **长尾、一次性、无可靠奖励** 的任务收益很小，甚至负迁移；
- 所以插件应默认“影子 + 门控 + 可关闭”，先用指标证明，再逐步放开。

> 若目标是优化当前 DSH Harness，需要先确认 Harness 是否暴露候选动作和任务终局事件；
> 若只暴露 prompt，则只能做形态 C，不建议声称“JitRL 插件”。
