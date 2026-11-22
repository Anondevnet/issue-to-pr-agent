from app.intelligence.models import _safe_text_list


def test_mixed_set_is_filtered_not_crashing():
    assert _safe_text_list({"b", 1, "a"}) == ("a", "b")
    assert _safe_text_list(frozenset({2.5, "z", None})) == ("z",)


def test_list_behaviour_unchanged():
    assert _safe_text_list(["b", 1, "a", "b"]) == ("b", "a")
