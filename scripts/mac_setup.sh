#!/usr/bin/env bash
# One-time setup on an Apple Silicon Mac. Read-only checks first; it only installs into ./.venv
# and builds the local Docker image. It never pushes or opens anything.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== arch: $(uname -m) (arm64 expected)"
command -v docker >/dev/null || { echo "Docker missing: install Docker Desktop, or: brew install colima docker && colima start --cpu 4 --memory 8"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon not running (open Docker Desktop, or: colima start)"; exit 1; }
command -v ollama >/dev/null || { echo "Ollama missing: brew install ollama (or the Ollama.app), then: ollama serve"; exit 1; }
ollama list | grep -q "huihui_ai/qwen3.5-abliterated:9b" || echo "Model not pulled yet: ollama pull huihui_ai/qwen3.5-abliterated:9b"

python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m i2p build-image
.venv/bin/python -m i2p doctor || true
echo "Next: .venv/bin/python -m i2p verify-tasks   then   .venv/bin/python -m i2p run --runs 3"
