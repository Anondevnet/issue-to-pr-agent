from audit_rag.citations.format import excerpt


def test_small_widths_respected():
    for w in range(0, 6):
        assert len(excerpt("abcdefghij", w)) <= w, w
    assert excerpt("abcdefghij", 2) == "ab"


def test_normal_width_unchanged():
    assert excerpt("one  two   three four", 11) == "one two..."
    assert excerpt("short", 240) == "short"
