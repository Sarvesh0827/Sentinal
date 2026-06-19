#!/bin/bash
echo "Starting Sentinel in demo mode..."
export INJECT_ATTACK="rapid_exfil@20s"
export PYTHONPATH="$(pwd):$PYTHONPATH"

# Run server in background
uvicorn sentinel.src.app:app --host 0.0.0.0 --port 8000 &
PID=$!

echo "Server started. Open http://localhost:8000 to view the live dashboard."
echo "Waiting 22 seconds for normal traffic to establish and attack to inject at t=20s..."
sleep 22

echo ""
echo "--- Proving Enforcement via /act ---"
echo "Sending manual action for compromised agent-0007..."
curl -s -X POST http://localhost:8000/act \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "agent-0007", "action_type": "purchase", "merchant": "test-merchant", "amount": 10.0}' | jq || echo "Failed to parse JSON"

echo ""
echo "--- Fetching Audit Log ---"
curl -s http://localhost:8000/audit | jq || echo "Failed to parse JSON"

echo ""
echo "Demo complete. Press Ctrl+C to stop the server."
wait $PID
