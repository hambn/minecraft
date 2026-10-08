# Implementation contracts

Interfaces shared between the parts of this repository. `plan.md` says *what* to build; this file pins the file formats, CLI commands, and module APIs that the resolver, images, workflows, and website exchange. Change both sides together.

## Settled decisions

- **Automatic updates:** bots commit generated locks and status files **directly to `main`** (no PRs). Each server workflow only writes `src/mc-server-images/<server>/locks/`, so concurrent workflows never touch the same files; the push step retries `git pull --rebase` + `git push` up to 5 times. Pushes use `secrets.LOCKS_PUSH_TOKEN` when set (needed only if `main` is protected), otherwise `GITHUB_TOKEN`. Pushes made with `GITHUB_TOKEN` do not trigger workflows, so lock commits cannot loop. `web.yml` is triggered by `workflow_run` of the server workflows instead.
- **Pumpkin "stable":** build from the newest `master` commit of `Pumpkin-MC/Pumpkin` that passes our CI checks. That commit supports one Minecraft version; only a window version equal to it is buildable, the others are `pending`.
- **Custom source-build artifacts:** stored as assets of a GitHub Release with tag `custom-artifacts`, asset name `<cache_key>-<filename>`. `cache_key` = sha256 of the build inputs (see below). Uploaded by the publish job only.
- **Packages:** the workflows push to `ghcr.io/hambn/<image>`; package visibility (public/private) is a GHCR setting the owner chooses (see plan constraints about Mojang files).
- **Stable only:** Modrinth `version_type == "release"`, CurseForge `releaseType == 1`.
- **No churn:** locks contain no timestamps. A target whose `inputs_hash` equals the committed lock's and which is already published is `unchanged` and is not rebuilt or re-pushed (manual dispatch with `force: true` overrides).

## Python layout (`src/mc-server-images/`)

Python 3.12, `PyYAML` (pinned in `requirements.txt`), otherwise stdlib. The directory name contains a hyphen, so modules import each other as top-level modules: `cli.py` inserts its own directory into `sys.path`. Tests live in `tests/` and run offline with `python -m unittest discover -s src/mc-server-images/tests -t src/mc-server-images`.

```text
cli.py            argparse entry point, dispatches to the modules below
manifest.py       load + validate mods.yml / plugins.yml
versions.py       Minecraft version parsing, ordering, family expansion ("26.1.x")
resolver.py       per-target resolution, plan command
locks.py          lock schema, inputs_hash, read/write, finalize (lock command)
custom_build.py   build-custom command
staging.py        stage command (Docker build context)
publish.py        publish command (push images, retag latest, write status.json, commit locks)
licenses.yml      redistribution allowlist (SPDX ids) and per-project permissions
requirements.txt
sources/          upstream API clients (http, models, mojang, modrinth, curseforge, registry, github)
loaders.py        shared loader base; get_loader imports <server>/loader.py
<server>/loader.py  server-specific rules (fabric, neoforge, paper, pumpkin), module-level LOADER
common/           files baked into images + CI check tooling
<server>/locks/<minecraft>.json, <server>/locks/status.json
```

### `sources/models.py`

```python
@dataclass
class FileInfo:        filename: str; url: str; sha512: str | None; sha1: str | None; size: int | None
@dataclass
class DependencyRef:   provider: str; project_id: str; version_id: str | None; kind: str  # required|optional|incompatible|embedded
@dataclass
class ProjectInfo:     provider: str; project_id: str; slug: str; name: str | None; description: str | None
                       authors: list[str]; license: str | None; homepage: str | None
                       server_side: str          # required|optional|unsupported|unknown
                       distribution_allowed: bool | None   # CurseForge allowModDistribution; None = not reported
                       missing: list[str]        # metadata fields the provider did not supply
@dataclass
class ReleaseInfo:     provider: str; project_id: str; version_id: str; version_number: str; name: str
                       release_type: str         # release|beta|alpha
                       published: str            # ISO-8601, used for ordering
                       game_versions: list[str]; loaders: list[str]
                       file: FileInfo | None; dependencies: list[DependencyRef]
class ProviderUnavailable(Exception)             # e.g. the keyless CurseForge proxy is down
```

Provider objects (`modrinth.ModrinthClient()`, `curseforge.CurseForgeClient(api_key=None)` which reads `CURSEFORGE_API_KEY`; without a key it uses the keyless proxy `https://api.curse.tools/v1/cf`, and `CURSEFORGE_API_BASE` overrides the base URL) expose:

```python
name: str                                              # "modrinth" | "curseforge"
def project(self, ref: str | int) -> ProjectInfo       # slug or id
def releases(self, project_id: str, loaders: list[str]) -> list[ReleaseInfo]   # every release for those loaders, all game versions, all types
def release(self, version_id: str) -> ReleaseInfo
```

Other source modules:

```python
# sources/http.py   (User-Agent "hambn/minecraft (+https://github.com/hambn/minecraft)", retries with backoff)
get_json(url, headers=None) -> Any ; get_text(url, headers=None) -> str
download(url, dest: Path, *, sha1=None, sha256=None, sha512=None) -> str   # returns sha512 hex, raises HashMismatch
class HttpError(Exception); class HashMismatch(Exception)
# sources/mojang.py
stable_releases() -> list[dict]          # [{"id","release_time","url"}], type=="release", newest first by releaseTime
maintenance_window(count=3) -> list[str] # newest first
version_details(mc: str) -> dict         # {"java_major": int, "server_jar": {"url","sha1","size"}}
# sources/registry.py
resolve_digest(image: str) -> str        # "eclipse-temurin:25-jre" -> "sha256:..." (Docker Hub, ghcr.io, other v2 registries; anonymous token flow; multi-arch index digest)
# sources/github.py   (uses GITHUB_TOKEN when set)
latest_commit(repo: str, branch: str) -> str
file_at(repo: str, ref: str, path: str) -> str
release_asset_url(repo: str, tag: str, asset: str) -> str | None
upload_release_asset(repo: str, tag: str, path: Path, name: str) -> None   # creates the release if missing
```

### `loaders.py` and `<server>/loader.py`

```python
@dataclass
class ServerBuild:
    status: str                 # available | pending
    reason: str | None
    loader_version: str | None  # fabric loader / neoforge version / paper build number / pumpkin commit
    runtime: dict               # {"base_image": "eclipse-temurin:25-jre", "base_digest": "sha256:...", "java_major": 25 | None}
    details: dict               # stored verbatim as lock["server_build"]["details"], see below

class Loader:
    server: str                 # "fabric"
    image: str                  # "minecraft-server-fabric"
    catalog_kind: str           # "mods" | "plugins"
    env_var: str                # "MODS" | "PLUGINS"
    manifest: str               # "fabric/mods/mods.yml" (relative to src/mc-server-images)
    provider_loaders: dict      # {"modrinth": ["fabric"], "curseforge": ["Fabric"]}; empty list = provider unsupported
    artifact_ext: str           # ".jar" | ".wasm"
    def resolve_build(self, minecraft: str) -> ServerBuild

def get_loader(server: str) -> Loader      # loaders.py, loads <server>/loader.py as module <server>_loader
SERVERS = ["fabric", "neoforge", "paper", "pumpkin"]
```

`details` per server (consumed by `staging.py` and the Dockerfiles):

- `downloads`: `{name: {"url", "sha1"|"sha256"|"sha512" (at least one)}}`. `stage` downloads each to `downloads/<name>.<ext of url>` in the build context and verifies the hash.
  - fabric: `installer` (fabric-installer jar), `server` (vanilla server jar, Mojang sha1). Plus `installer_version`.
  - neoforge: `installer` (`neoforge-<v>-installer.jar`).
  - paper: `paper` (Fill API v3 `server:default` download, sha256). Plus `build` number and `channel`.
  - pumpkin: none (`downloads: {}`); `source: {"repo": "https://github.com/Pumpkin-MC/Pumpkin", "commit": "<sha>"}`, `builder_image: "rust:<ver>-<debian>@sha256:..."`, `supported_minecraft: "<version>"`.

### Manifest (`mods.yml` / `plugins.yml`)

Sections `modrinth`, `curseforge`, `custom_build`, `prebuilt` (each optional, list). Shapes as in `plan.md`. IDs: `^[a-z0-9][a-z0-9-]*$`, unique across the manifest. `custom_build`/`prebuilt` `dependencies` are lists of other manifest IDs. `minecraft_versions` entries may be exact (`26.3`) or families (`26.1.x`), expanded by version components. Paths are relative to the manifest's directory.

### Lock file: `<server>/locks/<minecraft>.json`

JSON, 2-space indent, keys sorted, trailing newline, entries sorted by `id`. No timestamps.

```json
{
  "schema": 1,
  "server": "fabric",
  "image": "minecraft-server-fabric",
  "minecraft_version": "26.3",
  "inputs_hash": "sha256:<hex>",
  "runtime": {"base_image": "eclipse-temurin:25-jre", "base_digest": "sha256:...", "java_major": 25},
  "server_build": {"status": "available", "reason": null, "loader_version": "0.17.3", "details": {}},
  "entries": [
    {
      "id": "lithium",
      "declared": true,
      "source": "modrinth",
      "identity": {"project_id": "gvQqBUqZ", "slug": "lithium", "version_id": "abc123", "file_id": null},
      "metadata": {"name": "Lithium", "description": "...", "authors": ["jellysquid3"], "version": "0.18.0", "license": "LGPL-3.0-only", "homepage": "https://modrinth.com/mod/lithium", "missing": []},
      "status": "compatible",
      "reason": null,
      "supported_minecraft_versions": ["26.3"],
      "supported_loaders": ["fabric"],
      "dependencies": [{"id": "fabric-api", "kind": "required"}],
      "conflicts": [],
      "closure": ["fabric-api", "lithium"],
      "selectable": true,
      "artifact": {"filename": "lithium-fabric-0.18.0.jar", "url": "https://cdn.modrinth.com/...", "sha512": "...", "size": 123},
      "local": null,
      "build": null
    }
  ]
}
```

- `status`: `compatible` | `unsupported_fallback` | `unavailable`. `artifact` is `null` only for `unavailable`.
- `selectable`: `status == "compatible"` and every closure member is `compatible`.
- `reason`: human text, required unless `compatible`. For fallbacks it names supported Minecraft versions/loaders and the image's version/loader, e.g. `supports Minecraft 26.1, 26.1.1, 26.1.2 (fabric); this image is Minecraft 26.3 (fabric 0.17.3)`. A selectable=false compatible entry explains which dependency blocks it.
- Auto-resolved dependencies: `declared: false`, `id` = provider slug (`cf-<slug>` for CurseForge); if that collides with a different project's declared ID, prefix `modrinth-`/`cf-`.
- `local` (prebuilt): `{"path": "jars/x.jar", "sha512": "..."}`. `build` (custom_build): `{"directory", "source_tree_sha256", "command", "output", "builder_image", "targets": {"minecraft", "loader", "loader_version"}, "cache_key", "storage": {"release": "custom-artifacts", "asset": "<cache_key>-<filename>"} | null}`.
- `inputs_hash`: sha256 over the canonical JSON of the lock with `inputs_hash` removed, plus the bytes of `<server>/Dockerfile`, `<server>/entrypoint.sh`, and every file in `common/` whose name ends in `.sh`, in sorted path order.
- `cache_key` (custom builds): sha256 of canonical JSON `{source_tree_sha256, builder_image, command, output, version, minecraft, loader, loader_version}`. `source_tree_sha256` hashes `git ls-files` of the directory (path + bytes, sorted).

### Status file: `<server>/locks/status.json`

Written by `publish`, read by the website.

```json
{
  "schema": 1,
  "server": "fabric",
  "image": "ghcr.io/hambn/minecraft-server-fabric",
  "updated_at": "2026-10-08T12:00:00Z",
  "window": ["26.3", "26.2", "26.1.2"],
  "latest": "26.3",
  "latest_outside_window": false,
  "targets": {
    "26.3": {"state": "published", "digest": "sha256:...", "published_at": "2026-10-08T12:00:00Z", "lock": "26.3.json"},
    "26.2": {"state": "pending", "reason": "No stable Fabric loader build for 26.2 yet"},
    "26.1.1": {"state": "frozen", "digest": "sha256:...", "published_at": "...", "lock": "26.1.1.json"}
  }
}
```

`updated_at` changes only when something else in the file changes. A previously published version that leaves the window becomes `frozen` and keeps its digest. A previously published version whose new build is pending stays `published`.

## CLI (`python src/mc-server-images/cli.py <command>`)

| Command | Arguments | Effect |
| --- | --- | --- |
| `window` | `[--count 3]` | Print the window as a JSON list, newest first. |
| `plan` | `--server S --out DIR [--force] [--github-output]` | Resolve all three targets. Write `DIR/plan.json` and a draft lock `DIR/<mc>.json` per non-pending target. With `--github-output`, append `matrix=<json>` to `$GITHUB_OUTPUT`. |
| `build-custom` | `--server S --minecraft V --plan DIR --out DIR2` | Build or fetch custom source artifacts for that target into `DIR2/`, writing `DIR2/results.json`. |
| `lock` | `--server S --minecraft V --plan DIR --custom DIR2 --out FILE` | Finalize the draft into the final lock (custom results filled in, `inputs_hash` recomputed). |
| `stage` | `--server S --lock FILE --out CTX [--custom DIR2]` | Produce the Docker build context described below. |
| `check-window` | `--minecraft V` | Exit 0 when V is in the current window, 3 otherwise. |
| `publish` | `--server S --artifacts DIR --registry ghcr.io/hambn [--dry-run] [--no-commit]` | See "Publish". |

`plan.json`: `{"server", "window": [...], "targets": [{"minecraft", "status": "build"|"unchanged"|"pending", "reason", "draft": "26.3.json"|null, "inputs_hash"|null}]}`.
Matrix output: `{"include": [{"minecraft": "26.3", "status": "build"}, ...]}` — always exactly the window's three versions.

`build-custom` `results.json`: `{"<id>": {"status": "built"|"cached"|"failed"|"skipped", "filename", "sha512", "cache_key", "path": "<file in DIR2>"|null, "uploaded": false, "reason"}}`. Builds run `docker run --rm -v <dir>:/src -w /src -e ARTIFACT_VERSION -e MINECRAFT_VERSION -e LOADER -e LOADER_VERSION <builder_image> <command...>`. A failure marks the entry `unavailable`; it never fails the command. Cached artifacts are fetched from the `custom-artifacts` release.

## Docker build context (output of `stage`)

```text
CTX/
  Dockerfile               copied from <server>/Dockerfile
  entrypoint.sh            copied from <server>/entrypoint.sh
  common/                  copied from common/ (*.sh and mc_status.py)
  downloads/<name>.<ext>   verified server_build.details.downloads
  catalog/files/<filename> every entry with an artifact (compatible + unsupported_fallback), sha512-verified
  catalog/catalog.tsv
  catalog/catalog.json     {"server","minecraft_version","loader_version","entries":[lock entries]}
  catalog/lock.json        the full lock
  build-args.env           KEY=VALUE lines passed as --build-arg
```

`build-args.env` keys: `BASE_IMAGE` (`<base_image>@<base_digest>`), `MINECRAFT_VERSION`, `LOADER_VERSION`, `JAVA_MAJOR` (empty for pumpkin), plus pumpkin `BUILDER_IMAGE`, `PUMPKIN_REPO`, `PUMPKIN_COMMIT`, and `INSTALLER_VERSION` for fabric.

### `catalog.tsv`

UTF-8, one entry per line, tab-separated, first line is a `#`-prefixed header. Empty values are written as `-` (bash `read` collapses empty tab fields). Tabs/newlines in values are replaced with spaces.

```text
#id	status	selectable	kind	filename	closure	conflicts	reason
lithium	compatible	yes	declared	lithium-fabric-0.18.0.jar	fabric-api,lithium	-	-
```

`kind` is `declared` or `dependency`. `closure`/`conflicts` are comma-separated IDs.

## Image layout and runtime contract

- `/opt/server` server files (read-only use), `/opt/catalog/{files/,catalog.tsv,catalog.json,lock.json}`, `/opt/scripts/{entrypoint.sh,common/}`. `WORKDIR /data`, `VOLUME /data`, `USER 1000:1000`, `EXPOSE 25565`. `ENTRYPOINT ["/opt/scripts/entrypoint.sh"]`.
- Labels: `org.opencontainers.image.source=https://github.com/hambn/minecraft`, `org.opencontainers.image.version=<minecraft>`, `io.github.hambn.minecraft.server=<server>`, `io.github.hambn.minecraft.catalog-env=MODS|PLUGINS`, `io.github.hambn.minecraft.catalog-dir=/data/mods|/data/plugins`, `io.github.hambn.minecraft.ready-pattern=<Python regex for the "server ready" log line>`.
- Environment: `EULA` (Java servers; must be `TRUE`), `MEMORY` (default `2G`, sets `-Xms`/`-Xmx`), `INIT_MEMORY` (default = `MEMORY`), `JVM_OPTS` (extra JVM flags), `PROP_<NAME>` → `server.properties` key `<name>` lowercased with `_` → `-` (e.g. `PROP_ONLINE_MODE=false`), `MODS`/`PLUGINS`, `ACTIVATE_ONLY=true` (run activation, then exit 0 without starting the server; used by CI).
- `common/lib.sh` (bash, sourced by every entrypoint) provides:
  - `log`, `die` helpers.
  - `catalog_activate <selection> <target_dir> <env_name>`: parse `/opt/catalog/catalog.tsv`; unknown/unavailable/unsupported/non-selectable IDs and conflicting selections → `die` with the entry, image Minecraft/loader version, and reason. Remove files listed in `<target_dir>/.catalog-managed`, copy the union of closures from `/opt/catalog/files`, write the new managed list. Never touches unlisted files.
  - `require_eula`, `apply_server_properties` (from `PROP_*`), `java_memory_args` (prints the JVM memory flags).
  - Image version info read from `/opt/catalog/catalog.json` or build-time env `MINECRAFT_VERSION`/`LOADER_VERSION`.
- Entrypoints end with `exec` so SIGTERM reaches the server and it saves and stops cleanly.

## CI checks (`common/ci_check.py`, stdlib, runs on the CI host)

`python3 src/mc-server-images/common/ci_check.py --image REF --catalog CTX/catalog/catalog.tsv --out checks.json [--python-image python:3.12-slim]`. Reads the server type, catalog env/dir, and ready pattern from the image labels. Blocking checks: baseline boot with `--network none` until the ready pattern, status ping (via `docker run --network container:<id> <python-image> python mc_status.py 127.0.0.1 25565`), clean stop with `docker stop -t 120`; empty selection leaves the catalog inactive; `ACTIVATE_ONLY` for each selectable entry on a reused volume (stale files removed when the selection changes, unrelated files kept); unknown ID rejected; unsupported fallback rejected when one exists. Non-blocking: boot with all selectable entries. Output `{"image", "server", "minecraft", "passed": bool, "checks": [{"name", "passed", "blocking", "detail"}]}`; exit 1 if a blocking check failed.

## Workflows

Per server (`.github/workflows/<server>.yml`): jobs `plan` → `build` → `push_image` as in `plan.md`. Build job artifact name `build-<server>-<minecraft>` containing:

```text
result.json   {"server", "minecraft", "status": "built"|"unchanged"|"pending", "passed": bool, "reason", "inputs_hash"}
image.tar     docker save of local/<image>:<minecraft>   (only when built)
lock.json     final lock                                  (built or unchanged)
checks.json   ci_check output                             (only when built)
custom/       build-custom output dir incl. results.json   (only when built)
```

`push_image` runs `cli.py publish`, which: rechecks the window; refuses to publish when any `built` target has `passed: false`; for each passed built target in the window, pushes `image.tar` with `skopeo copy docker-archive:… docker://<registry>/<image>:<mc>` and records the digest; uploads new custom artifacts to the `custom-artifacts` release; moves `latest` (`skopeo copy docker://…:<mc> docker://…:latest`) to the newest published window target when it changed or was rebuilt; copies final locks into `<server>/locks/`, rewrites `status.json`; then commits `chore(<server>): update locks for <versions>` as `github-actions[bot]` and pushes to `main` with rebase retries (skipped with `--no-commit`).

`web.yml` builds the site with `python src/web/build.py --servers src/mc-server-images --out site --base-path <path>` (`/minecraft/` for Pages, `/` for the image).
