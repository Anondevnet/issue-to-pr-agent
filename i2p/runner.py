"""Run one attempt end to end and score it with the hidden test.

attempt dir layout (runs/<run_id>/<task_id>/attempt-<n>/):
  steps.jsonl   per-step log      result.json   outcome + scores
  final.diff    agent's diff      pr_body.md    PR body (if submitted)
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from .agent import Agent, TaskContext
from .config import Config
from .models import Provider
from .pr import PRPolicyError, branch_name, build_pr_body, commit_branch, open_pr
from .sandbox import Sandbox, make_sandbox
from .steplog import StepLogger
from .tasks import HIDDEN_TEST_DEST, Task, ensure_mirror, fresh_clone, install_hidden_test
from .testrun import TestRun, new_failures, run_pytest
from .tools import ToolBox, git

FAILURE_REASONS = (
    "no_repro", "patch_failed_tests", "hidden_test_failed", "broke_other_tests", "step_limit", "timeout",
    "invalid_model_output", "stuck_loop", "model_error", "gave_up", "sandbox_error",
)


def file_overview(workdir: Path, limit: int = 60) -> str:
    files = [line for line in git(workdir, "ls-files").splitlines() if line.endswith(".py")]
    files = [f for f in files if not f.startswith(("data/", "docs/"))]
    shown = files[:limit]
    more = f"\n... {len(files) - limit} more .py files" if len(files) > limit else ""
    return "\n".join(shown) + more


def _sandbox_for(cfg: Config, task: Task, workdir: Path) -> Sandbox:
    env = task.env if cfg.sandbox.backend == "docker" else task.local_env(workdir)
    return make_sandbox(cfg.sandbox, workdir, env)


def evaluate(cfg: Config, task: Task, agent_workdir: Path, eval_dir: Path, baseline: TestRun) -> dict:
    """Copy the agent's final tree, drop in the hidden test, run it + the suite in a fresh sandbox."""
    if eval_dir.exists():
        shutil.rmtree(eval_dir)
    shutil.copytree(agent_workdir, eval_dir, symlinks=True)
    install_hidden_test(task, eval_dir)
    with _sandbox_for(cfg, task, eval_dir) as sb:
        hidden = run_pytest(sb, [HIDDEN_TEST_DEST], timeout_s=cfg.sandbox.command_timeout_s)
        suite = run_pytest(sb, None, timeout_s=cfg.sandbox.command_timeout_s * 2)
    broken = sorted(f for f in new_failures(suite, baseline) if not f.startswith(HIDDEN_TEST_DEST))
    return {
        "hidden_passed": hidden.passed,
        "hidden_exit": hidden.exit_code,
        "hidden_output_tail": hidden.output[-1500:],
        "suite_new_failures": broken,
        "suite_exit": suite.exit_code,
    }


def run_attempt(cfg: Config, task: Task, provider: Provider, *, run_id: str, attempt: int, out_root: Path,
                open_pr_flag: bool = False) -> dict:
    out_dir = Path(out_root) / run_id / task.id / f"attempt-{attempt}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    scratch = Path(cfg.cache_dir) / "work" / run_id / task.id / f"attempt-{attempt}"
    workdir = scratch / "repo"
    t0 = time.monotonic()
    result: dict = {
        "task_id": task.id, "repo": task.repo, "attempt": attempt, "run_id": run_id, "model": provider.label(),
        "difficulty": task.difficulty, "category": task.category, "source": task.source, "cost_usd": 0.0,
    }
    logger = StepLogger(out_dir / "steps.jsonl", task.id, attempt, provider.label())
    try:
        mirror = ensure_mirror(Path(cfg.cache_dir), task)
        fresh_clone(mirror, task, workdir)
        with _sandbox_for(cfg, task, workdir) as sb:
            b0 = time.monotonic()
            baseline = run_pytest(sb, None, timeout_s=cfg.sandbox.command_timeout_s * 2)
            logger.log(step=0, phase="setup", tool="baseline_suite", outcome=f"exit_{baseline.exit_code}",
                       duration_s=time.monotonic() - b0, baseline_failures=sorted(baseline.failed))
            tools = ToolBox(workdir, sb, read_window=cfg.agent.read_window_lines,
                            obs_limit=cfg.agent.max_observation_chars, test_timeout_s=cfg.sandbox.command_timeout_s,
                            protected={HIDDEN_TEST_DEST})
            agent = Agent(cfg.agent, provider, tools, logger, baseline)
            ctx = TaskContext(task.id, task.repo, task.title, task.body, task.import_roots, file_overview(workdir))
            outcome = agent.run(ctx)
        result.update({k: v for k, v in asdict(outcome).items()})
        result["baseline_failures"] = sorted(baseline.failed)
        diff = git(workdir, "diff", "--no-color", "--no-ext-diff")
        git(workdir, "add", "-A")
        diff = git(workdir, "diff", "--cached", "--no-color", "--no-ext-diff")
        git(workdir, "reset", "-q")
        (out_dir / "final.diff").write_text(diff)
        if outcome.submitted:
            ev = evaluate(cfg, task, workdir, scratch / "eval", baseline)
            result["eval"] = ev
            if not ev["hidden_passed"]:
                result["failure_reason"] = "hidden_test_failed"
            elif ev["suite_new_failures"]:
                result["failure_reason"] = "broke_other_tests"
        result["solved"] = bool(outcome.submitted and result.get("failure_reason") is None)
        result["broke_other_tests"] = bool(result.get("eval", {}).get("suite_new_failures"))
        if outcome.submitted:
            branch = branch_name(task.id, attempt, run_id)
            diffstat = git(workdir, "diff", "--stat", "HEAD") or ""
            body = build_pr_body(
                task_id=task.id, issue_title=task.title, summary=outcome.pr_summary, diffstat=diffstat,
                repro_test=outcome.repro_test if outcome.repro_confirmed else None,
                suite_note="Full test suite: no new failures vs. the base commit",
                model=provider.label(), steps=outcome.steps, minutes=outcome.duration_s / 60)
            (out_dir / "pr_body.md").write_text(body)
            sha = commit_branch(workdir, branch, outcome.pr_title or f"Fix: {task.title}")
            result["branch"] = branch
            result["commit"] = sha
            pr_title = outcome.pr_title or f"Fix: {task.title}"
            if result["solved"] and sha:
                try:
                    pr = open_pr(repo=task.repo, workdir=workdir, branch=branch, base=task.base_branch,
                                 title=pr_title, body_file=out_dir / "pr_body.md", enabled=open_pr_flag)
                    result["pr"] = {"opened": pr.opened, "reason": pr.reason, "url": pr.url,
                                    "commands": pr.commands}
                except PRPolicyError as exc:
                    result["pr"] = {"opened": False, "reason": f"blocked: {exc}"}
    except Exception as exc:  # infra failure: record it, never crash the whole run
        result.setdefault("solved", False)
        result["failure_reason"] = result.get("failure_reason") or "sandbox_error"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    finally:
        logger.close()
    result["wall_s"] = round(time.monotonic() - t0, 2)
    result.setdefault("solved", False)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
    return result
