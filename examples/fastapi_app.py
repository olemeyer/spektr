"""
Minimal FastAPI app with full spektr instrumentation.

Run:
    pip install spektr[otlp] fastapi uvicorn
    python examples/fastapi_app.py

Try:
    curl http://localhost:8000/users/42
    curl http://localhost:8000/orders -X POST -H 'Content-Type: application/json' -d '{"item": "book", "amount": 29.99}'
    curl http://localhost:8000/fail
    curl http://localhost:8000/healthz

Send traces to a backend:
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python examples/fastapi_app.py
"""

import asyncio
import random

from fastapi import FastAPI

import spektr
from spektr import log, trace

app = FastAPI()
spektr.install(app)


# ── Routes ───────────────────────────────────────────────────


@app.get("/users/{user_id}")
@trace
async def get_user(user_id: int):
    user = await fetch_user(user_id)
    log("user fetched", user_id=user_id, name=user["name"])
    return user


@app.post("/orders")
@trace
async def create_order(item: str = "book", amount: float = 29.99):
    log("creating order", item=item, amount=amount)
    await charge_payment(amount)
    await send_confirmation(item=item)
    log.count("orders.created", item=item)
    return {"status": "created", "item": item, "amount": amount}


@app.get("/fail")
async def fail():
    raise ValueError("something went wrong")


# ── Simulated services ───────────────────────────────────────


@trace
async def fetch_user(user_id: int):
    await asyncio.sleep(random.uniform(0.005, 0.02))
    return {"id": user_id, "name": "Ole", "email": "ole@example.com"}


@trace
async def charge_payment(amount: float):
    await asyncio.sleep(random.uniform(0.01, 0.05))
    log("payment charged", amount=amount)


@trace
async def send_confirmation(item: str):
    await asyncio.sleep(random.uniform(0.005, 0.015))
    log("confirmation sent", item=item)


# ── Startup ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    log("starting server", port=8000)
    uvicorn.run(app, host="0.0.0.0", port=8000)
