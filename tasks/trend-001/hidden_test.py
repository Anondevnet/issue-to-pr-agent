from trend_intelligence.trends.identity import slugify


def test_no_trailing_dash_after_truncation():
    s = slugify("a" * 79 + " b")
    assert s == "a" * 79


def test_long_names_bounded():
    s = slugify("Restaking & liquid restaking tokens " * 4)
    assert len(s) <= 80 and not s.endswith("-") and not s.startswith("-")
    assert slugify("AI Agents") == "ai-agents"
