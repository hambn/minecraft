"""Per-target resolution and the ``plan`` command.

For one server this resolves the maintenance window (the three newest stable
Minecraft releases that server supports) into draft lock files: loader build, provider releases with
required dependencies, licenses, custom/prebuilt entries.  Provider access is
injected, so everything here is testable offline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import locks
import manifest as manifest_mod
import versions

try:  # the sources package is optional at import time (tests inject fakes)
    from sources.models import ProviderUnavailable
except ImportError:  # pragma: no cover
    class ProviderUnavailable(Exception):  # type: ignore[no-redef]
        pass

try:
    from sources.http import HttpError
except ImportError:  # pragma: no cover
    class HttpError(Exception):  # type: ignore[no-redef]
        pass

BASE_DIR = Path(__file__).resolve().parent
PROVIDER_ERRORS = (ProviderUnavailable, HttpError)
MISSING_METADATA = ["name", "description", "authors", "license", "homepage"]


# ------------------------------------------------------------------- licenses

def load_licenses(path: str | Path | None = None) -> dict:
    import yaml

    data = yaml.safe_load(Path(path or BASE_DIR / "licenses.yml").read_text(encoding="utf-8")) or {}
    return {"allowed": list(data.get("allowed") or []), "permissions": list(data.get("permissions") or [])}


def spdx_allowed(expression: str | None, allowed: set[str]) -> bool:
    """Evaluate an SPDX expression against the (lower-cased) allowlist."""
    if not expression or not expression.strip():
        return False
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def parse_or() -> bool:
        nonlocal pos
        result = parse_and()
        while (peek() or "").upper() == "OR":
            pos += 1
            right = parse_and()
            result = result or right
        return result

    def parse_and() -> bool:
        nonlocal pos
        result = parse_atom()
        while (peek() or "").upper() == "AND":
            pos += 1
            right = parse_atom()
            result = result and right
        return result

    def parse_atom() -> bool:
        nonlocal pos
        token = peek()
        if token is None:
            return False
        pos += 1
        if token == "(":
            value = parse_or()
            if peek() == ")":
                pos += 1
            return value
        if token == ")":
            return False
        if (peek() or "").upper() == "WITH":
            pos += 2  # exceptions are ignored
        ident = token[:-1] if token.endswith("+") else token
        if ident.lower().startswith("licenseref-"):
            return False
        return ident.lower() in allowed

    try:
        return parse_or()
    except Exception:  # noqa: BLE001 - unparseable means not allowed
        return False


def has_permission(licenses: dict, provider: str, *refs: Any) -> bool:
    wanted = {str(r).lower() for r in refs if r is not None}
    for item in licenses.get("permissions", []):
        if str(item.get("provider", "")).lower() == provider and str(item.get("project", "")).lower() in wanted:
            return True
    return False


def license_problem(licenses: dict, provider: str, license_id: str | None, *refs: Any) -> str | None:
    allowed = {str(a).lower() for a in licenses.get("allowed", [])}
    if spdx_allowed(license_id, allowed) or has_permission(licenses, provider, *refs):
        return None
    if not license_id:
        return "no license reported by the provider; redistribution is not permitted without a licenses.yml permission"
    return f"license {license_id!r} is not on the redistribution allowlist (licenses.yml); no author permission recorded"


# ------------------------------------------------------------------- helpers

def _meta(info: Any, release: Any | None = None) -> dict:
    return {
        "name": info.name,
        "description": info.description,
        "authors": list(info.authors or []),
        "version": release.version_number if release is not None else None,
        "license": info.license,
        "homepage": info.homepage,
        "missing": sorted(info.missing or []),
    }


def _empty_meta(missing: list[str] | None = None) -> dict:
    return {"name": None, "description": None, "authors": [], "version": None, "license": None,
            "homepage": None, "missing": sorted(missing if missing is not None else MISSING_METADATA)}


def _entry(entry_id: str, *, declared: bool, source: str, identity: dict, metadata: dict, status: str,
           reason: str | None, mc_versions: list[str], loaders: list[str], dependencies: list[dict] | None = None,
           conflicts: list[str] | None = None, artifact: dict | None = None, local: dict | None = None,
           build: dict | None = None) -> dict:
    return {
        "id": entry_id, "declared": declared, "source": source, "identity": identity, "metadata": metadata,
        "status": status, "reason": reason, "supported_minecraft_versions": mc_versions,
        "supported_loaders": loaders, "dependencies": dependencies or [], "conflicts": conflicts or [],
        "closure": [entry_id], "selectable": False, "artifact": artifact, "local": local, "build": build,
    }


def _release_versions(release: Any) -> list[str]:
    parsed = [v for v in release.game_versions if versions.try_parse(v) is not None]
    return versions.sort_versions(parsed or release.game_versions)


def source_tree_sha256(directory: Path) -> str:
    """Hash path + bytes of ``git ls-files`` for ``directory`` (walk when untracked)."""
    files: list[str] = []
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=directory, check=True,
                             capture_output=True).stdout.decode("utf-8")
        files = [f for f in out.split("\0") if f]
    except (OSError, subprocess.CalledProcessError):
        pass
    if not files:
        files = [p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()]
    digest = hashlib.sha256()
    for rel in sorted(files):
        path = directory / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        digest.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return digest.hexdigest()


def cache_key(parts: dict) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha512_file(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-")
    return slug or "dep"


# ------------------------------------------------------------------ resolver

class Resolver:
    """Resolves one server; provider responses are cached across targets."""

    def __init__(self, server: str, loader: Any, manifest: Any, providers: dict[str, Any] | Callable[[], dict] | None = None,
                 licenses: dict | None = None, known_releases: list[str] | None = None) -> None:
        self.server = server
        self.loader = loader
        self.manifest = manifest
        self._providers = providers
        self._licenses = licenses
        self._known = known_releases
        self._project_cache: dict[tuple, Any] = {}
        self._release_cache: dict[tuple, list] = {}

    # lazily-acquired inputs ------------------------------------------------
    @property
    def providers(self) -> dict[str, Any]:
        if callable(self._providers):
            self._providers = self._providers()
        if self._providers is None:
            self._providers = default_providers()
        return self._providers

    @property
    def licenses(self) -> dict:
        if self._licenses is None:
            self._licenses = load_licenses()
        return self._licenses

    @property
    def known_releases(self) -> list[str]:
        if self._known is None:
            from sources import mojang

            self._known = [r["id"] for r in mojang.stable_releases()]
        return self._known

    # provider access ----------------------------------------------------------
    def _provider(self, name: str) -> Any:
        client = self.providers.get(name)
        if isinstance(client, Exception):
            raise client
        if client is None:
            raise ProviderUnavailable(f"provider {name} is not configured")
        return client

    def _project(self, provider: str, ref: Any) -> Any:
        key = (provider, str(ref))
        if key not in self._project_cache:
            info = self._provider(provider).project(ref)
            self._project_cache[key] = info
            self._project_cache[(provider, str(info.project_id))] = info
        return self._project_cache[key]

    def _releases(self, provider: str, project_id: Any, loaders: list[str]) -> list:
        key = (provider, str(project_id), tuple(loaders))
        if key not in self._release_cache:
            self._release_cache[key] = list(self._provider(provider).releases(str(project_id), loaders))
        return self._release_cache[key]

    # target ----------------------------------------------------------------------
    def resolve_target(self, minecraft: str, build: Any, base_dir: Path | None = None) -> dict:
        """Draft lock for an *available* ``build``."""
        self._used_ids = set(self.manifest.ids)
        self._declared: dict[tuple, str] = {}
        self._auto: dict[tuple, str] = {}
        self._queue: list[tuple[str, str]] = []
        self._entries: dict[str, dict] = {}
        self._incompatible: dict[str, list[tuple]] = {}
        self._minecraft = minecraft
        self._build = build

        # Phase 1: look up declared upstream projects so dependency IDs can reuse them.
        infos: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for item in self.manifest.upstream:
            try:
                info = self._project(item.provider, item.project)
                infos[item.id] = info
                self._declared[(item.provider, str(info.project_id))] = item.id
            except PROVIDER_ERRORS as exc:
                errors[item.id] = f"{item.provider} lookup failed: {exc}"

        # Phase 2: declared upstream entries, then dependency closure.
        for item in self.manifest.upstream:
            if item.id in errors:
                self._entries[item.id] = self._lookup_failed(item.id, True, item.provider, item.project, errors[item.id])
            else:
                self._entries[item.id] = self._upstream_entry(item.id, True, item.provider, infos[item.id])
        while self._queue:
            provider, pid = self._queue.pop(0)
            entry_id = self._auto[(provider, pid)]
            try:
                info = self._project(provider, pid)
            except PROVIDER_ERRORS as exc:
                self._entries[entry_id] = self._lookup_failed(entry_id, False, provider, pid, f"{provider} lookup failed: {exc}")
                continue
            self._entries[entry_id] = self._upstream_entry(entry_id, False, provider, info)

        # Local entries.
        for local in self.manifest.local:
            self._entries[local.id] = self._local_entry(local)

        entries = list(self._entries.values())
        self._apply_conflicts(entries)
        lock = {
            "schema": locks.SCHEMA,
            "server": self.server,
            "image": self.loader.image,
            "minecraft_version": minecraft,
            "inputs_hash": "",
            "runtime": dict(build.runtime),
            "server_build": {
                "status": build.status, "reason": build.reason,
                "loader_version": build.loader_version, "details": build.details,
            },
            "entries": entries,
        }
        locks.sort_entries(lock)
        locks.recompute_graph(lock["entries"])
        lock["inputs_hash"] = locks.compute_inputs_hash(lock, base_dir or BASE_DIR)
        return lock

    # upstream -------------------------------------------------------------------
    def _lookup_failed(self, entry_id: str, declared: bool, provider: str, ref: Any, reason: str) -> dict:
        return _entry(
            entry_id, declared=declared, source=provider,
            identity={"project_id": str(ref), "slug": None, "version_id": None, "file_id": None},
            metadata=_empty_meta(), status="unavailable", reason=reason, mc_versions=[], loaders=[],
        )

    def _dep_id(self, provider: str, project_id: Any) -> str:
        """ID for a dependency project, registering a new auto entry when needed."""
        key = (provider, str(project_id))
        if key in self._declared:
            return self._declared[key]
        if key in self._auto:
            return self._auto[key]
        try:
            slug = self._project(provider, project_id).slug or str(project_id)
        except PROVIDER_ERRORS:
            slug = str(project_id)
        base = _slugify(slug)
        if provider == "curseforge":
            base = f"cf-{base}"
        candidate = base
        if candidate in self._used_ids:
            candidate = f"{'cf' if provider == 'curseforge' else provider}-{base}"
        n = 2
        while candidate in self._used_ids:
            candidate = f"{base}-{n}"
            n += 1
        self._used_ids.add(candidate)
        self._auto[key] = candidate
        self._queue.append(key)
        return candidate

    def _upstream_entry(self, entry_id: str, declared: bool, provider: str, info: Any) -> dict:
        build = self._build
        mc = self._minecraft
        identity = {"project_id": str(info.project_id), "slug": info.slug, "version_id": None, "file_id": None}
        metadata = _meta(info)

        def unavailable(reason: str, mc_versions: list[str] | None = None, loaders: list[str] | None = None) -> dict:
            return _entry(entry_id, declared=declared, source=provider, identity=identity, metadata=metadata,
                          status="unavailable", reason=reason, mc_versions=mc_versions or [], loaders=loaders or [])

        wanted = list(self.loader.provider_loaders.get(provider) or [])
        if not wanted:
            return unavailable(f"{provider} does not provide {self.server} artifacts")
        problem = license_problem(self.licenses, provider, info.license, info.slug, info.project_id)
        if problem:
            return unavailable(problem)
        if provider == "curseforge" and info.distribution_allowed is False:
            return unavailable("the author disabled third-party distribution on CurseForge")
        if info.server_side == "unsupported":
            return unavailable("the project is client-side only (server side unsupported)")
        try:
            releases = self._releases(provider, info.project_id, wanted)
        except PROVIDER_ERRORS as exc:
            return unavailable(f"{provider} release lookup failed: {exc}")

        wanted_l = {w.lower() for w in wanted}
        stable = [r for r in releases
                  if r.release_type == "release" and r.file is not None and wanted_l & {x.lower() for x in r.loaders}]
        stable.sort(key=lambda r: r.published, reverse=True)
        exact = [r for r in stable if mc in r.game_versions]
        if exact:
            release, status, reason = exact[0], "compatible", None
        elif stable:
            release, status = stable[0], "unsupported_fallback"
            supported = _release_versions(release)
            loaders = sorted({x.lower() for x in release.loaders} & wanted_l)
            reason = (f"supports Minecraft {', '.join(supported)} ({', '.join(loaders)}); "
                      f"this image is Minecraft {mc} ({self.server} {build.loader_version})")
        else:
            return unavailable(f"no stable {self.server} release found for Minecraft {mc} or any other version")

        file = release.file
        artifact = {"filename": file.filename, "url": file.url, "sha512": file.sha512, "size": file.size}
        if not file.sha512 and file.sha1:
            artifact["sha1"] = file.sha1
        identity = {**identity, "version_id": release.version_id,
                    "file_id": release.version_id if provider == "curseforge" else None}
        metadata = _meta(info, release)

        dependencies: list[dict] = []
        incompatible: list[tuple] = []
        for dep in release.dependencies:
            if dep.kind == "required":
                dependencies.append({"id": self._dep_id(dep.provider, dep.project_id), "kind": "required"})
            elif dep.kind == "incompatible":
                incompatible.append((dep.provider, str(dep.project_id)))
        self._incompatible[entry_id] = incompatible
        dependencies = sorted({d["id"]: d for d in dependencies}.values(), key=lambda d: d["id"])
        loaders_out = sorted({x.lower() for x in release.loaders} & wanted_l)
        return _entry(entry_id, declared=declared, source=provider, identity=identity, metadata=metadata,
                      status=status, reason=reason, mc_versions=_release_versions(release), loaders=loaders_out,
                      dependencies=dependencies, artifact=artifact)

    def _apply_conflicts(self, entries: list[dict]) -> None:
        by_project = {}
        for entry in entries:
            if entry["source"] in ("modrinth", "curseforge"):
                by_project[(entry["source"], entry["identity"]["project_id"])] = entry["id"]
        conflicts: dict[str, set[str]] = {}
        for entry_id, refs in self._incompatible.items():
            for ref in refs:
                other = by_project.get(ref)
                if other and other != entry_id:
                    conflicts.setdefault(entry_id, set()).add(other)
                    conflicts.setdefault(other, set()).add(entry_id)
        for entry in entries:
            entry["conflicts"] = sorted(conflicts.get(entry["id"], set()))

    # local ------------------------------------------------------------------------
    def _local_entry(self, local: Any) -> dict:
        build = self._build
        mc = self._minecraft
        meta = local.metadata
        metadata = {
            "name": meta.get("name"), "description": meta.get("description"),
            "authors": list(meta.get("authors") or []), "version": str(meta.get("version")),
            "license": meta.get("license"), "homepage": meta.get("homepage"), "missing": [],
        }
        if not metadata["homepage"]:
            metadata["missing"] = ["homepage"]
        identity = {"project_id": local.id, "slug": local.id, "version_id": metadata["version"], "file_id": None}
        deps = [{"id": d, "kind": "required"} for d in sorted(set(local.dependencies))]
        common = dict(declared=True, source=local.kind, identity=identity, metadata=metadata,
                      loaders=[self.server], dependencies=deps)
        supported = versions.expand(local.minecraft_versions, self.known_releases) or list(local.minecraft_versions)

        problem = license_problem(self.licenses, "custom", metadata["license"], local.id)
        if problem:
            return _entry(local.id, status="unavailable", reason=problem, mc_versions=supported, **common)
        covered = versions.covers(local.minecraft_versions, mc)
        mismatch = (f"supports Minecraft {', '.join(supported)} ({self.server}); "
                    f"this image is Minecraft {mc} ({self.server} {build.loader_version})")

        if local.kind == "prebuilt":
            path = local.abs_path
            if path is None or not path.is_file():
                return _entry(local.id, status="unavailable", reason=f"prebuilt file {local.path} is missing",
                              mc_versions=supported, **common)
            sha = sha512_file(path)
            artifact = {"filename": path.name, "url": None, "sha512": sha, "size": path.stat().st_size}
            return _entry(local.id, status="compatible" if covered else "unsupported_fallback",
                          reason=None if covered else mismatch, mc_versions=supported, artifact=artifact,
                          local={"path": local.path, "sha512": sha}, **common)

        if not covered:
            return _entry(local.id, status="unavailable", reason=mismatch, mc_versions=supported, **common)
        spec = local.build
        tree = source_tree_sha256(local.abs_directory)
        targets = {"minecraft": mc, "loader": self.server, "loader_version": build.loader_version}
        key = cache_key({
            "source_tree_sha256": tree, "builder_image": spec["builder_image"], "command": spec["command"],
            "output": spec["output"], "version": metadata["version"], "minecraft": mc,
            "loader": self.server, "loader_version": build.loader_version,
        })
        build_block = {
            "directory": local.directory, "source_tree_sha256": tree, "command": list(spec["command"]),
            "output": spec["output"], "builder_image": spec["builder_image"], "targets": targets,
            "cache_key": key, "storage": None,
        }
        return _entry(local.id, status="compatible", reason=None, mc_versions=supported, artifact=None,
                      build=build_block, **common)


def default_providers() -> dict[str, Any]:
    from sources import curseforge, modrinth

    providers: dict[str, Any] = {"modrinth": modrinth.ModrinthClient()}
    try:
        providers["curseforge"] = curseforge.CurseForgeClient()
    except ProviderUnavailable as exc:
        providers["curseforge"] = exc
    return providers


# ---------------------------------------------------------------------- plan

def _committed_unchanged(servers_dir: Path, server: str, minecraft: str, inputs_hash: str) -> bool:
    lock_path = locks.server_locks_dir(server, servers_dir) / f"{minecraft}.json"
    status_path = locks.server_locks_dir(server, servers_dir) / "status.json"
    if not lock_path.is_file() or not status_path.is_file():
        return False
    try:
        old = locks.read_json(lock_path)
        status = locks.read_json(status_path)
    except (OSError, ValueError):
        return False
    if old.get("inputs_hash") != inputs_hash:
        return False
    if status.get("targets", {}).get(minecraft, {}).get("state") != "published":
        return False
    # Failed custom builds are retried.
    return not any(str(e.get("reason") or "").startswith(locks.BUILD_FAILED_PREFIX) for e in old.get("entries", []))


def plan(server: str, out: str | Path, *, force: bool = False, window: list[str] | None = None,
         loader: Any = None, manifest: Any = None, resolver: Resolver | None = None,
         servers_dir: str | Path | None = None, base_dir: Path | None = None,
         releases: list[str] | None = None) -> dict:
    """Resolve the window and write ``plan.json`` plus draft locks into ``out``.

    Without an explicit ``window`` the server's own window is detected from the
    Mojang releases it has stable builds for; newer unsupported releases become
    pending targets.
    """
    if loader is None:
        from loaders import get_loader

        loader = get_loader(server)
    if window is None:
        from loaders import server_window

        detected = server_window(loader, releases=releases)
        window, upcoming, builds = detected.window, detected.upcoming, detected.builds
    else:
        upcoming, builds = [], {}
    base = Path(base_dir) if base_dir else BASE_DIR
    if manifest is None:
        manifest = manifest_mod.load(base / loader.manifest, artifact_ext=loader.artifact_ext)
    resolver = resolver or Resolver(server, loader, manifest)
    locks_path = Path(servers_dir) if servers_dir else BASE_DIR
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    targets = []
    for mc in list(upcoming) + list(window):
        build = builds.get(mc) or loader.resolve_build(mc)
        if build.status != "available":
            targets.append({"minecraft": mc, "status": "pending", "reason": build.reason or "server build pending",
                            "draft": None, "inputs_hash": None})
            continue
        lock = resolver.resolve_target(mc, build, base)
        locks.write_lock(out / f"{mc}.json", lock)
        unchanged = not force and _committed_unchanged(locks_path, server, mc, lock["inputs_hash"])
        targets.append({"minecraft": mc, "status": "unchanged" if unchanged else "build",
                        "reason": "inputs unchanged since the published build" if unchanged else None,
                        "draft": f"{mc}.json", "inputs_hash": lock["inputs_hash"]})
    result = {"server": server, "window": list(window), "upcoming": list(upcoming), "targets": targets}
    locks.write_json(out / "plan.json", result)
    return result


def matrix(result: dict) -> dict:
    return {"include": [{"minecraft": t["minecraft"], "status": t["status"]} for t in result["targets"]]}


def plan_command(args: Any) -> int:
    result = plan(args.server, args.out, force=bool(getattr(args, "force", False)))
    for target in result["targets"]:
        note = f" ({target['reason']})" if target["reason"] else ""
        print(f"{result['server']} {target['minecraft']}: {target['status']}{note}")
    if getattr(args, "github_output", False):
        path = os.environ.get("GITHUB_OUTPUT")
        if not path:
            print("error: --github-output needs $GITHUB_OUTPUT", file=sys.stderr)
            return 1
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("matrix=" + json.dumps(matrix(result), separators=(",", ":")) + "\n")
    return 0
