# syntax=docker/dockerfile:1
# Build context: the staged CTX produced by `cli.py stage` (not the repository).
# Build args come from CTX/build-args.env.
ARG BASE_IMAGE

# ---------------------------------------------------------------------------
# Installer stage: Fabric loader libraries + launcher jar (needs maven access).
# The vanilla server jar is staged (and sha1-verified) by CI, not downloaded here.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS installer
ARG MINECRAFT_VERSION
ARG LOADER_VERSION
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
WORKDIR /build
COPY downloads/installer.jar downloads/server.jar ./
RUN java -jar installer.jar server \
        -mcversion "${MINECRAFT_VERSION}" \
        -loader "${LOADER_VERSION}" \
        -dir /opt/server; \
    cp server.jar /opt/server/server.jar; \
    # The launcher only reads this file from its working directory (/data at
    # runtime), so the entrypoint also passes -Dfabric.gameJarPath. Kept so the
    # launcher also works when started with cwd=/opt/server.
    printf 'serverJar=/opt/server/server.jar\n' > /opt/server/fabric-server-launcher.properties; \
    test -f /opt/server/fabric-server-launch.jar; \
    find /opt/server -name '*.log' -delete; \
    chmod -R a+rX /opt/server

# ---------------------------------------------------------------------------
# Final image
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE}
ARG MINECRAFT_VERSION
ARG LOADER_VERSION
ARG JAVA_MAJOR
ARG INSTALLER_VERSION

LABEL org.opencontainers.image.source="https://github.com/hambn/minecraft" \
      org.opencontainers.image.version="${MINECRAFT_VERSION}" \
      io.github.hambn.minecraft.server="fabric" \
      io.github.hambn.minecraft.catalog-env="MODS" \
      io.github.hambn.minecraft.catalog-dir="/data/mods" \
      io.github.hambn.minecraft.ready-pattern='Done \(\d+(?:[.,]\d+)?s\)! For help, type' \
      io.github.hambn.minecraft.loader-version="${LOADER_VERSION}" \
      io.github.hambn.minecraft.java-major="${JAVA_MAJOR}" \
      io.github.hambn.minecraft.fabric-installer="${INSTALLER_VERSION}"

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
