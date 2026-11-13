"""The model binding used when the slot is vacant.

It fails on first use with an actionable message rather than silently returning
an empty proposal. The vacancy report marks it ``stub``, and ``--strict``
refuses to run with it.
"""

from __future__ import annotations

from typing import Sequence

from expert_pack.contracts import ModelMessage, ModelReply
from expert_pack.errors import ModelError

_MESSAGE = """The model slot is vacant.

Bind a real backend in assembly.json, for example:

  {"slot": "model", "type": "module",
   "target": "expert_pack.adapters.model_openai:OpenAIModel",
   "config": {"model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"}}

or set EXPERT_PACK_MODEL / EXPERT_PACK_BASE_URL / EXPERT_PACK_API_KEY and use
the module binding without config. Run `expert-pack slots` to see every vacancy.
"""


class UnboundModel:
    name = "unbound"

    def complete(
        self,
        messages: Sequence[ModelMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelReply:
        raise ModelError(_MESSAGE)
