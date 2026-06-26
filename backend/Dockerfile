# ---------- Stage 1: build dependencies into a venv ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Create an isolated venv we can copy wholesale into the runtime image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


# ---------- Stage 2: slim runtime image ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Bring over only the built venv — no build tools / caches in the final image.
COPY --from=builder /opt/venv /opt/venv

# App source (see .dockerignore for what's excluded, e.g. .env, frontend/).
COPY . .

# Run as a non-root user.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Railway injects $PORT at runtime; fall back to 8000 for local `docker run`.
# Shell form so ${PORT} expands. --proxy-headers makes the per-client rate
# limiter see the real client IP via X-Forwarded-For behind Railway's proxy.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
