from aiinf.schemas import estimate_beat_seconds


def test_fractional_ranges():
    assert estimate_beat_seconds({"seconds": "4.5-8"}) == 3.5
    assert estimate_beat_seconds({"seconds": "0-2.75"}) == 2.75


def test_whole_and_bad_ranges():
    assert estimate_beat_seconds({"seconds": "0-4"}) == 4
    assert estimate_beat_seconds({"seconds": "abc"}) == 0
