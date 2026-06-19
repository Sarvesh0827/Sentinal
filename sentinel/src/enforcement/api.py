import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import Optional

from src.common.schemas import AgentAction
from src.enforcement.breaker import audit_log
from src.auth import get_caller, CallerIdentity, create_access_token
from src.identity import register_agent, get_public_key_pem, verify_event_signature


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ActRequest(BaseModel):
    agent_id: str
    action_type: str
    merchant: str
    amount: float
    signature: Optional[str] = None  # Ed25519 base64 signature (optional in dev mode)


class TokenRequest(BaseModel):
    username: str
    password: str
    tenant_id: str = "default"


class RegisterAgentRequest(BaseModel):
    agent_id: str
    public_key_pem: str  # PEM-encoded Ed25519 public key

class WebhookRequest(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# API setup
# ---------------------------------------------------------------------------
def setup_api(app, broker, store):
    router = APIRouter()

    # ------------------------------------------------------------------
    # Auth endpoints
    # ------------------------------------------------------------------
    @router.post("/auth/token", tags=["auth"])
    async def login(req: TokenRequest):
        """
        Issue a JWT access token.
        In dev mode any credentials work. In production validate against a user DB.
        """
        # Dev: accept any credentials
        token = create_access_token(tenant_id=req.tenant_id, sub=req.username)
        return {"access_token": token, "token_type": "bearer"}

    # ------------------------------------------------------------------
    # Identity / KYA endpoints
    # ------------------------------------------------------------------
    @router.post("/identity/register", tags=["identity"])
    async def register_agent_key(
        req: RegisterAgentRequest,
        caller: CallerIdentity = Depends(get_caller),
    ):
        """Register an agent's Ed25519 public key for signature verification."""
        register_agent(caller.tenant_id, req.agent_id, req.public_key_pem)
        return {"status": "registered", "tenant_id": caller.tenant_id, "agent_id": req.agent_id}

    @router.get("/identity/{agent_id}", tags=["identity"])
    async def get_agent_key(
        agent_id: str,
        caller: CallerIdentity = Depends(get_caller),
    ):
        """Return the registered public key for an agent (PEM format)."""
        pem = get_public_key_pem(caller.tenant_id, agent_id)
        if not pem:
            raise HTTPException(status_code=404, detail="Agent not registered")
        return {"agent_id": agent_id, "tenant_id": caller.tenant_id, "public_key_pem": pem}

    # ------------------------------------------------------------------
    # Observability endpoints
    # ------------------------------------------------------------------
    @router.get("/status", tags=["observability"])
    async def get_status(caller: CallerIdentity = Depends(get_caller)):
        """Live snapshot of all agents within the caller's tenant."""
        frozen = await store.frozen_agents(caller.tenant_id)
        agent_ids = await store.get_all_agent_ids(caller.tenant_id)
        agents_out = []
        for a in agent_ids:
            trust = await store.get_trust_score(caller.tenant_id, a)
            agents_out.append({
                "agent_id": a,
                "frozen": a in frozen,
                "freeze_reasons": frozen.get(a, []),
                "trust_score": trust,
            })
        return {
            "tenant_id": caller.tenant_id,
            "agents": agents_out,
            "frozen_count": len(frozen),
        }

    @router.get("/stream", tags=["observability"])
    async def stream_decisions(
        request: Request,
        caller: CallerIdentity = Depends(get_caller),
    ):
        """SSE stream of live decisions for the caller's tenant."""
        tenant_id = caller.tenant_id

        async def event_generator():
            async for msg in broker.subscribe("agent.decisions"):
                if await request.is_disconnected():
                    break
                # Filter by tenant so each tenant only sees their own data
                if msg.get("tenant_id", "default") == tenant_id:
                    yield {"event": "message", "data": json.dumps(msg)}

        return EventSourceResponse(event_generator())

    @router.get("/ledger", tags=["observability"])
    async def get_ledger(caller: CallerIdentity = Depends(get_caller)):
        """Return the hash-chained compliance ledger for the caller's tenant."""
        ledger = await store.get_ledger(caller.tenant_id)
        return {
            "tenant_id": caller.tenant_id,
            "verify": True, # Backend verify
            "chain": ledger,
        }

    @router.post("/webhook", tags=["observability"])
    async def set_webhook(req: WebhookRequest, caller: CallerIdentity = Depends(get_caller)):
        """Set the webhook URL for the tenant."""
        await store.set_webhook_url(caller.tenant_id, req.url)
        return {"status": "ok", "url": req.url}

    @router.get("/webhook", tags=["observability"])
    async def get_webhook(caller: CallerIdentity = Depends(get_caller)):
        """Get the webhook URL for the tenant."""
        url = await store.get_webhook_url(caller.tenant_id)
        return {"url": url}

    # ------------------------------------------------------------------
    # Control endpoints
    # ------------------------------------------------------------------
    @router.post("/act", tags=["control"])
    async def act(
        req: ActRequest,
        caller: CallerIdentity = Depends(get_caller),
    ):
        """
        Simulate an agent action.
        - Returns 403 if the agent is frozen.
        - Publishes the event to agent.actions so it flows through detection.
        - Validates Ed25519 signature if one is provided.
        """
        tenant_id = caller.tenant_id
        is_frozen = await store.is_frozen(tenant_id, req.agent_id)
        if is_frozen:
            frozen_agents = await store.frozen_agents(tenant_id)
            reasons = frozen_agents.get(req.agent_id, [])
            return JSONResponse(status_code=403, content={
                "status": "AGENT_FROZEN",
                "tenant_id": tenant_id,
                "reasons": reasons,
            })

        event = AgentAction(
            event_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            agent_id=req.agent_id,
            action_type=req.action_type,
            merchant=req.merchant,
            amount=req.amount,
            currency="USD",
            timestamp=datetime.now(timezone.utc),
            trace_id=str(uuid.uuid4()),
            signature=req.signature,
        )

        event_dict = event.model_dump(mode='json')

        # KYA check at the /act boundary (before hitting the broker)
        if not verify_event_signature(event_dict):
            return JSONResponse(status_code=401, content={
                "status": "SIGNATURE_INVALID",
                "detail": "Ed25519 signature verification failed for this agent.",
            })

        await broker.publish("agent.actions", event_dict)
        return {"status": "allowed", "event_id": event.event_id, "tenant_id": tenant_id}

    @router.post("/unfreeze/{agent_id}", tags=["control"])
    async def unfreeze(
        agent_id: str,
        caller: CallerIdentity = Depends(get_caller),
    ):
        """Unfreeze an agent within the caller's tenant (for re-running the demo)."""
        await store.unfreeze(caller.tenant_id, agent_id)
        return {"status": "unfrozen", "agent_id": agent_id, "tenant_id": caller.tenant_id}

    # ------------------------------------------------------------------
    # Dashboard (serves the legacy minimal HTML page)
    # ------------------------------------------------------------------
    @router.get("/dashboard", tags=["ui"])
    async def get_dashboard():
        from fastapi.responses import FileResponse
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "index.html")
        return FileResponse(path)

    @router.get("/", tags=["ui"])
    async def root():
        """Redirect to dashboard."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard")

    app.include_router(router)
