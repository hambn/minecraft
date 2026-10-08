# syntax=docker/dockerfile:1
# Build context: the staged CTX produced by `cli.py stage` (not the repository).
# Build args come from CTX/build-args.env.
ARG BUILDER_IMAGE
ARG BASE_IMAGE

# ---------------------------------------------------------------------------
# Builder stage: fetch the exact Pumpkin commit and build the release binary.
# Needs network access (git + crates.io) at build time only.
# ---------------------------------------------------------------------------
FROM ${BUILDER_IMAGE} AS builder
ARG PUMPKIN_REPO
ARG PUMPKIN_COMMIT
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
RUN if ! command -v git >/dev/null || ! command -v cmake >/dev/null || ! command -v pkg-config >/dev/null; then \
        apt-get update; \
        apt-get install -y --no-install-recommends ca-certificates git cmake pkg-config; \
        rm -rf /var/lib/apt/lists/*; \
    fi
WORKDIR /src
RUN test -n "${PUMPKIN_REPO}" && test -n "${PUMPKIN_COMMIT}"; \
    git init -q .; \
    git remote add origin "${PUMPKIN_REPO}"; \
    git fetch --depth 1 origin "${PUMPKIN_COMMIT}"; \
    git checkout -q FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "${PUMPKIN_COMMIT}"
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    cargo build --release --locked; \
    install -D -m 0755 target/release/pumpkin /out/pumpkin

# ---------------------------------------------------------------------------
# Final image: Debian slim runtime, no Java, no Mojang code.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE}
ARG MINECRAFT_VERSION
ARG LOADER_VERSION
ARG PUMPKIN_COMMIT

LABEL org.opencontainers.image.source="https://github.com/hambn/minecraft" \
      org.opencontainers.image.version="${MINECRAFT_VERSION}" \
      io.github.hambn.minecraft.server="pumpkin" \
      io.github.hambn.minecraft.catalog-env="PLUGINS" \
      io.github.hambn.minecraft.catalog-dir="/data/plugins" \
      io.github.hambn.minecraft.ready-pattern='Started server|You now can connect|Done \(' \
      io.github.hambn.minecraft.loader-version="${LOADER_VERSION}" \
      io.github.hambn.minecraft.pumpkin-commit="${PUMPKIN_COMMIT}"

# bash, awk, coreutils and grep come with Debian; ca-certificates is for TLS
# (online-mode session checks). Run as 1000:1000.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    if getent passwd 1000 >/dev/null; then userdel "$(getent passwd 1000 | cut -d: -f1)"; fi; \
    if getent group 1000 >/dev/null; then groupdel "$(getent group 1000 | cut -d: -f1)"; fi; \
    groupadd --gid 1000 minecraft; \
    useradd --uid 1000 --gid 1000 --home-dir /data --no-create-home --shell /usr/sbin/nologin minecraft; \
    mkdir -p /data /opt/scripts /opt/server; \
    chown 1000:1000 /data

COPY --from=builder --chmod=0755 /out/pumpkin /opt/server/pumpkin
COPY catalog/ /opt/catalog/
COPY --chmod=0755 entrypoint.sh /opt/scripts/entrypoint.sh
COPY --chmod=0755 common/ /opt/scripts/common/

ENV MINECRAFT_VERSION=${MINECRAFT_VERSION} \
    LOADER_VERSION=${LOADER_VERSION}

EXPOSE 25565
VOLUME /data
WORKDIR /data
USER 1000:1000
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/scripts/entrypoint.sh"]
