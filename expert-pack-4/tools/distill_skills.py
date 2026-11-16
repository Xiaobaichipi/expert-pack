#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从轨迹树提炼 Skill 候选。

示例：
    python tools/distill_skills.py trajectory-tree/tree.jsonl \
      --replays trajectory-tree/replays-all.jsonl \
      --generated trajectory-tree/generated-branches.jsonl \
      --out skill-candidates --min-success 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parents[1]
if str(PACK_DIR) not in sys.path:
    sys.path.insert(0, str(PACK_DIR))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从轨迹树提炼 Skill 候选")
    parser.add_argument("tree", help="tree.jsonl")
    parser.add_argument("--replays", default="", help="replays.jsonl")
    parser.add_argument("--generated", default="", help="generated-branches.jsonl")
    parser.add_argument("--out", default="skill-candidates", help="输出目录")
    parser.add_argument("--min-success", type=int, default=2, help="最少成功样本数")
    args = parser.parse_args(argv)

    from expert_pack.trajectory.skill_distiller import distill_skills

    candidates = distill_skills(
        args.tree,
        replays_path=args.replays or None,
        generated_path=args.generated or None,
        out_dir=args.out,
        min_success=args.min_success,
    )
    print(f"提炼出 {len(candidates)} 个 Skill 候选，写入 {args.out}/")
    for cand in candidates:
        print(
            "  {} {} [{}] success={} generated={} file={}".format(
                cand["id"],
                cand["family"],
                cand["status"],
                cand["success_count"],
                cand["generated_count"],
                cand.get("file"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
