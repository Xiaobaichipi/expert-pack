---
name: expert-pack-assemble
description: 在目标电脑上把 expert-pack 的空缺（model / MCP tools / skills / 评测器）装配成可运行智能体，并做离线自检与最小验证。
when_to_use: 用户要在新机器上组装 expert-pack、接 MCP 服务器 / Skill、或排查"槽位没填好/跑不起来"。
---

# expert-pack 装配

目标：把一个带空缺的 expert-pack 骨架，在这台机器上**验证到能跑**，
并且每一步失败都能定位到具体槽位。

## 0. 先看状态，不要先改配置

```bash
python -m expert_pack slots --assembly .expert_pack/assembly.json
```

只读绑定表，不启动任何东西。`open`/`vacant`/`invalid` 是你的输入；
`stub` 的必需槽等同未装配。

完成标准：你能说出剩下几个空缺、哪个是必需、每个空缺要什么类型。

## 1. 填 hard 空缺：`model`

唯二必需槽之一（另一个是循环本身）。二选一：

- 真模型：

```json
{"slot": "model", "type": "module",
 "target": "expert_pack.adapters.model_openai:from_config",
 "config": {"model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1",
           "api_key_env": "OPENAI_API_KEY"}}
```

- 离线自检（没有 API key 时先用它确认管道通）：

```json
{"slot": "model", "type": "builtin", "target": "scripted",
 "config": {"planner": "demo"}}
```

完成标准：`validate` 里 `model` 是 `bound production`（离线自检时是 `bound demo`）。

## 2. 接 MCP 工具（`tools`）

一条服务器一条绑定，`target` 是短名，会变成动作 id `tool:<name>/<tool>`：

```json
{"slot": "tools", "type": "mcp_stdio", "target": "fs",
 "config": {"command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
            "timeout": 20}}
```

注意：
- `command` 必须是**这台机器上真能执行**的命令：Windows 上优先写全路径，
  或确认在 PATH 里（`npx`/`uvx`/`python` 都可能不在 Agent 的 PATH）。
- 只支持 stdio + `initialize`/`tools/list`/`tools/call`。资源、prompts、HTTP 传输**未实现**，
  不要把需要它们的服务器硬塞进来。
- 启动失败是**立即失败**并带 stderr 尾部，不会静默变成"零工具"。

完成标准：`validate` 里 `tools` 是 `bound`，且 `run --trace` 第一步的
`AVAILABLE ACTIONS` 里能看到该服务器的工具 id。

## 3. 接 Skill（`skills`）

```json
{"slot": "skills", "type": "skill_dir", "target": "skills"}
```

目录结构：

```
skills/
  my-skill/
    SKILL.md      # frontmatter: name / description / when_to_use + 正文指令
    skill.py      # 可选：def run(context, arguments) -> dict
```

- 只有 `SKILL.md`：选择它会把正文加载进上下文（`kind="instructions"`）。
- 有 `skill.py`：选择它会执行 `run`，结果作为观察回灌。
- `description` 是模型的路由依据，写"做什么"而不是"是什么"。

完成标准：`actions` 列表里出现 `skill:<name>`；prompt-only Skill 被选中后，
后续提示里能看到它的指令。

## 4. 选评测器（`evaluator`）

- 任务有明确期望答案（数字/固定短语）：默认 `heuristic` 足够，
  并在任务里写 `"context": {"expect": "..."}`。
- 开放任务：`{"slot":"evaluator","type":"builtin","target":"llm"}`。
  它用模型打逐步奖励，格式不合法时回退启发式，且 `expect` 永远优先于模型的"成功"判断。

完成标准：`results.jsonl` 里 `evaluator` 字段符合预期，`returns` 长度等于步数。

## 5. 离线自检 → 真模型最小验证

```bash
# A. 不依赖任何外部服务：只验证装配、管道、记忆
python -m expert_pack demo --tasks 3

# B. 用目标装配跑 2–3 个已知答案的任务
python -m expert_pack run --tasks examples/tasks.arithmetic.jsonl \
       --assembly .expert_pack/assembly.json --trace
```

完成标准：A 里 baseline 明显低于 memory（记忆确实在起作用）；
B 里至少一条任务成功，且 `trace` 的 `shaped` 能解释每一步的选择。

## 6. 只在必要时动这些槽

| 现象 | 动哪个槽 | 不动什么 |
|---|---|---|
| 检索总是抓到不相干经验 | `retriever`（先关 `require_structural_match` 试） | 不要改 `store` 格式 |
| 经验跨任务串参数 | `abstractor`（加分面）/ 任务 `family` | 不要放宽 `_arguments_portable` |
| 探索过多/过少 | `policy.adaptive_exploration`、`lambda_explore`、`beta` | 不要关 `memory_context` 了事 |
| 记忆要共享/持久到别处 | `store`（实现 `ExperienceStore`） | 不要改 `agent` 写回时序 |
| 需要语义检索 | `retriever`（实现 `Retriever`） | 不要引入嵌入依赖到核心包 |

## 不要做的事

- 不要为了让 `validate` 过而删掉 `--strict` 的语义：`stub` 就是没装。
- 不要手工改 `.sqlite3`：用 `memory clear` / `memory export`。
- 不要在 `assembly.json` 里写密钥：用 `${ENV}` 展开，缺变量会报错而不是传空串。
- 不要把"模型说成功"当成成功：任务里给 `expect`，让判定可复现。

## 交接产物

装配完成后，把这三样交给下一台机器：

1. `assembly.json`（脱敏后，密钥留 `${ENV}`）
2. 任务文件 `*.jsonl`
3. `python -m expert_pack pack --out dist/expert-pack.zip`

对方解压后：`python -m expert_pack validate --assembly ...` → `run ...`。
