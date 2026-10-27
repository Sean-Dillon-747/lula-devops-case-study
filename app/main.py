"""Trivial orders API for the DevOps case study.

This app is deliberately simple - it is NOT what we're assessing. Extend or replace it
as you like. The platform work around it (container, pipeline, migration, observability)
is the point.
"""
import logging
import os

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from observability import configure_logging, instrument, record_order_created

DB_URL = os.environ.get("DB_URL", "postgresql://app:app@localhost:5432/app")
configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("orders")
app = FastAPI(title="Orders API")
instrument(app)


class Order(BaseModel):
    amount: float
    status: str = "pending"


def _conn():
    return psycopg.connect(DB_URL)


@app.get("/livez")
def livez():
    """Liveness: is the process able to serve at all? Deliberately does NOT touch the DB.
    If it did, a DB blip would make the orchestrator restart every replica at once."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness: can this replica serve real traffic? Failing it takes the replica out
    of the load balancer without restarting it."""
    try:
        with psycopg.connect(DB_URL, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        # Full detail goes to our logs; callers only get a generic message, because
        # driver errors can leak hostnames/usernames.
        log.warning("readiness check failed", extra={"fields": {"error": type(exc).__name__}})
        raise HTTPException(status_code=503, detail="db unavailable")


# Kept for backwards compatibility with existing callers; same semantics as before.
app.add_api_route("/health", readyz, methods=["GET"])


@app.get("/orders")
def list_orders():
    with _conn() as conn:
        rows = conn.execute("SELECT id, amount, status FROM orders ORDER BY id").fetchall()
    return [{"id": r[0], "amount": float(r[1]), "status": r[2]} for r in rows]


@app.post("/orders")
def create_order(order: Order):
    with _conn() as conn:
        row = conn.execute(
            "INSERT INTO orders (amount, status) VALUES (%s, %s) RETURNING id",
            (order.amount, order.status),
        ).fetchone()
        conn.commit()
    record_order_created(order.status)
    log.info("order created", extra={"fields": {"order_id": row[0], "status": order.status}})
    return {"id": row[0], "amount": order.amount, "status": order.status}
