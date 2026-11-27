# syntax=docker/dockerfile:1
FROM rust:1.99.1-bookworm AS build
ARG X402_REV=03b45e4caa6fe82af64a8fff968f4d248999ea69
RUN apt-get update && apt-get install -y --no-install-recommends clang libclang-dev cmake pkg-config python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/mikeperry-tor/x402_treazury.git \
    && git fetch --depth=1 origin "${X402_REV}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${X402_REV}"
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/src/target \
    CARGO_TARGET_DIR=/src/target make build CARGO_ARGS='--bin x402_treazury' \
    && install -D target/release/x402_treazury /out/x402_treazury
COPY components/x402_treazury/render-config.py components/x402_treazury/endpoints.py /opt/
RUN python3 /opt/render-config.py /src/examples/deployments/research_desk.toml /out/research_desk.toml

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgcc-s1 libstdc++6 libssl3 python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10003 x402_treazury \
    && useradd --uid 10003 --gid 10003 --home-dir /var/lib/x402 --no-create-home x402_treazury \
    && install -d -o 10003 -g 10003 -m 0700 /var/lib/x402 \
    && install -d -m 0755 /opt/x402/examples/deployments
COPY --from=build /out/x402_treazury /opt/x402/bin/x402_treazury
COPY --chmod=0755 components/x402_treazury/x402_treazury-wrapper.py /usr/local/bin/x402_treazury
COPY --from=build /out/research_desk.toml /opt/x402/defaults/deployments/research_desk.toml
COPY --from=build /src/providers /opt/x402/providers
COPY components/x402_treazury/entrypoint.py /opt/x402_treazury-entrypoint.py
COPY components/x402_treazury/onboarding.py components/x402_treazury/endpoints.py /opt/
USER 10003:10003
ENV HOME=/var/lib/x402
ENTRYPOINT ["python3", "/opt/x402_treazury-entrypoint.py"]
CMD ["serve"]
