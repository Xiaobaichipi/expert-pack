# 空缺位置

这份文档解释"空缺"是什么、怎么读报告、以及目标机器上的智能体该按什么顺序填。

机器可读清单由代码生成，可能随装配变化：

- [VACANCIES.txt](VACANCIES.txt) —— 默认骨架的人类可读表
- [VACANCIES.json](VACANCIES.json) —— 默认骨架的 JSON（含契约名、提示、状态）

重新生成：

```bash
python -m expert_pack slots --write docs/VACANCIES.txt
python -m expert_pack slots --json --write docs/VACANCIES.json
python -m expert_pack slots --assembly my.json --write docs/MY-VACANCIES.txt
```

## 五个状态

| 状态 | 含义 | 是否算空缺 |
|---|---|---|
| `bound` | 装配文件给了绑定，且通过契约检查 | 否 |
| `builtin` | 没给绑定，用框架自带实现 | 否（但可能是 `stub`） |
| `open` | 可选槽，什么也没有 | 是 |
| `vacant` | 必需槽，什么也没有 | 是（阻断） |
| `invalid` | 装了东西但违约/配置错 | 是（阻断，且带原因） |

`quality` 是第二维：`production` / `demo` / `stub` / `unknown`。
一个 `bound` 但 `quality=stub` 的必需槽，在 `--strict` 下仍被拒绝——因为"装上了"
不等于"装对了"。

## 默认骨架的空缺

| 槽位 | 状态 | 缺什么 | 填法 |
|---|---|---|---|
| `model` | `builtin`、`stub` | 真模型后端 | `module: expert_pack.adapters.model_openai:from_config` + config；或 `builtin: scripted` 做离线自检 |
| `tools` | `open` | 至少一个 ToolProvider / MCP 服务器 | 每条 `{"type":"mcp_stdio","target":"<name>","config":{...}}` |
| `skills` | `open` | Skill 目录 | `{"type":"skill_dir","target":"skills"}` |
| `store` | `builtin` | —（有 SQLite） | 需要共享/向量时可替换 |
| `retriever` | `builtin` | —（Jaccard） | 需要语义检索时替换 |
| `abstractor` | `builtin` | —（通用归一化） | 领域分面更强时替换 |
| `policy` | `builtin` | —（JitRL） | 做消融时可替换成纯先验 |
| `evaluator` | `builtin`、`demo` | 开放任务需要 LLM 评测 | `{"type":"builtin","target":"llm"}` |

## 目标机器上的填充顺序

1. `model`：**唯一硬阻断**。没有它，`run` 会给出可执行的提示后退出（exit 2）。
2. `tools`：先接一个只读 MCP 服务器，确认 `tools/list` 能通。
3. `skills`：有现成 `SKILL.md` 目录就接；没有就跳过（纯工具智能体也能跑）。
4. `evaluator`：任务有明确期望答案时，启发式够用；开放任务接 `llm`。
5. `store` / `retriever` / `abstractor` / `policy`：先留默认，等有真实流量再换。

## 为什么空缺是"位置"而不是"待办列表"

- 每个空缺在代码里**已经存在**：`DEFAULT_SLOTS` 里有名字、契约、解析顺序、内置回退。
  填空不会改变回环结构，只改变某一步由谁实现。
- 每个空缺有**契约**：装错东西当场报错（`slot 'x' does not satisfy Contract`），
  而不是等到运行到某个分支才炸。
- 每个空缺有**回退**：`store`/`retriever`/`abstractor`/`policy`/`evaluator` 都有可用默认，
  所以"只填模型"就能跑通；空缺是增量，不是硬门槛（`model` 除外）。

这正是"先搭骨架、后组装"的含义：空缺是**已定义的接口位置**，不是 TODO 注释。
