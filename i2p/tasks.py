"""Task files (tasks/<id>/task.yaml + hidden_test.py + fix.patch) and fresh clones."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .pr import assert_allowed_repo
from .tools import git

HIDDEN_TEST_DEST = "tests/test_i2p_hidden.py"


@dataclass
class Task:
    id: str
    repo: str  # Anondevnet/<name>
    base_commit: str
    title: str
    body: str
    import_roots: str = "."
    base_branch: str = "main"
    difficulty: str = "easy"
    category: str = ""
    source: str = "real"  # real = bug present in the repo at base_commit
    dir: Path = field(default_factory=Path)

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]

    @property
    def hidden_test(self) -> Path:
        return self.dir / "hidden_test.py"

    @property
    def fix_patch(self) -> Path:
        return self.dir / "fix.patch"

    @property
    def env(self) -> dict[str, str]:
        return {"PYTHONPATH": ":".join(f"/work/{p}".rstrip("/.") if p != "." else "/work"
                                       for p in self.import_roots.split(":"))}

    def local_env(self, workdir: Path) -> dict[str, str]:
        return {"PYTHONPATH": ":".join(str((Path(workdir) / p).resolve()) for p in self.import_roots.split(":"))}


def load_task(path: Path) -> Task:
    data = yaml.safe_load(Path(path).read_text())
    task = Task(**{k: v for k, v in data.items() if k in Task.__dataclass_fields__ and k != "dir"},
                dir=Path(path).parent)
    assert_allowed_repo(task.repo)
    if not task.hidden_test.is_file() or not task.fix_patch.is_file():
        raise ValueError(f"{task.id}: hidden_test.py and fix.patch are required")
    return task


def load_tasks(tasks_dir: Path, only: list[str] | None = None) -> list[Task]:
    tasks = [load_task(p) for p in sorted(Path(tasks_dir).glob("*/task.yaml"))]
    if only:
        wanted = set(only)
        tasks = [t for t in tasks if t.id in wanted or t.repo_name in wanted]
    return tasks


def mirror_path(cache_dir: Path, task: Task) -> Path:
    return Path(cache_dir) / "mirrors" / f"{task.repo_name}.git"


def ensure_mirror(cache_dir: Path, task: Task, source_url: str | None = None) -> Path:
    """Clone (once) a bare mirror of the task repo; later attempts clone from it offline."""
    mirror = mirror_path(cache_dir, task)
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        url = source_url or f"https://github.com/{task.repo}.git"
        subprocess.run(["git", "clone", "--quiet", "--mirror", url, str(mirror)], check=True, timeout=600)
    has = subprocess.run(["git", "-C", str(mirror), "cat-file", "-e", f"{task.base_commit}^{{commit}}"],
                         capture_output=True)
    if has.returncode != 0:
        subprocess.run(["git", "-C", str(mirror), "fetch", "--quiet", "origin"], check=False, timeout=600)
    return mirror


def fresh_clone(mirror: Path, task: Task, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(mirror), str(dest)], check=True, timeout=600)
    git(dest, "checkout", "-q", "--detach", task.base_commit, check=True)
    git(dest, "remote", "set-url", "origin", f"https://github.com/{task.repo}.git", check=True)
    return dest


def install_hidden_test(task: Task, workdir: Path) -> Path:
    dest = Path(workdir) / HIDDEN_TEST_DEST
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(task.hidden_test, dest)
    return dest


def apply_patch(workdir: Path, patch: Path) -> None:
    git(workdir, "apply", "--whitespace=nowarn", str(Path(patch).resolve()), check=True)
