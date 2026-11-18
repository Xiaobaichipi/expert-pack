# 变电智能问数专家包

[English README](README.en.md)

PMS（生产管理系统）× JitRL 实验框架：26 个接口、4 组任务集、5 组对照实验、轨迹树 replay 与 Skill 候选提炼。

## 一、项目结构

```
专家包/
├── expert-pack/              # 原始专家包（12 skills + 2 MCP）
├── expert-pack-2/            # 修复版（mock gateway + 分析工具 + 376 tests）
├── expert-pack-3/            # 独立拆分包（standalone/12 skills + 2 MCP，384 tests）
├── expert-pack-4/            # JitRL 实验框架（本目录）
│   ├── expert_pack/          # 核心库
│   │   ├── extensions/pms/   # PMS 扩展（抽象器/评测器/任务/检索器/报告）
│   │   ├── trajectory/       # 轨迹树（存储/可视化/replay/Skill 提炼）
│   │   └── jitrl/            # JitRL 核心（记忆/优势/策略/检索）
│   ├── tools/                # 实验工具
│   │   ├── run_pms_experiment.py   # 主实验 harness
│   │   ├── replay_tree.py          # 轨迹树 replay
│   │   └── distill_skills.py       # Skill 候选提炼
│   ├── tests/                # 137 tests
│   ├── docs/                 # 完整文档
│   └── trajectory-tree/      # 示例轨迹树与 replay 结果
├── .env                      # API 配置（不入库）
└── README.md
```

## 二、快速开始

### 1. 环境

```powershell
# Conda 环境（Python 3.12）
conda activate jitrl
# 或直接使用
D:\App\Tool\MiniConda\envs\jitrl\python.exe
```

### 2. 配置

`.env` 中配置模型（支持 ARK / DeepSeek / Kimi）：

```text
ARK_API_KEY=...
ARK_OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
ARK_MODEL=deepseek-v4-1-flash-261017

DEEPSEEK_API_KEY=...
DEEPSEEK_OPENAI_BASE_URL=https://api.deepseek.com
DEEP_MODEL=deepseek-flash

KIMI_API_KEY=...
KIMI_OPENAI_BASE_URL=https://api.kimi.com/coding/v1
KIMI_MODEL=k3.1-pro-highspeed
```

### 3. 运行实验

```powershell
cd expert-pack-4

# 基础 42 题（4 站，脚本规划器）
python tools/run_pms_experiment.py --model scripted --dataset base --out runs/p0

# 复杂 26 题（异构站，真实模型，工具提示 + 白名单）
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex \
  --arms D,E --enforce-hints --out runs/p3-complex

# 带确定性 rank 工具（推荐）
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex \
  --arms E --enforce-hints --rank-tool --out runs/p3-rank

# 带轨迹树记录
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex \
  --arms E --limit 6 --enforce-hints --tree-store trajectory-tree/tree.jsonl --out runs/tree-demo
```

### 4. 轨迹树 replay

```powershell
# 列出可 replay 的分支
python tools/replay_tree.py trajectory-tree/tree.jsonl --list

# 批量 replay（模型驱动 rollout）
python tools/replay_tree.py trajectory-tree/tree.jsonl --all --rollout model --provider deepseek \
  --out trajectory-tree/replays-all.jsonl --memory trajectory-tree/replay-all-memory.sqlite3

# 生成新分支候选
python tools/replay_tree.py trajectory-tree/tree.jsonl --generate --provider deepseek \
  --out trajectory-tree/generated-branches.jsonl --max-gen 5
```

### 5. Skill 候选提炼

```powershell
python tools/distill_skills.py trajectory-tree/tree.jsonl \
  --replays trajectory-tree/replays-all.jsonl \
  --generated trajectory-tree/generated-branches.jsonl \
  --out trajectory-tree/skill-candidates --min-success 1
```

### 6. 报告生成

```powershell
# 绑定 report 工具后运行实验
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex \
  --arms E --limit 2 --enforce-hints --report-tool --out runs/p3-report-demo
```

## 三、实验结果摘要

### 复杂 26 题（异构站，真实模型）

| 配置 | 模型 | 成功 | 成功率 | 平均步数 |
|---|---|---|---|---|
| 无提示 | ARK | 16/26 | 61.54% | 2.65 |
| 工具提示+白名单 | ARK | 21/26 | 80.77% | 2.50 |
| 工具提示+白名单+比较引导+计划提示 | Kimi | 25/26 | 96.15% | 2.54 |
| 工具提示+白名单+rank 工具 | DeepSeek | **26/26** | **100.00%** | **2.46** |
| 结构化候选表 | DeepSeek | 18/26 | 69.23% | 3.35 |

### 记忆注入验证（DeepSeek，6 题）

| 配置 | 成功 | 成功率 | 平均步数 |
|---|---|---|---|
| D（无 replay 记忆） | 5/6 | 83.33% | 2.67 |
| **D（注入 replay 记忆）** | **6/6** | **100.00%** | **2.50** |

## 四、核心结论

1. **技能（SKILL.md）是开销**：12 个技能让 B 臂错 1 题，无技能 D/E 反而 100%；
2. **工具提示 + 白名单有效**：复杂任务从 61% → 80%；
3. **确定性 rank 工具最优**：比较/排序交给代码，26/26 100%；
4. **记忆有收益但依赖场景**：replay 记忆注入后 83% → 100%；
5. **轨迹树 replay 是知识沉淀的雏形**：可批量验证、生成新分支、提炼 Skill 候选。

## 五、文档

- [docs/PMS-LANDING.md](expert-pack-4/docs/PMS-LANDING.md)：P0-P3 完整实验记录
- [docs/TRAJECTORY-TREE.md](expert-pack-4/docs/TRAJECTORY-TREE.md)：轨迹树设计与 replay
- [docs/TODO.md](expert-pack-4/docs/TODO.md)：中期/长期待办
- [docs/JITRL.md](expert-pack-4/docs/JITRL.md)：JitRL 数学与实现
- [docs/JITRL-PLUGIN.md](expert-pack-4/docs/JITRL-PLUGIN.md)：插件化设计

## 六、待办（中期/长期）

- **中期**：在线监测接入、健康度评分、风险评估、缺陷诊断推理；
- **长期**：主动预警闭环、自动写 Skill、仿真推演、知识图谱。

详见 [docs/TODO.md](expert-pack-4/docs/TODO.md)。

## 七、测试

```powershell
cd expert-pack-4
python -m unittest discover -s tests -t .        # 137 tests OK
python -m expert_pack validate --assembly assembly/pms.demo.json   # strict PASS
```
