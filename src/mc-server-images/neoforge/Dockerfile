# syntax=docker/dockerfile:1
# Build context: the staged CTX produced by `cli.py stage` (not the repository).
# Build args come from CTX/build-args.env.
ARG BASE_IMAGE

# ---------------------------------------------------------------------------
# Installer stage: downloads the vanilla server and libraries, runs the
# NeoForge processors (needs network access at build time only).
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS installer
ARG MINECRAFT_VERSION
ARG LOADER_VERSION
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
WORKDIR /build
COPY downloads/installer.jar ./
RUN java -jar installer.jar --install-server /opt/server; \
    args="/opt/server/libraries/net/neoforged/neoforge/${LOADER_VERSION}/unix_args.txt"; \
    test -f "${args}"; \
    # Make the launch arguments independent of the working directory. The file
    # references everything as `libraries/...` (in -p / -classpath /
    # -DlegacyClassPath entries, ':'-separated) plus `-DlibraryDirectory=libraries`.
    sed -i -E \
        -e 's#(^|[[:space:]:=@"])libraries/#\1/opt/server/libraries/#g' \
        -e 's#=libraries$#=/opt/server/libraries#' \
        "${args}"; \
    if grep -nE '(^|[[:space:]:=@"])libraries(/|$)' "${args}"; then \
        echo "unix_args.txt still has relative libraries paths" >&2; exit 1; \
    fi; \
    grep -qF -- '-DlibraryDirectory=/opt/server/libraries' "${args}"; \
    # Every absolute jar the args reference must exist.
    grep -oE '/opt/server/libraries/[^[:space:]:"]+\.jar' "${args}" | sort -u | \
        while read -r jar; do test -f "${jar}" || { echo "missing ${jar}" >&2; exit 1; }; done; \
    rm -f /opt/server/run.sh /opt/server/run.bat /opt/server/user_jvm_args.txt \
          "$(dirname "${args}")/win_args.txt"; \
    find /opt/server -maxdepth 1 -name '*.log' -delete; \
    rm -f /opt/server/installer.jar.log; \
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
      io.github.hambn.minecraft.server="neoforge" \
      io.github.hambn.minecraft.catalog-env="MODS" \
      io.github.hambn.minecraft.catalog-dir="/data/mods" \
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

COPY --from=installer /opt/server /opt/server
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
