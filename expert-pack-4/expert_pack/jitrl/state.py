"""State abstraction: turn a noisy observation into a retrievable situation.

The JitRL paper's key design principle is that *functionally equivalent states
map to similar representations*. For an agent that calls tools, that means:

* drop volatile identifiers (paths, URLs, hex ids, numbers),
* keep the task family (not the task instance),
* keep the observation kind and success flag,
* keep a bounded amount of normalised text.

Two tasks that differ only in an item id therefore land on the same state key,
which is exactly the cross-instance transfer the paper relies on.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from expert_pack.contracts import Observation, State, Task

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_URL = re.compile(r"(?:https?|ftp)://[^\s'\"<>]+", re.IGNORECASE)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_WIN_PATH = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s'\"<>]+")
_POSIX_PATH = re.compile(r"(?<![\w.])/(?:[^\s/]+/)+[^\s]*")
_HEX = re.compile(r"\b(?:0x)?[0-9a-f]{8,}\b", re.IGNORECASE)
_NUM = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?![A-Za-z0-9_.])")
_WS = re.compile(r"\s+")
#: ASCII words (tool ids, units, English state text).
_WORD = re.compile(r"[a-z0-9_]{1,64}")
#: CJK runs. Chinese/Japanese state text needs character n-grams; without this
#: ``tokenize`` returns almost nothing for Chinese queries (only ASCII digits
#: survive normalisation), so retrieval degenerates to exact-key matching.
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def normalize_text(text: str) -> str:
    """Canonicalise one observation so equivalent situations collide.

    Volatile values (numbers, ids, URLs, paths) become readable placeholders.
    Keeping them *spelled out* rather than dropped is deliberate: a placeholder
    still counts as a token, so "returned __num__" and "returned __num__" match
    while "returned __num__ and then failed" does not.
    """

    text = _ANSI.sub(" ", text or "")
    text = _URL.sub(" __url__ ", text)
    text = _UUID.sub(" __id__ ", text)
    text = _WIN_PATH.sub(" __path__ ", text)
    text = _POSIX_PATH.sub(" __path__ ", text)
    text = _HEX.sub(" __id__ ", text)
    text = _NUM.sub(" __num__ ", text)
    text = text.lower()
    text = _WS.sub(" ", text)
    return text.strip()


def tokenize(text: str, ngram: int = 2) -> list[str]:
    """Unigrams plus word/character n-grams, as multiset units for Jaccard.

    English-like text contributes word unigrams and word n-grams; CJK text
    contributes character unigrams and character bigrams. The latter is
    essential for Chinese Q&A: regex word tokenization alone yields almost no
    tokens (``"查询郑州变电站1号主变套管缺陷"`` -> ``["1"/"__num__"]``), which
    makes retrieved neighbours useless for cross-question transfer.
    """

    normalized = normalize_text(text)
    words = [m.group(0) for m in _WORD.finditer(normalized)]
    tokens: list[str] = list(words)
    for n in range(2, max(2, ngram) + 1):
        if len(words) < n:
            break
        tokens.extend("~".join(words[i : i + n]) for i in range(len(words) - n + 1))

    for run in _CJK_RUN.findall(normalized):
        chars = list(run)
        tokens.extend(chars)
        # Character bigrams are the cheapest robust approximation to Chinese
        # word segmentation; no external segmenter/dictionary is required.
        tokens.extend("".join(chars[i : i + 2]) for i in range(len(chars) - 1))
    return tokens


@dataclass(frozen=True)
class AbstractorConfig:
    max_chars: int = 240
    max_tokens: int = 96
    ngram: int = 2
    include_previous_action: bool = True
    include_ok: bool = True


class DefaultAbstractor:
    """The built-in state abstractor; replace via the ``abstractor`` slot."""

    name = "default"

    def __init__(self, config: AbstractorConfig | None = None) -> None:
        self.config = config or AbstractorConfig()

    def abstract(
        self,
        task: Task,
        observation: Observation,
        step_index: int,
        previous_action: str | None = None,
    ) -> State:
        family = normalize_text(task.family or task.goal)[: self.config.max_chars]
        body = [f"family={family}", f"obs={observation.kind}"]
        if self.config.include_ok:
            body.append(f"ok={str(bool(observation.ok)).lower()}")
        text = normalize_text(observation.text)[: self.config.max_chars]
        body.append(f"text={text}")
        if self.config.include_previous_action and previous_action:
            body.append(f"prev={previous_action}")
        joined = " | ".join(body)
        # Tokens describe the content (not the boilerplate), so Jaccard measures
        # how similar two situations are once they are structurally compatible.
        token_source = f"{text} prev={previous_action or ''}"
        tokens = tuple(tokenize(token_source, self.config.ngram)[: self.config.max_tokens])
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
        facets = {
            "family": family,
            "obs": observation.kind,
            "ok": "true" if observation.ok else "false",
        }
        return State(key=digest, text=joined, tokens=tokens, facets=facets)
