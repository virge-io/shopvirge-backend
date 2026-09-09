FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /uvx /bin/

WORKDIR /app

# Fail the build if uv.lock is out of date with pyproject.toml, and write
# bytecode so container start-up doesn't pay the compile cost.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_LOCKED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY ./server /app/server
COPY ./migrations /app/migrations
COPY ./alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080"]
