# AGENTS.md

本仓库是一个可运行的骨架：**槽位 + 契约 + 装配文件**。改动前先读这几条指针，
不要靠猜。

## 入口

| 想知道 | 读 |
|---|---|
| 接口与数据类型 | [expert_pack/contracts.py](expert_pack/contracts.py) —— 唯一必须读的接口文件 |
| 有哪些槽、怎么算空缺 | [expert_pack/slots.py](expert_pack/slots.py)、[docs/VACANCIES.md](docs/VACANCIES.md) |
| 装配文件怎么写 | [docs/ASSEMBLY.md](docs/ASSEMBLY.md) |
| 整体设计与不变量 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| JitRL 借了什么、偏离什么 | [docs/JITRL.md](docs/JITRL.md) |
| 批处理与检查点 | [docs/PIPELINE.md](docs/PIPELINE.md) |
| 在目标机器上装配的流程 | [skills/expert-pack-assemble/SKILL.md](skills/expert-pack-assemble/SKILL.md) |

## 改动规则

1. **新增能力优先做成适配器 + 装配绑定**，不要改 `agent.py` 的循环。
   循环只知道槽位名，不应该知道具体模型或服务器。
2. **新增字段前先问：它属于哪个契约？** 不属于任何槽位的字段应该进 `AgentConfig`
   （装配的 `agent` 段），并且 `assembly.load_assembly` 会拒绝未知键。
3. **保持核心零第三方依赖**。`jitrl/`、`adapters/`、`agent.py` 只用标准库。
   YAML（可选）、npx、模型 SDK 都属于外部世界。
4. **失败要分类**：配置错 → `AssemblyError`；契约不合 → `ContractError`；
   必需槽空 → `VacancyError`；外部系统挂了 → `ToolError`/`McpError`/`ModelError`。
   循环里任何适配器异常都变成 `Observation(ok=False)`，绝不冒泡成崩溃。
5. **先写测试再改行为**。测试不联网、不需要 key、必须可复现：

```bash
python -m unittest discover -s tests -t .
```

6. **改 JitRL 数学**（归一化、探索、权重、回报）时，同时更新
   [docs/JITRL.md](docs/JITRL.md) 的对应表与测试；这些数字是被测试锁住的。

## 不变量（改代码前确认不会破坏）

- 记忆只在回合结束后写（`agent._write_memory`），一步的回报依赖整条轨迹的评测。
- 记忆回放的参数必须"可移植"（`agent._arguments_portable`）。
- 检索先结构相容再文本相似（`jitrl/retrieval.py`）。
- `task.context["expect"]` 决定成功，优先于评测器与模型的自评。
- `temperature=0` 是纯 argmax，不消耗随机数，保证演示可复现。

## 验证改动的最小流程

```bash
python -m unittest discover -s tests -t .
python -m expert_pack slots
python -m expert_pack validate --assembly assembly.example.json
python -m expert_pack demo --tasks 6          # 期望：baseline 0% → memory ≥ 66%
```

## 常见坑

- Windows 上 `python` 不一定是真解释器；用 `python -m unittest` 前确认解释器路径。
- MCP 服务器只支持 stdio；不要在 `assembly.json` 里写 HTTP 传输配置。
- `builtin: scripted` 的 `quality` 是 `demo`，`--strict` 允许；`builtin: unbound` 是 `stub`，不允许。
- 演示用的脚本规划器是"故意固执"的固定先验，不要拿它的分数当模型能力。
