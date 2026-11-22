import subprocess

import pytest

from i2p.pr import ALLOWED_OWNER, PRPolicyError, assert_allowed_repo, branch_name, open_pr


@pytest.mark.parametrize("repo", ["scottpike7-hash/x", "solanaape2k-art/x", "Anondevnet-evil/x", "anondevnetx/y",
                                  "Anondevnet/../x", "Anondevnet", "", "evil/Anondevnet", "Anondevnet/x/y"])
def test_disallowed_repos(repo):
    with pytest.raises(PRPolicyError):
        assert_allowed_repo(repo)


def test_allowed_repo_case_insensitive():
    assert assert_allowed_repo("anondevnet/atlas-agent") == (ALLOWED_OWNER, "atlas-agent")


class FakeRunner:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append(args)
        out = ""
        for prefix, reply in self.replies.items():
            if " ".join(args).startswith(prefix):
                out = reply
        return subprocess.CompletedProcess(args, 0, out, "")


def _open(runner, enabled=True, repo="Anondevnet/atlas-agent", tmp_path=None):
    return open_pr(repo=repo, workdir=tmp_path, branch="i2p/x", base="main", title="t",
                   body_file=tmp_path / "b.md", enabled=enabled, runner=runner)


def test_disabled_by_default_never_calls_out(tmp_path):
    runner = FakeRunner({})
    res = _open(runner, enabled=False, tmp_path=tmp_path)
    assert not res.opened and runner.calls == []


def test_blocked_owner_even_in_dry_run(tmp_path):
    with pytest.raises(PRPolicyError):
        _open(FakeRunner({}), enabled=False, repo="scottpike7-hash/atlas-agent", tmp_path=tmp_path)


def test_wrong_gh_login_blocks(tmp_path):
    runner = FakeRunner({"gh api user": "scottpike7-hash"})
    with pytest.raises(PRPolicyError, match="logged in"):
        _open(runner, tmp_path=tmp_path)
    assert not any(c[:2] == ["git", "push"] for c in runner.calls)


def test_repo_owner_mismatch_blocks(tmp_path):
    runner = FakeRunner({"gh api user": "Anondevnet", "gh repo view": "someone-else"})
    with pytest.raises(PRPolicyError, match="owned by"):
        _open(runner, tmp_path=tmp_path)
    assert not any(c[:2] == ["git", "push"] for c in runner.calls)


def test_enabled_happy_path(tmp_path):
    runner = FakeRunner({"gh api user": "Anondevnet", "gh repo view": "Anondevnet",
                         "gh pr create": "https://github.com/Anondevnet/atlas-agent/pull/1"})
    res = _open(runner, tmp_path=tmp_path)
    assert res.opened and res.url.endswith("/pull/1")
    push = [c for c in runner.calls if c[:2] == ["git", "push"]][0]
    assert push[2] == "https://github.com/Anondevnet/atlas-agent.git"
    create = runner.calls[-1]
    assert create[:5] == ["gh", "pr", "create", "--repo", "Anondevnet/atlas-agent"]


def test_branch_name_safe():
    b = branch_name("tci-003", 2, "2026 11/22")
    assert b.startswith("i2p/") and " " not in b and b.count("/") == 1
