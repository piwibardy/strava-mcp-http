# Build stage
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

RUN mkdir -p /app/data
VOLUME /app/data

EXPOSE 8000

CMD ["strava-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
