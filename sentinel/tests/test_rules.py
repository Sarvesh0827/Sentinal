from src.detector.rules import score_rules

def test_score_rules_warmup():
    f = {"is_warming_up": True}
    score, reasons = score_rules(f)
    assert score == 0.0
    assert "warming up" in reasons

def test_score_rules_merchant_burst():
    f = {
        "is_warming_up": False,
        "new_merchant_burst": 4
    }
    score, reasons = score_rules(f)
    assert score == 1.0
    assert any("new_merchant_burst" in r for r in reasons)

def test_score_rules_zscore():
    f = {
        "is_warming_up": False,
        "amount_zscore": 5.0
    }
    score, reasons = score_rules(f)
    assert score > 0.0
    assert any("amount_zscore" in r for r in reasons)
