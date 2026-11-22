import json
import shutil
import subprocess

import yaml

from i2p.config import Config
from i2p.models import MockProvider
from i2p.runner import run_attempt
from i2p.tasks import load_task, mirror_path
from tests.test_agent import HAPPY


def _task(tmp_path, sha):
    d = tmp_path / "tasks" / "toy-1"
    d.mkdir(parents=True)
    (d / "task.yaml").write_text(yaml.dump({
        "id": "toy-1", "repo": "Anondevnet/toy", "base_commit": sha, "title": "add() subtracts",
        "body": "add(2, 3) returns -1", "import_roots": "."}))
    (d / "hidden_test.py").write_text("from mathutil import add\n\ndef test_hidden():\n    assert add(-1, 1) == 0\n")
    (d / "fix.patch").write_text("unused in this test\n")
    return load_task(d / "task.yaml")


def _cfg(tmp_path):
    cfg = Config()
    cfg.sandbox.backend = "local"
    cfg.cache_dir = str(tmp_path / "cache")
    return cfg


def _mirror(cfg, task, repo):
    m = mirror_path(tmp := __import__("pathlib").Path(cfg.cache_dir), task)
    m.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--mirror", str(repo), str(m)], check=True)


def test_end_to_end_solved_dry_run_pr(toy_repo, tmp_path):
    repo, sha = toy_repo
    task = _task(tmp_path, sha)
    cfg = _cfg(tmp_path)
    _mirror(cfg, task, repo)
    r = run_attempt(cfg, task, MockProvider(list(HAPPY)), run_id="t", attempt=1, out_root=tmp_path / "runs")
    assert r["solved"], r
    assert r["eval"]["hidden_passed"] and r["eval"]["suite_new_failures"] == []
    assert r["pr"]["opened"] is False and "dry run" in r["pr"]["reason"]
    push, create = r["pr"]["commands"]
    assert push[2] == "https://github.com/Anondevnet/toy.git"
    assert create[:5] == ["gh", "pr", "create", "--repo", "Anondevnet/toy"]
    out = tmp_path / "runs" / "t" / "toy-1" / "attempt-1"
    assert json.loads((out / "result.json").read_text())["solved"]
    assert "return a + b" in (out / "final.diff").read_text()
    assert "tests/test_repro.py" in (out / "pr_body.md").read_text()
    assert (out / "steps.jsonl").read_text().count("\n") == 8  # baseline + 7 agent steps
    # the upstream toy repo was never touched
    assert "return a - b" in (repo / "mathutil.py").read_text()


def test_hidden_test_failure_is_scored(toy_repo, tmp_path):
    repo, sha = toy_repo
    task = _task(tmp_path, sha)
    cfg = _cfg(tmp_path)
    _mirror(cfg, task, repo)
    # A "fix" that only special-cases the repro input: repro passes, hidden test does not.
    script = list(HAPPY)
    script[4] = {"tool": "edit_file", "args": {"path": "mathutil.py", "old": "return a - b",
                                                "new": "return 5 if (a, b) == (2, 3) else a - b"}}
    r = run_attempt(cfg, task, MockProvider(script), run_id="t", attempt=1, out_root=tmp_path / "runs")
    assert not r["solved"] and r["failure_reason"] == "hidden_test_failed"
    assert "pr" not in r


def test_infra_error_recorded(tmp_path):
    task = _task(tmp_path, "0" * 40)
    cfg = _cfg(tmp_path)
    m = mirror_path(__import__("pathlib").Path(cfg.cache_dir), task)
    m.mkdir(parents=True)  # broken mirror
    r = run_attempt(cfg, task, MockProvider([]), run_id="t", attempt=1, out_root=tmp_path / "runs")
    assert r["solved"] is False and r["failure_reason"] == "sandbox_error" and "error" in r
