# miniflux at a pinned commit; modules and build cache are warmed so tests run offline
FROM golang:1.26.4-trixie

ARG REPO_URL=https://github.com/miniflux/v2.git
ARG REPO_COMMIT=b31f7867f4a1ad9b4abfcebd376c94cecf5f1942

WORKDIR /app
RUN git clone --quiet "$REPO_URL" /app \
 && git checkout --quiet "$REPO_COMMIT" \
 && rm -rf .github \
 && git config --global user.email task@incidentforge.local \
 && git config --global user.name incidentforge

ENV GOTOOLCHAIN=local CGO_ENABLED=0 GOFLAGS=-mod=readonly
RUN go mod download && go test -count=1 -run '^$' ./... >/dev/null

# no network after build; a missing module fails fast instead of hanging
ENV GOPROXY=off

COPY run_tests.sh /usr/local/bin/run_tests
RUN chmod +x /usr/local/bin/run_tests
