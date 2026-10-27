"""Observability contract: metrics exist with bounded labels, logs are JSON with request ids."""
import io
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_request_metrics_use_route_template_and_status(client):
    client.get("/livez")
    client.get("/does-not-exist")
    body = client.get("/metrics").text
    assert 'http_requests_total{method="GET",route="/livez",status="200"}' in body
    assert 'route="unmatched",status="404"' in body  # raw unknown paths never become labels
    assert "http_request_duration_seconds_bucket" in body


def test_order_status_label_is_bounded(client):
    client.post("/orders", json={"amount": 1, "status": "paid"})
    client.post("/orders", json={"amount": 1, "status": "anything-a-user-types"})
    body = client.get("/metrics").text
    assert 'orders_created_total{status="paid"}' in body
    assert 'orders_created_total{status="other"}' in body
    assert "anything-a-user-types" not in body


def test_logs_are_json_and_carry_request_id(client):
    from observability import JsonFormatter
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)
    try:
        response = client.post("/orders", json={"amount": 5, "status": "paid"},
                               headers={"x-request-id": "trace-me-123"})
    finally:
        logging.getLogger().removeHandler(handler)
    assert response.headers["x-request-id"] == "trace-me-123"
    lines = [json.loads(l) for l in buf.getvalue().splitlines()]  # every line must be valid JSON
    mine = [l for l in lines if l["request_id"] == "trace-me-123"]
    assert {l["msg"] for l in mine} >= {"order created", "request"}
    request_line = next(l for l in mine if l["msg"] == "request")
    assert request_line["route"] == "/orders" and request_line["status"] == 200
