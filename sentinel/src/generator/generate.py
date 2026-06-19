import asyncio
import time
import uuid
import random
from datetime import datetime, timezone
from src.common.config import settings
from src.common.schemas import AgentAction
from src.common.broker import Broker

MERCHANTS = [f"merchant-{i}" for i in range(1, 11)]
ACTION_TYPES = ["purchase", "transfer", "api_call"]

import os

async def inject_rapid_exfil(broker: Broker, agent_id: str):
    print(f"Injecting rapid_exfil for {agent_id}...")
    for i in range(5):
        event = AgentAction(
            event_id=str(uuid.uuid4()),
            agent_id=agent_id,
            action_type="purchase",
            merchant=f"new-merchant-evil-{i}",
            amount=5.0,
            currency="USD",
            timestamp=datetime.now(timezone.utc),
            trace_id=str(uuid.uuid4())
        )
        await broker.publish("agent.actions", event.model_dump(mode='json'))
        await asyncio.sleep(0.01)

async def inject_runaway_loop(broker: Broker, agent_id: str):
    print(f"Injecting runaway_loop for {agent_id}...")
    for i in range(15):
        event = AgentAction(
            event_id=str(uuid.uuid4()),
            agent_id=agent_id,
            action_type="transfer",
            merchant="merchant-loop",
            amount=1.0,
            currency="USD",
            timestamp=datetime.now(timezone.utc),
            trace_id=str(uuid.uuid4())
        )
        await broker.publish("agent.actions", event.model_dump(mode='json'))
        await asyncio.sleep(0.02)

async def inject_amount_spike(broker: Broker, agent_id: str):
    print(f"Injecting amount_spike for {agent_id}...")
    event = AgentAction(
        event_id=str(uuid.uuid4()),
        agent_id=agent_id,
        action_type="purchase",
        merchant="merchant-expensive",
        amount=5000.0,  # Huge amount
        currency="USD",
        timestamp=datetime.now(timezone.utc),
        trace_id=str(uuid.uuid4())
    )
    await broker.publish("agent.actions", event.model_dump(mode='json'))

async def generate_normal_traffic(broker: Broker, inject_config: str = ""):
    agents = [f"agent-{i:04d}" for i in range(1, settings.NUM_AGENTS + 1)]
    print(f"Starting generator with {settings.NUM_AGENTS} normal agents, {settings.ACTIONS_PER_SECOND} actions/sec.")
    
    start_time = time.time()
    attack_injected = False
    
    if not inject_config:
        inject_config = os.getenv("INJECT_ATTACK", "")
        
    attack_type, attack_time = "", 0
    if "@" in inject_config:
        attack_type, time_str = inject_config.split("@")
        attack_time = int(time_str.replace("s", ""))

    while True:
        now = time.time()
        if not attack_injected and attack_time > 0 and (now - start_time) >= attack_time:
            attack_injected = True
            target_agent = "agent-0007"
            if target_agent not in agents:
                target_agent = agents[0]
            if attack_type == "rapid_exfil":
                asyncio.create_task(inject_rapid_exfil(broker, target_agent))
            elif attack_type == "runaway_loop":
                asyncio.create_task(inject_runaway_loop(broker, target_agent))
            elif attack_type == "amount_spike":
                asyncio.create_task(inject_amount_spike(broker, target_agent))

        agent_id = random.choice(agents)
        action_type = random.choice(ACTION_TYPES)
        merchant = random.choice(MERCHANTS)
        amount = round(random.lognormvariate(2.0, 1.0), 2)
        
        event = AgentAction(
            event_id=str(uuid.uuid4()),
            agent_id=agent_id,
            action_type=action_type,
            merchant=merchant,
            amount=amount,
            currency="USD",
            timestamp=datetime.now(timezone.utc),
            trace_id=str(uuid.uuid4())
        )
        
        await broker.publish("agent.actions", event.model_dump(mode='json'))
        
        base_wait = 1.0 / settings.ACTIONS_PER_SECOND
        wait_time = random.uniform(base_wait * 0.5, base_wait * 1.5)
        await asyncio.sleep(wait_time)
