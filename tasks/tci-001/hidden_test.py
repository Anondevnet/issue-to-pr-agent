from app.dedupe import article_hash, normalize_url


def test_query_params_are_sorted():
    assert normalize_url("https://x.com/a?b=2&a=1") == normalize_url("https://x.com/a?a=1&b=2")
    assert normalize_url("https://x.com/a?b=2&a=1") == "https://x.com/a?a=1&b=2"


def test_hash_matches_for_reordered_query():
    one = {"url": "https://news.example/story?utm=x&id=7", "title": "T"}
    two = {"url": "https://news.example/story?id=7&utm=x#top", "title": "T"}
    assert article_hash(one) == article_hash(two)
