# 架构

## 一句话

整个系统是**一条回合循环 + 一组可替换的深模块**。循环本身不做任何领域决策；
所有会变化的东西都在 `contracts.py` 里有一个小接口，在 `slots.py` 里有一个名字，
在 `assembly.py` 里可以被一条声明换掉。

## 深模块与 seam

每个槽位是一个 **module**：小接口 + 大实现，并且在接口处是一个 **seam**。
测试和调用方跨过同一个 seam，所以换实现不需要改循环，也不需要改测试。

| 槽位 | 契约（接口） | 实现藏了什么 | 内置实现 |
|---|---|---|---|
| `model` | `name`, `complete(messages, temperature, max_tokens)` | 端点协议、鉴权、重试、解析 | `unbound`（响亮失败） |
| `tools` | `name`, `list_tools()`, `call_tool(name, args)` | 进程、JSON-RPC、错误归类、缓存 | 无（必须绑） |
| `skills` | `spec`, `run(context, args)` | frontmatter、模块加载、异常归一 | 无（可选） |
| `store` | `path`, `write_episode`, `transitions`, `stats`, `clear`, `close` | 表结构、缓存、修剪、并发 | `sqlite` |
| `retriever` | `retrieve(state, transitions, k, min_similarity)` | 相似度、结构相容性、排序 | `jaccard` |
| `abstractor` | `abstract(task, observation, step, previous_action)` | 归一化、占位符、键、分面 | `default` |
| `policy` | `name`, `decide(candidates, neighbors, episode_index, temperature)` | 优势、归一、探索、采样 | `jitrl` |
| `evaluator` | `name`, `evaluate(trajectory)` | 稠密奖励、成功判定、兜底 | `heuristic` / `llm` |

判断某物是不是深模块的标准是**删除测试**：把它删掉，复杂度会不会在 N 个调用点重现？
`retriever` 删掉 → 每个决策点都要自己算相似度；`policy` 删掉 → 优势/归一/探索三套逻辑散落。
它们都在挣位置。相反，`SlotState.binding_text` 这种纯转发就是浅的，刻意没有做成 seam。

## 数据流

```
Task ──► abstractor.abstract ──► State(key, tokens, facets)
                                   │
                    store.transitions() ──► retriever.retrieve ──► Neighbor[]
                                   │                                │
              model.complete(prompt) ──► Candidate[]（base=ln conf）│
                                   │                                │
                                   └──► agent._augment_with_memory ◄─┘（纯记忆动作，base=0）
                                   │
                         policy.decide ──► PolicyDecision(shaped, selected)
                                   │
                     执行：tool call / skill run / answer
                                   │
                               Observation ──► 下一步（回到最上）
                        任务结束：
        evaluator.evaluate ──► step_rewards ──► G_t（折扣回报）──► store.write_episode
```

推理流（每一步）与记忆流（每回合）是两条独立的流，只在 `policy` 与 `store` 相交。
这正是 JitRL 图 1 的结构，也是我们能分别消融它们的依据（`--no-memory` 只关掉记忆流）。

## 不变量（接口的一部分，不只是实现细节）

1. **候选集有限且封闭。** 模型只能从 `available_actions()` 里选；未知 action 会被拒绝并要求重试，
   重试用尽后回退到 `answer`。没有"模型想调什么就调什么"的路径。
2. **任何适配器异常都是观察，不是崩溃。** 工具、Skill、记忆读写、模型后端，失败都变成
   `Observation(ok=False)`，再由连续失败计数器决定是否提前结束。
3. **记忆只在回合结束后写。** 一步的回报要等整条轨迹被评测后才知道（JitRL 的记忆更新流）。
   这也意味着记忆永远是"完整回合"的一致切片，不会出现半步记录。
4. **记忆回放必须"参数可移植"。** 从记忆复活一个动作时，参数字符串必须出现在当前任务文本或当前状态里；
   否则是另一个实例的参数（`alpha` vs `beta`、`17*3` vs `42*3`），拒绝回放。
   这条防止了"记忆把上一个任务的答案硬搬过来"这类最危险的错误。
5. **结构相容先于文本相似。** 检索前先要求 family / 观察类型 / 成功标记一致，
   避免共同的样板词（`family=... | ok=true`）把不相干状态拉成邻居。
6. **确定性可复现。** `seed` 同时作用于策略的探索随机与采样；`temperature=0` 时是 argmax，
   不消耗随机数，因此演示与测试可稳定复现。

## 为什么 batch-pipeline 风格

用户要的是"先把整体框架做好，后续在别的电脑上组装"。所以：

- **骨架先于内容。** `DEFAULT_SLOTS` 在没有任何 Skill/MCP 时就已经完整存在，报告直接告诉你缺什么。
- **装配是数据，不是代码。** 换模型/服务器/目录 = 改 JSON；只有新增"阶段"才需要写代码。
- **阶段可组合、可重跑。** `pipeline.Stage` 是普通可调用对象，逐项检查点；
  一个坏任务不会拖垮整批，`--resume` 从断点继续。
- **可移植。** 核心零第三方依赖；`pack` 生成 zip；`init` 在目标机器上生成带空缺的骨架。

## 目录职责

- `contracts.py`：协议 + 数据类型 + 契约检查。**新增适配器只需读这一个文件。**
- `slots.py`：目录与状态机；`describe()` 不构造适配器、不碰磁盘，只读绑定表。
- `assembly.py`：加载 → 解析（模块/路径/MCP/技能目录/内置）→ 契约检查 → `Runtime`。
- `agent.py`：回合循环、候选校验、记忆增强、执行、回报、写回。唯一"知道全部槽位"的地方。
- `pipeline.py`：阶段执行与检查点。唯一"知道多任务"的地方。
- `jitrl/`：论文实现的等价物（见 [JITRL.md](JITRL.md)）。
- `adapters/`：外部世界翻译层，每个只碰一个契约。
- `builtin/`：参考 MCP 服务器、示例 Skill、离线演示。

## 扩展点

| 想做什么 | 改哪里 | 不需要改 |
|---|---|---|
| 接新模型/推理服务 | 新增 `ModelBackend` 适配器 + 一行装配 | 循环、策略、记忆 |
| 接新 MCP 服务器 | 装配里加一条 `mcp_stdio` | 任何代码 |
| 加 Skill | 放一个 `SKILL.md` 目录（可选 `skill.py`） | 任何代码 |
| 换向量检索 | 新增 `Retriever`，装到 `retriever` 槽 | 存储格式、策略 |
| 换记忆后端 | 新增 `ExperienceStore` | 检索、策略、循环 |
| 加 LLM 评测 | 装配 `evaluator: {type: builtin, target: llm}` | 循环 |
| 加批处理阶段（如去重、路由） | 在 `pipeline` 里加 `Stage` | 槽位、装配格式 |
