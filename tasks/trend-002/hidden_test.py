from trend_intelligence.sources.feeds import to_iso_unix


def test_bools_are_not_timestamps():
    assert to_iso_unix(True) is None
    assert to_iso_unix(False) is None


def test_numbers_still_convert():
    assert to_iso_unix(0) == "1970-01-01T00:00:00.000000Z"
    assert to_iso_unix(1.5) == "1970-01-01T00:00:01.500000Z"
    assert to_iso_unix("123") is None
