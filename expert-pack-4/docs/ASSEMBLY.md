# 装配参考

装配文件是一份 JSON（也接受 YAML，需要 PyYAML），描述"哪个槽位装什么"。
它**不描述**智能体怎么工作——那是代码；它只填空。相对路径以装配文件所在目录为基准。

## 完整结构

```json
{
  "version": 1,
  "name": "my-pack",
  "agent": {
    "max_steps": 8,
    "temperature": 0.0,
    "seed": 7,
    "memory_context": true,
    "memory_context_k": 3,
    "max_candidates": 5,
    "max_consecutive_errors": 3,
    "write_memory": true,
    "repair_attempts": 1,
    "memory_actions": true,
    "memory_action_limit": 3,
    "max_answer_chars": 400,
    "max_prompt_observation_chars": 500
  },
  "bindings": [ ... ]
}
```

| 字段 | 含义 |
|---|---|
| `version` | 必须是 `1` |
| `name` | 报告与运行日志里的名字 |
| `agent` | 覆盖 `AgentConfig` 字段；写错的键会直接报错并列出允许键 |
| `bindings` | 绑定列表，按顺序解析；`tools`/`skills` 可多条，其余单条 |

`config` 里的字符串支持 `${ENV_VAR}` 展开，缺变量会报错而不是静默传空串。
每条绑定可选 `quality`，不写时按类型自动判定：

- `builtin: unbound` → `stub`
- `builtin: scripted / null / heuristic` → `demo`
- 其余 → `production`

`--strict` 拒绝：`vacant`、`invalid`、以及**必需槽位**装的是 `stub`/`unknown`。
`demo` 允许通过（它可用，只是能力有限）。

## 五种绑定类型

### `builtin` — 框架自带

| 槽位 | target | config |
|---|---|---|
| `model` | `unbound` | — （响亮失败，提示怎么绑） |
| `model` | `scripted` | `{"planner": "demo"}` 或 `{"responses": ["..."]}` |
| `store` | `sqlite` | `{"path": "...", "max_records": 200000}` |
| `store` | `null` | —（不记忆的对照臂） |
| `policy` | `jitrl` | 见下方 `AdvantageConfig` |
| `evaluator` | `heuristic` | `{"step_penalty": -0.03, ...}` |
| `evaluator` | `llm` | `{"temperature": 0.0}`（需要 `model` 先解析） |
| `retriever` | `jaccard` | `{"max_scan": 20000, "exact_boost": 1.0, "require_structural_match": true}` |
| `abstractor` | `default` | `{"max_chars": 240, "max_tokens": 48, "ngram": 2, ...}` |

`policy: jitrl` 的 config 来自 `AdvantageConfig`：

```json
{"top_k": 5, "min_similarity": 0.4, "gamma": 0.5, "alpha": 1.0,
 "lambda_explore": 0.3, "beta": 1.0, "adaptive_exploration": true,
 "exploration_rate": 1.0, "normalization": "signed",
 "episode_weight": true, "max_memory_actions": 3}
```

### `module` — `包.模块:名字`

```json
{"slot": "model", "type": "module",
 "target": "expert_pack.adapters.model_openai:from_config",
 "config": {"model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1",
           "api_key_env": "OPENAI_API_KEY", "timeout": 60}}
```

有 `config` 时该属性会被当作**工厂**调用（`factory(**config)`）；
无 `config` 时直接使用该对象（适合类本身即可构造、或已是实例的情况）。

### `path` — 本地 `.py` 文件

```json
{"slot": "retriever", "type": "path", "target": "adapters/my_retriever.py"}
```

文件里必须有一个与文件名同名的对象（`my_retriever`）；或改用 `module` 写法显式命名。

### `mcp_stdio` — 只用于 `tools`

```json
{"slot": "tools", "type": "mcp_stdio", "target": "filesystem",
 "config": {"command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
            "env": {"TOKEN": "${FS_TOKEN}"},
            "cwd": ".",
            "timeout": 20}}
```

`target` 是 provider 名（出现在动作 id `tool:<name>/<tool>` 里），`command` 是真正启动的命令。
启动失败会立刻给出 `McpError`，附 stderr 尾部，不会静默降级成"没有工具"。

### `skill_dir` — 只用于 `skills`

```json
{"slot": "skills", "type": "skill_dir", "target": "skills"}
```

加载该目录下每个含 `SKILL.md` 的子目录。Skill 格式：

```markdown
---
name: my-skill
description: 一句话说明（会出现在 AVAILABLE ACTIONS 里）
when_to_use: 什么时候该用
---
正文就是加载到上下文的指令。
```

有 `skill.py` 且定义了 `run(context, arguments)` 时，该 Skill 变成**可执行动作**：

```python
def run(context, arguments):
    # context: task / state / step_index / observation
    return {"ok": True, "content": "结果文本", "data": {...}}   # 或 SkillResult
```

没有 `skill.py` 时选择它只加载正文（`kind="instructions"`），与 Claude/Agent Skill 行为一致。

## 配方

### OpenAI / OpenRouter / vLLM / Ollama

```json
{"slot": "model", "type": "module",
 "target": "expert_pack.adapters.model_openai:from_config",
 "config": {"model": "gpt-4o-mini", "base_url": "https://openrouter.ai/api/v1",
           "api_key_env": "OPENROUTER_API_KEY"}}
```

本地 Ollama（OpenAI 兼容层）：

```json
{"slot": "model", "type": "module",
 "target": "expert_pack.adapters.model_openai:from_config",
 "config": {"model": "qwen2.5:7b", "base_url": "http://127.0.0.1:11434/v1",
           "api_key_env": "OLLAMA_KEY"}}
```

（Ollama 不校验 key，随便设一个环境变量即可；`api_key_env` 只是"从哪个变量读"。）

### 多 MCP 服务器

```json
{"slot": "tools", "type": "mcp_stdio", "target": "fs",  "config": {...}},
{"slot": "tools", "type": "mcp_stdio", "target": "git", "config": {...}}
```

每个服务器是独立进程，工具 id 形如 `tool:fs/read_file`、`tool:git/status`，互不冲突。

### 完全离线的自检

```json
{"slot": "model", "type": "builtin", "target": "scripted", "config": {"planner": "demo"}}
```

用于验证装配、管道、记忆是否通，不需要任何外部服务。

## 校验与报错

```bash
python -m expert_pack validate --assembly assembly.json          # 解析 + 契约检查
python -m expert_pack validate --assembly assembly.json --strict # 还要没有 stub
```

常见错误与含义：

| 报错 | 原因 | 修法 |
|---|---|---|
| `unknown slot 'xxx'; known slots: ...` | slot 名字打错 | 用 `slots` 命令里的名字 |
| `slot 'model' accepts exactly one binding` | 单值槽装了两条 | 删掉一条 |
| `binding #n: 'type' must be one of [...]` | type 拼错 | 用五种类型之一 |
| `unknown keys [...]` | config 里有未定义字段 | 删掉或改用支持字段 |
| `cannot import 'pkg.mod'` | 模块不存在/依赖没装 | 装依赖或用 `path` |
| `slot 'x' does not satisfy Contract` | 对象缺方法 | 按契约补 `complete`/`call_tool` 等 |
| `strict assembly failed: model: required slot holds a stub binding` | 没绑真模型 | 绑模型或去掉 `--strict` |
| `environment variable 'FOO' is not set` | `${FOO}` 没定义 | 设环境变量 |

## 从空缺到可运行的最短路径

```bash
python -m expert_pack init my-pack && cd my-pack
python -m expert_pack slots --assembly .expert_pack/assembly.json      # 看缺什么
# 编辑 .expert_pack/assembly.json：填 model（必需），按需填 tools / skills
python -m expert_pack validate --assembly .expert_pack/assembly.json
python -m expert_pack run --tasks tasks.example.jsonl \
       --assembly .expert_pack/assembly.json --trace
```

目标机器上没有给 Agent 用的技能库时，可直接加载本仓库的装配 Skill：
`skills/expert-pack-assemble/SKILL.md`。
