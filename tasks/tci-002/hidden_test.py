from app.dedupe import normalize_url


def test_trailing_slash_removed_with_query():
    assert normalize_url("https://x.com/a/?q=1") == normalize_url("https://x.com/a?q=1")
    assert normalize_url("https://x.com/a/?q=1") == "https://x.com/a?q=1"


def test_plain_trailing_slash_still_removed():
    assert normalize_url("https://x.com/a/") == "https://x.com/a"
    assert normalize_url("https://x.com/a/#frag") == "https://x.com/a"
