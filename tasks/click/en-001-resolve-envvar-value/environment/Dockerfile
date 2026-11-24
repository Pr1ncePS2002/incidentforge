# pallets/click 8.5.1 at a pinned commit; installed the way the project documents: pip install -e . and pytest
FROM python:3.12-slim-bookworm

ARG REPO_URL=https://github.com/pallets/click.git
ARG REPO_COMMIT=cf19179e8e2fd54c601378cec9e0d21bb12b6fb1

# the pager tests run real less
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates less \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --quiet "$REPO_URL" /app \
 && git checkout --quiet "$REPO_COMMIT" \
 && git config --global user.email task@incidentforge.local \
 && git config --global user.name incidentforge

# pytest matches the repo's uv.lock; coverage is only used by the failure map's coverage run
ENV VIRTUAL_ENV=/app/.venv PATH="/app/.venv/bin:$PATH" PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /app/.venv \
 && pip install -q -e . pytest==9.0.2 coverage==7.10.7

COPY run_tests.sh /usr/local/bin/run_tests
RUN chmod +x /usr/local/bin/run_tests
