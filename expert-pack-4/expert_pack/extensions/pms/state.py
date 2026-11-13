"""PMS 问数专用的状态抽象：把工具观察压缩成可检索的业务状态。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from expert_pack.contracts import Observation, State, Task
from expert_pack.jitrl.state import normalize_text, tokenize


@dataclass(frozen=True)
class PmsAbstractorConfig:
    """PmsAbstractor 的可调参数（与装配文件 config 一一对应）。"""

    max_chars: int = 360
    max_tokens: int = 96
    ngram: int = 2
    include_previous_action: bool = True
    include_ok: bool = True


class PmsAbstractor:
    """中文 PMS 问数的状态抽象器。

    与 ``DefaultAbstractor`` 的区别：
    * family 优先取 ``task.family``，其次 ``context["intent"]``；同一意图的不同问法
      会落到同一个起始状态，这是 JitRL 跨实例迁移的前提；
    * 起始观察（kind=start）的文本只保留 family/intent/obs/ok，不包含具体 goal，
      因此同族任务的起始状态完全一致；
    * 工具观察只保留 ``code/data`` 的紧凑摘要（条数、首条关键字段），避免长 JSON
      把中文 tokens 挤爆；
    * 其余使用修复后的中文 tokenizer（CJK unigram + bigram）。
    """

    name = "pms"

    def __init__(self, config: PmsAbstractorConfig | None = None) -> None:
        self.config = config or PmsAbstractorConfig()

    def abstract(
        self,
        task: Task,
        observation: Observation,
        step_index: int,
        previous_action: str | None = None,
    ) -> State:
        intent = str(task.context.get("intent") or "").strip()
        family = str(task.family or intent or "pms.general").strip()
        family_text = normalize_text(family)[: self.config.max_chars]
        body = [f"family={family_text}", f"obs={observation.kind}"]
        if intent:
            body.append(f"intent={normalize_text(intent)}")
        if self.config.include_ok:
            body.append(f"ok={str(bool(observation.ok)).lower()}")
        text = self._compact_text(observation)
        if text:
            body.append(f"text={text}")
        if self.config.include_previous_action and previous_action:
            body.append(f"prev={previous_action}")
        joined = " | ".join(body)
        token_source = f"{text} prev={previous_action or ''}"
        tokens = tuple(tokenize(token_source, self.config.ngram)[: self.config.max_tokens])
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
        facets = {
            "family": family_text,
            "obs": observation.kind,
            "ok": "true" if observation.ok else "false",
        }
        if intent:
            facets["intent"] = normalize_text(intent)
        for key in ("deviceType", "voltageLevel"):
            value = task.context.get(key)
            if value:
                facets[key] = normalize_text(str(value))
        return State(key=digest, text=joined, tokens=tokens, facets=facets)

    def _compact_text(self, observation: Observation) -> str:
        if observation.kind == "start":
            return ""
        raw = observation.text or ""
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return normalize_text(raw)[: self.config.max_chars]
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        compact: Any = data
        if isinstance(data, dict) and isinstance(data.get("list"), list):
            items = data["list"]
            first = items[0] if items else {}
            compact = {
                "total": data.get("total", len(items)),
                "listLen": len(items),
                "first": _pick_fields(first) if isinstance(first, dict) else first,
            }
        elif isinstance(data, dict):
            compact = _pick_fields(data)
        text = json.dumps(compact, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return normalize_text(text)[: self.config.max_chars]


def _pick_fields(item: dict[str, Any]) -> dict[str, Any]:
    """保留对状态比较有意义的业务字段，丢弃长文本/ID 列表。"""

    wanted = (
        "name",
        "assetName",
        "nodeName",
        "deviceName",
        "psrName",
        "defectLevel",
        "level",
        "part",
        "riskLevel",
        "status",
        "planTime",
        "planType",
        "loadRate",
        "availabilityRate",
        "outageCount",
        "sourceName",
        "total",
    )
    picked: dict[str, Any] = {}
    for key in wanted:
        if key in item:
            value = item[key]
            if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 80:
                picked[key] = value
    return picked


def from_config(**kwargs: Any) -> PmsAbstractor:
    """装配工厂：把 config 字典转成 PmsAbstractor。"""

    return PmsAbstractor(PmsAbstractorConfig(**kwargs))
