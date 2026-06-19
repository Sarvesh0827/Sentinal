# PLANNING.md — Sentinel: Real-Time Runaway-Agent Detector & Circuit Breaker

## 0. One-line pitch
A real-time safety layer for the agentic economy: it watches a stream of AI-agent
actions, detects compromised / looping / runaway agents using behavioral anomaly
detection, and trips a circuit breaker that freezes the offending agent in seconds —
with an explainable reason and a tamper-evident audit trail.

> Positioning: This is NOT a payments/wallet product. It is the *safety & observability
> layer that sits on top of* agent infrastructure. Conventional guardrails enforce
> static limits (budgets, rate limits); Sentinel catches agents that misbehave *while
> still inside* those limits, by modeling behavior instead of just checking rules.

> Build location: This is a self-contained Python service. Build it in a top-level
> `sentinel/` directory so it does NOT interfere with the existing Next.js app in this repo.
> Do not import from or modify anything outside `sentinel/`.

---

## 1. Goals & Non-Goals

### Goals (must achieve in MVP)
- Stream agent actions through Kafka (or an in-memory broker fallback).
- Compute per-agent behavioral features in real time.
- Score each agent for anomaly using (a) explainable statistical rules and (b) a light ML model.
- Trip a circuit breaker: publish a `FREEZE` decision; an enforcement consumer then rejects
  further actions from that agent.
- Produce an explainable reason for every freeze ("spend velocity 6.2σ above baseline + 4 new merchants in 10s").
- Show it live (minimal dashboard or rich terminal view).
- Ship a 60-second demo: normal traffic → injected rogue agent → detection → freeze.

### Non-Goals (explicitly out of scope for MVP)
- Real payment rails / real money (use synthetic events).
- Real agent identity/KYA issuance (assume `agent_id` is trusted input).
- Production auth, multi-tenant, horizontal scaling.
- A polished frontend. Keep UI minimal.

---

## 2. Tech Stack
- **Language:** Python 3.11+
- **Streaming:** Kafka via `confluent-kafka` or `aiokafka`. MUST provide an in-memory
  broker fallback (a simple asyncio pub/sub) so the demo runs without Docker if needed.
- **Service framework:** FastAPI (control API + SSE for the dashboard).
- **ML/stats:** `numpy`, `scipy`, `scikit-learn` (IsolationForest), `pandas`.
- **State:** Redis (rolling per-agent windows) with an in-memory dict fallback.
- **Dashboard:** Minimal. Option A (preferred for speed): FastAPI serves a single HTML
  page that consumes Server-Sent Events and renders a live table. Option B: `rich` library
  terminal dashboard. DO NOT build a heavy React/Next.js app for the MVP.
- **Infra:** `docker-compose.yml` for Kafka + Redis (optional; fallbacks must work without it).

---

## 2.5 Process & Concurrency Model — READ THIS FIRST (critical)

This is the single most important design decision. Get it wrong and nothing works.

- **In-memory mode (`USE_KAFKA=false`, the default and the demo mode):** the in-memory
  broker is a plain asyncio pub/sub object living in ONE Python process. It CANNOT cross
  process boundaries. Therefore in this mode the generator, detection engine, enforcement
  consumer, and FastAPI server MUST all run inside a **single process**, as concurrent
  `asyncio` tasks sharing the same broker and store instances.
  - Implement this as one entrypoint (`src/app.py`) that:
    1. builds a single `Broker` and `Store` (from config),
    2. starts the detection engine consumer task,
    3. starts the enforcement consumer task,
    4. starts the generator task,
    5. launches the FastAPI app (uvicorn) in the same event loop.
  - `./scripts/run_local.sh` just runs `python -m sentinel.src.app` (or `uvicorn` with a
    lifespan that spawns the tasks).

- **Kafka mode (`USE_KAFKA=true`, optional, for credibility):** the same modules can run as
  separate processes against a real Kafka + Redis from `docker-compose`. The generator,
  engine, and API become independently launchable. This mode is a stretch goal — make the
  single-process in-memory path rock-solid FIRST.

- **Golden rule:** all four components talk to each other ONLY through the `Broker` interface
  (topics) and the `Store` interface. No direct function calls between generator → engine →
  enforcement. This keeps the in-memory and Kafka modes behaviorally identical.

---

## 2.6 Component Interface Contracts (so backends are swappable)

Define these as abstract interfaces in `src/common/`. Provide TWO implementations of each
(in-memory + Kafka/Redis) selected by env var at startup via a factory.

### Broker (`src/common/broker.py`)
```python
from collections.abc import AsyncGenerator

class Broker(Protocol):
    async def publish(self, topic: str, message: dict) -> None: ...
    async def subscribe(
        self, topic: str, group: str | None = None
    ) -> AsyncGenerator[dict, None]:
        """Yields message dicts as they arrive. In-memory uses asyncio.Queue per subscriber."""
        ...
    async def close(self) -> None: ...

def make_broker(settings) -> Broker:  # returns InMemoryBroker or KafkaBroker
```
- **Implement `subscribe` as an `async def` that uses `yield`** (an `AsyncGenerator`), not a
  regular function returning an iterator. Consumers should use `async for msg in broker.subscribe(...)`.
- **InMemoryBroker:** keeps `dict[topic, list[asyncio.Queue]]`; `publish` puts the message on
  every subscriber queue; `subscribe` creates a queue and `yield`s from it in a loop. Messages are Python
  dicts (no serialization needed in-memory).
- **KafkaBroker:** wraps `aiokafka` producer/consumer; JSON-encodes/decodes; uses `group`.

### Store (`src/common/store.py`)
```python
class Store(Protocol):
    async def append_window(self, agent_id: str, event: dict) -> None: ...
    async def get_window(self, agent_id: str, horizon_s: float) -> list[dict]: ...
    async def get_all_agent_ids(self) -> list[str]: ...
    async def freeze(self, agent_id: str, reason: list[str]) -> None: ...
    async def unfreeze(self, agent_id: str) -> None: ...
    async def is_frozen(self, agent_id: str) -> bool: ...
    async def frozen_agents(self) -> dict[str, list[str]]:  # agent_id -> reasons
        ...
```
- **InMemoryStore:** dicts + `collections.deque` per agent; prune events older than the max
  window on each append. Frozen set is a dict.
- **RedisStore:** sorted sets keyed by timestamp for windows; a Redis set/hash for frozen.

### Settings (`src/common/config.py`)
- Load from environment (use `pydantic-settings` or `os.environ`).
- Fields exactly match section 12. Provide sane defaults so it runs with no `.env`.

---

## 3. High-Level Architecture

```
+-------------------+      agent.actions      +--------------------+
|  Event Generator  | ----------------------> |  Detection Engine  |
| (normal + attack) |        (Kafka)          |  - feature builder |
+-------------------+                         |  - rule scorer     |
                                              |  - ML scorer       |
                                              +---------+----------+
                                                        | agent.decisions (FREEZE/OK)
                                                        v
+-------------------+    rejects frozen      +--------------------+
|  Enforcement /    | <--------------------- |  Decision/Policy   |
|  Circuit Breaker  |   reads decisions      |  Publisher         |
+-------------------+                        +--------------------+
        |                                              |
        |  audit events                                | SSE
        v                                              v
+-------------------+                        +--------------------+
|   Audit Log       |                        |  Dashboard (live)  |
| (append-only,     |                        |  agents, scores,   |
|  hash-chained)    |                        |  FROZEN highlights |
+-------------------+                        +--------------------+
```

---

## 4. Kafka Topics & Event Schemas

### Topics
- `agent.actions` — raw agent actions (produced by generator).
- `agent.decisions` — detector output (OK / FREEZE) per evaluated action.
- `agent.audit` — append-only audit records of every freeze decision.

### Schema: `agent.actions`
```json
{
  "event_id": "uuid",
  "agent_id": "agent-0007",
  "action_type": "purchase | api_call | transfer",
  "merchant": "merchant-xyz",
  "amount": 12.50,
  "currency": "USD",
  "timestamp": "2026-06-22T17:00:00.123Z",
  "trace_id": "uuid"
}
```

### Schema: `agent.decisions`
```json
{
  "decision_id": "uuid",
  "agent_id": "agent-0007",
  "event_id": "uuid",
  "decision": "OK | FREEZE",
  "anomaly_score": 0.87,
  "reasons": [
    "spend_velocity z=6.2 (threshold 4.0)",
    "new_merchant_burst=4 in 10s (threshold 3)"
  ],
  "timestamp": "2026-06-22T17:00:00.456Z"
}
```

### Schema: `agent.audit` (hash-chained for tamper-evidence)
```json
{
  "seq": 42,
  "prev_hash": "sha256(...)",
  "record": { "...the decision record..." },
  "hash": "sha256(prev_hash + record)"
}
```

---

## 5. Detection Logic (the core IP)

### Per-agent rolling window state (Redis or in-memory)
Maintain a sliding window (e.g. last 60s and last 50 events) per `agent_id`:
- timestamps of recent actions
- amounts of recent actions
- set of merchants seen (with first-seen time)
- count of actions

### Features computed per incoming action
1. **spend_velocity** — sum(amount) over last 10s.
2. **action_rate** — count of actions over last 10s.
3. **amount_zscore** — z-score of current amount vs agent's historical mean/std.
4. **new_merchant_burst** — # of never-before-seen merchants in last 10s.
5. **action_entropy** — Shannon entropy of action_type distribution over window
   (very low entropy = repetitive loop; flag looping agents).
6. **inter_arrival_min** — min time between consecutive actions (machine-gun behavior).

### Cold start / warmup (MUST handle — otherwise you get div-by-zero and false freezes)
- An agent has NO baseline for its first few events. Do NOT score an agent until it has at
  least `MIN_WARMUP_EVENTS` (default 15) observations. Before that, always emit `OK` with
  reason `["warming up"]`.
- When computing any z-score, guard against zero variance: `z = (x - mean) / max(std, EPS)`
  with `EPS = 1e-6`. If `std == 0` and `x == mean`, z = 0.
- Baselines are computed over the agent's own history window EXCLUDING the current event,
  so a spike doesn't inflate its own baseline.
- Absolute floors so tiny-but-rule-breaking patterns still trip even with a noisy baseline:
  e.g. `new_merchant_burst >= NEW_MERCHANT_BURST` fires regardless of z-score.

### Scorer A — explainable statistical rules (primary, always on)
- Maintain per-agent baseline (rolling mean/std) for velocity & amount (after warmup).
- Flag if any feature crosses a configured threshold (z-score > `ZSCORE_THRESHOLD`,
  new_merchant_burst >= `NEW_MERCHANT_BURST`, inter_arrival_min < 50ms sustained,
  entropy < 0.2 with high rate).
- Each crossed rule produces a human-readable reason string. Use a consistent format:
  `"<feature>=<value> (threshold <threshold>)"` and for z-scores
  `"<feature> z=<value> above baseline (threshold <z>)"`.
- Composite rule score = weighted sum of normalized rule violations, clamped to [0,1].
  A single hard rule (e.g. merchant burst) may set score directly to 1.0.

### Scorer B — ML anomaly model (secondary, adds credibility)
- `sklearn.ensemble.IsolationForest` trained on a warmup buffer of "normal" feature vectors.
- Produces an anomaly score in [0,1].
- Used to corroborate Scorer A; report both.

### Final decision
- `anomaly_score = max(rule_score, ml_score)` (rules dominate for explainability).
- If `anomaly_score >= FREEZE_THRESHOLD` (default 0.8) → decision = FREEZE, attach reasons.
- Otherwise OK.
- Cooldown: once frozen, agent stays frozen (manual `/unfreeze` to reset for re-demo).

---

## 6. Circuit Breaker / Enforcement

### Data flow — how the two action paths reconcile (important)
There are two ways an action enters the system; they are NOT duplicates:
1. **Generator → `agent.actions` topic:** the continuous synthetic traffic that the detector
   scores. This is what drives detection and the live dashboard. The generator does NOT call
   `/act`; it publishes directly to the broker.
2. **`POST /act` (manual / demo):** a single human-triggered action used in the demo to PROVE
   enforcement. It first checks `is_frozen(agent_id)`; if frozen → 403; if allowed, it ALSO
   publishes the action to `agent.actions` so it flows through detection like any other event.

So: generator = the firehose the detector watches; `/act` = a manual probe that demonstrates
the freeze actually blocks an agent. Both end up on the same topic.

### Enforcement consumer
- An `enforcement` consumer subscribes to `agent.decisions`.
- On a `FREEZE` decision: call `store.freeze(agent_id, reasons)` and append a record to
  `agent.audit` (hash-chained, see below).
- Maintains the frozen set via the `Store` (so `/act` and the consumer share one source of truth).

### Audit hash-chain (exact algorithm — be deterministic)
- Maintain an in-order list. For each new record:
  - `prev_hash` = hash of the previous record (or 64 zeros for seq 0).
  - `canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))`
  - `hash = sha256((prev_hash + canonical).encode()).hexdigest()`
- `GET /audit` recomputes the chain and returns `verify=True` only if every link matches.
- A tampered `record` field must make `verify=False`.

---

## 7. Attack / Scenario Generator
The generator MUST produce believable normal traffic plus injectable attacks:

- **normal**: Poisson-ish arrivals, amounts ~ lognormal, a stable small merchant set.
- **attack: rapid_exfil** — burst of micro-spends across many NEW merchants (card-testing pattern).
- **attack: runaway_loop** — same action_type repeated at high rate (entropy collapse).
- **attack: amount_spike** — sudden large amount vs the agent's history.

CLI flags: `--agents N --rate R --inject rapid_exfil@t=20s` etc.

---

## 8. Repo Structure
```
sentinel/
├── README.md
├── requirements.txt
├── docker-compose.yml            # kafka + redis (optional)
├── .env.example
├── src/
│   ├── app.py                    # SINGLE entrypoint: wires broker+store, starts all asyncio tasks + FastAPI
│   ├── common/
│   │   ├── config.py             # settings loaded from env (pydantic-settings)
│   │   ├── schemas.py            # pydantic models for all events
│   │   ├── broker.py             # Broker interface + InMemoryBroker + KafkaBroker + make_broker()
│   │   └── store.py              # Store interface + InMemoryStore + RedisStore + make_store()
│   ├── generator/
│   │   └── generate.py           # normal + attack traffic producer
│   ├── detector/
│   │   ├── features.py           # rolling window feature computation
│   │   ├── rules.py              # statistical rule scorer (explainable)
│   │   ├── ml_model.py           # IsolationForest scorer
│   │   └── engine.py             # consumes actions, scores, publishes decisions
│   ├── enforcement/
│   │   ├── breaker.py            # frozen set + audit hash-chain
│   │   └── api.py                # FastAPI: /act, /unfreeze, /status, /stream (SSE)
│   └── dashboard/
│       └── index.html            # minimal live SSE table
├── scripts/
│   ├── run_local.sh              # starts everything with in-memory fallbacks (no docker)
│   └── demo.sh                   # runs the scripted 60s demo
└── tests/
    ├── test_features.py
    ├── test_rules.py
    └── test_breaker.py
```

---

## 9. API Endpoints (FastAPI)
- `GET  /status` — live snapshot: agents, latest scores, frozen set.
- `GET  /stream` — SSE stream of decisions for the dashboard.
- `POST /act` — simulate an agent action; returns 200 (allowed) or 403 (frozen).
- `POST /unfreeze/{agent_id}` — reset an agent (for re-running the demo).
- `GET  /audit` — return the hash-chained audit log + a `verify` flag.

### Request/response shapes
- `POST /act` body: `{"agent_id": "agent-0007", "action_type": "purchase", "merchant": "m1", "amount": 12.5}`
  - allowed → `200 {"status": "allowed", "event_id": "..."}`
  - frozen  → `403 {"status": "AGENT_FROZEN", "reasons": ["spend_velocity z=6.2 ..."]}`
- `GET /status` → `{"agents": [{"agent_id", "last_score", "frozen", "events"}], "frozen_count": N}`
- `GET /stream` → `text/event-stream`, each event is one `agent.decisions` JSON object.

---

## 9.5 Dependencies & How to Run (exact)

### `requirements.txt`
```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.7
pydantic-settings>=2.3
numpy>=1.26
scipy>=1.13
scikit-learn>=1.5
pandas>=2.2
sse-starlette>=2.1
aiokafka>=0.11        # only used when USE_KAFKA=true
redis>=5.0            # only used when USE_REDIS=true
rich>=13.7            # optional terminal dashboard
pytest>=8.2
pytest-asyncio>=0.23
```
> Kafka/Redis libs are imported lazily inside the Kafka/Redis backends so the default
> in-memory mode never requires them to be installed/running.

### Run (default in-memory mode, no Docker)
```bash
cd sentinel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/run_local.sh          # = uvicorn sentinel.src.app:app  (lifespan starts all tasks)
# then open http://localhost:8000  for the dashboard
```

### Run the demo
```bash
./scripts/demo.sh               # drives a scripted normal→attack→freeze sequence via the API
```

### Run tests
```bash
pytest -q
```

### Optional Kafka mode
```bash
docker compose up -d            # starts kafka + redis
USE_KAFKA=true USE_REDIS=true ./scripts/run_local.sh
```

---

## 10. Build Phases (ordered for a one-day build)

> Build in this order. Each phase should be runnable/verifiable before moving on.

- [ ] **P0 — Skeleton (40m):** repo structure, `requirements.txt`, `config.py`, pydantic
      `schemas.py`, `broker.py` + `store.py` with the interfaces + in-memory implementations
      and factories. Create `app.py` that wires a broker/store and starts empty asyncio tasks
      + FastAPI. Verify a message round-trips through the in-memory broker (publish → subscribe).
      Confirm the single-process model (section 2.5) works before adding logic.
- [ ] **P1 — Generator (45m):** normal traffic producer task publishing to `agent.actions`.
      Print events. Wire it into `app.py` as a task.
- [ ] **P2 — Features (60m):** rolling-window feature computation per agent. Unit test it.
- [ ] **P3 — Rule scorer + decisions (60m):** thresholds, reasons, publish to `agent.decisions`.
      This alone should already catch an injected attack — verify end to end.
- [ ] **P4 — Circuit breaker (45m):** enforcement consumer + `/act` returns 403 when frozen +
      hash-chained audit log.
- [ ] **P5 — ML scorer (45m):** IsolationForest warmup + corroborating score.
- [ ] **P6 — Attacks (30m):** implement `rapid_exfil`, `runaway_loop`, `amount_spike` injection.
- [ ] **P7 — Dashboard (60m):** SSE + minimal HTML table; frozen rows highlighted red.
- [ ] **P8 — Demo + README (45m):** `demo.sh`, record 60s clip, write README with the story.

Cut order if short on time: drop P7 (use `rich` terminal or plain logs), then P5 (rules alone
are enough for the wow). NEVER cut P3 or P4 — the detection + freeze is the whole point.

---

## 11. Demo Script (the "wow")
1. Start system: `./scripts/run_local.sh` (in-memory mode, no Docker needed).
2. Generator runs 6 normal agents — dashboard shows low scores, all OK.
3. At t=20s inject `rapid_exfil` on `agent-0007`.
4. Within seconds: score spikes → decision FREEZE → row turns red.
5. Call `POST /act` as `agent-0007` → returns `403 AGENT_FROZEN` with reason.
6. Show `/audit` — the freeze record, hash-chain verifies = true.
7. Narrate: "An agent inside its spending limits still got compromised; Sentinel caught the
   behavior, not just the budget, and froze it in ~2s with an explainable reason."

Record this as a 60-second screen capture → this is the artifact to share.

---

## 12. Configuration (.env.example)
```
USE_KAFKA=false            # false = in-memory broker (no docker needed)
KAFKA_BOOTSTRAP=localhost:9092
USE_REDIS=false            # false = in-memory store
REDIS_URL=redis://localhost:6379/0
FREEZE_THRESHOLD=0.8
WINDOW_SECONDS=10
ZSCORE_THRESHOLD=4.0
NEW_MERCHANT_BURST=3
MIN_WARMUP_EVENTS=15       # no scoring until an agent has this many observations
MAX_WINDOW_SECONDS=60      # longest history kept per agent (for pruning)
API_PORT=8000
NUM_AGENTS=6               # generator: number of normal agents
ACTIONS_PER_SECOND=5       # generator: aggregate event rate
```

> The detector and generator read ALL tunables from here. No magic numbers hardcoded in logic.

---

## 13. Acceptance Criteria (definition of done)
- `./scripts/run_local.sh` boots the whole system with zero external services (fallbacks).
- Normal traffic produces no false freezes over a 60s run (tune thresholds).
- Each injected attack type triggers a FREEZE within 5 seconds.
- Every FREEZE has at least one human-readable reason.
- A frozen agent's `/act` calls return 403; `/unfreeze` restores it.
- `/audit` hash-chain verification returns true; tampering a record makes it false.
- `tests/` pass (`pytest`).
- README explains the behavioral-safety positioning + includes the 60s demo.
- The whole default path runs with `pip install -r requirements.txt` + one command, no Docker.

---

## 14. README framing (for the human, not the agent)
Lead the README with: "Static guardrails (budgets, rate limits) stop an agent from exceeding
limits. Sentinel catches the agent that gets compromised or stuck *while still inside* those
limits — a behavioral safety layer for autonomous agents." Then the demo gif, then architecture.
Keep it product-neutral: describe the problem and the system on their own terms; do not
reference any specific company.

---

## 15. Stretch goals (only if ahead of schedule)
- Per-agent baselines that adapt over time (EWMA) instead of fixed thresholds.
- A "trust score" that decays on anomalies and recovers on good behavior.
- Replay mode: feed a recorded action log to reproduce a detection deterministically.
- Webhook on FREEZE (simulate notifying the wallet provider to suspend the agent).
