# expert-pack

一个**槽位化（slot-based）的 Skills + MCP 智能体框架**：骨架先做好，能力用声明式装配文件填。
骨架里每个可替换的位置都是一个**显式空缺**，并带契约、状态和可读的"还缺什么"报告；
填充物是 Skill、MCP 服务器、模型后端、记忆实现或评测器。

它同时用 **JitRL**（Just-In-Time Reinforcement Learning，ICML 2026）的思想改造了智能体本身：
不做梯度更新，而是把每次任务的 `<状态, 动作, 回报>` 存进经验记忆，推理时检索邻居、
估计优势、直接修正候选动作的分数。优势项就是论文闭式解的离散版本。

```
一次任务 = 抽象状态 → 检索邻居 N(s) → 模型给候选 → 记忆优势修正 → 选一个 → 执行 → 观察
任务结束 = 评测器给每步奖励 → 折扣回报 G_t → 写回记忆（下一轮更好）
```

## 30 秒验证（不需要 API key、不需要联网）

```bash
python -m expert_pack demo
```

真实输出（本机 Python 3.10，Windows）：

```
task       baseline         with JitRL memory
demo-1     FAIL (0)         FAIL (0)
demo-2     FAIL (0)         ok   (51)
demo-3     FAIL (0)         ok   (126)
...
success rate: baseline 0% -> memory 83%
memory: 6 episodes, 17 transitions
```

- `baseline`：不读不写记忆，固定策略每次都先算 `0`，失败。
- `memory`：第 1 集失败后，记忆里"查 alpha 得到 42"这类经验的回报把"先检索"抬到"先算"之上，
  后面全部成功。**没有梯度、没有微调、没有 API key**。
- 两条臂共用同一套 Skill、同一个 MCP 服务器（`expert_pack.builtin.mcp_demo_server`）、同一个模型先验。

可复现：`python -m expert_pack demo --tasks 6 --seed 7 --trace` 会打印每一步的
`base / q / advantage / shaped`，以及每次决策为什么翻转。换 seed 1–10、任务数 5/8/12，
结果稳定在 75%–83%（脚本：`tools/check_demo.py`）。

## 两个核心概念

### 1. 槽位 = 空缺位置

`python -m expert_pack slots`：

```
SLOT        STATUS   QUALITY     REQ  CONTRACT         BINDING
model       builtin  stub        yes  ModelBackend     builtin:unbound
tools       open     -           no   ToolProvider     -
skills      open     -           no   Skill            -
store       builtin  production  no   ExperienceStore  builtin:sqlite
retriever   builtin  production  no   Retriever        builtin:jaccard
abstractor  builtin  production  no   StateAbstractor  builtin:default
policy      builtin  production  no   PolicyShaper     builtin:jitrl
evaluator   builtin  demo        no   Evaluator        builtin:heuristic

2 vacancy(ies); strict FAIL
```

五种状态：`bound`（已装配且通过契约检查）、`builtin`（用框架自带实现）、
`open`（可选槽，空着）、`vacant`（必需槽，空着）、`invalid`（装了但不合格）。
`open` 与 `vacant` 就是**等着别的电脑上的智能体来填的空缺**，机器可读版本见
[docs/VACANCIES.json](docs/VACANCIES.json)。

### 2. 装配文件 = 填空清单

```json
{"version": 1, "name": "my-pack",
 "agent": {"max_steps": 8, "seed": 7},
 "bindings": [
   {"slot": "model", "type": "module",
    "target": "expert_pack.adapters.model_openai:from_config",
    "config": {"model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"}},
   {"slot": "tools", "type": "mcp_stdio", "target": "filesystem",
    "config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]}},
   {"slot": "skills", "type": "skill_dir", "target": "skills"}
 ]}
```

`expert-pack validate --assembly X.json` 会真正解析每个绑定、检查契约、打印空缺，再决定能不能跑。
格式与全部配方见 [docs/ASSEMBLY.md](docs/ASSEMBLY.md)。

## 安装与命令

不需要装任何依赖（核心只用标准库；测试用 `unittest`）：

```bash
python -m expert_pack slots                 # 空缺清单
python -m expert_pack validate --assembly assembly.example.json
python -m expert_pack demo                  # 离线演示
python -m expert_pack init my-pack          # 生成带空缺的骨架项目
python -m expert_pack run --tasks tasks.jsonl --assembly assembly.json --trace
python -m expert_pack memory stats          # 记忆规模/动作回报
python -m expert_pack pack --out dist/expert-pack.zip   # 打包到别的电脑
```

也可以 `pip install -e .` 后用 `expert-pack ...`。

## 目录

```
expert_pack/
  contracts.py        所有 seam 的 Protocol + 契约检查（唯一需要读的接口文件）
  slots.py            槽位目录（DEFAULT_SLOTS）、状态、空缺报告
  assembly.py         装配文件加载 → 解析 → 构造运行时
  agent.py            单任务回合循环（推理流 + 记忆流）
  pipeline.py         批处理管道：阶段、逐项检查点、断点续跑
  cli.py              命令行
  jitrl/              状态抽象、记忆、检索、优势估计、策略、评测器
  adapters/           OpenAI 兼容后端、脚本模型、SKILL.md 加载、MCP stdio 客户端
  builtin/            参考 MCP 服务器、示例 Skill、离线演示
docs/                 架构、装配、JitRL 对应、管道、空缺
skills/expert-pack-assemble/   给另一台电脑上的智能体用的"装配 Skill"
tests/                101 个测试（无网络、无 API key）
```

## 诚实边界

- **不是真的改 logits。** 工具的候选是有限动作集，JitRL 的闭式解在这里落到"候选分数"上：
  `score = base + β·Â`，`base = ln(confidence)`，纯记忆动作 `base = 0`（论文 Algorithm 1 的规定）。
  我们没有、也不能在只调用 API 的智能体里改模型权重或 token logits。见 [docs/JITRL.md](docs/JITRL.md)。
- **理论定理有条件。** 论文的收敛性（Thm 4.2/4.3）依赖采样与平稳性假设；本实现不做验证，
  只把公式对齐，并在文档里列出假设。
- **评测器默认是启发式**（`quality: demo`），只看工具失败、重复动作、最终答案；
  开放任务要接 LLM 评测器（`builtin: llm`），它自带启发式兜底。
- **离线"模型"是脚本规划器**，只用来证明记忆能改变决策，不代表语言能力。
  真跑请绑 `OpenAIModel`（任何 OpenAI 兼容端点：OpenAI / OpenRouter / vLLM / LM Studio / Ollama）。

## 继续读

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) —— 深模块、seam、数据流
- [docs/ASSEMBLY.md](docs/ASSEMBLY.md) —— 装配文件参考与配方
- [docs/JITRL.md](docs/JITRL.md) —— 论文/代码 → 本实现的逐条对应与偏离
- [docs/PIPELINE.md](docs/PIPELINE.md) —— 批处理阶段、检查点、续跑
- [docs/VACANCIES.md](docs/VACANCIES.md) —— 空缺清单的含义与填法
- [docs/PMS-LANDING.md](docs/PMS-LANDING.md) —— PMS 问数 × JitRL 落地设计与 P0/P1/P2-1 实验结果
- [docs/JITRL-PLUGIN.md](docs/JITRL-PLUGIN.md) —— 把 JitRL 抽象成 Harness 插件的设计（形态/钩子/风险）
- [AGENTS.md](AGENTS.md) —— 给在本仓库工作的智能体的入口指针
- [skills/expert-pack-assemble/SKILL.md](skills/expert-pack-assemble/SKILL.md) —— 在另一台电脑上装配时加载
