#!/usr/bin/env bash
# Paper server entrypoint: EULA, server.properties, plugin activation, then exec the server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../common/lib.sh
source "${SCRIPT_DIR}/common/lib.sh"

cd /data

require_eula
apply_server_properties
catalog_activate "${PLUGINS:-}" /data/plugins PLUGINS
maybe_exit_after_activation

[[ -f /opt/server/paper.jar ]] || die "Paper launcher not found: /opt/server/paper.jar"
{ compgen -G '/opt/server/cache/patched_*.jar' || compgen -G '/opt/server/versions/*/*.jar'; } >/dev/null \
    || die "Patched Paper jar not found in /opt/server/{cache,versions} (broken image)"

# Intentional word splitting (no globbing) for the memory flags and JVM_OPTS.
read -r -a mem_args <<< "$(java_memory_args)"
read -r -a extra_args <<< "${JVM_OPTS:-}"

# Paperclip (paper.jar) looks for cache/, libraries/ and versions/ in the
# directory named by bundlerRepoDir (default: the working directory). The build
# already patched everything into /opt/server, so pointing it there means the
# launcher finds the cached patched jar and downloads nothing. The world,
# configs, logs and plugins stay in the working directory (/data).
log "Starting Paper server (Minecraft ${MINECRAFT_VERSION:-unknown}, build ${LOADER_VERSION:-unknown})"
exec java "${mem_args[@]}" \
    -DbundlerRepoDir=/opt/server \
    "${extra_args[@]}" \
    -jar /opt/server/paper.jar nogui
