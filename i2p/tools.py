"""The agent's tools. File tools act on the clone from the host with strict path
containment (they never execute repo code). Anything that executes code
(run_tests) goes through the sandbox.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .sandbox import Sandbox
from .testrun import TestRun, pytest_command, run_pytest, tail

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache",
             "data", "exports", "renders", "clips", "frames"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".ini", ".cfg", ".yaml", ".yml", ".json", ".sql",
                 ".sh", ".js", ".ts", ".html"}
MAX_FILE_BYTES = 400_000


class ToolError(Exception):
    pass


@dataclass
class ToolResult:
    ok: bool
    text: str
    data: dict | None = None


def is_test_path(rel: str) -> bool:
    name = os.path.basename(rel)
    parts = Path(rel).parts
    if not name.endswith(".py"):
        return False
    return ("tests" in parts or "test" in parts or name.startswith("test_")
            or name.endswith("_test.py") or name == "conftest.py")


class ToolBox:
    def __init__(self, workdir: Path, sandbox: Sandbox, *, read_window: int = 80, obs_limit: int = 1800,
                 test_timeout_s: int = 180, protected: set[str] | None = None):
        self.root = Path(workdir).resolve()
        self.sandbox = sandbox
        self.read_window = read_window
        self.obs_limit = obs_limit
        self.test_timeout_s = test_timeout_s
        self.protected = set(protected or set())
        self.edited_files: set[str] = set()
        self.created_tests: set[str] = set()
        self.tracked: set[str] = set(git(self.root, "ls-files").splitlines()) if (self.root / ".git").exists() else set()

    # -- path safety -------------------------------------------------------
    def resolve(self, rel: str) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise ToolError("path is required")
        rel = rel.strip()
        while rel.startswith("./"):
            rel = rel[2:]
        if os.path.isabs(rel):
            raise ToolError("use a path relative to the repo root")
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise ToolError("path escapes the repository")
        relp = target.relative_to(self.root).as_posix()
        if relp.split("/")[0] == ".git":
            raise ToolError(".git is off limits")
        return target

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _iter_files(self, base: Path):
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if p.suffix in TEXT_SUFFIXES and not p.is_symlink():
                    yield p

    # -- tools -------------------------------------------------------------
    def list_files(self, path: str = ".", limit: int = 150) -> ToolResult:
        base = self.root if path in (".", "", None) else self.resolve(path)
        if not base.is_dir():
            raise ToolError(f"not a directory: {path}")
        files = [self.rel(p) for p in self._iter_files(base)]
        shown = files[: int(limit)]
        more = f"\n... {len(files) - len(shown)} more" if len(files) > len(shown) else ""
        return ToolResult(True, "\n".join(shown) + more, {"count": len(files)})

    def search_code(self, pattern: str, path: str = ".", max_results: int = 30) -> ToolResult:
        if not pattern:
            raise ToolError("pattern is required")
        try:
            rx = re.compile(pattern)
        except re.error:
            rx = re.compile(re.escape(pattern))
        base = self.root if path in (".", "", None) else self.resolve(path)
        files = [base] if base.is_file() else list(self._iter_files(base))
        hits: list[str] = []
        for p in files:
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    hits.append(f"{self.rel(p)}:{i}: {line.strip()[:160]}")
                    if len(hits) >= int(max_results):
                        return ToolResult(True, "\n".join(hits) + "\n... (more results truncated)")
        return ToolResult(True, "\n".join(hits) if hits else "no matches")

    def read_file(self, path: str, start: int = 1, end: int | None = None) -> ToolResult:
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ToolError("file too large to read")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start or 1))
        end = int(end) if end else start + self.read_window - 1
        end = min(len(lines), end, start + 2 * self.read_window - 1)
        body = "\n".join(f"{i:>4}| {lines[i - 1]}" for i in range(start, end + 1))
        note = f"[{self.rel(p)} lines {start}-{end} of {len(lines)}]"
        return ToolResult(True, f"{note}\n{body}")

    def write_file(self, path: str, content: str) -> ToolResult:
        """Create or overwrite a TEST file (repro tests). Source changes go through edit_file."""
        p = self.resolve(path)
        relp = self.rel(p)
        if not is_test_path(relp):
            raise ToolError("write_file is only for test files (tests/... or test_*.py); use edit_file for source")
        if relp in self.protected:
            raise ToolError("that path is reserved")
        if relp in self.tracked:
            raise ToolError(f"{relp} is an existing test file; existing tests are read-only. "
                            "Create a NEW file such as tests/test_issue_repro.py")
        if not isinstance(content, str) or not content.strip():
            raise ToolError("content is required")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        self.created_tests.add(relp)
        return ToolResult(True, f"wrote {relp} ({len(content.splitlines())} lines)", {"path": relp})

    def edit_file(self, path: str, old: str, new: str) -> ToolResult:
        """Replace exactly one occurrence of `old` with `new`."""
        p = self.resolve(path)
        relp = self.rel(p)
        if relp in self.protected:
            raise ToolError("that path is reserved")
        if is_test_path(relp) and relp in self.tracked:
            raise ToolError("existing tests are read-only; fix the source code, or edit your own new test file")
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        if not isinstance(old, str) or not old:
            raise ToolError("'old' must be the exact text to replace (copy it from read_file, without line numbers)")
        if not isinstance(new, str):
            raise ToolError("'new' must be a string")
        text = p.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            stripped = old.strip()
            hint = " (whitespace differs; copy exact indentation)" if stripped and stripped in text else ""
            raise ToolError("'old' text not found in file" + hint)
        if count > 1:
            raise ToolError(f"'old' text occurs {count} times; include more surrounding lines")
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        self.edited_files.add(relp)
        return ToolResult(True, f"edited {relp}", {"path": relp, "is_test": is_test_path(relp)})

    def run_tests(self, target: str | None = None) -> tuple[ToolResult, TestRun]:
        targets = None
        if target:
            node = str(target).split("::", 1)[0]
            self.resolve(node)  # containment check
            targets = [str(target)]
        run = run_pytest(self.sandbox, targets, timeout_s=self.test_timeout_s)
        status = "PASSED" if run.passed else ("TIMED OUT" if run.timed_out else f"FAILED (exit {run.exit_code})")
        text = f"pytest {target or '(full suite)'}: {status}\n{tail(run.output, self.obs_limit)}"
        return ToolResult(run.passed, text, {"exit_code": run.exit_code, "failed": sorted(run.failed)}), run

    def git_diff(self) -> ToolResult:
        diff = git(self.root, "diff", "--no-color", "--no-ext-diff")
        untracked = git(self.root, "ls-files", "--others", "--exclude-standard").split()
        extra = "".join(f"\n(new file) {u}" for u in untracked)
        return ToolResult(True, tail(diff + extra, self.obs_limit) or "(no changes)")


def git(cwd: Path, *args: str, check: bool = False) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd, capture_output=True,
                          text=True, env=env, timeout=120)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout
