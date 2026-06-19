import uuid
from datetime import datetime, timezone
from src.common.broker import Broker
from src.common.store import Store
from src.common.schemas import AgentDecision
from src.common.config import settings
from src.detector.rules import score_rules
from src.detector.ml_model import ml_scorer
from src.detector.features import compute_features, update_ewma
from src.identity import verify_event_signature

async def run_detection_engine(broker: Broker, store: Store):
    print("Starting detection engine...")
    async for msg in broker.subscribe("agent.actions", group="detector"):
        agent_id = msg["agent_id"]
        tenant_id = msg.get("tenant_id", "default")

        # --- KYA: Signature verification ---
        if not verify_event_signature(msg):
            print(f"[SECURITY] Rejected event from {agent_id} (tenant={tenant_id}): invalid signature")
            # Publish a security-rejection decision without scoring
            rejection = AgentDecision(
                decision_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                agent_id=agent_id,
                event_id=msg.get("event_id", "unknown"),
                decision="FREEZE",
                anomaly_score=1.0,
                reasons=["invalid_signature: event rejected by KYA identity check"],
                timestamp=datetime.now(timezone.utc),
            )
            await broker.publish("agent.decisions", rejection.model_dump(mode='json'))
            continue

        # Get history (excluding current msg which is not in store yet)
        history = await store.get_window(tenant_id, agent_id, settings.MAX_WINDOW_SECONDS)

        features = compute_features(msg, history)

        rule_score, reasons = score_rules(features)

        # Scorer B - ML model
        ml_score = ml_scorer.score(agent_id, features, features.get("is_warming_up", True))

        anomaly_score = max(rule_score, ml_score)

        if ml_score > 0.6 and "ml_anomaly" not in reasons:
            reasons.append(f"ML anomaly score: {ml_score:.2f}")

        decision_str = "FREEZE" if anomaly_score >= settings.FREEZE_THRESHOLD else "OK"

        # Trust score decay / recovery
        current_trust = await store.get_trust_score(tenant_id, agent_id)
        if decision_str == "FREEZE":
            new_trust = max(0.0, current_trust - 0.2)
        elif anomaly_score == 0.0:
            new_trust = min(1.0, current_trust + 0.05)
        else:
            new_trust = current_trust
        await store.set_trust_score(tenant_id, agent_id, new_trust)

        decision = AgentDecision(
            decision_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            agent_id=agent_id,
            event_id=msg["event_id"],
            decision=decision_str,
            anomaly_score=anomaly_score,
            reasons=reasons,
            features=features,
            timestamp=datetime.now(timezone.utc),
            trust_score=new_trust,
        )

        await broker.publish("agent.decisions", decision.model_dump(mode='json'))

        # Update state
        await store.append_window(tenant_id, agent_id, msg)
        update_ewma(f"{tenant_id}:{agent_id}", msg.get("amount", 0.0))
