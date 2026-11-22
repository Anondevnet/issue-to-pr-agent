import pytest

from i2p.config import SandboxConfig
from i2p.sandbox import DockerSandbox, LocalSandbox, SandboxError


def test_docker_args_are_locked_down(tmp_path):
    sb = DockerSandbox(SandboxConfig(), tmp_path, {"PYTHONPATH": "/work/src"}, name="i2p-test")
    a = sb.run_args()
    s = " ".join(a)
    assert "--network none" in s and "--cap-drop ALL" in s and "--read-only" in s
    assert "--security-opt no-new-privileges" in s and "--memory 2g" in s and "--memory-swap 2g" in s
    assert "--pids-limit 256" in s and "--cpus 2.0" in s
    user = a[a.index("--user") + 1]
    assert not user.startswith("0:")
    assert f"{tmp_path.resolve()}:/work:rw" in a
    assert "PYTHONPATH=/work/src" in a
    ex = sb.exec_args("python -m pytest", 60)
    assert ex[ex.index("i2p-test") + 1:] == ["timeout", "-k", "5", "60", "sh", "-c", "python -m pytest"]


def test_network_must_be_none(tmp_path):
    sb = DockerSandbox(SandboxConfig(network="bridge"), tmp_path)
    with pytest.raises(SandboxError):
        sb.start()


def test_docker_cmd_prefix(tmp_path):
    sb = DockerSandbox(SandboxConfig(docker_cmd="sudo docker"), tmp_path, name="n")
    assert sb.run_args()[:3] == ["sudo", "docker", "run"]


def test_local_requires_explicit_opt_in(tmp_path):
    with pytest.raises(SandboxError):
        LocalSandbox(tmp_path)
    sb = LocalSandbox(tmp_path, allow_unsafe=True, command_timeout_s=1)
    res = sb.exec("sleep 5")
    assert res.timed_out
