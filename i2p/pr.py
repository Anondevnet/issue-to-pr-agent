"""Branch + PR body, and the guarded `gh pr create` step.

Hard rules (not configurable):
- Only repositories owned by ALLOWED_OWNER can get a push or a PR.
- Nothing is pushed or opened unless the caller passes enabled=True (CLI: --open-pr).
- Before pushing, the active gh login must be ALLOWED_OWNER and the target repo's owner
  (as reported by GitHub) must be ALLOWED_OWNER.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .tools import git

ALLOWED_OWNER = "Anondevnet"
_REPO_RE = re.compile(r"^([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)$")


class PRPolicyError(PermissionError):
    pass


def assert_allowed_repo(full_name: str) -> tuple[str, str]:
    m = _REPO_RE.match(full_name or "")
    if not m:
        raise PRPolicyError(f"not an owner/name repo: {full_name!r}")
    owner, name = m.groups()
    if owner.lower() != ALLOWED_OWNER.lower():
        raise PRPolicyError(f"PRs are only allowed on {ALLOWED_OWNER}/* repos, not {full_name}")
    return ALLOWED_OWNER, name


def branch_name(task_id: str, attempt: int, run_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{task_id}-r{attempt}-{run_id}")
    return f"i2p/{safe}"[:100]


def build_pr_body(*, task_id: str, issue_title: str, summary: str, diffstat: str, repro_test: str | None,
                  suite_note: str, model: str, steps: int, minutes: float) -> str:
    lines = [
        f"Fixes: {issue_title}",
        "",
        "## Summary",
        summary.strip() or "(the agent did not write a summary)",
        "",
        "## Tests",
        f"- Regression test: `{repro_test}` (fails before this change, passes after)" if repro_test
        else "- No regression test was produced",
        f"- {suite_note}",
        "",
        "## Changes",
        "```",
        diffstat.strip() or "(no diff)",
        "```",
        "",
        "---",
        f"Opened by issue-to-pr-agent (task `{task_id}`), model `{model}`, {steps} steps, {minutes:.1f} min, cost $0.",
    ]
    return "\n".join(lines) + "\n"


def commit_branch(workdir: Path, branch: str, message: str) -> str | None:
    """Create a local branch with the agent's changes. Returns the commit sha or None if no changes."""
    git(workdir, "checkout", "-q", "-b", branch, check=True)
    git(workdir, "add", "-A", check=True)
    if not git(workdir, "status", "--porcelain").strip():
        return None
    git(workdir, "-c", "user.name=issue-to-pr-agent", "-c", "user.email=i2p@localhost", "commit", "-q",
        "--no-verify", "-m", message, check=True)
    return git(workdir, "rev-parse", "HEAD").strip()


@dataclass
class PRResult:
    opened: bool
    reason: str
    url: str | None = None
    commands: list[list[str]] | None = None


Runner = Callable[..., subprocess.CompletedProcess]


def _run(runner: Runner, args: list[str], cwd: Path | None = None) -> str:
    proc = runner(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise PRPolicyError(f"{' '.join(args[:3])} failed: {(proc.stderr or '').strip()[:300]}")
    return (proc.stdout or "").strip()


def open_pr(*, repo: str, workdir: Path, branch: str, base: str, title: str, body_file: Path,
            enabled: bool = False, runner: Runner = subprocess.run) -> PRResult:
    owner, name = assert_allowed_repo(repo)  # hard check happens even in dry-run
    full = f"{owner}/{name}"
    push_url = f"https://github.com/{full}.git"
    create = ["gh", "pr", "create", "--repo", full, "--head", branch, "--base", base,
              "--title", title, "--body-file", str(body_file)]
    push = ["git", "push", push_url, f"{branch}:{branch}"]
    if not enabled:
        return PRResult(False, "dry run: pass --open-pr to push and open the PR", commands=[push, create])
    login = _run(runner, ["gh", "api", "user", "--jq", ".login"])
    if login.lower() != ALLOWED_OWNER.lower():
        raise PRPolicyError(f"gh is logged in as {login!r}, expected {ALLOWED_OWNER}")
    actual_owner = _run(runner, ["gh", "repo", "view", full, "--json", "owner", "--jq", ".owner.login"])
    if actual_owner.lower() != ALLOWED_OWNER.lower():
        raise PRPolicyError(f"{full} is owned by {actual_owner!r}, not {ALLOWED_OWNER}")
    _run(runner, ["gh", "auth", "setup-git"])
    _run(runner, push, cwd=workdir)
    url = _run(runner, create, cwd=workdir)
    return PRResult(True, "opened", url=url.splitlines()[-1] if url else None, commands=[push, create])
