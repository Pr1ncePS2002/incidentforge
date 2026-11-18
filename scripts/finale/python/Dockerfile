# generic python target: repo at /app, deps from uv.lock, pyproject or requirements, pytest available
FROM python:3.12-slim-bookworm

ARG REPO_URL=REPLACE_ME
ARG REPO_COMMIT=REPLACE_ME

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app
RUN git clone --quiet "$REPO_URL" /app \
 && git checkout --quiet "$REPO_COMMIT" \
 && git config --global user.email task@incidentforge.local \
 && git config --global user.name incidentforge

ENV UV_LINK_MODE=copy VIRTUAL_ENV=/app/.venv PATH="/app/.venv/bin:$PATH"
# first matching install strategy wins; pytest is always added so run_tests works
RUN if [ -f uv.lock ]; then uv sync --frozen --all-extras --all-groups || uv sync --frozen; \
    else uv venv -q /app/.venv \
      && if [ -f pyproject.toml ] || [ -f setup.py ]; then \
           uv pip install -q -e ".[test]" 2>/dev/null || uv pip install -q -e ".[dev]" 2>/dev/null || uv pip install -q -e .; fi \
      && for r in requirements.txt requirements-dev.txt requirements-test.txt requirements/test.txt; do \
           [ -f "$r" ] && uv pip install -q -r "$r" || true; done; \
    fi \
 && uv pip install -q pytest

COPY run_tests.sh /usr/local/bin/run_tests
RUN chmod +x /usr/local/bin/run_tests
