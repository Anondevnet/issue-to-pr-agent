import os

from cyberintel.config import _load_dotenv


def test_export_prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("I2P_HIDDEN_A", raising=False)
    monkeypatch.delenv("I2P_HIDDEN_B", raising=False)
    p = tmp_path / ".env"
    p.write_text('export I2P_HIDDEN_A=abc\nI2P_HIDDEN_B="q"\n')
    _load_dotenv(p)
    assert os.environ.get("I2P_HIDDEN_A") == "abc"
    assert os.environ.get("I2P_HIDDEN_B") == "q"
    assert "export I2P_HIDDEN_A" not in os.environ


def test_existing_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("I2P_HIDDEN_C", "keep")
    p = tmp_path / ".env"
    p.write_text("export I2P_HIDDEN_C=override\n")
    _load_dotenv(p)
    assert os.environ["I2P_HIDDEN_C"] == "keep"
