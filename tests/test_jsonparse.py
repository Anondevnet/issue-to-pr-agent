import pytest

from i2p.jsonparse import ParseError, parse_tool_call


def test_plain_json():
    assert parse_tool_call('{"tool": "read_file", "args": {"path": "a.py"}}') == ("read_file", {"path": "a.py"})


def test_fenced_and_prose():
    text = 'Sure!\n```json\n{"thought": "x", "tool": "git_diff", "args": {}}\n```\nthanks'
    assert parse_tool_call(text) == ("git_diff", {})


def test_braces_inside_strings():
    text = 'ok {"tool": "write_file", "args": {"path": "tests/t.py", "content": "d = {\\"a\\": 1}\\n"}} trailing'
    tool, args = parse_tool_call(text)
    assert tool == "write_file" and args["content"] == 'd = {"a": 1}\n'


def test_alt_keys_and_string_args():
    assert parse_tool_call('{"name": "run_tests", "arguments": "{\\"target\\": \\"t.py\\"}"}') == \
        ("run_tests", {"target": "t.py"})


@pytest.mark.parametrize("bad", ["", "no json here", '{"args": {}}', "[1, 2]"])
def test_rejects(bad):
    with pytest.raises(ParseError):
        parse_tool_call(bad)
