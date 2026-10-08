#!/usr/bin/env bash
# Fabric server entrypoint: EULA, server.properties, mod activation, then exec the server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../common/lib.sh
source "${SCRIPT_DIR}/common/lib.sh"

cd /data

require_eula
apply_server_properties
catalog_activate "${MODS:-}" /data/mods MODS
maybe_exit_after_activation

# Intentional word splitting (no globbing) for the memory flags and JVM_OPTS.
read -r -a mem_args <<< "$(java_memory_args)"
read -r -a extra_args <<< "${JVM_OPTS:-}"

# The Fabric launcher reads fabric-server-launcher.properties from the working
# directory (/data); point it at the baked vanilla jar instead.
log "Starting Fabric server (Minecraft ${MINECRAFT_VERSION:-unknown}, loader ${LOADER_VERSION:-unknown})"
exec java "${mem_args[@]}" \
    -Dfabric.gameJarPath=/opt/server/server.jar \
    "${extra_args[@]}" \
    -jar /opt/server/fabric-server-launch.jar nogui
