# Contexto de build: raiz do repositório (precisa de loader/ e dbt/).
#   docker build -f loader/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY loader/pyproject.toml loader/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY loader/src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY dbt ./dbt
# Pacotes do dbt baixados no build: a execução não depende da internet.
RUN GCP_PROJECT=build .venv/bin/dbt deps --project-dir dbt --profiles-dir dbt

FROM python:3.12-slim-trixie
RUN useradd --create-home app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/dbt /app/dbt
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DBT_DIR=/app/dbt \
    DBT_TARGET_PATH=/tmp/dbt/target \
    DBT_LOG_PATH=/tmp/dbt/logs \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false
USER app
ENTRYPOINT ["telemetry-loader"]
