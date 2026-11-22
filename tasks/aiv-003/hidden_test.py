import json

from aiinf.state import advance, load_state


def test_partial_state_gets_defaults(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"schema_version": 1, "last_stage": "planned"}))
    st = load_state(p)
    assert st["last_stage"] == "planned"
    assert st["concepts"] == {} and st["history"] == []
    advance(st, "c1", "scripted")
    assert st["concepts"]["c1"]["last_stage"] == "scripted"


def test_non_dict_state_falls_back(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("[]")
    st = load_state(p)
    assert isinstance(st, dict) and st["concepts"] == {}
