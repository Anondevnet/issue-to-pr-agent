from aiinf.schemas import REQUIRED_CONCEPT_FIELDS, validate_concept_dict


def _concept(**over):
    d = {f: "x" for f in REQUIRED_CONCEPT_FIELDS}
    d["lane"] = "evergreen"
    d["beats"] = [{"seconds": "0-4"}] * 3
    d.update(over)
    return d


def test_string_beats_rejected():
    assert validate_concept_dict(_concept(beats="intro, middle, end"))
    assert validate_concept_dict(_concept(beats={"a": 1, "b": 2, "c": 3}))


def test_valid_and_short_lists():
    assert validate_concept_dict(_concept()) == []
    assert "need >= 3 beats" in validate_concept_dict(_concept(beats=[{}]))
