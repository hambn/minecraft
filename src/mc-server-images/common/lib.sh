#!/usr/bin/env bash
# Shared helpers sourced by every server entrypoint:
#   source /opt/scripts/common/lib.sh
#
# Works under `set -euo pipefail`. Needs bash >= 4.4 plus coreutils, grep, sed
# and awk (POSIX awk is enough, mawk included).
#
# Functions
#   log MESSAGE...                          informational line on stderr
#   die MESSAGE...                          error line on stderr, exit 1
#   catalog_info [minecraft|loader]         image version info
#   catalog_activate SELECTION DIR ENV      activate selected catalog entries
#   maybe_exit_after_activation             exit 0 when ACTIVATE_ONLY=true
#   require_eula [DIR]                      demand EULA=TRUE, write DIR/eula.txt
#   apply_server_properties [FILE]          PROP_* -> server.properties
#   java_memory_args                        print -Xms/-Xmx flags
#
# Environment
#   CATALOG_DIR  catalog location (default /opt/catalog); tests override it.
#   MINECRAFT_VERSION, LOADER_VERSION  win over $CATALOG_DIR/catalog.json.

if [ -n "${_MC_COMMON_LIB_LOADED:-}" ]; then
  return 0
fi
_MC_COMMON_LIB_LOADED=1

# ---------------------------------------------------------------- logging

log() {
  printf '[%s] %s\n' "${LOG_PREFIX:-mc-image}" "$*" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "${LOG_PREFIX:-mc-image}" "$*" >&2
  exit 1
}

# ---------------------------------------------------------------- helpers

_catalog_dir() {
  printf '%s' "${CATALOG_DIR:-/opt/catalog}"
}

# Strip leading and trailing whitespace.
_trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# Print the value of a top-level key of a JSON file (strings and numbers;
# null prints nothing). Entries nested deeper never match.
_json_top_value() {
  local key="$1" file="$2"
  awk -v key="$key" '
    function skipws() { while (j <= n && substr(buf, j, 1) ~ /[ \t\r\n]/) j++ }
    function readstr(   out, ch) {
      out = ""
      j++
      while (j <= n) {
        ch = substr(buf, j, 1)
        if (ch == "\\") { out = out substr(buf, j, 2); j += 2; continue }
        if (ch == "\"") break
        out = out ch
        j++
      }
      j++
      return out
    }
    { buf = buf $0 "\n" }
    END {
      n = length(buf); depth = 0; j = 1
      while (j <= n) {
        c = substr(buf, j, 1)
        if (c == "{" || c == "[") { depth++; j++ }
        else if (c == "}" || c == "]") { depth--; j++ }
        else if (c == "\"") {
          s = readstr()
          if (depth == 1) {
            skipws()
            if (substr(buf, j, 1) == ":" && s == key) {
              j++
              skipws()
              if (substr(buf, j, 1) == "\"") { print readstr() }
              else {
                v = ""
                while (j <= n && substr(buf, j, 1) !~ /[ \t\r\n,}\]]/) { v = v substr(buf, j, 1); j++ }
                if (v != "null") print v
              }
              exit
            }
          }
        } else j++
      }
    }' "$file"
}

# catalog_info [minecraft|loader]
# Without an argument prints "Minecraft <v>, loader <v>". Sources: env
# MINECRAFT_VERSION / LOADER_VERSION, then $CATALOG_DIR/catalog.json, else "unknown".
catalog_info() {
  local what="${1:-}" mc="${MINECRAFT_VERSION:-}" lv="${LOADER_VERSION:-}"
  local json
  json="$(_catalog_dir)/catalog.json"
  if [ -r "$json" ]; then
    if [ -z "$mc" ]; then mc="$(_json_top_value minecraft_version "$json")"; fi
    if [ -z "$lv" ]; then lv="$(_json_top_value loader_version "$json")"; fi
  fi
  mc="${mc:-unknown}"
  lv="${lv:-unknown}"
  case "$what" in
    minecraft) printf '%s' "$mc" ;;
    loader) printf '%s' "$lv" ;;
    '') printf 'Minecraft %s, loader %s' "$mc" "$lv" ;;
    *) return 2 ;;
  esac
}

# A file name that is safe to create or remove directly inside the target dir.
_safe_name() {
  local n="$1"
  case "$n" in
    '' | . | .. | -) return 1 ;;
    */* | *$'\n'*) return 1 ;;
    .catalog-managed) return 1 ;;
  esac
  return 0
}

# ------------------------------------------------------- catalog activation

# catalog_activate SELECTION TARGET_DIR ENV_NAME
#   SELECTION   comma-separated catalog IDs (whitespace ignored, may be empty)
#   TARGET_DIR  directory scanned by the server (/data/mods, /data/plugins)
#   ENV_NAME    variable the user set (MODS/PLUGINS), used in messages only
# Everything is validated before TARGET_DIR is touched.
catalog_activate() {
  local selection="${1-}" target="${2:?catalog_activate: target dir required}" env_name="${3:-MODS}"
  local cdir tsv mc lv
  cdir="$(_catalog_dir)"
  tsv="$cdir/catalog.tsv"
  mc="$(catalog_info minecraft)"
  lv="$(catalog_info loader)"

  # ---- load the catalog
  local -A c_status=() c_sel=() c_file=() c_clos=() c_conf=() c_reason=()
  local -a c_order=()
  local f_id f_status f_sel f_kind f_file f_clos f_conf f_reason
  if [ -r "$tsv" ]; then
    while IFS=$'\t' read -r f_id f_status f_sel f_kind f_file f_clos f_conf f_reason || [ -n "${f_id:-}" ]; do
      f_reason="${f_reason%$'\r'}"
      case "$f_id" in '' | '#'*) continue ;; esac
      if [ "$f_file" = "-" ]; then f_file=""; fi
      if [ "$f_clos" = "-" ]; then f_clos=""; fi
      if [ "$f_conf" = "-" ]; then f_conf=""; fi
      if [ "$f_reason" = "-" ]; then f_reason=""; fi
      c_status[$f_id]="$f_status"
      c_sel[$f_id]="$f_sel"
      c_file[$f_id]="$f_file"
      c_clos[$f_id]="$f_clos"
      c_conf[$f_id]="$f_conf"
      c_reason[$f_id]="$f_reason"
      c_order+=("$f_id")
    done <"$tsv"
  fi

  # ---- parse the selection
  local -a requested=()
  local -A seen_req=()
  local -a parts=()
  local part
  if [ -n "$selection" ]; then
    IFS=',' read -r -a parts <<<"$selection" || true
    for part in "${parts[@]}"; do
      part="$(_trim "$part")"
      if [ -z "$part" ] || [ -n "${seen_req[$part]+x}" ]; then continue; fi
      seen_req[$part]=1
      requested+=("$part")
    done
  fi
  if [ "${#requested[@]}" -gt 0 ] && [ ! -r "$tsv" ]; then
    die "$env_name: cannot activate '${requested[0]}': catalog $tsv is missing. Image: Minecraft $mc, loader $lv. Reason: this image has no catalog."
  fi

  # ---- validate selected entries and expand closures
  local -a final_ids=()
  local -A in_final=()
  local id m status reason blockers known
  local -a members=() extra=()
  for id in "${requested[@]}"; do
    if [ -z "${c_status[$id]+x}" ]; then
      known=""
      for m in "${c_order[@]}"; do
        if [ "${c_status[$m]}" = "compatible" ] && [ "${c_sel[$m]}" = "yes" ]; then known+="${known:+, }$m"; fi
      done
      die "$env_name: cannot activate '$id': unknown catalog entry. Image: Minecraft $mc, loader $lv. Reason: '$id' is not part of this image's catalog (selectable IDs: ${known:-none})."
    fi
    status="${c_status[$id]}"
    reason="${c_reason[$id]}"
    case "$status" in
      compatible)
        if [ "${c_sel[$id]}" != "yes" ]; then
          blockers=""
          IFS=',' read -r -a members <<<"${c_clos[$id]}" || true
          for m in "${members[@]}"; do
            m="$(_trim "$m")"
            if [ -z "$m" ] || [ "$m" = "$id" ]; then continue; fi
            if [ -z "${c_status[$m]+x}" ]; then
              blockers+="${blockers:+, }$m (not in catalog)"
            elif [ "${c_status[$m]}" != "compatible" ]; then
              blockers+="${blockers:+, }$m (${c_status[$m]})"
            fi
          done
          die "$env_name: cannot activate '$id': entry is not selectable because its dependencies cannot be activated${blockers:+ ($blockers)}. Image: Minecraft $mc, loader $lv. Reason: ${reason:-a required dependency is unavailable for this image}."
        fi
        ;;
      unsupported_fallback)
        die "$env_name: cannot activate '$id': entry is bundled only as an unsupported fallback. Image: Minecraft $mc, loader $lv. Reason: ${reason:-not compatible with this Minecraft version or loader}."
        ;;
      unavailable)
        die "$env_name: cannot activate '$id': entry is unavailable in this image. Image: Minecraft $mc, loader $lv. Reason: ${reason:-no usable artifact}."
        ;;
      *)
        die "$env_name: cannot activate '$id': unrecognised status '$status' in catalog. Image: Minecraft $mc, loader $lv. Reason: ${reason:-none given}."
        ;;
    esac

    members=("$id")
    if [ -n "${c_clos[$id]}" ]; then
      extra=()
      IFS=',' read -r -a extra <<<"${c_clos[$id]}" || true
      members+=("${extra[@]}")
    fi
    for m in "${members[@]}"; do
      m="$(_trim "$m")"
      if [ -z "$m" ]; then continue; fi
      if [ -n "${in_final[$m]+x}" ]; then continue; fi
      if [ "$m" != "$id" ]; then
        if [ -z "${c_status[$m]+x}" ]; then
          die "$env_name: cannot activate '$id': required dependency '$m' is not in the catalog. Image: Minecraft $mc, loader $lv. Reason: ${reason:-inconsistent catalog}."
        fi
        if [ "${c_status[$m]}" != "compatible" ]; then
          die "$env_name: cannot activate '$id': required dependency '$m' is ${c_status[$m]}. Image: Minecraft $mc, loader $lv. Reason: ${c_reason[$m]:-dependency not usable in this image}."
        fi
      fi
      if ! _safe_name "${c_file[$m]}"; then
        die "$env_name: cannot activate '$id': catalog entry '$m' has no usable file name ('${c_file[$m]}'). Image: Minecraft $mc, loader $lv. Reason: broken catalog."
      fi
      if [ ! -f "$cdir/files/${c_file[$m]}" ]; then
        die "$env_name: cannot activate '$id': file '${c_file[$m]}' of '$m' is missing from $cdir/files. Image: Minecraft $mc, loader $lv. Reason: broken image."
      fi
      in_final[$m]=1
      final_ids+=("$m")
    done
  done

  # ---- conflicts inside the final set
  local other
  local -a confl=()
  for id in "${final_ids[@]}"; do
    if [ -z "${c_conf[$id]}" ]; then continue; fi
    IFS=',' read -r -a confl <<<"${c_conf[$id]}" || true
    for other in "${confl[@]}"; do
      other="$(_trim "$other")"
      if [ -z "$other" ] || [ "$other" = "$id" ]; then continue; fi
      if [ -n "${in_final[$other]+x}" ]; then
        die "$env_name: conflicting selection: '$id' cannot be activated together with '$other' (both are in the selected set including dependencies). Image: Minecraft $mc, loader $lv. Reason: ${c_reason[$id]:-'$id' declares a conflict with '$other'}."
      fi
    done
  done

  # ---- apply: nothing above has touched the target
  mkdir -p -- "$target"
  local managed="$target/.catalog-managed"
  local -A new_files=()
  for id in "${final_ids[@]}"; do new_files[${c_file[$id]}]=1; done

  local old
  local -a removed=()
  if [ -f "$managed" ]; then
    while IFS= read -r old || [ -n "$old" ]; do
      old="${old%$'\r'}"
      if [ -z "$old" ]; then continue; fi
      if ! _safe_name "$old"; then
        log "ignoring unsafe entry '$old' in $managed"
        continue
      fi
      if [ -n "${new_files[$old]+x}" ]; then continue; fi
      if [ -L "${target:?}/${old:?}" ] || [ -f "${target:?}/${old:?}" ]; then
        rm -f -- "${target:?}/${old:?}"
        removed+=("$old")
      fi
    done <"$managed"
  fi

  local fn
  for fn in "${!new_files[@]}"; do
    rm -f -- "${target:?}/${fn:?}"
    cp -- "$cdir/files/$fn" "${target:?}/.${fn:?}.tmp.$$"
    mv -f -- "${target:?}/.${fn:?}.tmp.$$" "${target:?}/${fn:?}"
  done

  {
    if [ "${#new_files[@]}" -gt 0 ]; then
      printf '%s\n' "${!new_files[@]}" | LC_ALL=C sort
    fi
  } >"$managed.tmp.$$"
  mv -f -- "$managed.tmp.$$" "$managed"

  if [ "${#removed[@]}" -gt 0 ]; then
    log "$env_name: removed stale catalog files: ${removed[*]}"
  fi
  if [ "${#requested[@]}" -eq 0 ]; then
    log "$env_name: no catalog entries selected; nothing activated in $target"
  else
    log "$env_name: activated ${#final_ids[@]} catalog entries in $target (selected: ${requested[*]}; with dependencies: ${final_ids[*]})"
  fi
}

# Exit 0 right after activation when ACTIVATE_ONLY=true (used by CI).
maybe_exit_after_activation() {
  if [ "${ACTIVATE_ONLY:-}" = "true" ]; then
    log "ACTIVATE_ONLY=true: activation finished, not starting the server"
    exit 0
  fi
}

# ------------------------------------------------------------------- EULA

# require_eula [DIR]  - demands EULA=TRUE and writes DIR/eula.txt (default .).
require_eula() {
  local dir="${1:-.}" value="${EULA:-}"
  case "${value,,}" in
    true) ;;
    *) die "You must accept the Minecraft EULA (https://aka.ms/MinecraftEULA) by setting EULA=TRUE." ;;
  esac
  mkdir -p -- "$dir"
  if ! grep -qx 'eula=true' "$dir/eula.txt" 2>/dev/null; then
    printf '# Accepted via the EULA environment variable.\neula=true\n' >"$dir/eula.txt"
  fi
}

# ------------------------------------------------------- server.properties

# apply_server_properties [FILE]
# PROP_FOO_BAR=x becomes foo-bar=x. Existing keys are rewritten in place, new
# keys appended in sorted order, other lines kept. Values are written verbatim.
apply_server_properties() {
  local file="${1:-/data/server.properties}" tmp var name
  mkdir -p -- "$(dirname -- "$file")"
  if [ ! -e "$file" ]; then : >"$file"; fi
  tmp="$(mktemp "${file}.XXXXXX")"
  if ! awk '
    BEGIN {
      for (k in ENVIRON) {
        if (substr(k, 1, 5) != "PROP_") continue
        name = tolower(substr(k, 6))
        gsub(/_/, "-", name)
        if (name == "") continue
        val = ENVIRON[k]
        gsub(/[\r\n]/, " ", val)
        want[name] = val
      }
    }
    {
      line = $0
      eq = index(line, "=")
      if (line ~ /^[ \t]*[#!]/ || eq == 0) { print line; next }
      key = substr(line, 1, eq - 1)
      sub(/^[ \t]+/, "", key)
      sub(/[ \t]+$/, "", key)
      if (key in want) { print key "=" want[key]; seen[key] = 1 }
      else print line
    }
    END {
      n = 0
      for (k in want) if (!(k in seen)) names[++n] = k
      for (i = 2; i <= n; i++) {
        v = names[i]
        for (j = i - 1; j >= 1 && names[j] > v; j--) names[j + 1] = names[j]
        names[j + 1] = v
      }
      for (i = 1; i <= n; i++) print names[i] "=" want[names[i]]
    }' "$file" >"$tmp"; then
    rm -f -- "${tmp:?}"
    die "failed to process $file"
  fi
  cat -- "$tmp" >"$file"
  rm -f -- "${tmp:?}"
  for var in $(compgen -e | grep '^PROP_' || true); do
    name="${var#PROP_}"
    if [ -z "$name" ]; then continue; fi
    name="${name,,}"
    log "server.properties: set ${name//_/-}"
  done
}

# ----------------------------------------------------------------- memory

# Print KiB for values like 512M / 4G / 1024k, or return 1.
_mem_to_kib() {
  local v="$1"
  [[ "$v" =~ ^([1-9][0-9]{0,8})([kKmMgG])$ ]] || return 1
  local n="${BASH_REMATCH[1]}"
  case "${BASH_REMATCH[2]}" in
    k | K) printf '%s' "$n" ;;
    m | M) printf '%s' "$((n * 1024))" ;;
    g | G) printf '%s' "$((n * 1024 * 1024))" ;;
  esac
}

# Prints "-Xms<INIT_MEMORY> -Xmx<MEMORY>"; MEMORY defaults to 2G, INIT_MEMORY to MEMORY.
java_memory_args() {
  local mem="${MEMORY:-2G}" init="${INIT_MEMORY:-}"
  if [ -z "$init" ]; then init="$mem"; fi
  local mem_kib init_kib
  mem_kib="$(_mem_to_kib "$mem")" || die "invalid MEMORY='$mem' (expected a number with unit k, M or G, e.g. 512M or 4G)"
  init_kib="$(_mem_to_kib "$init")" || die "invalid INIT_MEMORY='$init' (expected a number with unit k, M or G, e.g. 512M or 4G)"
  if [ "$init_kib" -gt "$mem_kib" ]; then
    die "INIT_MEMORY='$init' must not be larger than MEMORY='$mem'"
  fi
  printf -- '-Xms%s -Xmx%s\n' "$init" "$mem"
}
