# generic go target: repo at /app with modules downloaded so tests run offline
FROM golang:1.25-bookworm

ARG REPO_URL=REPLACE_ME
ARG REPO_COMMIT=REPLACE_ME

WORKDIR /app
RUN git clone --quiet "$REPO_URL" /app \
 && git checkout --quiet "$REPO_COMMIT" \
 && git config --global user.email task@incidentforge.local \
 && git config --global user.name incidentforge \
 && go mod download \
 && go build ./... \
 && go test -count=1 -run '^$' ./... >/dev/null

COPY run_tests.sh /usr/local/bin/run_tests
RUN chmod +x /usr/local/bin/run_tests
