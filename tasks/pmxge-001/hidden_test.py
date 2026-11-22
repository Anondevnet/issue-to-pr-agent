from pmxge.content.models import Draft
from pmxge.content.validator import validate_draft


def _warn(text):
    return validate_draft(Draft(content_type="question", tweets=[text])).warnings


def test_percentage_counts_as_anchor():
    assert "no explicit prediction-market anchor detected" not in _warn("Trump is trading at 62% today")
    assert "no explicit prediction-market anchor detected" not in _warn("Up to 12.5 % overnight, who sold?")


def test_text_without_anchor_still_warns():
    assert "no explicit prediction-market anchor detected" in _warn("Nice weather in Detroit today")
