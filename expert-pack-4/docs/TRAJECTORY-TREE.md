# 轨迹树存储与可视化

## 1. 为什么这样存

在一次复杂任务里，模型把“可用率最低的站”答成了 110kV 大学城（99.70%），而真正最低的
35kV 物流园（99.60%）根本没被模型看到：工具返回约 2310 字符，prompt 只保留 2000 字符，
最后一条记录被截断。

所以轨迹不能只存 `(state, action, return)`。本目录存的是**可 replay 的原始事件树**：

- 每个 step 的 **完整 observation**（不是 prompt 截断后的版本）；
- 模型提出的 **所有候选动作**（selected + alternatives）；
- state、分数、模型输出、usage、错误；
- 评测结果和 episode 元数据。

派生 JitRL 记忆可以随时从这棵树重建，而不是反过来。

## 2. 与 Dream-RSI 的关系

Dream-RSI 把探索历史组织成 discovery tree，用历史作低成本 replay simulator 来评估探索策略
（[论文](https://arxiv.org/abs/2609.14858)、[项目](https://www.dream-rsi.com/)）。

本存储只做它需要的地基：

- **高保真历史**：如果历史和模型实际看到的不一致，dream/replay 就会建立在失真世界上；
- **保留分支**：未选候选也写入，才能 replay “当时如果选另一条路会怎样”；
- **append-only**：不覆盖失败轨迹，失败样本同样有 replay 价值。

## 3. 不把人类的经验总结当成硬约束

人类写下的 Skill/意图/成功标准，可能收窄 AI 的搜索空间。因此：

- 树的拓扑只由**实际执行过的 step**和**模型提出的候选**决定；
- `family`、`intent`、`expect` 只作为 metadata 保存，**不用于剪枝或合并节点**；
- 不按“正确/错误”提前删除分支；
- 派生记忆的筛选是后置的、可配置的，不是存储时的硬规则。

## 4. 数据格式（JSONL）

每行一条记录：

```json
{"type":"episode","episodeId":"pms-E:001:...","taskId":"capacity-max-01",
 "goal":"...","success":true,"score":1.0,"answer":"...","meta":{"provider":"deepseek"}}

{"type":"node","nodeId":"...:0","episodeId":"...","parentId":"...:root",
 "step":0,"kind":"step",
 "state":{"key":"...","text":"...","tokens":[...],"facets":{}},
 "observation":{"kind":"tool","ok":true,"text":"完整工具返回","data":{}},
 "selected":{"actionId":"tool:pms/query_open_capacity",...},
 "candidates":[...],
 "alternatives":[...],
 "shaped":[...],
 "decision":{...},
 "modelText":"...",
 "usage":{...}}
```

- `selected`：实际执行的动作；
- `candidates`：本 step 模型/记忆给出的全部候选；
- `alternatives`：未选中的候选，即可 replay 的分支；
- `observation.text`：完整原文。

## 5. 用法

```powershell
# 跑实验时边跑边记
python tools/run_pms_experiment.py --provider deepseek --dataset complex \
  --arms E --limit 6 --enforce-hints \
  --tree-store trajectory-tree/tree.jsonl --out runs/tree-demo

# 渲染 HTML（完整森林，可交互）
python -m expert_pack.trajectory.visualize trajectory-tree/tree.jsonl \
  --html trajectory-tree/tree.html

# 额外渲染一张 PNG（需要 Pillow；可用 bundled Python）
python -m expert_pack.trajectory.visualize trajectory-tree/tree.jsonl \
  --png trajectory-tree/tree.png --episode 5
```

HTML 是自包含文件，内网可直接打开；PNG 适合快速发图。

## 6. 示例数据

`trajectory-tree/` 中的样本来自一次 DeepSeek 复杂任务运行：

- 6 个 episode（5 成功、1 失败）；
- 22 个 node、16 个 step；
- 1 个未选分支（`defect-presence-02` 的 answer 节点另有 `inquire_defect` 候选）。

打开 [tree.html](tree.html) 查看完整森林；[tree-branch.png](tree-branch.png) 是带未选分支的单棵子树。

## 7. 当前限制

- 记录在 episode 结束后写入，不是实时流式写；
- 当前模型大多数 step 只提出一个候选，所以树的“分叉”还不够多；
- 没有存渲染后的完整 prompt，只存了完整 observation；下一步可加 `promptHash` 和
  截断元数据（原始长度/保留长度/丢弃记录）；
- PNG 是辅助图，交互请用 HTML。
