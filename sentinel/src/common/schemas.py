from pydantic import BaseModel, Field
from typing import Literal, List, Optional, Dict, Any
from datetime import datetime

class AgentAction(BaseModel):
    event_id: str
    tenant_id: str = "default"
    agent_id: str
    action_type: str
    merchant: str
    amount: float
    currency: str = "USD"
    timestamp: datetime
    trace_id: str
    signature: Optional[str] = None

class AgentDecision(BaseModel):
    decision_id: str
    tenant_id: str = "default"
    agent_id: str
    event_id: str
    decision: Literal["OK", "FREEZE"]
    anomaly_score: float
    reasons: List[str]
    features: Optional[Dict[str, Any]] = None
    timestamp: datetime
    trust_score: float = 1.0

class AgentAuditRecord(BaseModel):
    seq: int
    prev_hash: str
    record: AgentDecision
    hash: str
