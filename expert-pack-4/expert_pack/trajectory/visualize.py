"""把轨迹树 JSONL 渲染成可离线打开的 HTML，以及便于快速浏览的 PNG。"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any

from expert_pack.trajectory.tree_store import build_forest, load_records


def _short(text: str, limit: int = 240) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _action_label(node: dict[str, Any]) -> str:
    selected = node.get("selected") or {}
    return selected.get("actionId") or selected.get("name") or "(none)"


def _node_lines(node: dict[str, Any]) -> list[str]:
    if node.get("kind") == "root":
        return ["ROOT: " + _short(node.get("goal", ""), 120)]
    observation = node.get("observation") or {}
    lines = [
        "STEP {}  selected={}".format(node.get("step"), _action_label(node)),
        "observation: " + _short(observation.get("text", ""), 220),
    ]
    alternatives = node.get("alternatives") or []
    if alternatives:
        lines.append("alternatives:")
        for alt in alternatives[:6]:
            lines.append(
                "  - {} (base={:.3f})".format(
                    alt.get("actionId"), float(alt.get("baseScore") or 0.0)
                )
            )
    return lines


def text_tree(episode: dict[str, Any]) -> str:
    lines = [
        "TASK {}  success={}".format(episode.get("taskId"), episode.get("success")),
        "GOAL: " + _short(episode.get("goal", ""), 160),
    ]
    root = episode.get("root")
    if not root:
        return "\n".join(lines)

    def walk(node: dict[str, Any], prefix: str, last: bool) -> None:
        connector = "└─ " if last else "├─ "
        label = "root" if node.get("kind") == "root" else f"step {node.get('step')}"
        lines.append(prefix + connector + label)
        child_prefix = prefix + ("   " if last else "│  ")
        for text in _node_lines(node)[1:]:
            lines.append(child_prefix + text)
        children = node.get("children") or []
        for index, child in enumerate(children):
            walk(child, child_prefix, index == len(children) - 1)

    walk(root, "", True)
    return "\n".join(lines)


def _html(forest: list[dict[str, Any]]) -> str:
    payload = json.dumps(forest, ensure_ascii=False).replace("</", "<\\/")
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JitRL 轨迹树</title>
<style>
:root{--bg:#0f172a;--panel:#172033;--line:#334155;--text:#e2e8f0;--muted:#94a3b8;
--ok:#22c55e;--bad:#ef4444;--accent:#38bdf8;--alt:#f59e0b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Microsoft YaHei",system-ui,sans-serif}
header{padding:24px 28px 10px}
h1{margin:0 0 6px;font-size:22px}
.sub{color:var(--muted);font-size:13px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 14px}
.stat b{font-size:18px;display:block;color:var(--accent)}
.toolbar{padding:0 28px 12px}
button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;
padding:6px 12px;cursor:pointer;margin-right:8px}
button:hover{border-color:var(--accent)}
main{padding:0 28px 48px;display:flex;flex-direction:column;gap:22px}
.episode{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.ep-head{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start}
.ep-title{font-size:16px;font-weight:600;margin:0 0 4px}
.ep-goal{color:var(--muted);margin:4px 0 0;max-width:1000px}
.badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600}
.ok{background:rgba(34,197,94,.18);color:var(--ok)}
.bad{background:rgba(239,68,68,.18);color:var(--bad)}
.tree{margin-top:16px;border-left:2px solid var(--line);padding-left:18px}
.tree .tree{padding-left:16px;margin-top:8px}
.node{position:relative;margin:10px 0}
.node::before{content:"";position:absolute;left:-20px;top:18px;width:18px;height:2px;background:var(--line)}
.card{background:#0b1220;border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.card.root{border-color:var(--accent)}
.card.step{border-left:4px solid var(--accent)}
.card.fail{border-left-color:var(--bad)}
.card.okstep{border-left-color:var(--ok)}
.step-title{font-weight:600;color:var(--accent);margin-bottom:4px}
.obs{color:#cbd5e1;word-break:break-word}
.meta{color:var(--muted);font-size:12px;margin-top:6px}
.alt{margin-top:6px;color:var(--alt);font-size:12px;white-space:pre-wrap}
.answer{margin-top:10px;border-top:1px dashed var(--line);padding-top:8px;color:#fde68a;word-break:break-word}
.empty{color:var(--muted);padding:20px}
</style>
</head>
<body>
<header>
<h1>JitRL 轨迹树</h1>
<div class="sub">append-only 事件树 · 保留每个 step 的全部候选分支（未选中候选 = 可 replay 的分支）</div>
<div class="stats" id="stats"></div>
</header>
<div class="toolbar">
<button data-filter="all">全部</button>
<button data-filter="success">只看成功</button>
<button data-filter="failure">只看失败</button>
</div>
<main id="app"></main>
<script>
const data = __DATA__;
const app = document.getElementById('app');
const stats = document.getElementById('stats');
let filter = 'all';

function esc(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}
function short(text, n) {
  text = (text == null ? '' : String(text)).replace(/\\s+/g, ' ').trim();
  return text.length <= n ? text : text.slice(0, n - 1) + '…';
}
function nodeView(node, isRoot) {
  const wrap = document.createElement('div');
  wrap.className = 'node';
  const card = document.createElement('div');
  if (isRoot) {
    card.className = 'card root';
    card.innerHTML = '<div class="step-title">ROOT</div><div class="obs">' + esc(node.goal || '') + '</div>';
  } else {
    const obs = node.observation || {};
    card.className = 'card step ' + (obs.ok ? 'okstep' : 'fail');
    let html = '<div class="step-title">Step ' + esc(node.step) + ' · ' + esc((node.selected||{}).actionId || '') + '</div>';
    html += '<div class="obs">' + esc(short(obs.text || '', 700)) + '</div>';
    const alts = node.alternatives || [];
    if (alts.length) {
      html += '<div class="alt">未选分支：' + alts.map(a => esc(a.actionId) + ' (' + Number(a.baseScore||0).toFixed(2) + ')').join(' · ') + '</div>';
    }
    card.innerHTML = html;
  }
  wrap.appendChild(card);
  const children = node.children || [];
  if (children.length) {
    const childWrap = document.createElement('div');
    childWrap.className = 'tree';
    children.forEach(child => childWrap.appendChild(nodeView(child, false)));
    wrap.appendChild(childWrap);
  }
  return wrap;
}
function render() {
  const visible = data.filter(ep => filter === 'all' || (filter === 'success' ? ep.success : !ep.success));
  const totalNodes = data.reduce((n, ep) => n + countNodes(ep.root), 0);
  const ok = data.filter(ep => ep.success).length;
  stats.innerHTML = '<div class="stat"><b>' + data.length + '</b>episodes</div>'
    + '<div class="stat"><b>' + totalNodes + '</b>nodes</div>'
    + '<div class="stat"><b>' + ok + '</b>success</div>'
    + '<div class="stat"><b>' + (data.length - ok) + '</b>failed</div>';
  app.innerHTML = '';
  if (!visible.length) {
    app.innerHTML = '<div class="empty">没有匹配的轨迹</div>';
    return;
  }
  visible.forEach(ep => {
    const section = document.createElement('section');
    section.className = 'episode';
    const head = document.createElement('div');
    head.className = 'ep-head';
    head.innerHTML = '<div><p class="ep-title">' + esc(ep.taskId) + ' · ' + esc(ep.family || '') + '</p>'
      + '<p class="ep-goal">' + esc(ep.goal) + '</p></div>'
      + '<div><span class="badge ' + (ep.success ? 'ok' : 'bad') + '">' + (ep.success ? 'SUCCESS' : 'FAILED') + '</span></div>';
    section.appendChild(head);
    const tree = document.createElement('div');
    tree.className = 'tree';
    if (ep.root) tree.appendChild(nodeView(ep.root, true));
    section.appendChild(tree);
    if (ep.answer) {
      const answer = document.createElement('div');
      answer.className = 'answer';
      answer.textContent = 'ANSWER: ' + ep.answer;
      section.appendChild(answer);
    }
    app.appendChild(section);
  });
}
function countNodes(node) {
  if (!node) return 0;
  return 1 + (node.children || []).reduce((n, c) => n + countNodes(c), 0);
}
document.querySelectorAll('button[data-filter]').forEach(btn => {
  btn.addEventListener('click', () => { filter = btn.dataset.filter; render(); });
});
render();
</script>
</body>
</html>
""".replace("__DATA__", payload)


def render_png(forest: list[dict[str, Any]], out: Path, episode_index: int = 0) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    if not forest:
        return None
    episode = forest[episode_index]
    font_path = Path(r"C:\Windows\Fonts\msyh.ttc")
    if not font_path.is_file():
        font_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    title_font = ImageFont.truetype(str(font_path), 28)
    body_font = ImageFont.truetype(str(font_path), 17)
    small_font = ImageFont.truetype(str(font_path), 14)

    lines: list[tuple[str, tuple[int, int, int], Any]] = []
    lines.append(("TASK " + str(episode.get("taskId")) + "  success=" + str(episode.get("success")), (56, 189, 248), title_font))
    lines.append((episode.get("goal", ""), (226, 232, 240), body_font))
    lines.append(("", (255, 255, 255), body_font))
    root = episode.get("root")

    def add_node(node: dict[str, Any], depth: int, is_root: bool) -> None:
        indent = "  " * depth
        if is_root:
            lines.append((indent + "ROOT", (56, 189, 248), body_font))
        else:
            obs = node.get("observation") or {}
            lines.append((indent + "Step {} · {}".format(node.get("step"), _action_label(node)), (56, 189, 248), body_font))
            for chunk in textwrap.wrap("observation: " + _short(obs.get("text", ""), 220), 74):
                lines.append((indent + "  " + chunk, (203, 213, 225), small_font))
            for alt in (node.get("alternatives") or [])[:5]:
                lines.append((indent + "  ↳ 未选: {} ({:.2f})".format(alt.get("actionId"), float(alt.get("baseScore") or 0)), (245, 158, 11), small_font))
        for child in node.get("children") or []:
            add_node(child, depth + 1, False)

    if root:
        add_node(root, 0, True)
    lines.append(("", (255, 255, 255), body_font))
    lines.append(("ANSWER: " + str(episode.get("answer", "")), (253, 230, 138), body_font))

    wrapped: list[tuple[str, tuple[int, int, int], Any, int]] = []
    width = 1500
    for text, color, font in lines:
        if not text:
            wrapped.append(("", color, font, 10))
            continue
        box = font.getbbox("测")
        line_height = box[3] - box[1] + 10
        for chunk in textwrap.wrap(text, 100, break_long_words=False) or [""]:
            wrapped.append((chunk, color, font, line_height))
    height = 80 + sum(item[3] for item in wrapped) + 40
    image = Image.new("RGB", (width, max(height, 500)), (15, 23, 42))
    draw = ImageDraw.Draw(image)
    y = 40
    for text, color, font, line_height in wrapped:
        if text:
            draw.text((40, y), text, fill=color, font=font)
        y += line_height
    image.save(out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="渲染 JitRL 轨迹树")
    parser.add_argument("input", help="tree.jsonl")
    parser.add_argument("--html", default=None)
    parser.add_argument("--png", default=None)
    parser.add_argument("--episode", type=int, default=0)
    args = parser.parse_args(argv)
    records = load_records(args.input)
    forest = build_forest(records)
    base = Path(args.input).with_suffix("")
    html_path = Path(args.html) if args.html else base.with_suffix(".html")
    html_path.write_text(_html(forest), encoding="utf-8")
    print(f"HTML: {html_path}")
    if args.png:
        png_path = render_png(forest, Path(args.png), args.episode)
        print(f"PNG: {png_path}" if png_path else "PNG: skipped (Pillow unavailable)")
    print(text_tree(forest[args.episode]) if forest else "no episodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
