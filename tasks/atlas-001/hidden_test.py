from atlas_tools import _slug


def test_truncated_slug_has_no_trailing_dash():
    s = _slug("a" * 59 + " bbb")
    assert s == "a" * 59
    assert not s.endswith("-")


def test_slug_length_and_fallback():
    s = _slug("Solana liquid staking landscape " * 5)
    assert len(s) <= 60 and not s.endswith("-") and not s.startswith("-")
    assert _slug("---") == "report"
