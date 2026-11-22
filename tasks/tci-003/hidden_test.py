from app.security import safe_public_https_url


def test_shorthand_private_ipv4_rejected():
    for url in ("https://127.1/latest", "https://0x7f.0.0.1/", "https://10.1/x.png", "https://0177.0.0.1/"):
        assert safe_public_https_url(url) is None, url


def test_public_hosts_still_allowed():
    assert safe_public_https_url("https://images.example.com/a.png") == "https://images.example.com/a.png"
    assert safe_public_https_url("https://8.8.8.8/a.png") == "https://8.8.8.8/a.png"
    assert safe_public_https_url("https://127.0.0.1/") is None
