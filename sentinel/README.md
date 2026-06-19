# Sentinel: Real-Time Runaway-Agent Detector & Circuit Breaker

Static guardrails (budgets, rate limits) stop an agent from exceeding limits. Sentinel catches the agent that gets compromised or stuck *while still inside* those limits — a behavioral safety layer for autonomous agents.

## How it works

Sentinel watches a stream of agent actions and computes behavioral features (spend velocity, action rate, merchant bursts, etc.) in real-time using rolling windows. It uses explainable statistical rules combined with an IsolationForest ML model to score behavior. When an agent behaves anomalously, Sentinel trips a circuit breaker, freezing the agent in seconds and generating a tamper-evident audit log explaining exactly why.

### Features
- **In-Memory & Streaming modes:** Ships with a zero-dependency in-memory pub/sub broker and store, with swappable interfaces for Kafka and Redis.
- **Explainable Freezes:** Every freeze decision includes human-readable reasons (e.g., `spend_velocity z=6.2 above baseline`, `new_merchant_burst=4 in 10s`).
- **Hash-chained Audit Log:** Every freeze generates a cryptographically verifiable record.

## Running the Demo

1. Clone and install dependencies:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the 60-second demo script:
```bash
./scripts/demo.sh
```

This will:
- Start the server and generator with 6 normal agents.
- Inject a `rapid_exfil` attack on `agent-0007` at t=20s.
- Automatically freeze the agent based on anomalous behavior.
- Perform a manual `/act` request to prove the agent is blocked.
- Fetch the verifiable `/audit` log.

Open [http://localhost:8000](http://localhost:8000) to watch the live dashboard during the demo.

## Tests

```bash
pytest -q
```
