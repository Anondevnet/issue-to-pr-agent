from pmxge.content.scorer import score_reply_potential


def test_trailing_thoughts_is_bait():
    r = score_reply_potential("The election odds moved 12% overnight on thin liquidity. Thoughts?")
    assert r.breakdown.get("engagement_bait") == -30.0
    assert "reads as engagement bait" in r.warnings


def test_trailing_agree_is_bait_case_insensitive():
    r = score_reply_potential("Fed cut odds are mispriced at 40 cents. AGREE?  ")
    assert r.breakdown.get("engagement_bait") == -30.0


def test_thoughts_mid_sentence_is_not_bait():
    r = score_reply_potential("My thoughts? The base rate says 30%, the book says 45%. What am I missing")
    assert "engagement_bait" not in r.breakdown
