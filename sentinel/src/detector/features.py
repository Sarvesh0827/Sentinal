import numpy as np
import math
from typing import Dict, Any, List
from datetime import datetime
from src.common.config import settings

EPS = 1e-6

class EWMABaseline:
    def __init__(self, alpha=0.1):
        self.alpha = alpha
        self.mean = 0.0
        self.var = 0.0
        self.initialized = False

    def update(self, value: float):
        if not self.initialized:
            self.mean = value
            self.var = 0.0
            self.initialized = True
        else:
            diff = value - self.mean
            self.mean += self.alpha * diff
            self.var = (1 - self.alpha) * (self.var + self.alpha * diff ** 2)

    @property
    def std(self):
        return math.sqrt(self.var)

ewma_state: Dict[str, EWMABaseline] = {}

def update_ewma(agent_id: str, amount: float):
    if agent_id not in ewma_state:
        ewma_state[agent_id] = EWMABaseline()
    ewma_state[agent_id].update(amount)

def compute_features(current_event: dict, history: List[dict]) -> Dict[str, Any]:
    """
    Computes features for the current event given the rolling window history (which excludes the current event).
    """
    agent_id = current_event.get("agent_id")
    features = {
        "is_warming_up": len(history) < settings.MIN_WARMUP_EVENTS,
        "spend_velocity": 0.0,
        "action_rate": 0,
        "amount_zscore": 0.0,
        "new_merchant_burst": 0,
        "action_entropy": 0.0,
        "inter_arrival_min": float('inf'),
        "amount": current_event.get("amount", 0.0)
    }

    if not history:
        features["spend_velocity"] = current_event.get("amount", 0.0)
        features["action_rate"] = 1
        features["new_merchant_burst"] = 1
        return features

    def get_ts(ev):
        ts_str = ev["timestamp"]
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str).timestamp()

    current_ts = get_ts(current_event)
    history_ts = [get_ts(ev) for ev in history]
    
    recent_history = [ev for ev, ts in zip(history, history_ts) if current_ts - ts <= 10.0]
    recent_merchants = set(ev["merchant"] for ev in recent_history)
    older_merchants = set(ev["merchant"] for ev, ts in zip(history, history_ts) if current_ts - ts > 10.0)
    
    new_merchants_in_recent = recent_merchants - older_merchants
    if current_event["merchant"] not in older_merchants and current_event["merchant"] not in recent_merchants:
        new_merchants_in_recent.add(current_event["merchant"])
        
    features["new_merchant_burst"] = len(new_merchants_in_recent)
    features["spend_velocity"] = sum(ev.get("amount", 0.0) for ev in recent_history) + current_event.get("amount", 0.0)
    features["action_rate"] = len(recent_history) + 1

    if agent_id in ewma_state and ewma_state[agent_id].initialized:
        mean_amt = ewma_state[agent_id].mean
        std_amt = ewma_state[agent_id].std
        z = (current_event.get("amount", 0.0) - mean_amt) / max(std_amt, EPS)
        features["amount_zscore"] = float(z)
    else:
        features["amount_zscore"] = 0.0

    all_action_types = [ev.get("action_type") for ev in history] + [current_event.get("action_type")]
    counts = {}
    for at in all_action_types:
        counts[at] = counts.get(at, 0) + 1
    
    total = len(all_action_types)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    features["action_entropy"] = float(entropy)

    all_ts = sorted(history_ts + [current_ts])
    if len(all_ts) > 1:
        diffs = np.diff(all_ts)
        features["inter_arrival_min"] = float(np.min(diffs))

    return features
