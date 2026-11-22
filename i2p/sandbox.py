"""Execution sandboxes. Repo code (tests, the agent's patch) only ever runs inside one.

DockerSandbox (default): one container per attempt, created from a fresh clone that is
bind-mounted at /work. No network (model calls happen on the host), CPU/memory/pids
limits, all capabilities dropped, no-new-privileges, read-only root filesystem with a
tmpfs /tmp, non-root user, and a hard timeout on every command. Multi-arch base image,
so it runs on Apple Silicon (arm64) with Docker Desktop or colima.

LocalSandbox: plain subprocess in the work dir. NOT isolated. Only for the harness's own
unit tests and for verifying the task set on a throwaway machine; it must be enabled
explicitly with allow_unsafe=True.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import SandboxConfig

CONTAINER_WORKDIR = "/work"


class SandboxError(RuntimeError):
    pass


@dataclass
class ExecResult:
    code: int
    output: str
    duration_s: float
    timed_out: bool = False


class Sandbox:
    workdir: Path

    def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def exec(self, command: str, timeout_s: int | None = None) -> ExecResult:  # pragma: no cover
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def __enter__(self) -> "Sandbox":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


def _host_user() -> str:
    getuid = getattr(os, "getuid", None)
    if getuid is None:  # pragma: no cover - Windows
        return "1000:1000"
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:  # never run the container as root, even if the host process is root
        return "65534:65534"
    return f"{uid}:{gid}"


class DockerSandbox(Sandbox):
    def __init__(self, cfg: SandboxConfig, workdir: Path, env: dict[str, str] | None = None,
                 name: str | None = None):
        self.cfg = cfg
        self.workdir = Path(workdir).resolve()
        self.env = dict(env or {})
        self.name = name or f"i2p-{uuid.uuid4().hex[:12]}"
        self.started = False

    @property
    def docker(self) -> list[str]:
        return shlex.split(self.cfg.docker_cmd)

    def run_args(self) -> list[str]:
        args = [
            *self.docker, "run", "-d", "--rm",
            "--name", self.name,
            "--network", self.cfg.network,
            "--cpus", str(self.cfg.cpus),
            "--memory", self.cfg.memory,
            "--memory-swap", self.cfg.memory,
            "--pids-limit", str(self.cfg.pids_limit),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", f"/tmp:rw,exec,size={self.cfg.tmpfs_size}",
            "--user", _host_user(),
            "-e", "HOME=/tmp",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PIP_NO_INDEX=1",
            "-v", f"{self.workdir}:{CONTAINER_WORKDIR}:rw",
            "-w", CONTAINER_WORKDIR,
        ]
        for key, value in sorted(self.env.items()):
            args += ["-e", f"{key}={value}"]
        # The container itself only lives as long as one attempt may run.
        args += [self.cfg.image, "sleep", "7200"]
        return args

    def start(self) -> None:
        if self.cfg.network not in ("none",):
            raise SandboxError("sandbox network must be 'none' (model calls run on the host)")
        proc = subprocess.run(self.run_args(), capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise SandboxError(f"docker run failed: {proc.stderr.strip()[:400]}")
        self.started = True

    def exec_args(self, command: str, timeout_s: int) -> list[str]:
        return [*self.docker, "exec", self.name, "timeout", "-k", "5", str(timeout_s), "sh", "-c", command]

    def exec(self, command: str, timeout_s: int | None = None) -> ExecResult:
        if not self.started:
            raise SandboxError("sandbox not started")
        timeout_s = int(timeout_s or self.cfg.command_timeout_s)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(self.exec_args(command, timeout_s), capture_output=True, text=True,
                                  timeout=timeout_s + 30)
        except subprocess.TimeoutExpired:
            return ExecResult(124, "command timed out (host watchdog)", time.monotonic() - t0, True)
        out = (proc.stdout or "") + (proc.stderr or "")
        return ExecResult(proc.returncode, out, time.monotonic() - t0, proc.returncode in (124, 137))

    def stop(self) -> None:
        if self.started:
            subprocess.run([*self.docker, "rm", "-f", self.name], capture_output=True, timeout=60)
            self.started = False


class LocalSandbox(Sandbox):
    """Unsafe, unisolated runner for tests/verification only."""

    def __init__(self, workdir: Path, env: dict[str, str] | None = None, allow_unsafe: bool = False,
                 command_timeout_s: int = 180):
        if not allow_unsafe:
            raise SandboxError("LocalSandbox is not isolated; pass allow_unsafe=True explicitly")
        self.workdir = Path(workdir).resolve()
        self.env = dict(env or {})
        self.command_timeout_s = command_timeout_s

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def exec(self, command: str, timeout_s: int | None = None) -> ExecResult:
        timeout_s = int(timeout_s or self.command_timeout_s)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **self.env}
        t0 = time.monotonic()
        try:
            proc = subprocess.run(["sh", "-c", command], cwd=self.workdir, env=env, capture_output=True,
                                  text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return ExecResult(124, out + "\ncommand timed out", time.monotonic() - t0, True)
        return ExecResult(proc.returncode, (proc.stdout or "") + (proc.stderr or ""), time.monotonic() - t0)


def make_sandbox(cfg: SandboxConfig, workdir: Path, env: dict[str, str] | None = None) -> Sandbox:
    if cfg.backend == "docker":
        return DockerSandbox(cfg, workdir, env)
    if cfg.backend == "local":
        return LocalSandbox(workdir, env, allow_unsafe=True, command_timeout_s=cfg.command_timeout_s)
    raise SandboxError(f"unknown sandbox backend {cfg.backend!r}")
