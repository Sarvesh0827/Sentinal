import pytest
from datetime import datetime, timezone, timedelta
from src.detector.features import compute_features, update_ewma
from src.common.config import settings

def make_event(amount, ts, merchant="m1", action_type="purchase", agent_id="test_agent"):
    return {
        "agent_id": agent_id,
        "amount": amount,
        "timestamp": ts.isoformat(),
        "merchant": merchant,
        "action_type": action_type
    }

def test_compute_features_warmup():
    now = datetime.now(timezone.utc)
    ev = make_event(10.0, now)
    
    f = compute_features(ev, [])
    assert f["is_warming_up"] == True
    
    history = [make_event(5.0, now - timedelta(seconds=20)) for _ in range(settings.MIN_WARMUP_EVENTS - 1)]
    f = compute_features(ev, history)
    assert f["is_warming_up"] == True
    
    history.append(make_event(5.0, now - timedelta(seconds=15)))
    f = compute_features(ev, history)
    assert f["is_warming_up"] == False

def test_amount_zscore():
    now = datetime.now(timezone.utc)
    # Populate EWMA state
    for _ in range(settings.MIN_WARMUP_EVENTS):
        update_ewma("test_agent", 10.0)
        
    history = [make_event(10.0, now - timedelta(seconds=20)) for _ in range(settings.MIN_WARMUP_EVENTS)]
    ev = make_event(20.0, now) # mean=10, std=0 => zscore very large due to EPS
    
    f = compute_features(ev, history)
    assert f["amount_zscore"] > 1000  # since EPS is 1e-6
