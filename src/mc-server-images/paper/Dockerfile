# syntax=docker/dockerfile:1
# Build context: the staged CTX produced by `cli.py stage` (not the repository).
# Build args come from CTX/build-args.env.
ARG BASE_IMAGE

# ---------------------------------------------------------------------------
# Patch stage: Paperclip downloads the vanilla server jar and applies Paper's
# patches (needs network access at build time only). The paper.jar itself is
# staged (and sha256-verified) by CI.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS patcher
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
WORKDIR /opt/server
COPY downloads/paper.jar /opt/server/paper.jar
# paperclip.patchonly=true: build cache/ (patched + vanilla jars), libraries/ and
# versions/ next to paper.jar, then exit without starting the server.
RUN java -Dpaperclip.patchonly=true -jar paper.jar; \
    ls /opt/server/cache/patched_*.jar >/dev/null; \
    test -d /opt/server/libraries; \
    find /opt/server -maxdepth 1 -name '*.log' -delete; \
    rm -rf /opt/server/logs; \
    chmod -R a+rX /opt/server

# ---------------------------------------------------------------------------
# Final image
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE}
ARG MINECRAFT_VERSION
ARG LOADER_VERSION
ARG JAVA_MAJOR

LABEL org.opencontainers.image.source="https://github.com/hambn/minecraft" \
      org.opencontainers.image.version="${MINECRAFT_VERSION}" \
      io.github.hambn.minecraft.server="paper" \
      io.github.hambn.minecraft.catalog-env="PLUGINS" \
      io.github.hambn.minecraft.catalog-dir="/data/plugins" \
      io.github.hambn.minecraft.ready-pattern='Done \(\d+(?:[.,]\d+)?s\)! For help, type' \
      io.github.hambn.minecraft.loader-version="${LOADER_VERSION}" \
      io.github.hambn.minecraft.java-major="${JAVA_MAJOR}"

# Run as 1000:1000. Ubuntu-based Temurin images ship an `ubuntu` user/group with
# that ID; remove whatever owns 1000 and create a dedicated user.
RUN set -eux; \
    if getent passwd 1000 >/dev/null; then userdel "$(getent passwd 1000 | cut -d: -f1)"; fi; \
    if getent group 1000 >/dev/null; then groupdel "$(getent group 1000 | cut -d: -f1)"; fi; \
    groupadd --gid 1000 minecraft; \
    useradd --uid 1000 --gid 1000 --home-dir /data --no-create-home --shell /usr/sbin/nologin minecraft; \
    mkdir -p /data /opt/scripts; \
    chown 1000:1000 /data

COPY --from=patcher /opt/server /opt/server
COPY catalog/ /opt/catalog/
COPY --chmod=0755 entrypoint.sh /opt/scripts/entrypoint.sh
COPY --chmod=0755 common/ /opt/scripts/common/

ENV MINECRAFT_VERSION=${MINECRAFT_VERSION} \
    LOADER_VERSION=${LOADER_VERSION} \
    MEMORY=2G

EXPOSE 25565
VOLUME /data
WORKDIR /data
USER 1000:1000
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/scripts/entrypoint.sh"]
