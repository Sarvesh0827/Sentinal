import json
import hashlib
import asyncio
from src.common.broker import Broker
from src.common.store import Store
from src.common.schemas import AgentAuditRecord
import httpx

class AuditLog:
    def __init__(self):
        self.chain: list[AgentAuditRecord] = []

    def append(self, record_dict: dict):
        seq = len(self.chain)
        prev_hash = self.chain[-1].hash if self.chain else "0" * 64

        canonical = json.dumps(record_dict, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256((prev_hash + canonical).encode()).hexdigest()

        audit_record = AgentAuditRecord(
            seq=seq,
            prev_hash=prev_hash,
            record=record_dict,
            hash=h
        )
        self.chain.append(audit_record)

    def verify(self) -> bool:
        for i, rec in enumerate(self.chain):
            prev_hash = self.chain[i-1].hash if i > 0 else "0" * 64
            if rec.prev_hash != prev_hash:
                return False
            canonical = json.dumps(rec.record.model_dump(mode='json'), sort_keys=True, separators=(",", ":"))
            h = hashlib.sha256((prev_hash + canonical).encode()).hexdigest()
            if rec.hash != h:
                return False
        return True

audit_log = AuditLog()


async def execute_webhook(tenant_id: str, agent_id: str, reasons: list[str], url: str):
    """Notify an external wallet provider (or Discord/Slack) to suspend the agent."""
    print(f"[WEBHOOK] tenant={tenant_id} | Notifying configured webhook url: {url}")
    payload = {
        "content": f"🚨 **SENTINEL CIRCUIT BREAKER TRIPPED** 🚨\n**Agent:** `{agent_id}`\n**Tenant:** `{tenant_id}`\n**Reasons:** {', '.join(reasons)}\nAction: Agent has been frozen to secure funds.",
        "username": "Sentinel Bot",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "action": "FREEZE",
        "reasons": reasons
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=5.0)
            print(f"[WEBHOOK] Successfully fired webhook for {agent_id}")
    except Exception as e:
        print(f"[WEBHOOK] Failed to fire webhook: {e}")


async def run_enforcement_consumer(broker: Broker, store: Store):
    print("Starting enforcement consumer...")
    async for msg in broker.subscribe("agent.decisions", group="enforcement"):
        if msg["decision"] == "FREEZE":
            agent_id = msg["agent_id"]
            tenant_id = msg.get("tenant_id", "default")

            if not await store.is_frozen(tenant_id, agent_id):
                print(f"[FREEZE] tenant={tenant_id} | agent={agent_id} | reasons={msg['reasons']}")
                await store.freeze(tenant_id, agent_id, msg["reasons"])
                audit_log.append(msg)
                
                # Append to store ledger
                await store.append_ledger(tenant_id, audit_log.chain[-1].model_dump(mode='json'))

                webhook_url = await store.get_webhook_url(tenant_id)
                if webhook_url:
                    asyncio.create_task(execute_webhook(tenant_id, agent_id, msg["reasons"], webhook_url))
                else:
                    print(f"[WEBHOOK SIMULATOR] tenant={tenant_id} | No webhook configured. Agent {agent_id} frozen.")
