import json

from i2p.agent import Agent, TaskContext
from i2p.config import AgentConfig
from i2p.models import MockProvider
from i2p.sandbox import LocalSandbox
from i2p.steplog import REQUIRED_KEYS, StepLogger, read_steps
from i2p.testrun import run_pytest
from i2p.tools import ToolBox

REPRO = "from mathutil import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
CTX = TaskContext("toy-1", "Anondevnet/toy", "add() subtracts", "add(2, 3) returns -1, expected 5.")


def make_agent(repo, script, tmp_path, **cfg):
    sb = LocalSandbox(repo, {"PYTHONPATH": str(repo)}, allow_unsafe=True)
    tools = ToolBox(repo, sb)
    log = StepLogger(tmp_path / "steps.jsonl", "toy-1", 1, "mock")
    baseline = run_pytest(sb)
    return Agent(AgentConfig(**cfg), MockProvider(script), tools, log, baseline), log


HAPPY = [
    {"tool": "search_code", "args": {"pattern": "def add"}},
    {"tool": "read_file", "args": {"path": "mathutil.py"}},
    {"tool": "write_file", "args": {"path": "tests/test_repro.py", "content": REPRO}},
    {"tool": "run_tests", "args": {"target": "tests/test_repro.py"}},
    {"tool": "edit_file", "args": {"path": "mathutil.py", "old": "return a - b", "new": "return a + b"}},
    {"tool": "run_tests", "args": {}},
    {"tool": "finish", "args": {"title": "Fix add()", "summary": "add subtracted; now adds."}},
]


def test_happy_path_solves_and_logs(toy_repo, tmp_path):
    repo, _ = toy_repo
    agent, log = make_agent(repo, list(HAPPY), tmp_path)
    out = agent.run(CTX)
    log.close()
    assert out.submitted and out.failure_reason is None
    assert out.repro_confirmed and out.repro_test == "tests/test_repro.py"
    assert out.pr_title == "Fix add()" and out.steps == 7
    assert "mathutil.py" in out.edited_files and out.failed_suite_runs == 0
    steps = read_steps(tmp_path / "steps.jsonl")
    assert len(steps) == 7
    for s in steps:
        for key in REQUIRED_KEYS:
            assert key in s
        assert s["cost_usd"] == 0.0
    outcomes = [s["outcome"] for s in steps]
    assert "repro_confirmed" in outcomes and "suite_green" in outcomes and outcomes[-1] == "finished"


def test_source_edit_rejected_before_repro(toy_repo, tmp_path):
    repo, _ = toy_repo
    script = [{"tool": "edit_file", "args": {"path": "mathutil.py", "old": "return a - b", "new": "return a + b"}},
              {"tool": "give_up", "args": {"reason": "stuck"}}]
    agent, log = make_agent(repo, script, tmp_path)
    out = agent.run(CTX)
    log.close()
    assert not out.submitted
    assert read_steps(tmp_path / "steps.jsonl")[0]["outcome"] == "rejected"
    assert "return a - b" in (repo / "mathutil.py").read_text()
    assert out.failure_reason == "no_repro"


def test_passing_repro_is_not_accepted(toy_repo, tmp_path):
    repo, _ = toy_repo
    script = [{"tool": "write_file", "args": {"path": "tests/test_repro.py",
                                               "content": "def test_x():\n    assert True\n"}},
              {"tool": "run_tests", "args": {"target": "tests/test_repro.py"}}]
    agent, log = make_agent(repo, script, tmp_path, max_steps=2)
    out = agent.run(CTX)
    log.close()
    assert not out.repro_confirmed and out.failure_reason == "no_repro"
    assert read_steps(tmp_path / "steps.jsonl")[1]["outcome"] == "repro_passes"


def test_retries_exhausted(toy_repo, tmp_path):
    repo, _ = toy_repo
    bad_edit = {"tool": "edit_file", "args": {"path": "mathutil.py", "old": "return x * 2", "new": "return x * 3"}}
    script = list(HAPPY[2:4]) + [bad_edit] + [{"tool": "run_tests", "args": {}}] * 4
    agent, log = make_agent(repo, script, tmp_path, max_retries=3)
    out = agent.run(CTX)
    log.close()
    assert not out.submitted and out.failure_reason == "patch_failed_tests"
    assert out.failed_suite_runs == 4  # first attempt + 3 retries


def test_finish_requires_green_suite_and_source_change(toy_repo, tmp_path):
    repo, _ = toy_repo
    script = [{"tool": "finish", "args": {"title": "t", "summary": "s"}}, {"tool": "give_up", "args": {}}]
    agent, log = make_agent(repo, script, tmp_path)
    out = agent.run(CTX)
    log.close()
    assert not out.submitted
    assert read_steps(tmp_path / "steps.jsonl")[0]["outcome"] == "rejected"


def test_invalid_output_and_step_limit(toy_repo, tmp_path):
    repo, _ = toy_repo
    agent, log = make_agent(repo, ["not json"] * 10, tmp_path, max_parse_failures=3)
    out = agent.run(CTX)
    log.close()
    assert out.failure_reason == "invalid_model_output" and out.steps == 3

    agent2, log2 = make_agent(repo, [{"tool": "list_files", "args": {}}] * 10, tmp_path, max_steps=4)
    out2 = agent2.run(CTX)
    log2.close()
    assert out2.steps == 4 and out2.failure_reason == "no_repro"


def test_prompt_stays_small(toy_repo, tmp_path):
    repo, _ = toy_repo
    agent, log = make_agent(repo, [{"tool": "read_file", "args": {"path": "mathutil.py"}}] * 12, tmp_path,
                            max_steps=12)
    agent.run(CTX)
    log.close()
    sizes = [sum(len(m["content"]) for m in call) for call in agent.provider.calls]
    assert max(sizes) < 12000  # history is windowed, not accumulated
    assert json.dumps(agent.provider.calls[-1]).count("[step ") <= agent.cfg.history_turns


def test_repeated_calls_are_nudged_then_stopped(toy_repo, tmp_path):
    repo, _ = toy_repo
    call = {"tool": "search_code", "args": {"pattern": "def add"}}
    agent, log = make_agent(repo, [call] * 20, tmp_path, max_repeats=3)
    out = agent.run(CTX)
    log.close()
    steps = read_steps(tmp_path / "steps.jsonl")
    assert steps[0]["outcome"] == "ok" and steps[1]["outcome"] == "repeated_call"
    assert out.steps == 4 and out.failure_reason == "stuck_loop"


def test_full_suite_call_confirms_pending_repro(toy_repo, tmp_path):
    repo, _ = toy_repo
    script = [HAPPY[2], {"tool": "run_tests", "args": {}}] + HAPPY[4:]
    agent, log = make_agent(repo, script, tmp_path)
    out = agent.run(CTX)
    log.close()
    assert out.submitted and out.repro_confirmed
    assert read_steps(tmp_path / "steps.jsonl")[1]["outcome"] == "repro_confirmed"


def test_repeated_edit_not_reapplied(toy_repo, tmp_path):
    repo, _ = toy_repo
    edit = {"tool": "edit_file", "args": {"path": "mathutil.py", "old": "return x * 2", "new": "return x * 2  # ok"}}
    script = HAPPY[2:4] + [edit, edit, {"tool": "give_up", "args": {}}]
    agent, log = make_agent(repo, script, tmp_path)
    agent.run(CTX)
    log.close()
    assert (repo / "mathutil.py").read_text().count("# ok") == 1
    assert read_steps(tmp_path / "steps.jsonl")[3]["outcome"] == "repeated_call"
