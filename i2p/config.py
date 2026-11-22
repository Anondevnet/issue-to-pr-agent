"""Configuration. Defaults are the $0 setup: local Ollama, Docker sandbox, PRs off."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ModelConfig:
    # "ollama" (default, local, $0) | "openai_compat" (optional free tier, off by default) | "mock"
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "huihui_ai/qwen3.5-abliterated:9b"
    temperature: float = 0.2
    num_ctx: int = 8192
    max_output_tokens: int = 1024
    timeout_s: float = 300.0
    think: bool = False  # qwen3-family "thinking" off: faster, and output is JSON anyway
    # openai_compat only: the key is read from this env var, never from a file.
    api_key_env: str = "OPENROUTER_API_KEY"
    # Must be explicitly true to use a hosted provider at all.
    allow_hosted: bool = False


@dataclass
class SandboxConfig:
    backend: str = "docker"  # "docker" | "local" (unsafe; harness tests / dev only)
    docker_cmd: str = "docker"  # e.g. "sudo docker" on a Linux box
    image: str = "i2p-sandbox:py311"
    cpus: float = 2.0
    memory: str = "2g"
    pids_limit: int = 256
    network: str = "none"  # model calls happen on the host, so the container needs no network
    command_timeout_s: int = 180
    tmpfs_size: str = "512m"


@dataclass
class AgentConfig:
    max_steps: int = 40
    max_retries: int = 3  # failed suite runs allowed after the first patch attempt
    max_repro_steps: int = 16  # steps allowed before a failing repro test must exist
    wall_clock_s: int = 900
    max_observation_chars: int = 1800
    history_turns: int = 6
    max_parse_failures: int = 5
    max_repeats: int = 5  # identical consecutive calls before the attempt is ended as stuck
    read_window_lines: int = 80


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    runs_dir: str = "runs"
    cache_dir: str = "cache"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge(obj: Any, data: dict[str, Any]) -> None:
    names = {f.name for f in fields(obj)}
    for key, value in (data or {}).items():
        if key not in names:
            raise ValueError(f"unknown config key: {key}")
        current = getattr(obj, key)
        if hasattr(current, "__dataclass_fields__"):
            _merge(current, value)
        else:
            setattr(obj, key, value)


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    if path:
        data = yaml.safe_load(Path(path).read_text()) or {}
        _merge(cfg, data)
    env = os.environ
    if env.get("I2P_MODEL"):
        cfg.model.model = env["I2P_MODEL"]
    if env.get("I2P_OLLAMA_URL"):
        cfg.model.base_url = env["I2P_OLLAMA_URL"]
    if env.get("I2P_DOCKER"):
        cfg.sandbox.docker_cmd = env["I2P_DOCKER"]
    return cfg
