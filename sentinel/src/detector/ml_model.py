from sklearn.ensemble import IsolationForest
import numpy as np
from typing import List, Dict, Any

class MLScorer:
    def __init__(self):
        self.models: Dict[str, IsolationForest] = {}
        self.warmup_buffers: Dict[str, List[List[float]]] = {}
        
    def _extract_vector(self, features: Dict[str, Any]) -> List[float]:
        return [
            features.get("spend_velocity", 0.0),
            float(features.get("action_rate", 0)),
            features.get("amount_zscore", 0.0),
            float(features.get("new_merchant_burst", 0)),
            features.get("action_entropy", 0.0)
        ]

    def score(self, agent_id: str, features: Dict[str, Any], is_warming_up: bool) -> float:
        vec = self._extract_vector(features)
        
        if is_warming_up:
            if agent_id not in self.warmup_buffers:
                self.warmup_buffers[agent_id] = []
            self.warmup_buffers[agent_id].append(vec)
            return 0.0
            
        # If model not trained yet, train it now
        if agent_id not in self.models:
            if agent_id in self.warmup_buffers and len(self.warmup_buffers[agent_id]) > 0:
                clf = IsolationForest(n_estimators=50, contamination=0.05, random_state=42)
                X = np.array(self.warmup_buffers[agent_id])
                # add some noise to avoid identical values failure
                X += np.random.normal(0, 1e-5, X.shape)
                clf.fit(X)
                self.models[agent_id] = clf
                del self.warmup_buffers[agent_id]
            else:
                return 0.0

        clf = self.models[agent_id]
        X_test = np.array([vec])
        # decision_function gives score > 0 for normal, < 0 for anomaly.
        # We want score in [0,1] where 1 is highly anomalous.
        raw_score = clf.decision_function(X_test)[0]
        # raw_score is typically between -0.5 and 0.5. Let's map it:
        # > 0 (normal) -> ~0.0
        # < 0 (anomaly) -> scale up to 1.0
        
        if raw_score >= 0:
            return 0.0
        else:
            return min(1.0, abs(raw_score) * 2.0)

ml_scorer = MLScorer()
