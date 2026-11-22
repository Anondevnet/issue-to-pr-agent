from pathlib import Path

from i2p.tasks import load_tasks

TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"
EXCLUDED = {"contract-auditor", "auditor-evals"}


def test_task_set_shape():
    tasks = load_tasks(TASKS_DIR)
    assert 20 <= len(tasks) <= 25
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids))
    for t in tasks:
        assert t.repo.startswith("Anondevnet/")
        assert t.repo_name not in EXCLUDED
        assert len(t.base_commit) == 40
        assert t.title and len(t.body) > 80
        patch = t.fix_patch.read_text()
        assert patch.startswith("diff --git") and "tests/" not in patch.split("\n", 1)[0]
        assert "def test_" in t.hidden_test.read_text()
        assert t.source == "real"


def test_hidden_tests_not_leaked_into_issue_text():
    for t in load_tasks(TASKS_DIR):
        assert "hidden_test" not in t.body and "test_i2p_hidden" not in t.body
