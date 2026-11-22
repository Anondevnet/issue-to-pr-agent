"""Pull one JSON tool call out of a small model's reply (fences, prose, trailing junk)."""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ParseError(ValueError):
    pass


def _balanced_objects(text: str):
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start : i + 1]


def parse_tool_call(text: str) -> tuple[str, dict]:
    if not text or not text.strip():
        raise ParseError("empty reply")
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE_RE.findall(text)]
    candidates += list(_balanced_objects(text))
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        tool = obj.get("tool") or obj.get("name") or obj.get("action")
        args = obj.get("args", obj.get("arguments", obj.get("parameters", {})))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if isinstance(tool, str) and tool.strip():
            return tool.strip(), args if isinstance(args, dict) else {}
    raise ParseError("no JSON object with a 'tool' field found")
