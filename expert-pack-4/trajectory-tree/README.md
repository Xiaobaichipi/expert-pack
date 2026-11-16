# 轨迹树示例

由 `expert-pack-4` 的 `--tree-store` 生成的真实实验样本：

- `tree.jsonl`：append-only 轨迹树事件日志（6 episodes / 22 nodes / 16 steps）；
- `tree.html`：自包含森林视图，可直接用浏览器打开；
- `tree.png`：第一棵子树；
- `tree-branch.png`：带一个“未选分支”的子树。

- `replays.jsonl`：一次反事实 branch replay 的记录；
- `replay-memory.sqlite3`：验证成功的 replay 分支写回的记忆。

生成/渲染方式见 [../docs/TRAJECTORY-TREE.md](../docs/TRAJECTORY-TREE.md)。
