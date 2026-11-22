import pytest

from i2p.sandbox import LocalSandbox
from i2p.tools import ToolBox, ToolError, is_test_path


@pytest.fixture
def tb(toy_repo):
    repo, _ = toy_repo
    return ToolBox(repo, LocalSandbox(repo, {"PYTHONPATH": str(repo)}, allow_unsafe=True),
                   protected={"tests/test_i2p_hidden.py"})


@pytest.mark.parametrize("bad", ["../x.py", "/etc/passwd", "tests/../../x", ".git/config", "./.git/HEAD"])
def test_path_containment(tb, bad):
    with pytest.raises(ToolError):
        tb.read_file(bad)


def test_symlink_escape_blocked(tb, tmp_path):
    (tb.root / "link.py").symlink_to(tmp_path.parent)
    with pytest.raises(ToolError):
        tb.read_file("link.py/anything")


def test_write_file_only_tests(tb):
    with pytest.raises(ToolError):
        tb.write_file("mathutil.py", "x = 1")
    with pytest.raises(ToolError):
        tb.write_file("tests/test_i2p_hidden.py", "x = 1")
    assert tb.write_file("tests/test_repro.py", "def test_a():\n    assert True").ok


def test_edit_file_exact_unique(tb):
    with pytest.raises(ToolError, match="not found"):
        tb.edit_file("mathutil.py", "return a * b", "return a + b")
    (tb.root / "dup.py").write_text("x = 1\nx = 1\n")
    with pytest.raises(ToolError, match="2 times"):
        tb.edit_file("dup.py", "x = 1", "x = 2")
    assert tb.edit_file("mathutil.py", "return a - b", "return a + b").ok
    assert "return a + b" in (tb.root / "mathutil.py").read_text()
    assert "mathutil.py" in tb.edited_files


def test_search_and_read(tb):
    hits = tb.search_code(r"def add").text
    assert "mathutil.py:1:" in hits
    out = tb.read_file("mathutil.py", 1, 3).text
    assert "   3| " in out and "lines 1-3 of" in out
    assert "tests/test_existing.py" in tb.list_files().text


def test_run_tests_in_sandbox(tb):
    res, run = tb.run_tests("tests/test_existing.py")
    assert res.ok and run.exit_code == 0


def test_is_test_path():
    assert is_test_path("tests/test_x.py") and is_test_path("test_y.py") and is_test_path("pkg/tests/helpers.py")
    assert not is_test_path("app/main.py") and not is_test_path("tests/data.json")


def test_existing_tests_are_read_only(tb):
    with pytest.raises(ToolError, match="read-only"):
        tb.write_file("tests/test_existing.py", "def test_x():\n    pass\n")
    with pytest.raises(ToolError, match="read-only"):
        tb.edit_file("tests/test_existing.py", "double(3) == 6", "True")
    tb.write_file("tests/test_new.py", "def test_x():\n    assert 1\n")
    assert tb.edit_file("tests/test_new.py", "assert 1", "assert 2").ok  # own new test is editable
