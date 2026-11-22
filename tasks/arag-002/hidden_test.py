from audit_rag.chunk.chunker import parse_front_matter


def test_quoted_values_unquoted():
    meta, body = parse_front_matter('---\ntitle: "Reentrancy: basics"\nlicense: \'MIT\'\n---\nbody')
    assert meta["title"] == "Reentrancy: basics"
    assert meta["license"] == "MIT"
    assert body == "body"


def test_inner_quotes_kept():
    meta, _ = parse_front_matter('---\ntitle: The "safe" pattern\nid: swc-107\n---\nx')
    assert meta["title"] == 'The "safe" pattern'
    assert meta["id"] == "swc-107"
