import pytest

import server


@pytest.mark.parametrize("query", ["limit=%C2%B2", "offset=%E2%91%A0", "limit=%D9%A3"])
def test_unicode_digits_are_rejected_with_400(query):
    with pytest.raises(server.DashboardError) as info:
        server.normalize_query(query)
    assert info.value.status == 400


def test_ascii_digits_ok():
    assert server.normalize_query("limit=50&offset=0") == "limit=50&offset=0"
