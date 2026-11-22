import json

import make_table


def _write(tmp_path, run, task, attempt, solved, reason=None, wall=120, model="ollama:m"):
    d = tmp_path / run / task / f"attempt-{attempt}"
    d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({
        "task_id": task, "repo": "Anondevnet/r", "attempt": attempt, "run_id": run, "model": model,
        "solved": solved, "failure_reason": reason, "wall_s": wall, "difficulty": "easy",
        "tool_counts": {"read_file": 3, "edit_file": 1}, "prompt_tokens": 1000, "completion_tokens": 200,
        "cost_usd": 0.0, "broke_other_tests": reason == "broke_other_tests"}))


def test_table(tmp_path):
    for a in (1, 2, 3):
        _write(tmp_path, "r1", "t1", a, True)
        _write(tmp_path, "r1", "t2", a, a == 1, None if a == 1 else "no_repro", wall=240)
    md = make_table.build_tables(make_table.load_results([str(tmp_path)]))
    assert "| ollama:m | 2 | 3 | 2/2, 1/2, 1/2 | 67% ± 24 |" in md
    assert "| no_repro | 2 | 100% |" in md
    assert "| t2 | r | easy | 1/3 | 4.0 | no_repro |" in md
    assert "$0.00" in md


def test_readme_block(tmp_path):
    _write(tmp_path, "r1", "t1", 1, True)
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- results:start -->\nold\n<!-- results:end -->\nafter\n")
    make_table.main([str(tmp_path / "r1"), "--readme", str(readme)])
    text = readme.read_text()
    assert "old" not in text and "| ollama:m |" in text and text.endswith("after\n")


def test_empty():
    assert "No results" in make_table.build_tables([])
