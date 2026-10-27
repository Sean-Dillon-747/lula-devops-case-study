# Multi-stage: build deps in a throwaway stage, ship only the venv + code.
# For production, pin the base by digest (python:3.12-slim@sha256:...) and let
# Dependabot/Renovate bump it, so builds are reproducible.
ARG PYTHON_IMAGE=python:3.12-slim

# ---- build stage -------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Requirements first so this layer is cached until dependencies change.
WORKDIR /build
COPY app/requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime stage -----------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Fixed, non-root UID so file permissions and Kubernetes runAsUser are predictable.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /srv
COPY --from=builder /opt/venv /opt/venv
# Code stays owned by root: the app user can read it but not modify it.
COPY app/ ./
# Same image runs the migration job (python migrations/migrate.py up), so the
# schema change and the code that needs it ship as one versioned artifact.
COPY migrations/ ./migrations/

USER 10001
EXPOSE 8000

# python:slim has no curl/wget, so probe with the stdlib. Liveness only: no DB call.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=2)"]

# Exec form: uvicorn is PID 1 and receives SIGTERM directly for graceful shutdown.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
