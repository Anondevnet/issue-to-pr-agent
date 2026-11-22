"""Run pytest inside a sandbox and parse which tests failed."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from .sandbox import ExecResult, Sandbox

_SUMMARY_RE = re.compile(r"^(FAILED|ERROR) (\S+)", re.MULTILINE)
_COUNTS_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")


@dataclass
class TestRun:
    exit_code: int
    failed: set[str] = field(default_factory=set)
    output: str = ""
    duration_s: float = 0.0
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    @property
    def collection_error(self) -> bool:
        # pytest: 1 = tests failed, 2 = interrupted/collection error, 3 = internal, 4 = usage, 5 = none collected
        return self.exit_code in (2, 3, 4, 5)

    def counts(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for n, kind in _COUNTS_RE.findall(self.output[-2000:]):
            found[kind.rstrip("s") if kind == "errors" else kind] = int(n)
        return found


def pytest_command(targets: list[str] | None = None, extra: str = "") -> str:
    parts = ["python", "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", "--color=no"]
    parts += [shlex.quote(t) for t in (targets or [])]
    cmd = " ".join(parts)
    return f"{cmd} {extra}".strip()


def run_pytest(sandbox: Sandbox, targets: list[str] | None = None, timeout_s: int | None = None,
               extra: str = "", base_cmd: str | None = None) -> TestRun:
    cmd = pytest_command(targets, extra) if base_cmd is None else base_cmd
    res: ExecResult = sandbox.exec(cmd, timeout_s)
    failed = {m.group(2) for m in _SUMMARY_RE.finditer(res.output)}
    return TestRun(res.code, failed, res.output, res.duration_s, res.timed_out)


def new_failures(after: TestRun, baseline: TestRun) -> set[str]:
    return after.failed - baseline.failed


def tail(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else "...[truncated]...\n" + text[-limit:]
