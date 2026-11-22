"""Real-container checks. Opt in: I2P_DOCKER_TESTS=1 (and I2P_DOCKER="sudo docker" if needed)."""

import os

import pytest

from i2p.config import SandboxConfig
from i2p.sandbox import DockerSandbox

pytestmark = pytest.mark.skipif(os.environ.get("I2P_DOCKER_TESTS") != "1", reason="set I2P_DOCKER_TESTS=1")


@pytest.fixture
def sb(tmp_path):
    cfg = SandboxConfig(docker_cmd=os.environ.get("I2P_DOCKER", "docker"), command_timeout_s=20)
    (tmp_path / "hello.py").write_text("print('hi')\n")
    s = DockerSandbox(cfg, tmp_path, {"PYTHONPATH": "/work"})
    s.start()
    yield s
    s.stop()


def test_isolation(sb, tmp_path):
    assert sb.exec("python hello.py").output.strip() == "hi"
    assert sb.exec("id -u").output.strip() != "0"
    net = sb.exec("python -c \"import socket; socket.create_connection(('1.1.1.1', 80), timeout=3)\"")
    assert net.code != 0
    assert sb.exec("touch /etc/x").code != 0  # read-only root
    assert sb.exec("touch /tmp/x && echo ok").output.strip() == "ok"
    assert sb.exec("echo data > out.txt && cat out.txt").output.strip() == "data"
    assert (tmp_path / "out.txt").read_text().strip() == "data"


def test_timeout(sb):
    res = sb.exec("sleep 30", timeout_s=2)
    assert res.timed_out and res.duration_s < 15
