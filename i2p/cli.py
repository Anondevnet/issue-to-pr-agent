"""Command line: doctor | build-image | verify-tasks | run."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .config import load_config
from .models import make_provider
from .pr import ALLOWED_OWNER
from .runner import run_attempt
from .tasks import load_tasks
from .verify import verify_all

ROOT = Path(__file__).resolve().parent.parent


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else '!!'}] {label}{(': ' + detail) if detail else ''}")
    return ok


def cmd_doctor(args, cfg) -> int:
    ok = True
    ok &= _check("python >= 3.11", sys.version_info >= (3, 11), platform.python_version())
    print(f"     machine: {platform.system()} {platform.machine()}")
    docker = shlex.split(cfg.sandbox.docker_cmd)
    try:
        info = subprocess.run([*docker, "info", "--format", "{{.Architecture}} {{.NCPU}}cpu {{.MemTotal}}"],
                              capture_output=True, text=True, timeout=30)
        ok &= _check("docker daemon reachable", info.returncode == 0, (info.stdout or info.stderr).strip()[:120])
        img = subprocess.run([*docker, "image", "inspect", cfg.sandbox.image], capture_output=True, timeout=30)
        _check(f"sandbox image {cfg.sandbox.image}", img.returncode == 0,
               "" if img.returncode == 0 else "run: python -m i2p build-image")
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        ok &= _check("docker installed", False, str(exc))
    if cfg.model.provider == "ollama":
        try:
            with urllib.request.urlopen(cfg.model.base_url.rstrip("/") + "/api/tags", timeout=10) as r:
                names = [m["name"] for m in json.loads(r.read()).get("models", [])]
            ok &= _check("ollama reachable", True, cfg.model.base_url)
            have = cfg.model.model in names or f"{cfg.model.model}:latest" in names
            ok &= _check(f"model {cfg.model.model} pulled", have, "" if have else f"run: ollama pull {cfg.model.model}")
        except Exception as exc:  # noqa: BLE001
            ok &= _check("ollama reachable", False, str(exc)[:120])
    total, used, free = shutil.disk_usage(ROOT)
    ok &= _check("free disk >= 15 GB", free >= 15e9, f"{free / 1e9:.1f} GB free")
    gh = shutil.which("gh")
    if gh:
        who = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=30)
        login = who.stdout.strip()
        _check(f"gh logged in as {ALLOWED_OWNER} (only needed for --open-pr)",
               login.lower() == ALLOWED_OWNER.lower(), login or who.stderr.strip()[:100])
    else:
        _check("gh installed (only needed for --open-pr)", False)
    return 0 if ok else 1


def cmd_build_image(args, cfg) -> int:
    docker = shlex.split(cfg.sandbox.docker_cmd)
    cmd = [*docker, "build", "-t", cfg.sandbox.image, "-f", str(ROOT / "docker" / "Dockerfile.sandbox"),
           str(ROOT / "docker")]
    print(" ".join(cmd))
    return subprocess.run(cmd).returncode


def cmd_verify(args, cfg) -> int:
    tasks = load_tasks(Path(args.tasks), args.task)
    scratch = Path(cfg.cache_dir) / "verify"
    results = verify_all(cfg, tasks, scratch, Path(args.out) if args.out else None)
    bad = 0
    for r in results:
        bad += not r["ok"]
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['task_id']:<10} fails_before={r['fails_before']} "
              f"passes_after={r['passes_after']} new_suite_failures={len(r['suite_new_failures_with_fix'])} "
              f"baseline_failures={len(r['baseline_failures'])}")
    print(f"{len(results) - bad}/{len(results)} tasks verified")
    return 1 if bad else 0


def cmd_run(args, cfg) -> int:
    if args.model:
        cfg.model.model = args.model
    if args.provider:
        cfg.model.provider = args.provider
    provider = make_provider(cfg.model)
    tasks = load_tasks(Path(args.tasks), args.task)
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    out_root = Path(cfg.runs_dir)
    (out_root / run_id).mkdir(parents=True, exist_ok=True)
    (out_root / run_id / "config.json").write_text(json.dumps(cfg.to_dict(), indent=2))
    if args.open_pr:
        print(f"--open-pr is ON: solved tasks will be pushed and opened as PRs on {ALLOWED_OWNER}/* only.")
    solved = 0
    total = 0
    for attempt in range(1, args.runs + 1):
        for task in tasks:
            r = run_attempt(cfg, task, provider, run_id=run_id, attempt=attempt, out_root=out_root,
                            open_pr_flag=args.open_pr)
            total += 1
            solved += r["solved"]
            print(f"[run {attempt}] {task.id:<10} {'SOLVED' if r['solved'] else 'failed':<7} "
                  f"{r.get('failure_reason') or '':<20} steps={r.get('steps', 0):<3} {r['wall_s']:.0f}s", flush=True)
    print(f"solved {solved}/{total}  results in {out_root / run_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="i2p", description="$0 issue-to-PR agent")
    p.add_argument("--config", default=os.environ.get("I2P_CONFIG"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("build-image")
    v = sub.add_parser("verify-tasks")
    v.add_argument("--tasks", default=str(ROOT / "tasks"))
    v.add_argument("--task", action="append")
    v.add_argument("--out")
    r = sub.add_parser("run")
    r.add_argument("--tasks", default=str(ROOT / "tasks"))
    r.add_argument("--task", action="append", help="task id or repo name (repeatable)")
    r.add_argument("--runs", type=int, default=1)
    r.add_argument("--run-id")
    r.add_argument("--model")
    r.add_argument("--provider", choices=["ollama", "openai_compat"])
    r.add_argument("--open-pr", action="store_true",
                   help=f"push solved branches and open PRs (only on {ALLOWED_OWNER}/* repos)")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    return {"doctor": cmd_doctor, "build-image": cmd_build_image, "verify-tasks": cmd_verify,
            "run": cmd_run}[args.cmd](args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
