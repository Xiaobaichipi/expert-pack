# JitRL × PMS 问数落地设计（P0 方案）

> 目标：把 `expert-pack-4` 的 JitRL 智能体骨架接到 `expert-pack-3` 的 PMS 问数能力上，
> 用真实（先 mock）问数轨迹验证「经验记忆能否减少对 Skill 手工开发的依赖」。
>
> 本文是落地设计 + **P0 实施记录**；P0 只做可复现的离线实验，不接生产、不自动写 Skill。
> P0 状态：**已完成**（见文末「十一、P0 实施记录」）。
> P1 状态：**已完成**（真实模型接入、42 题任务集、检索校准；结论见「十二、P1 实施记录」12.6）。
> P2-1 状态：**已完成**（记忆门控；结果与剩余问题见「十三、P2-1 记忆门控」）。
> P2-2 状态：**已完成**（工具契约强制 + 自适应步数；A/B 结果见「十四、P2-2 工具契约与步数」）。
> P2-3 状态：**已完成**（技能裁剪 + 无技能对照；结果见「十五、P2-3 技能裁剪」）。
> P3 状态：**扩展模拟数据已完成**（6 站/66 题；真实鉴权后需真实日志复测，见「十六、P3-模拟扩展数据」）。
> P3-真实分布状态：**已完成异构模拟数据**（6 个异构站/33 题，见「十七、P3-异构真实分布模拟」）。
> P3-复杂任务状态：**已完成复杂任务模拟**（26 题多步/判断/比较，见「十八、P3-复杂任务与步进 RL 状态」）。
> P3-候选生成增强状态：**已完成**（意图工具提示 + 强制白名单，见「十九、候选生成增强」）。
> P3-比较引导状态：**已实现**（系统/动态比较约束 + 任务步数补齐，真实模型复测受账号配额限制，见「二十、比较引导」）。
> P3-Kimi 复测状态：**已完成**（复杂 26 题 D 96.15% / E 92.31%，见「二十一、Kimi 模型复测」）。
> P3-比较方案对比状态：**已完成**（结构化候选表 vs 确定性 rank 工具，见「二十二、比较方案对比」）。
> P3-轨迹树状态：**已完成实验版**（append-only 事件树 + HTML/PNG，见「二十三、轨迹树」）。

## 一、已验证的集成形态（本轮 smoke test）

把 `expert-pack-3` 的 `pms-gateway-mcp` 作为 stdio MCP 绑定到 `expert-pack-4` 的 `tools` 槽，
把 12 个技能目录绑定到 `skills` 槽，装配文件一次通过：

```text
model       bound    demo        ModelBackend     builtin:scripted
tools       bound    production  ToolProvider     mcp_stdio:pms
skills      bound    production  Skill            skill_dir:../expert-pack-3/skills
store       bound    production  ExperienceStore  builtin:sqlite
retriever   builtin  production  Retriever        builtin:jaccard
abstractor  builtin  production  StateAbstractor  builtin:default
policy      builtin  production  PolicyShaper     builtin:jitrl
evaluator   builtin  demo        Evaluator        builtin:heuristic

assembly is runnable
```

说明：`pms-gateway-mcp` 在 `PMS_AUTH_MODE=mock` 下不需要真实凭证；12 个技能目录可被
`skill_dir` 原样加载（prompt-only；`skill.py` 不参与）。装配参考见
[`docs/ASSEMBLY.md`](ASSEMBLY.md)、MCP 适配器见
[`adapters/mcp_stdio.py`](../expert_pack/adapters/mcp_stdio.py#L288-L339)。

## 二、目标与非目标

**目标**

- 用 12 个中文问数任务族 × 多实例，验证 JitRL 记忆在以下指标上的增益：
  成功率、步数、工具错误数、token/时延、对 Skill 数量的依赖。
- 产出可复现的 A/B 实验：`无记忆/全技能` vs `有记忆/全技能` vs `有记忆/薄技能`。
- 沉淀一个可替换的 PMS `abstractor` + `evaluator` 扩展。

**非目标（P0 不做）**

- 不接生产 PMS、不写生产库；不自动生成/执行 Skill；不做步级实时更新。
- 不承诺“完全替代 Skill”；只验证“哪些重复性 Skill 可以不再手写”。
- 不在 P0 复现论文 WebArena/Jericho 分数。

## 三、总体架构

```
ExpertAgent (expert-pack-4)
  ├─ model         → OpenAI 兼容端点（内网）或 scripted（离线回归）
  ├─ tools         → mcp_stdio: pms-gateway-mcp（26 个 PMS 工具，mock/真实网关）
  ├─ skills        → expert-pack-3 的 12 个 SKILL.md（全量或薄集）
  ├─ abstractor    → PmsAbstractor（意图/设备类型/观察类型 facets，中文 token）
  ├─ retriever     → Jaccard（结构相容 + 中文相似度）
  ├─ policy        → JitRL（score = base + β·Â）
  ├─ evaluator     → PmsEvaluator（确定性校验 + 可选 LLM）
  └─ store         → SQLite（按环境/版本命名空间）
```

## 四、PMS 状态抽象（P0 的核心改动）

`DefaultAbstractor` 只有 family/obs/ok；PMS 问数需要业务坐标。建议新增
`expert_pack/extensions/pms/state.py::PmsAbstractor`：

| facet | 来源 | 作用 |
|---|---|---|
| `family` | `task.family`（必须是意图，不是整句） | 结构相容，决定跨实例迁移范围 |
| `intent` | `task.context["intent"]`（如 `defect_query`） | 细分意图，避免台账/缺陷记忆互串 |
| `device_type` | `context["deviceType"]` | 同型设备迁移 |
| `obs` / `ok` | 观察类型/成败 | 保持现有结构相容 |
| `station_scope` | 可选，默认不参与相似度 | 跨站迁移；合规场景可改为强制同站 |

状态文本只保留“可比较的业务信号”：

- 工具返回的成功/失败、结果条数、关键字段（缺陷等级/负载率/可用率）；
- 去掉 `assetId/psrId/utcNum/站名` 等实例标识（数字归一 + 业务字段替换）；
- 中文以 CJK unigram/bigram 参与 Jaccard（本轮已修复，见 [`docs/JITRL.md`](JITRL.md#L102-L116)）。

**family 约定**：`defect_query` / `ledger_query` / `capacity_query` / `reliability_query` /
`topology_query` / `maintenance_query`。不要把整句 `goal` 当 family，否则跨站实例不会成为邻居。

## 五、奖励与评测（PmsEvaluator）

P0 先用确定性评测，避免 LLM 评测噪声污染记忆：

| 信号 | 规则 | 奖励 |
|---|---|---|
| 最终答案 | 与 `context["expect"]` 归一化匹配（数字/中文/编号） | +1.0 / -1.0 |
| 工具步骤 | `Observation.ok` 且参数符合 spec 必填 | +0.2 |
| 工具失败/鉴权失败 | `ok=False` | -0.5 |
| 重复同一失败动作 | 同 action+args 连续 | -0.1 |
| 步数惩罚 | 每步 | -0.03 |
| 幻觉 ID | 答案中的 ID 不在工具返回结果里 | 额外 -0.5 |

开放题（如“分析站内风险设备”）再启用 `LlmEvaluator` + 启发式兜底；P0 评测集中所有
题目都带 `expect`，可完全确定性判定。

## 六、记忆与在线闭环（P0）

- 采用**回合级**在线：`solve → evaluator → G_t → write_episode`，下一题立即检索；不改进 `Evaluation` 的逐步语义。
- 记忆库按环境/接口版本隔离：`memory.pms.<env>.sqlite3`；P0 用 `.tmp` 或 `runs/`。
- 检索参数沿用默认：`top_k=5`、`min_similarity=0.4`；等 P0 数据出来再按 family 校准。
- 探索：P0 `temperature=0`（可复现）；第二阶段再开 0.3–0.7 做多候选采样。
- 不写入失败轨迹？先保留失败轨迹（成功标记进入 meta），避免只学“正样本”导致过度自信。

## 七、实验设计

### 7.1 任务集（P0）

从 `expert-pack-3` 的 mock 数据构造 **可确定性判分** 的中文问数任务，覆盖 6 类意图 ×
多站/多设备实例，例如：

| intent | 示例问题 | 期望答案来源 |
|---|---|---|
| ledger_query | “220kV 郑州变电站有几台主变？” | mock 数据计数 |
| ledger_query | “1号主变的型号是什么？” | `get_asset_by_id` |
| defect_query | “1号主变有哪些严重缺陷？” | `inquire_defect` |
| defect_query | “2202断路器灭弧室缺陷等级？” | `inquire_defect` |
| capacity_query | “1号主变负载率是多少？” | `query_open_capacity` |
| reliability_query | “220kV 郑州变电站可用率是多少？” | `query_station_scale_analysis` |
| topology_query | “1号主变的上级电源来自哪个站？” | `search_power_path` |
| maintenance_query | “1号主变下一次检修计划是什么时候？” | `get_repair_plan` |

同一 intent 至少 3–5 个实例（换站/换设备），才能让 JitRL 的邻居估计有统计意义。

### 7.2 三条实验臂

| 臂 | 记忆 | 技能集 |
|---|---|---|
| A | 无 | 全量 12 个技能 |
| B | 有 | 全量 12 个技能 |
| C | 有 | 薄技能（1 个通用问数流程 + 1 个输出规范，工具契约仍由 MCP 提供） |

### 7.3 指标与验收

- 主指标：任务成功率（确定性判分）；
- 次指标：平均步数、工具调用数、失败工具数、token/耗时、记忆命中率；
- 验收门槛（P0 建议）：
  1. B 的成功率 ≥ A（同任务集）；
  2. C 的成功率 ≥ A − 5 个百分点，且 C 的技能文本量显著减少；
  3. 失败案例能归因到“检索不到邻居 / 评测错误 / 模型规划错误”三类之一。

## 八、P0 交付物

```
expert-pack-4/
  expert_pack/extensions/pms/
    __init__.py
    state.py          # PmsAbstractor
    evaluator.py      # PmsEvaluator
    tasks.py          # 构造 mock 任务集
  assembly/pms.demo.json
  tools/run_pms_experiment.py   # 三条臂跑批 + 指标汇总
  tests/test_pms_state.py
  tests/test_pms_evaluator.py
  tests/test_pms_integration.py # 装配 + MCP 26 工具 + 一次真实 tool call
```

P0 完成判定：上述测试全绿 + 三个实验臂输出同一份 `results.jsonl` 与指标表。

## 九、待确认决策（建议默认值）

1. **模型后端**：P0 先用 `scripted` 跑通链路，还是直接接内网 OpenAI 兼容端点？
   - 建议：先 scripted 做确定性链路；同时预留 `model_openai` 装配，等端点确定再跑真实 LLM。
2. **技能集**：C 臂“薄技能”用哪两个 SKILL.md？
   - 建议：`substation-qa-orchestrator`（问数总控）+ 一个“答案格式/引用规范”；其余 10 个不装。
3. **任务集**：P0 用 mock 构造 30–50 题；还是已有真实工单/问数日志？
   - 建议：先用 mock 构造，确保 `expect` 可判分；真实日志作为 P1 扩展。
4. **合规**：记忆是否允许跨站迁移？
   - 建议：P0 允许跨站（验证迁移能力），但元数据记录来源站；生产默认按站隔离。

## 十、风险与边界

- **评测器是瓶颈**：确定性 `expect` 覆盖不了的开放题，LLM 评测会引入噪声；P0 不碰。
- **中文 family 必须约定**：否则结构相容会挡住跨实例经验（见 JITRL.md 说明）。
- **MCP 工具面大**：26 个工具会让候选集变大、模型更容易选错；P0 考虑按 intent 动态裁剪工具集（P1 再实现）。
- **记忆规模**：P0 任务少，邻居只有几十条，结论只能说明“链路与方向”，不能说明规模化收益。

## 十一、P0 实施记录（2026-11-12）

### 11.1 已交付代码

```text
expert_pack/extensions/pms/
  state.py        PmsAbstractor：family=意图、起始状态同族一致、中文 token、观察压缩
  evaluator.py    PmsEvaluator：expect 严格判分 + 工具/重复/终局奖励
  planner.py      PmsScriptedPlanner：故意先选错工具（验证记忆翻转）
  tasks.py        21 道中文问数任务（6 个意图族 × 多实例）
  thin_skills/    C 臂用的 2 个薄技能
assembly/pms.demo.json      装配示例（26 工具 + 12 技能 + PMS abstractor/evaluator）
tools/run_pms_experiment.py 三条臂实验入口
tests/test_pms_state.py     中文/意图族状态测试
tests/test_pms_evaluator.py 确定性奖励测试
tests/test_pms_integration.py 26 工具 + 按 ID 过滤 + 任务集测试
```

### 11.2 运行命令（使用 `jitrl` conda 环境）

```powershell
cd expert-pack-4
python tools/run_pms_experiment.py --out runs/pms-p0
python -m unittest discover -s tests -t .
```

### 11.3 实测结果

```text
| 臂 | 任务数 | 成功 | 成功率 | 平均步数 | 工具错误 | 技能数 | 记忆 transitions |
| A | 21 | 0 | 0.00% | 2.0 | 0 | 12 | 0 |
| B | 21 | 15 | 71.43% | 2.0 | 0 | 12 | 42 |
| C | 21 | 15 | 71.43% | 2.0 | 0 | 2 | 42 |
```

- 每个意图族的**第 1 题**因冷启动失败（无邻居经验，模型先选错工具），此后记忆把正确工具抬到首位；
  6 个族共 6 次失败，其余 15 题成功。
- **C 臂（仅 2 个薄技能）与 B 臂（12 个技能）成功率完全相同**：在该脚本规划器任务集上，
  记忆足以承担路由，技能文本量不再是瓶颈。
- 工具错误数 0：失败全部来自“选错工具但工具成功返回”，不是 MCP 故障。

### 11.4 诚实边界

- 脚本规划器是固定先验（先错后对），**不能代表真实 LLM 能力**；P0 只证明“记忆 → 优势 → 决策”链路成立。
- 任务集 21 题规模小，邻居数少；P1 需要真实模型 + 更多任务/真实日志。
- C=B 不代表“所有场景不需要 Skill”：开放题、合规约束、冷启动仍需要薄技能/契约。
- `PMS_AUTH_MODE=mock` 的对象接口返回 spec 静态样例，**实验必须走本地 HTTP mock gateway**（P0 harness 已这样做）。

## 十二、P1 实施记录（2026-11-12）

### 12.1 配置（已写入工作区 `.env`，不入库）

```text
ARK_API_KEY=...
ARK_OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
ARK_ANTHROPIC_BASE_URL=https://ark.cn-beijing.volces.com/api/plan
ARK_MODEL=deepseek-v4-1-flash-261017
```

harness 启动时读取工作区 `.env`（不覆盖已有环境变量），`--model openai` 使用
`OpenAIModel`（chat/completions）连接上述端点；`--model scripted` 仍用于离线回归。

```powershell
python tools/run_pms_experiment.py --model scripted --out runs/pms-p1-scripted
python tools/run_pms_experiment.py --model openai   --out runs/pms-p1-openai
```

### 12.2 任务集扩到 42 题

在 21 道基础题上增加 21 道**同义改写**（`-v2`，如“麻烦你查一下，……”），保持
意图族/期望值不变，覆盖更多中文问法。[tasks.py](../expert_pack/extensions/pms/tasks.py) 当前 `build_tasks()` 返回 42 题。

### 12.3 检索校准（脚本规划器，42 题，B 臂）

| min_similarity | 成功/42 |
|---|---|
| 0.3 | 33 |
| 0.4 | 33 |
| 0.5 | 33 |
| 0.6 | 33 |

| top_k | 成功/42 |
|---|---|
| 3 | 30 |
| 5 | 33 |
| **7** | **36** |
| 9 | 36 |
| 12 | 36 |

结论：起始状态在同族内是 exact-key，阈值不敏感；`top_k` 从 5 提到 7 有增益，**PMS 默认改为 7**。
`PmsRetriever` 已支持按 `family` 配不同阈值，阈值数据留待真实日志再标定。

另新增：`PmsEvaluator` 的**幻觉 ID 惩罚**（答案出现工具结果中不存在的 `AST/PSR/DF/...` ID 时额外扣分）。

### 12.4 结果：脚本规划器 vs 真实模型

**脚本规划器（42 题，验证机制）**

| 臂 | 成功 | 成功率 | 平均步数 | 工具错误 | 技能数 |
|---|---|---|---|---|---|
| A 无记忆 | 0/42 | 0.00% | 2.0 | 0 | 12 |
| B 有记忆 | 36/42 | **85.71%** | 2.0 | 0 | 12 |
| C 有记忆+薄技能 | 36/42 | **85.71%** | 2.0 | 0 | 2 |

**真实模型 `deepseek-v4-1-flash-261017`（42 题，OpenAI 兼容端点）**

| 臂 | 成功 | 成功率 | 平均步数 | 工具错误 | 技能数 |
|---|---|---|---|---|---|
| A 无记忆 | 39/42 | **92.86%** | 2.79 | 16 | 12 |
| B 有记忆 | 36/42 | 85.71% | 2.71 | 9 | 12 |
| C 有记忆+薄技能 | 33/42 | 78.57% | 2.74 | 11 | 2 |

结果文件：[runs/pms-p1-scripted/summary.md](../runs/pms-p1-scripted/summary.md)、
[runs/pms-p1-openai/summary.md](../runs/pms-p1-openai/summary.md)。

### 12.5 真实模型上为什么记忆反而变差

逐题记录暴露了三类问题：

1. **工具参数幻觉**：模型把 `query_open_capacity` 的参数写成 `assetId/stationId`（spec 要求
   `deviceId`），把 `query_station_scale_analysis` 加上 `startDate/endDate` 等未声明参数；
   导致 1–2 次无效调用后耗尽 `max_steps`，最终没有答案。
2. **Skill 抢占步数**：模型会先激活 `skill:substation-reliability` 等技能，再做查询；
   步数上限 4 时，多一步就挤掉答案步骤。
3. **记忆负迁移**：B 臂的 JIT MEMORY 文本会把其他任务的“工具/参数习惯”带进当前任务，
   让强模型放弃本来正确的直接调用，改走无关工具链。

这不是 JitRL 公式的问题，而是**强模型 + 小样本记忆 + 工具契约没被强制执行**的组合问题；
脚本规划器因为有固定先验，才表现出“记忆翻转决策”的正向效果。

### 12.6 P1 结论与 P2 建议

**结论：P1 完成了三件事（接真实端点、任务集扩到 42、top_k/阈值校准 + 幻觉惩罚），
但“真实强模型上靠记忆减少 Skill 依赖”尚未成立。** 当前数据不支持直接去掉技能。

P2 优先做三件：

1. **记忆门控**：只有 `相似度 ≥ 阈值 + 邻居数 ≥ N + 回报方差低` 才注入 `JIT MEMORY` 文本；
   否则只做策略打分，不给模型看经验，避免负迁移。
2. **工具契约强制**：把 spec 的 required/参数名注入提示，调用前做本地 schema 校验；
   参数错直接拒绝并重试，而不是浪费一步。
3. **Skill 裁剪实验**：先测“去掉与任务无关的技能”能否降低步数/错误，再决定薄技能集；
   同步把 `max_steps` 自适应（按工具族 4–6 步）。

完成 P2 后重新跑 A/B/C；若 B 仍低于 A，就把记忆限定为“少数可复用工具链”的离线策略，
而不是在线注入。

## 十三、P2-1 记忆门控（2026-11-12）

### 13.1 实现

在 `AgentConfig` 增加三个 0=关闭的门控参数（[agent.py](../expert_pack/agent.py)）：

```python
memory_min_neighbors: int = 0       # 邻居数不足则整条记忆丢弃
memory_min_similarity: float = 0.0  # 最高相似度不足则丢弃
memory_max_return_std: float = 0.0  # 回报方差过大则丢弃
```

检索后由 `gate_neighbors()` 统一过滤；门控失败时：

- 提示词不出现 `JIT MEMORY` 段；
- `policy` 退回冻结先验（无邻居可修正）；
- `_augment_with_memory` 不注入记忆动作。

这样把“记忆证据是否足够可靠”变成显式配置，而不是让模型自己判断。

### 13.2 配置扫描（脚本规划器，42 题，B 臂）

| min_neighbors | min_similarity | max_return_std | 成功/42 |
|---|---|---|---|
| 2 | 0.8 | 0.5 | 30 (71.43%) |
| 2 | 0.9 | 0.8 | 30 (71.43%) |
| 3 | 0.9 | 1.0 | 24 (57.14%) |
| 2 | 0.0 | 0.5 | 30 (71.43%) |

门控越严格，冷启动需要更多失败样本，脚本规划器成功率下降；这是“安全换性能”的预期代价。

### 13.3 真实模型对比（42 题）

| 臂 | 配置 | 成功 | 成功率 | 平均步数 | 工具错误 |
|---|---|---|---|---|---|
| A | 无记忆 | 39/42 | 92.86% | 2.79 | 16 |
| B（P1，无门控） | 记忆 | 36/42 | 85.71% | 2.71 | 9 |
| B（P2-1，门控） | n=2, sim=0.8, std=0.5 | **37/42** | **88.10%** | 2.76 | 11 |

结论：

- 门控把真实模型负迁移从 −7.15pp 收敛到 **−4.76pp**，但仍未超过无记忆基线；
- 失败仍集中在 `query_open_capacity` 参数名错误、`query_station_scale_analysis` 自造日期参数、
  skill 抢占步数；
- 下一刀应做 **工具契约强制 + max_steps 自适应**（P2-2），而不是继续调记忆权重。

结果：[runs/p2-gate-real/B/results.jsonl](../runs/p2-gate-real/B/results.jsonl)。

### 13.4 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --arms B \
  --memory-min-neighbors 2 --memory-min-similarity 0.8 --memory-max-return-std 0.5 \
  --out runs/p2-gate-real
```

## 十四、P2-2 工具契约强制与自适应步数（2026-11-12）

### 14.1 实现

**工具契约强制**（[agent.py](../expert_pack/agent.py)）：

- 候选参数出现 spec `properties` 之外的键 → 直接拒绝，并把 `allowed: [...]` 写进 repair 提示；
- prompt 的 `AVAILABLE ACTIONS` 现在列出 `params: name*`（`*` 为 required），并明确
  “不要发明 params 之外的参数名”；
- harness `repair_attempts=2`，模型可在修复提示后重试。

**自适应步数**（[tasks.py](../expert_pack/extensions/pms/tasks.py)）：

| family | max_steps |
|---|---|
| ledger_model / defect_level | 4 |
| capacity_load / reliability_availability | 6 |
| topology_source / maintenance_plan | 5 |

同时 `AgentConfig.max_steps` 兜底设为 6。

### 14.2 真实模型 A/B（42 题，P2-1 门控 + P2-2）

| 臂 | 成功 | 成功率 | 平均步数 | 工具错误 | 记忆 transitions |
|---|---|---|---|---|---|
| A 无记忆 | 41/42 | **97.62%** | 2.45 | 0 | 0 |
| B 有记忆 | 41/42 | **97.62%** | **2.19** | 0 | 92 |

结论：

- 工具契约强制后，A/B 成功率都从 P1 的 92.86% / 85.71% 提升到 **97.62%**，**工具错误降为 0**；
- 记忆不再造成负迁移，且 **B 平均步数比 A 少 0.26 步**（2.19 vs 2.45）——同等正确率下的效率收益；
- A、B 都只在 `reliability-availability-2-v2` 一题失败：模型先激活 `substation-reliability`
  技能，随后在站级接口上反复尝试，6 步耗尽；这是 skill 抢占步数问题，留给 P2-3（技能裁剪）。

结果：[runs/p2-2-real/summary.md](../runs/p2-2-real/summary.md)。

### 14.3 结论

P2-2 把“记忆负迁移”问题压到 0 工具错误、成功率持平、步数更少；但注意：

- 这是 **42 题、单模型、单 seed** 的结果；
- 成功率持平而非提升，说明当前记忆主要价值是**效率**而非**正确率**；
- 若要提升正确率，需要 P2-3：技能裁剪/技能前置约束，或把技能从候选动作中移除。

### 14.4 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --arms A,B \
  --memory-min-neighbors 2 --memory-min-similarity 0.8 --memory-max-return-std 0.5 \
  --out runs/p2-2-real
```

## 十五、P2-3 技能裁剪（2026-11-12）

### 15.1 实验臂扩展

同一套 P2-1 门控 + P2-2 契约/步数配置下增加：

| 臂 | 记忆 | 技能集 | 说明 |
|---|---|---|---|
| A | 无 | 12 全技能 | P2-2 基线 |
| B | 有 | 12 全技能 | P2-2 记忆 |
| C | 有 | 2 薄技能 | 技能裁剪 |
| D | 有 | 0 技能 | 无技能 + 记忆 |
| E | 无 | 0 技能 | 无技能 + 无记忆（隔离记忆效果） |

### 15.2 真实模型结果（42 题，同一模型/seed）

| 臂 | 成功 | 成功率 | 平均步数 | 工具错误 | 技能数 |
|---|---|---|---|---|---|
| A | 41/42 | 97.62% | 2.45 | 0 | 12 |
| B | 41/42 | 97.62% | 2.19 | 0 | 12 |
| C | 42/42 | **100.00%** | 2.29 | 0 | 2 |
| D | 42/42 | **100.00%** | **2.10** | 0 | 0 |
| E | 42/42 | **100.00%** | 2.36 | 0 | 0 |

结果：
- [C/D 结果](../runs/p2-3-skills/summary.md)
- [E 无技能无记忆](../runs/p2-3-noskill-nomem/summary.md)

### 15.3 结论与决策

1. **技能反而拖后腿**：A/B（12 技能）的唯一失败来自 `skill:substation-reliability`
   被激活后反复调用站级接口；C（2 技能）与 D/E（0 技能）都 42/42。
2. **无技能也能 100%**：在 P2-2 契约强制 + 自适应步数下，D/E 证明“这批任务不需要技能文本”。
   这是对「减少 Skill 开发依赖」最直接的证据（但仅限本任务集）。
3. **记忆仍有价值，但只体现在效率**：无技能时 D(有记忆) 2.10 步 vs E(无记忆) 2.36 步；
   同等 100% 正确率，记忆省 0.26 步。记忆**没有**提升正确率。
4. **决策**：P2 阶段保留记忆（门控开启）作为“提效层”；技能从候选集中移除（或只保留
   极少数安全/合规薄技能，且不作为前置激活）。但这需要等 P3 用真实日志验证开放题后再定。

### 15.4 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --arms C,D \
  --memory-min-neighbors 2 --memory-min-similarity 0.8 --memory-max-return-std 0.5 \
  --out runs/p2-3-skills
python tools/run_pms_experiment.py --model openai --arms E \
  --memory-min-neighbors 2 --memory-min-similarity 0.8 --memory-max-return-std 0.5 \
  --out runs/p2-3-noskill-nomem
```

## 十六、P3-模拟扩展数据（2026-11-12）

真实鉴权尚未拿到，先做**可确定复现的扩展模拟数据**，用于验证 P2-3 的结论是否能推广到更多站/设备。

### 16.1 扩展数据

在 `expert-pack-3` 的 mock 数据模块增加可选扩展（默认数据集完全不变）：

- 设置 `PMS_MOCK_DATASET=extended` 才启用 [data_extended.py](../expert-pack-3/skills/pms-gateway-mcp/scripts/mock_gateway/data_extended.py)；
- 克隆 220kV 郑州变 6 份：新增 6 个站、30 台设备、36 个 PSR、30 条缺陷、12 条容量、
  6 条站可靠性、18 条检修计划；
- 主键（asset/psr/utc/defect/plan）全部重编号且互认，数值保持与原站一致，便于判分；
- 扩展后总量：10 站 / 39 设备 / 49 PSR / 36 缺陷 / 21 检修计划。

### 16.2 扩展任务集

[tasks.py](../expert_pack/extensions/pms/tasks.py) 新增 `build_extended_tasks()`：
6 个克隆站 × 11 题 = **66 题**，仍覆盖 6 个意图族。

### 16.3 真实模型结果（扩展 66 题）

| 臂 | 记忆 | 技能 | 成功 | 成功率 | 平均步数 | 工具错误 |
|---|---|---|---|---|---|---|
| B | 有 | 12 全技能 | 66/66 | **100.00%** | 2.23 | 0 |
| D | 有 | 0 技能 | 66/66 | **100.00%** | **2.12** | 0 |
| E | 无 | 0 技能 | 66/66 | **100.00%** | 2.38 | 0 |

结果：
- [B 扩展结果](../runs/p3-extended-skills/summary.md)
- [D/E 扩展结果](../runs/p3-extended-real/summary.md)

结论：

1. **扩展到 6 个新站后，D/E 仍然 100%**，P2-3 的“无技能也能做对”结论可推广到更多站/设备；
2. **B（12 技能）也 100%，但平均步数比 D 多 0.11 步**（2.23 vs 2.12），技能仍只是开销；
3. **记忆仍有提效价值**：D 比 E 少 0.26 步（2.12 vs 2.38），正确率相同；
4. 数据是“克隆同构站”，只能验证规模/路由泛化，**不能替代真实业务分布**；等拿到鉴权后仍需真实日志复测。

### 16.4 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --dataset extended --arms D,E \
  --memory-min-neighbors 2 --memory-min-similarity 0.8 --memory-max-return-std 0.5 \
  --out runs/p3-extended-real
```

## 十七、P3-异构真实分布模拟（2026-11-13）

### 17.1 数据

新增 `PMS_MOCK_DATASET=realistic`（[data_realistic.py](../expert-pack-3/skills/pms-gateway-mcp/scripts/mock_gateway/data_realistic.py)）：

- 6 个异构站：220kV 航空港/高新，110kV 大学城/滨河，35kV 城西/物流园；
- 7 台主变：容量 240/180/120/50/20MVA，厂家 3 家，投运年份 2012–2023；
- 负载率 12%–92%（含重载 92%）、可用率 99.60%–99.99%；
- 缺陷 4 条（危急/严重/一般，处理中/待处理/已消除），两站无缺陷；
- 检修计划 3 条（待执行/已逾期），部分站无计划。

扩展后总量：10 站 / 16 设备 / 26 PSR / 10 缺陷 / 6 检修计划。

### 17.2 任务集

[tasks_realistic.py](../expert_pack/extensions/pms/tasks_realistic.py)：**33 题**，覆盖 6 个意图族与不同电压等级/容量/状态。

### 17.3 真实模型结果（33 题）

| 臂 | 记忆 | 技能 | 成功 | 成功率 | 平均步数 | 工具错误 |
|---|---|---|---|---|---|---|
| B | 有 | 12 全技能 | 32/33 | 96.97% | 2.30 | 0 |
| D | 有 | 0 技能 | 33/33 | **100.00%** | 2.42 | 0 |
| E | 无 | 0 技能 | 33/33 | **100.00%** | 2.42 | 0 |

结果：
- [B 全技能](../runs/p3-realistic-skills/summary.md)
- [D/E 无技能](../runs/p3-realistic-real/summary.md)

### 17.4 结论

1. **技能又造成 1 次失败**：B 在 `reliability-availability-801` 先激活
   `skill:substation-reliability`，随后自造参数、耗尽步数；D/E 无技能均 100%。
2. **异构数据上记忆没有带来步数收益**：D 与 E 都是 2.42 步、100%。说明记忆的提效
   依赖“同族状态高度重复”；异构站/不同容量的场景下收益不稳定。
3. **决策**：继续采用“无技能 + 契约强制”的基线；记忆保留为可选层（门控开启），
   但不作为性能承诺；真实日志到位后再决定是否启用。

### 17.5 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --dataset realistic --arms D,E \
  --memory-min-neighbors 2 --memory-min-similarity 0.8 --memory-max-return-std 0.5 \
  --out runs/p3-realistic-real
```

## 十八、P3-复杂任务与步进 RL 状态（2026-11-13）

### 18.1 复杂任务集（26 题）

新增 [tasks_complex.py](../expert_pack/extensions/pms/tasks_complex.py)，用同一套 realistic 数据，但问题需要
**多步/比较/判断**：

| 类型 | 例子 | 为什么复杂 |
|---|---|---|
| `capacity_max` | “某站负载率最高的主变是哪台？” | 需要先取容量列表再比较 |
| `defect_presence` | “某站是否存在严重及以上缺陷？” | 需要查缺陷并做判断 |
| `reliability_threshold` | “某站可用率是否低于 99.9%？” | 需要查询 + 数值比较 |
| `highest_model` | “某站负载率最高的主变型号？” | 需要两步：找最高负载设备 → 查型号 |
| `global_rank` | “所有站里可用率最低的是哪个站？” | 需要跨站比较 |

### 18.2 真实模型结果（26 题）

| 臂 | 记忆 | 技能 | 成功 | 成功率 | 平均步数 | 工具错误 |
|---|---|---|---|---|---|---|
| D | 有 | 0 | 16/26 | 61.54% | 2.65 | 0 |
| E | 无 | 0 | 17/26 | 65.38% | 2.92 | 0 |

结果：[D/E 复杂任务](../runs/p3-complex-real/summary.md)。

### 18.3 失败分析（为什么复杂任务变差）

1. **候选生成瓶颈**：模型经常连续调 `list_asset_params` / `list_psr_by_filters`，根本没有提出
   “先 `query_open_capacity` 找最高负载”的正确候选。JitRL 只能给已有候选打分，**不能生成模型没提出的动作**。
2. **比较/判断错误**：如“可用率是否低于 99.9%”查到了 99.60 却答“否”；“最低可用率站”选错。
3. **步数耗尽**：复杂题需要 3–4 步，模型在错误工具链上打转。

因此这次 D 反而略低于 E（61.54% vs 65.38%）：**当正确候选根本不出现时，记忆无法救场**。

### 18.4 关于“步进 RL”：目前没有实现

之前讨论的“从回合改进改成步进”目前**只做了设计，没有落地**：

- 当前仍是**回合级**：任务结束后评测器给逐步奖励 → 写回记忆；
- 步级需要：即时/稠密奖励、provisional 写入、TD bootstrap、检索隔离；
- 更关键的是：本轮复杂任务失败的主因是**候选动作没生成**，步级更新也改变不了候选生成；
  如果模型不提出正确工具，更快的更新频率没有意义。

所以建议顺序是：

1. 先解决候选生成（工具选择提示、按意图裁剪工具集、schema 强约束）；
2. 再考虑步级 RL（用工具成功/业务校验做稠密奖励）；
3. 最后才做“逐 step 实时更新”的生产化。

### 18.5 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --dataset complex --arms D,E \
  --memory-min-neighbors 2 --memory-min-similarity 0.8 --memory-max-return-std 0.5 \
  --out runs/p3-complex-real
```

## 十九、候选生成增强（2026-11-13）

### 19.1 实现

1. **意图 → 工具提示**：在 [tasks.py](../expert_pack/extensions/pms/tasks.py) 增加
   `INTENT_ACTIONS` 映射，任务 `context["suggestedActions"]` 带上建议工具：
   - 台账型号 → `get_asset_by_id`
   - 缺陷等级 → `view_defect`
   - 负载率 → `query_open_capacity`
   - 可用率 → `query_station_scale_analysis`
   - 检修计划 → `get_repair_plan`
   - 复杂题：最高负载 → `query_open_capacity`；最高负载设备型号 → 再加 `get_asset_by_id`；
     缺陷存在性 → `inquire_defect`；跨站比较 → 站级/容量查询。
2. **提示词注入**（[agent.py](../expert_pack/agent.py)）：
   `SUGGESTED ACTIONS FOR THIS TASK`，明确告诉模型优先用这些工具，避免无关工具。
3. **可选强制白名单**：`AgentConfig.enforce_action_hints=true` 时，模型提出的候选若不在
   建议工具 + `answer` 内会被拒绝，并进入 repair 重试；可通过 `--enforce-hints` 开启。
4. 测试：
   - `test_suggested_actions_are_enforced`（提示注入 + 白名单拒绝）；
   - 复杂任务集 26 题形状测试。

### 19.2 效果（复杂 26 题，真实模型）

| 配置 | 臂 | 成功 | 成功率 | 平均步数 |
|---|---|---|---|---|
| 无提示 | D | 16/26 | 61.54% | 2.65 |
| 无提示 | E | 17/26 | 65.38% | 2.92 |
| **有提示+白名单** | D | 21/26 | **80.77%** | 2.50 |
| **有提示+白名单** | E | 21/26 | **80.77%** | 2.50 |

结果：
- [无提示复杂任务](../runs/p3-complex-real/summary.md)
- [有提示 D](../runs/p3-complex-hints-D/summary.md)
- [有提示 E](../runs/p3-complex-hints/summary.md)（E 在同一次运行中）

结论：

- **候选生成增强有效**：复杂任务成功率从 ~61–65% 提升到 **80.77%**（+15pp 左右），
  步数从 2.65/2.92 降到 2.50；
- **记忆仍没有额外收益**：D 与 E 都是 21/26、2.50 步；
- 剩余失败主要是**比较/判断错误**（如“最低可用率站”选错），不是工具选择问题；
- 因此下一刀不是步进 RL，而是 **比较/推理约束**（例如要求先列出候选再比较，或给出计算步骤）。

### 19.3 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --dataset complex --arms D,E \
  --enforce-hints --memory-min-neighbors 2 --memory-min-similarity 0.8 \
  --memory-max-return-std 0.5 --out runs/p3-complex-hints
```

## 二十、比较引导（2026-11-13）

### 20.1 实现

在候选生成增强的基础上，针对剩余“比较/判断错误”增加两层约束：

1. **系统级规则**（`agent._SYSTEM`）：凡是“最高/最低/阈值/是否大于/小于”的任务，
   必须先取回所有候选记录，比较后再回答，不允许看一行就下结论。
2. **动态提示**（`agent._render_prompt`）：检测到 goal 含比较关键词时追加
   `COMPARISON REQUIRED`，明确要求先列全候选、比较 `loadRate/availabilityRate/defectLevel`。

同时把复杂任务族的 `max_steps` 补齐：`highest_model=6`、`global_rank=6`、`capacity_max=5`，
`defect_presence/reliability_threshold=4`；单测验证 `COMPARISON REQUIRED` 注入。

### 20.2 复测状态

真实模型 26 题复测在任务 8/26 处被 **ARK 账号月度配额（HTTP 429）中断**；2026-11-16 再次尝试，
26/26 全部返回 `AccountQuotaExceeded`，仍未得到完整结果。代码与单测已完成
（`test_comparison_prompt_is_injected_for_compare_tasks`、`test_task_plan_hint_is_injected`）；
完整 A/B 结果需等 **2026-11-17 配额重置**后重跑。

### 20.3 任务计划提示（补强）

仅靠“比较规则”仍可能让模型选错第一步；为复杂意图补充 `INTENT_PLANS`：

- `capacity_max`：先 `query_open_capacity` 取全部负载，比较后回答；
- `defect_presence`：先 `inquire_defect`，判断是否存在严重/危急；
- `reliability_threshold`：先 `query_station_scale_analysis`，与 99.9 比较；
- `highest_model`：先 `query_open_capacity` 选最大负载 `deviceId`，再 `get_asset_by_id` 查型号；
- `global_rank`：先取全部候选，再在全部记录上比较。

任务 `context["planHint"]` 会自动进入 prompt 的 `TASK PLAN` 段；单测覆盖。

### 20.4 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --dataset complex --arms D,E \
  --enforce-hints --memory-min-neighbors 2 --memory-min-similarity 0.8 \
  --memory-max-return-std 0.5 --out runs/p3-complex-compare
```

## 二十一、Kimi 模型复测（2026-11-16）

ARK 月度配额未恢复，改用 `.env` 中新增的 Kimi 配置：

```text
KIMI_OPENAI_BASE_URL=https://api.kimi.com/coding/v1
KIMI_MODEL=k3.1-pro-highspeed
```

harness 新增 `--provider {ark,deepseek,kimi}`：

- Kimi 只接受 `temperature=1`，通过 `extra_body` 强制覆盖；
- Kimi 的 reasoning tokens 会占用 `max_tokens`，因此提高上限到 2000；
- 修复了 Kimi 返回空 content 时 repair 消息包含空 assistant 导致 HTTP 400 的问题。

### 21.1 复杂 26 题结果（Kimi，提示+白名单+比较引导+计划提示）

| 臂 | 记忆 | 成功 | 成功率 | 平均步数 | 工具错误 |
|---|---|---|---|---|---|
| D | 有 | 25/26 | **96.15%** | 2.54 | 0 |
| E | 无 | 24/26 | 92.31% | 2.54 | 0 |

结果：[runs/p3-kimi-complex/summary.md](../runs/p3-kimi-complex/summary.md)。

结论：

- Kimi 在复杂任务上明显强于 ARK 配额前的结果（ARK 有提示+白名单为 80.77%），但**不同模型/采样温度不可直接横比**；
- 记忆仍只带来 1 题差异（96.15% vs 92.31%），平均步数完全相同（2.54）；
- 两臂都失败的是 `global-lowest-availability-01`：跨 9 个站比较可用率时都选了 110kV 大学城（99.70），
  而最低是 35kV 物流园（99.60）。说明“候选生成/工具提示”已解决，**剩余瓶颈是比较逻辑本身**。

### 21.2 运行方式

```powershell
python tools/run_pms_experiment.py --model openai --provider kimi --dataset complex \
  --arms D,E --enforce-hints --memory-min-neighbors 2 --memory-min-similarity 0.8 \
  --memory-max-return-std 0.5 --out runs/p3-kimi-complex
```

## 二十二、比较方案对比：结构化候选表 vs 确定性 rank 工具（2026-11-16）

针对“跨记录比较”瓶颈，实现了两种方案并分别测试（均为 E 臂、复杂 26 题、无技能、带工具提示）：

### 22.1 方案 1：结构化候选表（prompt）
`--structured-compare`：要求模型在 `thought` 字段先列出每个候选的 `name: metric=value`，再回答。

### 22.2 方案 2：确定性 rank 工具（代码）
`--rank-tool`：绑定本地 `pms-rank` 工具：

- `rank_stations(metric=availabilityRate, direction=min)`；
- `rank_devices(stationId?, metric=loadRate, direction=max)`。

模型把比较交给代码，直接拿到 winner，不再心算。

### 22.3 结果（DeepSeek `deepseek-flash`，E 臂 26 题）

| 方案 | 成功 | 成功率 | 平均步数 |
|---|---|---|---|
| 方案 1：结构化候选表 | 18/26 | 69.23% | 3.35 |
| **方案 2：rank 工具** | **26/26** | **100.00%** | **2.46** |

结果：
- [结构化候选表](../runs/p3-deepseek-structured/summary.md)
- [rank 工具](../runs/p3-deepseek-rank/summary.md)

### 22.4 Kimi 上的对照

- 基线 E（无附加方案）：24/26（92.31%），2.54 步；
- 方案 1 结构化表：19/26（73.08%），3.23 步（**变差**）；
- 方案 2 rank 工具：跑到第 21 题时触发 Kimi 5 小时额度限制（前 21 题 20 对，未完成全量）。

Kimi 的 5 小时额度与 ARK 的月度额度不同，需等窗口重置后补齐方案 2 的 Kimi 全量结果。

### 22.5 结论

**方案 2（确定性 rank 工具）明显更好**：

- DeepSeek 上 100% vs 69.23%，步数 2.46 vs 3.35；
- Kimi 上结构化表也变差，rank 工具部分结果已显示优势；
- 结构化表让模型多写一步表格，容易拖长步数/触发循环；
- 比较/排序属于确定性计算，交给代码比交给模型心算更可靠。

后续默认采用 `--rank-tool`；结构化表保留为可选诊断手段。

### 22.6 运行方式

```powershell
# 方案 2：rank 工具
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex --arms E \
  --enforce-hints --rank-tool --out runs/p3-deepseek-rank

# 方案 1：结构化候选表（对照）
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex --arms E \
  --enforce-hints --structured-compare --out runs/p3-deepseek-structured
```

## 二十三、轨迹树存储与可视化（2026-11-16）

新增实验性能力：append-only 轨迹树 + 自包含 HTML 可视化，详见
[docs/TRAJECTORY-TREE.md](TRAJECTORY-TREE.md)。

- 存**完整 observation**（不是被截断的 prompt 片段）；
- 存每个 step 的**全部候选动作**（selected + alternatives）；
- 不按人类意图/Skill 标签做硬剪枝，树由实际轨迹长出来；
- 支持 `--tree-store` 边跑边记，HTML 查看森林，PNG 看单棵子树；
- 示例：[trajectory-tree/](../trajectory-tree/)。

这次改动不触碰 JitRL 数学与 agent 循环，只增加一个实验性记录器。
