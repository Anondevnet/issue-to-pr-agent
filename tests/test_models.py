import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from i2p.config import ModelConfig
from i2p.models import ModelError, OllamaProvider, OpenAICompatProvider, make_provider, strip_thinking


@pytest.fixture
def fake_ollama():
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            reply = {"message": {"content": '<think>hm</think>{"tool": "git_diff", "args": {}}'},
                     "prompt_eval_count": 321, "eval_count": 12}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()


def test_ollama_payload_and_tokens(fake_ollama):
    url, seen = fake_ollama
    p = OllamaProvider(ModelConfig(base_url=url, model="huihui_ai/qwen3.5-abliterated:9b"))
    r = p.chat([{"role": "user", "content": "hi"}])
    assert r.text == '{"tool": "git_diff", "args": {}}'
    assert (r.prompt_tokens, r.completion_tokens) == (321, 12)
    path, body = seen[0]
    assert path == "/api/chat" and body["format"] == "json" and body["stream"] is False
    assert body["model"] == "huihui_ai/qwen3.5-abliterated:9b" and body["options"]["num_ctx"] == 8192


def test_unreachable_is_model_error():
    p = OllamaProvider(ModelConfig(base_url="http://127.0.0.1:9", timeout_s=2))
    with pytest.raises(ModelError):
        p.chat([{"role": "user", "content": "hi"}])


def test_hosted_off_by_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    with pytest.raises(ModelError, match="disabled"):
        OpenAICompatProvider(ModelConfig(provider="openai_compat"))
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(ModelError, match="not set"):
        OpenAICompatProvider(ModelConfig(provider="openai_compat", allow_hosted=True))


def test_defaults_are_local():
    cfg = ModelConfig()
    assert cfg.provider == "ollama" and cfg.base_url == "http://127.0.0.1:11434"
    assert cfg.model == "huihui_ai/qwen3.5-abliterated:9b" and not cfg.allow_hosted
    assert isinstance(make_provider(cfg), OllamaProvider)


def test_strip_thinking():
    assert strip_thinking("<think>a\nb</think>\n{}") == "{}"
