import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextlib import asynccontextmanager

from src.common.broker import make_broker
from src.common.store import make_store

from src.generator.generate import generate_normal_traffic
from src.detector.engine import run_detection_engine
from src.enforcement.breaker import run_enforcement_consumer
from src.enforcement.api import setup_api

broker = make_broker()
store = make_store()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start tasks here
    generator_task = asyncio.create_task(generate_normal_traffic(broker))
    engine_task = asyncio.create_task(run_detection_engine(broker, store))
    enforcement_task = asyncio.create_task(run_enforcement_consumer(broker, store))
    yield
    generator_task.cancel()
    engine_task.cancel()
    enforcement_task.cancel()
    try:
        await asyncio.gather(generator_task, engine_task, enforcement_task)
    except asyncio.CancelledError:
        pass
    await broker.close()

app = FastAPI(title="Sentinel", lifespan=lifespan)

# Allow the Next.js dev server (and any localhost origin) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_api(app, broker, store)

@app.get("/status")
async def status():
    return {"status": "ok"}

if __name__ == "__main__":
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description="Sentinel Runaway-Agent Detector")
    parser.add_argument("--agents", type=int, help="Number of normal agents")
    parser.add_argument("--rate", type=float, help="Actions per second")
    parser.add_argument("--inject", type=str, help="Attack injection (e.g. rapid_exfil@20s)")
    args = parser.parse_args()
    
    if args.agents is not None:
        os.environ["NUM_AGENTS"] = str(args.agents)
    if args.rate is not None:
        os.environ["ACTIONS_PER_SECOND"] = str(args.rate)
    if args.inject is not None:
        os.environ["INJECT_ATTACK"] = args.inject
        
    uvicorn.run("src.app:app", host="0.0.0.0", port=8000, reload=True)
