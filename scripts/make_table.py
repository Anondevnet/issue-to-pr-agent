#!/usr/bin/env python3
"""Build the README results tables from runs/*/<task>/attempt-*/result.json.

Usage:
  python scripts/make_table.py runs/20261123-090000            # print markdown
  python scripts/make_table.py runs/* --readme README.md        # replace the block between markers
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

START, END = "<!-- results:start -->", "<!-- results:end -->"


def load_results(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        for f in sorted(Path(p).rglob("result.json")):
            out.append(json.loads(f.read_text()))
    return out


def _fmt_min(seconds: float) -> str:
    return f"{seconds / 60:.1f}"


def build_tables(results: list[dict]) -> str:
    if not results:
        return "_No results yet._\n"
    lines: list[str] = []
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_model[r.get("model", "?")].append(r)

    lines += ["| Model | Tasks | Runs | Solved / N (per run) | Success % (mean ± sd) | Avg min / task | "
              "Avg tool calls | Avg tokens / task | Broke other tests | Cost |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for model, rs in sorted(by_model.items()):
        tasks = sorted({r["task_id"] for r in rs})
        runs: dict[tuple, list[dict]] = defaultdict(list)
        for r in rs:
            runs[(r.get("run_id"), r.get("attempt"))].append(r)
        per_run = [sum(x["solved"] for x in v) for v in runs.values()]
        n = len(tasks)
        rates = [100 * s / n for s in per_run]
        sd = statistics.pstdev(rates) if len(rates) > 1 else 0.0
        solved_str = ", ".join(f"{s}/{n}" for s in per_run)
        avg_min = _fmt_min(statistics.mean(r.get("wall_s", 0) for r in rs))
        avg_calls = statistics.mean(sum((r.get("tool_counts") or {}).values()) for r in rs)
        avg_tok = statistics.mean((r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0) for r in rs)
        broke = sum(bool(r.get("broke_other_tests")) for r in rs)
        cost = sum(float(r.get("cost_usd") or 0) for r in rs)
        lines.append(f"| {model} | {n} | {len(per_run)} | {solved_str} | {statistics.mean(rates):.0f}% ± {sd:.0f} | "
                     f"{avg_min} | {avg_calls:.1f} | {avg_tok:,.0f} | {broke} | ${cost:.2f} |")

    failed = [r for r in results if not r["solved"]]
    lines += ["", "**Failure reasons** (all unsolved attempts)", "",
              "| Reason | Attempts | Share of failures |", "|---|---|---|"]
    counts = Counter(r.get("failure_reason") or "unknown" for r in failed)
    for reason, c in counts.most_common():
        lines.append(f"| {reason} | {c} | {100 * c / max(len(failed), 1):.0f}% |")
    if not failed:
        lines.append("| (none) | 0 | 0% |")

    lines += ["", "**Per task**", "", "| Task | Repo | Difficulty | Solved runs | Avg min | Last failure reason |",
              "|---|---|---|---|---|---|"]
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_task[r["task_id"]].append(r)
    for tid, rs in sorted(by_task.items()):
        last_fail = next((r.get("failure_reason") for r in reversed(rs) if not r["solved"]), "") or ""
        lines.append(f"| {tid} | {rs[0].get('repo', '').split('/')[-1]} | {rs[0].get('difficulty', '')} | "
                     f"{sum(r['solved'] for r in rs)}/{len(rs)} | {_fmt_min(statistics.mean(r.get('wall_s', 0) for r in rs))} "
                     f"| {last_fail} |")
    return "\n".join(lines) + "\n"


def replace_block(readme: Path, table: str) -> None:
    text = readme.read_text()
    if START not in text or END not in text:
        raise SystemExit(f"{readme} has no {START} ... {END} block")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    readme.write_text(f"{head}{START}\n{table}{END}{tail}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="run directories (or a parent of several)")
    ap.add_argument("--readme", help="README to update in place")
    args = ap.parse_args(argv)
    table = build_tables(load_results(args.runs))
    if args.readme:
        replace_block(Path(args.readme), table)
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
