import pytest
import uuid
from datetime import datetime, timezone
from src.enforcement.breaker import AuditLog
from src.common.schemas import AgentDecision

def test_audit_log_verify():
    log = AuditLog()
    d1 = AgentDecision(
        decision_id=str(uuid.uuid4()),
        agent_id="a1",
        event_id="e1",
        decision="FREEZE",
        anomaly_score=0.9,
        reasons=["test"],
        timestamp=datetime.now(timezone.utc)
    )
    
    log.append(d1.model_dump(mode='json'))
    assert log.verify() == True
    
    # Tamper
    log.chain[0].record.anomaly_score = 0.5
    assert log.verify() == False
