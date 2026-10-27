"""Trivial orders API for the DevOps case study.

This app is deliberately simple - it is NOT what we're assessing. Extend or replace it
as you like. The platform work around it (container, pipeline, migration, observability)
is the point.
"""
import os

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DB_URL = os.environ.get("DB_URL", "postgresql://app:app@localhost:5432/app")
app = FastAPI(title="Orders API")


class Order(BaseModel):
    amount: float
    status: str = "pending"


def _conn():
    return psycopg.connect(DB_URL)


@app.get("/health")
def health():
    try:
        with _conn() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}")


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
    return {"id": row[0], "amount": order.amount, "status": order.status}
