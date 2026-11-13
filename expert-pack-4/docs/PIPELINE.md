# 批处理管道

`expert_pack/pipeline.py` 把"多任务"从"单任务回合循环"里分离出来。
一个 run 是若干 `BatchItem` 穿过三个默认阶段，每阶段都是普通可调用对象。

## 默认阶段（`expert-pack run`）

| 阶段 | 做什么 | 失败时 |
|---|---|---|
| `prepare` | 校验 item 有 goal | 跳过该 item |
| `solve` | 构造 `Task` → `agent.solve` → 写入 `item.data["summary"]` | 跳过该 item |
| `record` | 追加一行到 `results.jsonl` | 跳过该 item |

`--no-memory` 不是管道开关，而是把 `store` 覆盖成 `NullStore`：同一条代码路径，
只关掉记忆流。这样对照臂与实验臂**代码完全一致**，差异只来自记忆。

## 检查点与续跑

- 每个 item 一个文件：`<out>/items/<safe_id>.json`，原子写（先 `.tmp` 再 replace）。
- 记录字段：`completed`（成功完成的阶段）、`error`（最后一次失败）、`status`、`data`。
- `--resume` 跳过 `status=done` 的 item，对未完成的 item 只重跑 `completed` 里没有的阶段。
- 一个阶段重试成功时，只有**它自己**的失败记录会被清除；后续阶段成功不会掩盖前面的失败
  （所以"部分完成"的 item 仍显示为 failed，直到所有阶段都成功）。

语义细节（也是测试锁住的行为）：

- `on_error="skip"`：该阶段失败 → 停止该 item，保持 failed。
- `on_error="continue"`：记录失败但继续下一阶段；终态仍是 failed，除非失败阶段在续跑中成功。
- 失败是逐项的：一个 item 抛异常不会中断其他 item 的处理。

## 结果文件

`run.json`（装配快照、开始时间、是否关记忆）+ `results.jsonl`（每任务一行），
每行包含：`success / steps / answer / expected / score / evaluator / returns / usage /
memory_before / memory_after / trace`。`trace` 里每步有 `shaped` 明细
（base、q、advantage、score），用于事后解释"为什么这么选"。

## 加一个阶段

```python
from expert_pack.pipeline import BatchPipeline, Stage

pipeline = BatchPipeline(
    [
        Stage("prepare", my_prepare),
        Stage("route", my_router, on_error="continue"),   # 例如按 family 选不同 Skill
        Stage("solve", my_solve),
        Stage("record", my_record),
    ],
    state_dir="runs/exp-1",
)
```

阶段签名固定：`(context: PipelineContext, item: BatchItem) -> BatchItem | None`。
`context.data` 是跨阶段共享的 dict（`run` 里用它算序号、任务总数）；
`context.runtime` 是装配好的 `Runtime`，阶段可以读到 `agent/policy/store`。

## 为什么阶段是代码而槽位是装配

- **槽位**回答"用什么实现某个能力"，范围是单个契约，换实现不该改流程 → 数据（JSON）。
- **阶段**回答"这批任务按什么顺序、分几步处理"，会改变控制流 → 代码。
  装配 agent 可以在目标机器上新增阶段，但它必须显式写进 pipeline，而不是塞进配置里的字符串。

这个边界让框架保持"骨架稳定、填充灵活"。
