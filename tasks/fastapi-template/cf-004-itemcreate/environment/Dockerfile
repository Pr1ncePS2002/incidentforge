# fastapi-template backend at a pinned commit, postgres inside the same container
FROM python:3.14-slim-trixie

ARG REPO_URL=https://github.com/fastapi/full-stack-fastapi-template.git
ARG REPO_COMMIT=77e550a73bb49dd2967622c5ed11bf7a49603c93

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates postgresql curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app
RUN git clone --quiet "$REPO_URL" /app \
 && git checkout --quiet "$REPO_COMMIT" \
 && rm -rf frontend .github \
 && git config --global user.email task@incidentforge.local \
 && git config --global user.name incidentforge

ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN uv sync --frozen --package app

# db the backend expects; env vars override the repo's .env
ENV POSTGRES_PASSWORD=changethis \
    DATABASE_URL=postgresql://postgres:changethis@localhost:5432/app \
    FASTAPI_ENV=development
RUN pg_ctlcluster "$(ls /etc/postgresql)" main start \
 && runuser -u postgres -- psql -qc "ALTER USER postgres PASSWORD 'changethis';" \
 && runuser -u postgres -- createdb app \
 && pg_ctlcluster "$(ls /etc/postgresql)" main stop

COPY run_tests.sh /usr/local/bin/run_tests
RUN chmod +x /usr/local/bin/run_tests

WORKDIR /app/backend
