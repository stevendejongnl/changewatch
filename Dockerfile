# ── Frontend build ─────────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit
COPY frontend/ ./
RUN npm run build
# Output is at /app/static/editor.js (vite outDir: "../app/static")

# ── Python app ─────────────────────────────────────────────────────
FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app/ ./app/
COPY monitors/ ./monitors/
COPY --from=frontend /app/static/editor.js ./app/static/editor.js

ENV DB_PATH=/data/state.db
ENV MONITORS_DIR=/app/monitors

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
