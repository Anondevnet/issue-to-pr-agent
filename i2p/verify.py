"""Verify the task set: hidden test fails at base, passes with the reference fix, no new suite failures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import Config
from .runner import _sandbox_for
from .tasks import HIDDEN_TEST_DEST, Task, apply_patch, ensure_mirror, fresh_clone, install_hidden_test
from .testrun import new_failures, run_pytest


def verify_task(cfg: Config, task: Task, scratch: Path, source_url: str | None = None) -> dict:
    mirror = ensure_mirror(Path(cfg.cache_dir), task, source_url)
    work = fresh_clone(mirror, task, Path(scratch) / task.id)
    rec: dict = {"task_id": task.id, "repo": task.repo}
    try:
        with _sandbox_for(cfg, task, work) as sb:
            base_suite = run_pytest(sb, None, timeout_s=cfg.sandbox.command_timeout_s * 2)
        install_hidden_test(task, work)
        with _sandbox_for(cfg, task, work) as sb:
            before = run_pytest(sb, [HIDDEN_TEST_DEST], timeout_s=cfg.sandbox.command_timeout_s)
        apply_patch(work, task.fix_patch)
        with _sandbox_for(cfg, task, work) as sb:
            after = run_pytest(sb, [HIDDEN_TEST_DEST], timeout_s=cfg.sandbox.command_timeout_s)
            fixed_suite = run_pytest(sb, None, timeout_s=cfg.sandbox.command_timeout_s * 2)
        broken = sorted(f for f in new_failures(fixed_suite, base_suite) if not f.startswith(HIDDEN_TEST_DEST))
        rec.update({
            "fails_before": before.exit_code == 1 and bool(before.failed),
            "passes_after": after.passed,
            "suite_new_failures_with_fix": broken,
            "baseline_failures": sorted(base_suite.failed),
            "base_suite_counts": base_suite.counts(),
            "hidden_before_failed": sorted(before.failed),
        })
        rec["ok"] = rec["fails_before"] and rec["passes_after"] and not broken
        if not rec["ok"]:
            rec["before_tail"] = before.output[-800:]
            rec["after_tail"] = after.output[-800:]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return rec


def verify_all(cfg: Config, tasks: list[Task], scratch: Path, out: Path | None = None) -> list[dict]:
    results = [verify_task(cfg, t, scratch) for t in tasks]
    if out:
        Path(out).write_text(json.dumps(results, indent=2))
    return results
