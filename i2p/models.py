"""Model providers. All return text plus token counts so every step can be logged.

- OllamaProvider: local, $0 (default).
- OpenAICompatProvider: optional free tiers (OpenRouter ':free' models, Gemini's
  OpenAI-compatible endpoint). Off unless config.model.allow_hosted is true; key from env.
- MockProvider: scripted replies for the harness's own tests.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable

from .config import ModelConfig


class ModelError(RuntimeError):
    pass


@dataclass
class ModelResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_s: float = 0.0


class Provider:
    name = "base"
    cost_per_1k_prompt = 0.0
    cost_per_1k_completion = 0.0

    def chat(self, messages: list[dict[str, str]]) -> ModelResponse:  # pragma: no cover
        raise NotImplementedError

    def label(self) -> str:
        return self.name


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise ModelError(f"HTTP {exc.code} from model endpoint: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ModelError(f"model endpoint unreachable or bad reply: {exc}") from exc


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg

    def label(self) -> str:
        return f"ollama:{self.cfg.model}"

    def chat(self, messages: list[dict[str, str]]) -> ModelResponse:
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "think": self.cfg.think,
            "options": {
                "temperature": self.cfg.temperature,
                "num_ctx": self.cfg.num_ctx,
                "num_predict": self.cfg.max_output_tokens,
            },
        }
        t0 = time.monotonic()
        data = _post_json(self.cfg.base_url.rstrip("/") + "/api/chat", payload, {}, self.cfg.timeout_s)
        if "error" in data and "think" in str(data["error"]).lower():
            payload.pop("think")  # older Ollama or non-thinking model
            data = _post_json(self.cfg.base_url.rstrip("/") + "/api/chat", payload, {}, self.cfg.timeout_s)
        if "error" in data:
            raise ModelError(str(data["error"])[:300])
        text = strip_thinking((data.get("message") or {}).get("content", ""))
        return ModelResponse(
            text=text,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            duration_s=time.monotonic() - t0,
        )


class OpenAICompatProvider(Provider):
    """Free-tier only by intent. Refuses to run unless allow_hosted is set and the key env var exists."""

    name = "openai_compat"

    def __init__(self, cfg: ModelConfig):
        if not cfg.allow_hosted:
            raise ModelError("hosted provider is disabled (set model.allow_hosted: true to opt in)")
        key = os.environ.get(cfg.api_key_env or "")
        if not key:
            raise ModelError(f"env var {cfg.api_key_env} is not set")
        self.cfg = cfg
        self._key = key

    def label(self) -> str:
        return f"openai_compat:{self.cfg.model}"

    def chat(self, messages: list[dict[str, str]]) -> ModelResponse:
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        t0 = time.monotonic()
        data = _post_json(
            self.cfg.base_url.rstrip("/") + "/chat/completions",
            payload,
            {"Authorization": f"Bearer {self._key}"},
            self.cfg.timeout_s,
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"unexpected reply shape: {str(data)[:200]}") from exc
        usage = data.get("usage") or {}
        return ModelResponse(
            text=strip_thinking(text),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            duration_s=time.monotonic() - t0,
        )


class MockProvider(Provider):
    """Replays scripted replies. Each item is a dict (serialized to JSON), a str, or a callable(messages)."""

    name = "mock"

    def __init__(self, script: Iterable[dict | str | Callable[[list[dict]], dict | str]]):
        self._script = list(script)
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> ModelResponse:
        self.calls.append(messages)
        if not self._script:
            item: dict | str = {"tool": "give_up", "args": {"reason": "mock script exhausted"}}
        else:
            item = self._script.pop(0)
        if callable(item):
            item = item(messages)
        text = item if isinstance(item, str) else json.dumps(item)
        prompt_chars = sum(len(m["content"]) for m in messages)
        return ModelResponse(text=text, prompt_tokens=prompt_chars // 4, completion_tokens=len(text) // 4)


def make_provider(cfg: ModelConfig) -> Provider:
    if cfg.provider == "ollama":
        return OllamaProvider(cfg)
    if cfg.provider == "openai_compat":
        return OpenAICompatProvider(cfg)
    raise ModelError(f"unknown provider {cfg.provider!r}")
