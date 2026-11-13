"""OpenAI-compatible chat backend on the Python standard library.

Any server exposing ``POST {base_url}/chat/completions`` works: OpenAI,
OpenRouter, vLLM, LM Studio, Ollama's OpenAI shim, or an internal gateway.
No SDK is required, which keeps the package installable on an air-gapped
machine with only a Python interpreter.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Sequence

from expert_pack.contracts import ModelMessage, ModelReply
from expert_pack.errors import ModelError


@dataclass
class OpenAIConfig:
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "EXPERT_PACK_API_KEY"
    timeout: float = 60.0
    max_tokens: int | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict = field(default_factory=dict)


class OpenAIModel:
    """One model, one endpoint. Configuration errors fail loudly at first use."""
    def __init__(self, config: OpenAIConfig | None = None, *, api_key: str | None = None) -> None:
        self.config = config or OpenAIConfig()
        self._key = api_key
        self.name = f"openai:{self.config.model or 'unset'}"

    # -- config ------------------------------------------------------------ #

    def _resolve(self) -> tuple[str, str, str]:
        config = self.config
        model = config.model or os.environ.get("EXPERT_PACK_MODEL", "")
        base_url = config.base_url or os.environ.get(
            "EXPERT_PACK_BASE_URL", "https://api.openai.com/v1"
        )
        key = self._key
        if not key:
            for env_name in (config.api_key_env, "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
                if env_name and os.environ.get(env_name):
                    key = os.environ[env_name]
                    break
        if not model:
            raise ModelError(
                "no model configured: set OpenAIConfig.model or EXPERT_PACK_MODEL"
            )
        if not key:
            raise ModelError(
                f"no API key found: set {config.api_key_env} or OPENAI_API_KEY"
            )
        return model, base_url.rstrip("/"), key

    # -- contract ---------------------------------------------------------- #

    def complete(
        self,
        messages: Sequence[ModelMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelReply:
        model, base_url, key = self._resolve()
        url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        payload: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        limit = max_tokens if max_tokens is not None else self.config.max_tokens
        if limit:
            payload["max_tokens"] = int(limit)
        payload.update(self.config.extra_body)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            **self.config.extra_headers,
        }
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:  # noqa: BLE001
                pass
            raise ModelError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ModelError(f"cannot reach {url}: {exc.reason}") from exc
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise ModelError(f"model endpoint returned non-JSON: {raw[:200]!r}") from exc
        try:
            content = parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"unexpected completion shape: {str(parsed)[:200]}") from exc
        if isinstance(content, list):  # some gateways return content blocks
            content = "".join(str(part.get("text", part)) for part in content)
        return ModelReply(text=str(content), usage=dict(parsed.get("usage") or {}), raw=parsed)


def from_config(**kwargs: object) -> OpenAIModel:
    """Assembly-friendly factory: ``target: "...model_openai:from_config"``."""

    return OpenAIModel(OpenAIConfig(**kwargs))  # type: ignore[arg-type]
