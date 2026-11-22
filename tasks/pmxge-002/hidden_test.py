from pmxge.content.models import Draft
from pmxge.content.validator import validate_draft

LINK = "link in main post body -- links belong in the first reply"


def _errors(text):
    return validate_draft(Draft(content_type="question", tweets=[text])).errors


def test_bare_domain_is_rejected():
    assert LINK in _errors("Odds moved 8 cents. Full breakdown at polymarket.com/event/fed-cut")
    assert LINK in _errors("Market odds mirror Kalshi.io pricing")


def test_decimals_are_not_links():
    assert LINK not in _errors("Yes side at 0.62 with a 12.5% spread. What am I missing?")
    assert LINK in _errors("see https://example.org")
