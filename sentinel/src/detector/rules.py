from typing import Dict, Any, Tuple, List
from src.common.config import settings

def score_rules(features: Dict[str, Any]) -> Tuple[float, List[str]]:
    if features.get("is_warming_up", True):
        return 0.0, ["warming up"]

    score = 0.0
    reasons = []

    # 1. z-score of amount
    z_score = features.get("amount_zscore", 0.0)
    if z_score > settings.ZSCORE_THRESHOLD:
        score += min(1.0, z_score / (settings.ZSCORE_THRESHOLD * 2))
        reasons.append(f"amount_zscore z={z_score:.2f} above baseline (threshold {settings.ZSCORE_THRESHOLD})")

    # 2. new merchant burst
    burst = features.get("new_merchant_burst", 0)
    if burst >= settings.NEW_MERCHANT_BURST:
        score = 1.0  # Hard rule, directly sets score to 1.0
        reasons.append(f"new_merchant_burst={burst} in 10s (threshold {settings.NEW_MERCHANT_BURST})")

    # 3. Inter-arrival min
    inter_arrival = features.get("inter_arrival_min", float('inf'))
    if inter_arrival < 0.05:
        score += 0.5
        reasons.append(f"inter_arrival_min={inter_arrival:.3f}s (threshold 0.05)")

    # 4. Action entropy
    entropy = features.get("action_entropy", 1.0)
    rate = features.get("action_rate", 0)
    if entropy < 0.2 and rate > 5:
        score += 0.8
        reasons.append(f"action_entropy={entropy:.2f} (threshold 0.2 with high rate)")

    final_score = min(1.0, score)
    return final_score, reasons
