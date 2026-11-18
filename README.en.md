# Substation Intelligent Q&A Expert Pack

PMS (Production Management System) × JitRL experimental framework: 26 interfaces, 4 task suites, 5 control arms, trajectory-tree replay, and skill-candidate distillation.

[中文 README](README.md)

## Repository Layout

```text
expert-pack/
├── expert-pack/              # Original pack (12 skills + 2 MCP servers)
├── expert-pack-2/            # Fixed pack (mock gateway + analysis tools + 376 tests)
├── expert-pack-3/            # Standalone split (12 skill dirs + 2 MCP zips, 384 tests)
├── expert-pack-4/            # JitRL experiment framework (main work)
│   ├── expert_pack/
│   │   ├── extensions/pms/   # PMS extension (abstractor/evaluator/tasks/retriever/report)
│   │   ├── trajectory/       # Trajectory tree (store/visualize/replay/skill distiller)
│   │   └── jitrl/            # JitRL core (memory/advantage/policy/retrieval)
│   ├── tools/                # run_pms_experiment.py / replay_tree.py / distill_skills.py
│   ├── tests/                # 137 unit tests
│   ├── docs/                 # Full experiment records (Chinese)
│   └── trajectory-tree/      # Sample trajectory tree + replay results
├── .env                      # API keys (git-ignored)
└── README.md
```

## Quick Start

```powershell
# Python 3.12 (conda env "jitrl")
cd expert-pack-4

# Base suite, scripted planner (offline, deterministic)
python tools/run_pms_experiment.py --model scripted --dataset base --out runs/p0

# Complex suite (26 tasks), real model, tool hints + whitelist
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex \
  --arms D,E --enforce-hints --out runs/p3-complex

# Deterministic rank tools (recommended for comparisons)
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex \
  --arms E --enforce-hints --rank-tool --out runs/p3-rank

# Record a trajectory tree while running
python tools/run_pms_experiment.py --model openai --provider deepseek --dataset complex \
  --arms E --limit 6 --enforce-hints --tree-store trajectory-tree/tree.jsonl --out runs/tree-demo
```

### Trajectory-tree replay (Dream-RSI style)

```powershell
# List replayable branches
python tools/replay_tree.py trajectory-tree/tree.jsonl --list

# Batch replay with model-driven rollout
python tools/replay_tree.py trajectory-tree/tree.jsonl --all --rollout model --provider deepseek \
  --out trajectory-tree/replays-all.jsonl --memory trajectory-tree/replay-all-memory.sqlite3

# Let the model propose new branch candidates
python tools/replay_tree.py trajectory-tree/tree.jsonl --generate --provider deepseek \
  --out trajectory-tree/generated-branches.jsonl --max-gen 5
```

### Skill distillation

```powershell
python tools/distill_skills.py trajectory-tree/tree.jsonl \
  --replays trajectory-tree/replays-all.jsonl \
  --generated trajectory-tree/generated-branches.jsonl \
  --out trajectory-tree/skill-candidates --min-success 1
```

## Key Results (complex 26-task suite, real models)

| Configuration | Model | Success | Avg steps |
|---|---|---|---|
| No hints | ARK | 16/26 (61.5%) | 2.65 |
| Tool hints + whitelist | ARK | 21/26 (80.8%) | 2.50 |
| Hints + comparison guidance + plan hints | Kimi | 25/26 (96.2%) | 2.54 |
| Hints + deterministic rank tools | DeepSeek | **26/26 (100%)** | **2.46** |
| Structured comparison table (prompt-only) | DeepSeek | 18/26 (69.2%) | 3.35 |

Replay-memory injection (DeepSeek, 6 tasks): 5/6 (83.3%) → **6/6 (100%)**, steps 2.67 → 2.50.

## Takeaways

1. **The 12 SKILL.md files are overhead** — the no-skill arms outperformed the full-skill arm.
2. **Tool hints + whitelist** lift complex-task success from ~61% to ~81%.
3. **Deterministic rank tools beat prompt-only comparison** — sorting belongs in code, not in the model.
4. **Memory helps only when tasks repeat**; heterogeneous tasks show little gain.
5. **Trajectory-tree replay** is a working seed for Dream-RSI-style self-improvement: branch replay, new-branch generation, and skill distillation all function end to end.

## Tests

```powershell
cd expert-pack-4
python -m unittest discover -s tests -t .      # 137 tests
python -m expert_pack validate --assembly assembly/pms.demo.json
```

## Docs (Chinese)

- [docs/PMS-LANDING.md](expert-pack-4/docs/PMS-LANDING.md) — full P0–P3 experiment log
- [docs/TRAJECTORY-TREE.md](expert-pack-4/docs/TRAJECTORY-TREE.md) — trajectory tree design & replay
- [docs/TODO.md](expert-pack-4/docs/TODO.md) — mid/long-term roadmap
- [docs/JITRL.md](expert-pack-4/docs/JITRL.md) — JitRL math and implementation
