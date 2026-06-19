import asyncio
import json
import argparse
from sentinel.src.common.broker import make_broker

async def run_replay(file_path: str):
    broker = make_broker()
    print(f"Starting replay from {file_path}...")
    with open(file_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            await broker.publish("agent.actions", event)
            # Replay quickly but yield
            await asyncio.sleep(0.001)
    print("Replay finished.")
    await broker.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay recorded actions")
    parser.add_argument("file", type=str, help="Path to JSONL file")
    args = parser.parse_args()
    asyncio.run(run_replay(args.file))
