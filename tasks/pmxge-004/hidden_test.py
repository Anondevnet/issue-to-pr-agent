from datetime import datetime, timedelta, timezone

from pmxge.monitoring.reply_fetcher import _parse_ts


def test_naive_timestamp_is_utc():
    ts = _parse_ts("2026-11-22T10:00:00")
    assert ts.tzinfo is not None
    assert ts == datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)


def test_offsets_preserved():
    ts = _parse_ts("2026-11-22T10:00:00+02:00")
    assert ts.utcoffset() == timedelta(hours=2)
    assert _parse_ts("2026-11-22T10:00:00Z") == datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
