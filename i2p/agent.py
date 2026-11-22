"""The agent loop: read issue -> explore -> failing repro test -> patch -> suite (<= N retries) -> finish.

Each turn the model sees a compact, freshly built prompt (issue, phase, budget, file list,
the last few observations) instead of an ever-growing chat. That keeps a 9B local model
inside an 8K context. Tool calls are a single JSON object per reply.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .config import AgentConfig
from .jsonparse import ParseError, parse_tool_call
from .models import ModelError, Provider
from .steplog import StepLogger
from .testrun import TestRun, new_failures, tail
from .tools import ToolBox, ToolError, is_test_path

SYSTEM_PROMPT = """You are a careful software engineer fixing ONE GitHub issue in a Python repository.
You work through tools. Reply with exactly ONE JSON object per turn and nothing else:
{"thought": "<one short sentence>", "tool": "<tool name>", "args": {...}}

Tools:
- list_files {"path": "."}
- search_code {"pattern": "<python regex>", "path": "."}
- read_file {"path": "<file>", "start": 1, "end": 80}
- write_file {"path": "tests/test_issue_repro.py", "content": "<full file>"}   (TEST files only)
- edit_file {"path": "<file>", "old": "<exact existing text>", "new": "<replacement>"}
- run_tests {"target": "tests/test_issue_repro.py"}   (omit target to run the full suite)
- git_diff {}
- finish {"title": "<PR title>", "summary": "<what was wrong and how you fixed it>"}
- give_up {"reason": "<why>"}

Workflow (the harness enforces it):
1. Find the relevant code with search_code / read_file.
2. Write a SMALL pytest test that reproduces the issue (write_file), then run_tests on it. It must FAIL before the fix.
3. Fix the source with edit_file. "old" must be copied exactly from the file (no line numbers), with enough lines to be unique.
4. run_tests with no target to run the full suite. Fix anything you broke.
5. finish with a PR title and summary.
Keep changes minimal. Do not edit unrelated files. Do not delete or weaken existing tests."""

PHASE_HELP = {
    "reproduce": "Locate the code, then write a failing test that reproduces the issue and run it.",
    "patch": "Your repro test fails as expected. Now fix the SOURCE with edit_file, then run the full suite (run_tests with no target).",
    "finish": "The full suite passes and your repro test passes. Call finish with a PR title and summary.",
}

READ_ONLY_TOOLS = {"list_files", "search_code", "read_file", "git_diff"}
NEXT_HINT = {
    "reproduce": "read_file the relevant source file, or write_file a failing test in tests/ and run_tests on it.",
    "patch": "edit_file the source to fix the bug, then run_tests with no target.",
    "finish": "call finish with a PR title and summary.",
}

TOOLS = {"list_files", "search_code", "read_file", "write_file", "edit_file", "run_tests", "git_diff",
         "finish", "give_up"}


@dataclass
class TaskContext:
    task_id: str
    repo: str
    title: str
    body: str
    import_roots: str = "."
    file_overview: str = ""


@dataclass
class AttemptOutcome:
    submitted: bool
    failure_reason: str | None
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_s: float = 0.0
    repro_test: str | None = None
    repro_confirmed: bool = False
    edited_files: list[str] = field(default_factory=list)
    suite_runs: int = 0
    failed_suite_runs: int = 0
    pr_title: str = ""
    pr_summary: str = ""
    tool_counts: dict[str, int] = field(default_factory=dict)


class Agent:
    def __init__(self, cfg: AgentConfig, provider: Provider, tools: ToolBox, logger: StepLogger,
                 baseline: TestRun, clock=time.monotonic):
        self.cfg = cfg
        self.provider = provider
        self.tools = tools
        self.log = logger
        self.baseline = baseline
        self.clock = clock
        self.history: list[str] = []
        self.phase = "reproduce"
        self.repro_test: str | None = None
        self.repro_confirmed = False
        self.suite_runs = 0
        self.failed_suite_runs = 0
        self.suite_green = False
        self.edits_since_suite = False
        self.parse_failures = 0
        self.tool_counts: dict[str, int] = {}
        self.finish_nudges = 0
        self.last_call: str | None = None
        self.repeat_count = 0

    # -- prompt ----------------------------------------------------------------
    def build_messages(self, ctx: TaskContext, step: int) -> list[dict[str, str]]:
        source_edits = sorted(f for f in self.tools.edited_files if not is_test_path(f))
        retries_left = self.cfg.max_retries - max(0, self.failed_suite_runs - 0)
        parts = [
            f"ISSUE ({ctx.repo}): {ctx.title}\n{ctx.body.strip()}",
            f"Python import roots (PYTHONPATH): {ctx.import_roots}",
        ]
        if ctx.file_overview:
            parts.append("Repository files:\n" + ctx.file_overview)
        parts.append(
            f"PHASE: {self.phase.upper()} - {PHASE_HELP[self.phase]}\n"
            f"Repro test: {self.repro_test or 'none yet'}{' (confirmed failing)' if self.repro_confirmed else ''}\n"
            f"Source files edited: {', '.join(source_edits) or 'none'}\n"
            f"Budget: step {step}/{self.cfg.max_steps}, failed-suite retries left: {max(retries_left, 0)}"
        )
        if self.history:
            parts.append("Recent steps (oldest first):\n" + "\n\n".join(self.history[-self.cfg.history_turns:]))
        parts.append("Reply with ONE JSON object.")
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}]

    def remember(self, step: int, tool: str, args: dict, observation: str) -> None:
        shown_args = {k: (v if not isinstance(v, str) or len(v) < 160 else v[:160] + "...") for k, v in args.items()}
        obs = tail(observation, self.cfg.max_observation_chars) if len(observation) > self.cfg.max_observation_chars \
            else observation
        self.history.append(f"[step {step}] {tool} {json.dumps(shown_args)}\n-> {obs}")

    # -- suite evaluation ----------------------------------------------------
    def _run_suite_check(self) -> tuple[bool, str]:
        self.suite_runs += 1
        self.edits_since_suite = False
        res, suite = self.tools.run_tests(None)
        broken = new_failures(suite, self.baseline)
        repro_ok = True
        repro_note = ""
        if self.repro_test:
            rres, rrun = self.tools.run_tests(self.repro_test)
            repro_ok = rrun.passed
            if not repro_ok:
                repro_note = f"\nYour repro test {self.repro_test} still FAILS:\n{tail(rrun.output, 700)}"
        if suite.timed_out:
            broken = broken or {"<suite timed out>"}
        if suite.collection_error and not self.baseline.collection_error and not suite.failed:
            broken = broken or {"<collection error>"}
        ok = not broken and repro_ok
        if ok:
            self.suite_green = True
            self.phase = "finish"
            return True, "Full suite: no new failures compared to the original code, and the repro test passes."
        self.failed_suite_runs += 1
        msg = ""
        if broken:
            msg = "Full suite has NEW failures (not failing before your change): " + ", ".join(sorted(broken)[:8])
            msg += "\n" + tail(suite.output, 900)
        return False, (msg + repro_note).strip()

    # -- one tool call -----------------------------------------------------------
    def dispatch(self, tool: str, args: dict, step: int) -> tuple[str, str, dict]:
        """Returns (outcome, observation, extra-log-fields)."""
        t = self.tools
        if tool not in TOOLS:
            return "bad_tool", f"Unknown tool {tool!r}. Valid tools: {', '.join(sorted(TOOLS))}.", {}
        if tool == "list_files":
            r = t.list_files(args.get("path", "."))
            return "ok", r.text, {}
        if tool == "search_code":
            r = t.search_code(args.get("pattern", ""), args.get("path", "."))
            return "ok", r.text, {}
        if tool == "read_file":
            r = t.read_file(args.get("path", ""), args.get("start", 1), args.get("end"))
            return "ok", r.text, {}
        if tool == "git_diff":
            return "ok", t.git_diff().text, {}
        if tool == "write_file":
            r = t.write_file(args.get("path", ""), args.get("content", ""))
            path = r.data["path"]
            if not self.repro_confirmed:
                self.repro_test = path
            return "ok", r.text + (". Now run it with run_tests." if not self.repro_confirmed else ""), {}
        if tool == "edit_file":
            path = args.get("path", "")
            target_rel = t.rel(t.resolve(path)) if path else ""
            if target_rel and not is_test_path(target_rel) and not self.repro_confirmed \
                    and step <= self.cfg.max_repro_steps:
                if self.repro_test:
                    hint = (f"Run your repro test first: {{\"tool\": \"run_tests\", \"args\": "
                            f"{{\"target\": \"{self.repro_test}\"}}}}. It must FAIL before you edit the source.")
                else:
                    hint = "Write a failing repro test first (write_file tests/test_issue_repro.py), run it, then edit."
                return "rejected", hint, {}
            r = t.edit_file(path, args.get("old", ""), args.get("new", ""))
            if not r.data["is_test"]:
                self.edits_since_suite = True
                self.suite_green = False
                if self.phase == "finish":
                    self.phase = "patch"
                if self.phase == "reproduce":  # repro deadline passed; allow patching without one
                    self.phase = "patch"
            return "ok", r.text + ". Next: run_tests with no target to run the full suite.", {}
        if tool == "run_tests":
            target = args.get("target") or None
            if target is None and self.repro_test and not self.repro_confirmed:
                target = self.repro_test  # check the repro first; the suite comes after a patch
            if target is None:
                if not [f for f in t.edited_files if not is_test_path(f)]:
                    res, run = t.run_tests(None)
                    return "ok" if run.passed else "tests_failed", res.text + \
                        "\n(Reminder: you have not changed any source file yet.)", {"exit_code": run.exit_code}
                ok, msg = self._run_suite_check()
                return ("suite_green" if ok else "suite_failed"), msg, {"suite_ok": ok}
            res, run = t.run_tests(target)
            node = str(target).split("::", 1)[0]
            extra = {"exit_code": run.exit_code}
            if self.repro_test and node == self.repro_test and not self.repro_confirmed:
                if run.exit_code == 1 and run.failed:
                    self.repro_confirmed = True
                    self.phase = "patch"
                    return "repro_confirmed", res.text + "\nGood: the test fails, so it reproduces the issue. " \
                        "Now fix the source with edit_file.", extra
                if run.passed:
                    return "repro_passes", res.text + "\nYour test PASSED on the unfixed code, so it does not " \
                        "reproduce the issue. Rewrite it to assert the behaviour the issue expects.", extra
                return "repro_error", res.text + "\nThe test could not run (syntax/import error?). Fix the test.", \
                    extra
            return ("ok" if run.passed else "tests_failed"), res.text, extra
        if tool == "finish":
            if not [f for f in t.edited_files if not is_test_path(f)]:
                return "rejected", "You have not changed any source file. Fix the issue before finishing.", {}
            if not self.suite_green or self.edits_since_suite:
                ok, msg = self._run_suite_check()
                if not ok:
                    return "suite_failed", "Cannot finish yet. " + msg, {"suite_ok": False}
            self._title = str(args.get("title") or "").strip()
            self._summary = str(args.get("summary") or "").strip()
            return "finished", "finished", {}
        if tool == "give_up":
            return "gave_up", str(args.get("reason", "")), {}
        raise AssertionError(tool)  # pragma: no cover

    # -- main loop ---------------------------------------------------------------
    def run(self, ctx: TaskContext) -> AttemptOutcome:
        t_start = self.clock()
        self._title, self._summary = "", ""
        reason: str | None = None
        submitted = False
        step = 0
        while True:
            if step >= self.cfg.max_steps:
                reason = "step_limit"
                break
            if self.clock() - t_start > self.cfg.wall_clock_s:
                reason = "timeout"
                break
            if self.failed_suite_runs > self.cfg.max_retries:
                reason = "patch_failed_tests"
                break
            step += 1
            messages = self.build_messages(ctx, step)
            t0 = self.clock()
            try:
                reply = self.provider.chat(messages)
            except ModelError as exc:
                self.log.log(step=step, phase=self.phase, tool="<model>", outcome="model_error",
                             duration_s=self.clock() - t0, observation=str(exc), error=str(exc)[:300])
                reason = "model_error"
                break
            model_s = self.clock() - t0
            try:
                tool, args = parse_tool_call(reply.text)
            except ParseError as exc:
                self.parse_failures += 1
                obs = f"Your reply was not a valid JSON tool call ({exc}). Reply with ONE JSON object like " \
                      '{"thought": "...", "tool": "read_file", "args": {"path": "x.py"}}'
                self.history.append(f"[step {step}] (invalid reply) {reply.text[:200]!r}\n-> {obs}")
                self.log.log(step=step, phase=self.phase, tool="<invalid>", outcome="parse_error",
                             duration_s=model_s, prompt_tokens=reply.prompt_tokens,
                             completion_tokens=reply.completion_tokens, observation=obs,
                             model_duration_s=round(model_s, 3))
                if self.parse_failures >= self.cfg.max_parse_failures:
                    reason = "invalid_model_output"
                    break
                continue
            self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1
            call_key = json.dumps([tool, args], sort_keys=True, default=str)
            self.repeat_count = self.repeat_count + 1 if call_key == self.last_call else 0
            self.last_call = call_key
            t1 = self.clock()
            try:
                if self.repeat_count and (tool in READ_ONLY_TOOLS or tool == "edit_file"):
                    outcome, extra = "repeated_call", {}
                    obs = ("You already made this exact call and its result is in the recent steps"
                           + (" (the edit was NOT applied again)" if tool == "edit_file" else "")
                           + ". Do something different: " + NEXT_HINT[self.phase])
                else:
                    outcome, obs, extra = self.dispatch(tool, args, step)
            except ToolError as exc:
                outcome, obs, extra = "tool_error", f"ERROR: {exc}", {}
            except Exception as exc:  # sandbox/infra problems should not look like model mistakes
                self.log.log(step=step, phase=self.phase, tool=tool, outcome="sandbox_error", args=args,
                             duration_s=self.clock() - t0, prompt_tokens=reply.prompt_tokens,
                             completion_tokens=reply.completion_tokens, observation=str(exc), error=str(exc)[:300])
                reason = "sandbox_error"
                break
            tool_s = self.clock() - t1
            self.log.log(step=step, phase=self.phase, tool=tool, outcome=outcome, args=args,
                         duration_s=self.clock() - t0, prompt_tokens=reply.prompt_tokens,
                         completion_tokens=reply.completion_tokens, observation=obs,
                         model_duration_s=round(model_s, 3), tool_duration_s=round(tool_s, 3), **extra)
            self.remember(step, tool, args, obs)
            if outcome == "finished":
                submitted = True
                break
            if outcome == "gave_up":
                reason = "gave_up"
                break
            if self.repeat_count >= self.cfg.max_repeats:
                reason = "stuck_loop"
                break
            if self.phase == "finish" and tool != "finish":
                self.finish_nudges += 1
                if self.finish_nudges >= 3:  # suite is green; don't let a small model wander off
                    submitted = True
                    break
        if not submitted and reason is None:  # pragma: no cover - defensive
            reason = "unknown"
        if not submitted and not self.repro_confirmed and reason in ("step_limit", "timeout", "gave_up",
                                                                     "invalid_model_output"):
            reason = "no_repro" if reason != "invalid_model_output" else reason
        return AttemptOutcome(
            submitted=submitted,
            failure_reason=None if submitted else reason,
            steps=step,
            prompt_tokens=self.log.prompt_tokens,
            completion_tokens=self.log.completion_tokens,
            duration_s=self.clock() - t_start,
            repro_test=self.repro_test,
            repro_confirmed=self.repro_confirmed,
            edited_files=sorted(self.tools.edited_files | self.tools.created_tests),
            suite_runs=self.suite_runs,
            failed_suite_runs=self.failed_suite_runs,
            pr_title=self._title,
            pr_summary=self._summary,
            tool_counts=dict(self.tool_counts),
        )
