FROM python:3.12-slim

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE LICENSE-DATA ./
COPY src ./src
RUN uv sync --locked --no-dev --extra anthropic
COPY config ./config
COPY sources ./sources

# Runs one pass every 30 minutes. The site is written to /app/build/site (a shared volume).
CMD ["sh", "-c", "while true; do /app/.venv/bin/haqiqat run --once; sleep 1800; done"]
