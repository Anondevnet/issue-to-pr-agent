# issue-to-pr-agent

[![CI](https://github.com/Anondevnet/issue-to-pr-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Anondevnet/issue-to-pr-agent/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A $0 coding agent that turns a GitHub issue into a tested pull request with a local 9B model, so you can measure end to end how many real bugs a small open model can fix inside a locked-down Docker sandbox.

## Quickstart

The test suite runs offline with a mocked model; no Docker, Ollama, or API keys needed.

```bash
git clone https://github.com/Anondevnet/issue-to-pr-agent && cd issue-to-pr-agent
python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python -m pytest tests          # mocked model + local runner; real-container tests are opt-in
python -m i2p doctor            # checks Python, Docker, Ollama, disk, and gh before a real run
```

The full benchmark (Docker sandbox + Ollama on an Apple Silicon Mac) is in [Quickstart (Apple Silicon Mac)](#quickstart-apple-silicon-mac).

## Overview

A small coding agent that takes a GitHub issue, reproduces it with a failing test, patches the code, runs the
test suite (up to 3 retries) and prepares a pull request. It runs on **$0**: a local 9B model through Ollama,
every attempt in a locked-down Docker container on an Apple Silicon Mac, and no paid APIs.

The point is the measured number: how many of **20 real issues from my own repositories** a local 9B model
can fix end to end, with a JSON trace for every step.

> Status: harness, task set and tests are done. The results table below gets filled in by the first full run.

## Results

<!-- results:start -->
_Benchmark results pending. The harness, Docker sandbox, scoring, and all 20 tasks are in place, and `i2p verify-tasks` checks that each hidden test fails at the base commit and passes with the reference fix. The full run (20 tasks x 3 runs with a local 9B model) has not been completed yet; run it with the commands in [Quickstart (Apple Silicon Mac)](#quickstart-apple-silicon-mac) and this table is filled in by `scripts/make_table.py`._
<!-- results:end -->

Regenerate with `python scripts/make_table.py runs/<run-id> --readme README.md`.
"Solved" means the agent submitted a patch, a **hidden** test it never saw passes, and the repo's existing
suite has no new failures compared with the base commit. Cost is $0 because the model runs locally.

## How it works

```
issue ─► explore (search_code, read_file) ─► write a failing repro test ─► edit_file patch
      ─► run full suite ─┬─ green ─► finish: branch + PR body ─► (optional) gh pr create
                         └─ red ──► feedback, retry (max 3) ─► give up: patch_failed_tests
```

- **One JSON tool call per turn.** A 9B model is more reliable with a single JSON object than with native
  tool calling. The prompt is rebuilt each turn from the issue, the current phase, the budget and the last 6
  observations, so it stays well inside an 8K context.
- **Test-first is enforced.** The harness rejects source edits until the agent has a test that *fails* on the
  unfixed code. A repro test that passes is rejected as "does not reproduce".
- **Suite check against a baseline.** Some repos have failures that depend on the environment. The harness
  runs the suite once before the agent starts and only counts *new* failures.
- **Caps.** 40 steps, 15 minutes, 3 failed-suite retries, 5 unparseable replies, and 5 identical calls in a
  row per attempt.

### Tools

| Tool | What it does | Runs where |
|---|---|---|
| `list_files`, `search_code`, `read_file` | browse the clone (paths are confined to the repo; `.git` blocked) | host, read only |
| `write_file` | create a **test** file (repro test) | host, tests only |
| `edit_file` | replace one exact, unique snippet | host |
| `run_tests` | `pytest` for one file or the full suite | **Docker sandbox** |
| `git_diff`, `finish`, `give_up` | review and submit | host |

### Sandbox

Each attempt gets a fresh clone (from a local mirror, pinned to the task's base commit) mounted at `/work`
in its own container:

- `--network none`. Model calls are made from the host, so the container needs no network at all.
- `--cpus 2 --memory 2g --memory-swap 2g --pids-limit 256`, and a timeout on every command
- `--read-only` root filesystem with a tmpfs `/tmp`, `--cap-drop ALL`, `no-new-privileges`
- non-root (`--user <your uid>:<gid>`, never 0)
- image `python:3.11-slim` plus the task repos' test dependencies, multi-arch so it builds natively on arm64

Scoring runs in a **second** fresh container on a copy of the agent's final tree, with the hidden test
added.

### Opening PRs (off by default)

Without `--open-pr`, the agent commits to a local branch `i2p/<task>-r<n>-<run>` and writes `pr_body.md`.
With `--open-pr`, only **solved** attempts are pushed and opened, and only after these checks pass:

1. the task repo is `Anondevnet/*` (hard-coded, not configurable)
2. `gh api user` reports `Anondevnet`
3. GitHub reports `Anondevnet` as the repo's owner

## Task set

20 issues, each in `tasks/<id>/`:

- `task.yaml`: repo, pinned base commit, and the issue text written the way a user would report it
- `hidden_test.py`: the scoring test, which the agent never sees
- `fix.patch`: a reference fix

These are **real bugs that exist in my repos at the pinned commits**, found by reviewing the code. They are
not seeded. The issue text was written for this benchmark and has not been filed on GitHub. Each task is
verified with `python -m i2p verify-tasks`: the hidden test fails on the base commit, passes with
`fix.patch`, and the suite shows no new failures. All 20 pass in the Docker sandbox.

| ID | Repo | Difficulty | Area | Issue |
|---|---|---|---|---|
| aiv-001 | ai-video-pipeline | easy | validation | validate_concept_dict accepts beats that aren't a list |
| aiv-002 | ai-video-pipeline | easy | numeric | Beat durations with fractional seconds are truncated |
| aiv-003 | ai-video-pipeline | medium | robustness | A partial or non-dict state.json makes advance() crash with KeyError |
| arag-001 | audit-rag-assistant | easy | string | excerpt() returns more than `width` characters for small widths |
| arag-002 | audit-rag-assistant | easy | parsing | Quoted front-matter values keep their quotes |
| atlas-001 | atlas-agent | easy | string | Report filenames can end in '-' when the title is long |
| cyx-001 | cyberintel-x | easy | parsing | .env lines with `export KEY=value` are loaded under the wrong name |
| cyx-002 | cyberintel-x | medium | regex | Awesome-Hacking rows whose URL contains parentheses are silently dropped |
| osint-001 | osint-dashboard | easy | validation | Unicode digits in ?limit= crash the API proxy with a 500 |
| pmxge-001 | polymarket-x-growth-engine | easy | regex | Validator warns 'no prediction-market anchor' on drafts that quote a percentage |
| pmxge-002 | polymarket-x-growth-engine | medium | regex | Bare domains like polymarket.com/event/... slip past the no-links rule |
| pmxge-003 | polymarket-x-growth-engine | easy | regex | Engagement-bait penalty never fires for posts ending in 'Thoughts?' |
| pmxge-004 | polymarket-x-growth-engine | easy | datetime | reply_fetcher._parse_ts returns naive datetimes for timestamps without an offset |
| tci-001 | telegram-content-intelligence | easy | url | normalize_url doesn't sort query params, so reordered URLs aren't deduped |
| tci-002 | telegram-content-intelligence | easy | url | Trailing slash isn't removed when the URL has a query string |
| tci-003 | telegram-content-intelligence | medium | security | safe_public_https_url accepts shorthand loopback/private IPs like https://127.1/ |
| tci-004 | telegram-content-intelligence | easy | types | _safe_text_list crashes on a set that contains a non-string |
| tci-005 | telegram-content-intelligence | medium | logic | Feed image extraction picks a video from media:content instead of the image |
| trend-001 | trend-intelligence | easy | string | Trend slugs can end in '-' after truncation to 80 chars |
| trend-002 | trend-intelligence | easy | types | to_iso_unix treats booleans as Unix timestamps |

## Quickstart (Apple Silicon Mac)

```bash
# prerequisites: Docker Desktop (or: brew install colima docker && colima start --cpu 4 --memory 8)
#                Ollama (brew install ollama; ollama serve)
ollama pull huihui_ai/qwen3.5-abliterated:9b
./scripts/mac_setup.sh                      # venv, builds the sandbox image, runs `doctor`
.venv/bin/python -m i2p verify-tasks        # all 20 should print PASS
.venv/bin/python -m i2p run --task atlas-001            # one task, one run
.venv/bin/python -m i2p run --runs 3 --run-id qwen9b    # full benchmark: 20 tasks x 3 runs
.venv/bin/python scripts/make_table.py runs/qwen9b --readme README.md
```

## Logs

`runs/<run-id>/<task>/attempt-<n>/`:

- `steps.jsonl`: one line per step, with `step, phase, tool, args (truncated) + digest, prompt_tokens,
  completion_tokens, duration_s, model_duration_s, tool_duration_s, outcome, cost_usd`
- `result.json`: solved, failure_reason, steps, tokens, tool counts, hidden-test and suite results
- `final.diff` and `pr_body.md`

Failure reasons: `no_repro`, `patch_failed_tests`, `hidden_test_failed`, `broke_other_tests`, `stuck_loop`,
`step_limit`, `timeout`, `invalid_model_output`, `model_error`, `gave_up`, `sandbox_error`.

## Development

```bash
python -m pytest tests                                     # mocked model + local runner
I2P_DOCKER_TESTS=1 python -m pytest tests/test_docker_integration.py   # real container checks
```

## Layout

```
i2p/agent.py      agent loop, phases, prompt      i2p/tools.py     tools + path containment
i2p/sandbox.py    Docker / local sandboxes        i2p/runner.py    attempt + hidden-test scoring
i2p/models.py     Ollama / OpenAI-compatible / mock providers
i2p/pr.py         branch, PR body, guarded gh pr create
i2p/tasks.py      task files, mirrors, clones     i2p/verify.py    task-set verification
scripts/make_table.py   README tables            docker/Dockerfile.sandbox
```
