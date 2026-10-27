# TODO (you): containerise the app in ./app.
# We're looking for a lean, multi-stage, non-root image with a sensible healthcheck.
# This single-stage stub just gets you a baseline to improve on.
FROM python:3.12-slim
WORKDIR /srv
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
