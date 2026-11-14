# syntax=docker/dockerfile:1
FROM golang:1.26-bookworm AS build
ARG TEEP_REV=eecd7e41a6d9f0b5a8324f2c174e25c831b9c941
WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/13rac1/teep.git \
    && git fetch --depth=1 origin "${TEEP_REV}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${TEEP_REV}"
RUN --mount=type=cache,target=/go/pkg/mod go mod download
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath \
    -ldflags="-X main.Version=${TEEP_REV} -X main.Commit=${TEEP_REV}" \
    -o /out/teep ./cmd/teep

FROM alpine:3.24
RUN apk add --no-cache ca-certificates curl \
    && addgroup -g 10002 teep \
    && adduser -D -u 10002 -G teep teep
COPY --from=build /out/teep /usr/local/bin/teep
USER 10002:10002
ENV TEEP_LISTEN_ADDR=127.0.0.1:8337
HEALTHCHECK --interval=10s --timeout=6s --start-period=20s --retries=6 \
    CMD curl --fail --silent --max-time 5 http://127.0.0.1:8337/health >/dev/null || exit 1
ENTRYPOINT ["teep"]
CMD ["serve"]
