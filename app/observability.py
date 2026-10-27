"""Structured logs + Prometheus metrics for the orders API.

Kept in its own module so main.py stays readable and this can be lifted into a
shared library for the next service the pod ships.

Logs:    one JSON object per line on stdout (12-factor). The platform (Container Apps /
         AKS -> Log Analytics) collects stdout; no log files, no agents in the image.
         Every line inside a request carries request_id, so one failing request can be
         followed end to end.
Metrics: RED metrics (Rate, Errors, Duration) per route, exposed on /metrics for
         Prometheus / Azure Monitor managed Prometheus to scrape.
"""
import contextvars
import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Probes and scrapes hit every few seconds: log them at DEBUG so they don't drown real traffic.
QUIET_PATHS = {"/livez", "/readyz", "/health", "/metrics"}

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
ORDERS_CREATED = Counter(
    "orders_created_total", "Orders created, by status", ["status"]
)
KNOWN_STATUSES = {"pending", "paid", "shipped"}


def record_order_created(status: str) -> None:
    # Never use raw user input as a label: the current API accepts any string, and
    # every distinct value would become a new time series (cardinality explosion).
    ORDERS_CREATED.labels(status=status if status in KNOWN_STATUSES else "other").inc()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.formatter.converter = time.gmtime  # timestamps in UTC
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Route uvicorn's own loggers through the same JSON handler. Its access log is
    # replaced by our middleware, which knows the route template and request id.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True


log = logging.getLogger("orders.http")


def instrument(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        except Exception:
            log.exception("unhandled error", extra={"fields": {"path": request.url.path}})
            raise
        finally:
            duration = time.perf_counter() - start
            # Label by route TEMPLATE (/orders/{id}), never the raw path, to bound cardinality.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
            HTTP_LATENCY.labels(request.method, route).observe(duration)
            log.log(
                logging.DEBUG if request.url.path in QUIET_PATHS else logging.INFO,
                "request",
                extra={"fields": {
                    "method": request.method, "route": route, "status": status,
                    "duration_ms": round(duration * 1000, 1),
                }},
            )
            request_id_var.reset(token)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
