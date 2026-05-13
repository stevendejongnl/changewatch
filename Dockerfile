FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv sync --no-dev --frozen

COPY app/ ./app/
COPY monitors/ ./monitors/

ENV DB_PATH=/data/state.db
ENV MONITORS_DIR=/app/monitors

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
