#!/usr/bin/env bash
# Pumpkin server entrypoint: configuration overrides, plugin activation, then exec the server.
#
# No EULA is required (Pumpkin contains no Mojang code) and there is no
# server.properties or JVM: MEMORY, INIT_MEMORY and JVM_OPTS do not apply.
#
# Configuration lives in /data/config/configuration.toml (Pumpkin creates it
# with defaults on first start). PROP_<NAME>=value sets the top-level key
# <name> (lowercased, underscores kept, TOML style), e.g.
#   PROP_ONLINE_MODE=false  ->  online_mode = false
#   PROP_MAX_PLAYERS=50     ->  max_players = 50
#   PROP_MOTD="Hello"       ->  motd = "Hello"
# ONLINE_MODE is a shortcut for PROP_ONLINE_MODE. true/false/numbers are
# written bare, anything else as a quoted string. Keys inside [tables] and
# features.toml are not touched; edit them in the /data volume.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../common/lib.sh
source "${SCRIPT_DIR}/common/lib.sh"

# apply_pumpkin_config [FILE]
apply_pumpkin_config() {
  local file="${1:-/data/config/configuration.toml}" tmp var name
  if [[ -n "${ONLINE_MODE:-}" && -z "${PROP_ONLINE_MODE:-}" ]]; then
    export PROP_ONLINE_MODE="${ONLINE_MODE}"
  fi
  # Nothing to do: leave Pumpkin to create its own default file.
  if ! compgen -e | grep -q '^PROP_'; then return 0; fi
  for var in $(compgen -e | grep '^PROP_' || true); do
    name="${var#PROP_}"
    name="${name,,}"
    [[ "$name" =~ ^[a-z][a-z0-9_]*$ ]] || die "invalid ${var}: key '${name}' must match [a-z][a-z0-9_]*"
  done
  mkdir -p -- "$(dirname -- "$file")"
  if [[ ! -e "$file" ]]; then : >"$file"; fi
  tmp="$(mktemp "${file}.XXXXXX")"
  if ! awk '
    function fmt(v) {
      if (v ~ /^[Tt][Rr][Uu][Ee]$/) return "true"
      if (v ~ /^[Ff][Aa][Ll][Ss][Ee]$/) return "false"
      if (v ~ /^-?[0-9]+(\.[0-9]+)?$/) return v
      if (v ~ /^"/ || v ~ /^\[/) return v
      gsub(/\\/, "\\\\", v)
      gsub(/"/, "\\\"", v)
      return "\"" v "\""
    }
    function flush(   k) {
      if (flushed) return
      flushed = 1
      for (k in want) if (!(k in seen)) { print k " = " want[k]; any = 1 }
      if (any) print ""
    }
    BEGIN {
      for (k in ENVIRON) {
        if (substr(k, 1, 5) != "PROP_") continue
        name = tolower(substr(k, 6))
        val = ENVIRON[k]
        gsub(/[\r\n]/, " ", val)
        want[name] = fmt(val)
      }
    }
    /^[ \t]*\[/ { flush(); intable = 1; print; next }
    {
      if (!intable && $0 !~ /^[ \t]*#/ && (eq = index($0, "=")) > 0) {
        key = substr($0, 1, eq - 1)
        gsub(/[ \t]/, "", key)
        if (key in want) { print key " = " want[key]; seen[key] = 1; next }
      }
      print
    }
    END { flush() }' "$file" >"$tmp"; then
    rm -f -- "${tmp:?}"
    die "failed to process $file"
  fi
  cat -- "$tmp" >"$file"
  rm -f -- "${tmp:?}"
  for var in $(compgen -e | grep '^PROP_' || true); do
    name="${var#PROP_}"
    log "configuration.toml: set ${name,,}"
  done
}

cd /data

apply_pumpkin_config
catalog_activate "${PLUGINS:-}" /data/plugins PLUGINS
maybe_exit_after_activation

[[ -x /opt/server/pumpkin ]] || die "Pumpkin binary not found: /opt/server/pumpkin"

# Pumpkin reads config/, world/ and plugins/ relative to the working directory
# (/data) and listens on 0.0.0.0:25565 by default.
log "Starting Pumpkin server (Minecraft ${MINECRAFT_VERSION:-unknown}, commit ${LOADER_VERSION:-unknown})"
exec /opt/server/pumpkin
