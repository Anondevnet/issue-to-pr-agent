"""JSONL step logs: one line per agent step (step, phase, tool, tokens, duration, outcome)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

REQUIRED_KEYS = ("ts", "task_id", "attempt", "step", "phase", "tool", "prompt_tokens",
                 "completion_tokens", "duration_s", "outcome")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _short(value: Any, limit: int = 300) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"...[{len(value)} chars]"
    if isinstance(value, dict):
        return {k: _short(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_short(v, limit) for v in value[:20]]
    return value


class StepLogger:
    def __init__(self, path: Path, task_id: str, attempt: int, model: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.task_id = task_id
        self.attempt = attempt
        self.model = model
        self.steps = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._fh = self.path.open("a", encoding="utf-8")

    def log(self, *, step: int, phase: str, tool: str, outcome: str, duration_s: float,
            prompt_tokens: int = 0, completion_tokens: int = 0, args: Any = None,
            observation: str = "", **extra: Any) -> dict:
        self.steps = max(self.steps, step)
        self.prompt_tokens += int(prompt_tokens or 0)
        self.completion_tokens += int(completion_tokens or 0)
        rec = {
            "ts": round(time.time(), 3),
            "task_id": self.task_id,
            "attempt": self.attempt,
            "model": self.model,
            "step": step,
            "phase": phase,
            "tool": tool,
            "args": _short(args) if args is not None else None,
            "args_digest": digest(args) if args is not None else None,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "duration_s": round(float(duration_s), 3),
            "outcome": outcome,
            "observation_digest": digest(observation) if observation else None,
            "observation_chars": len(observation or ""),
            "cost_usd": 0.0,
            **extra,
        }
        self._fh.write(json.dumps(rec, default=str) + "\n")
        self._fh.flush()
        return rec

    def close(self) -> None:
        self._fh.close()


def read_steps(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
