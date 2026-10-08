#!/usr/bin/env bash
# NeoForge server entrypoint: EULA, server.properties, mod activation, then exec the server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../common/lib.sh
source "${SCRIPT_DIR}/common/lib.sh"

cd /data

require_eula
apply_server_properties
catalog_activate "${MODS:-}" /data/mods MODS
maybe_exit_after_activation

ARGS_FILE="/opt/server/libraries/net/neoforged/neoforge/${LOADER_VERSION:?LOADER_VERSION is not set}/unix_args.txt"
[[ -f "${ARGS_FILE}" ]] || die "NeoForge launch arguments not found: ${ARGS_FILE}"

# Intentional word splitting (no globbing) for the memory flags and JVM_OPTS.
read -r -a mem_args <<< "$(java_memory_args)"
read -r -a extra_args <<< "${JVM_OPTS:-}"

log "Starting NeoForge server (Minecraft ${MINECRAFT_VERSION:-unknown}, NeoForge ${LOADER_VERSION})"
exec java "${mem_args[@]}" "${extra_args[@]}" "@${ARGS_FILE}" nogui
