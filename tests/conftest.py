import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

BUGGY = '''def add(a, b):
    """Return a + b."""
    return a - b


def double(x):
    return x * 2
'''

EXISTING_TEST = '''from mathutil import double


def test_double():
    assert double(3) == 6
'''


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def toy_repo(tmp_path):
    """A tiny git repo with a real bug (add subtracts) and one passing test."""
    repo = tmp_path / "toy"
    (repo / "tests").mkdir(parents=True)
    (repo / "mathutil.py").write_text(BUGGY)
    (repo / "tests" / "test_existing.py").write_text(EXISTING_TEST)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    return repo, sha
