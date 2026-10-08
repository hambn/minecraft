"""Load and validate ``mods.yml`` / ``plugins.yml`` manifests.

An invalid manifest raises :class:`ManifestError` with a message naming the
file, section and entry; CI treats that as a hard failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import versions

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SECTIONS = ("modrinth", "curseforge", "custom_build", "prebuilt")
UPSTREAM_SECTIONS = ("modrinth", "curseforge")


class ManifestError(Exception):
    """The manifest is structurally invalid."""


@dataclass
class UpstreamEntry:
    id: str
    provider: str            # "modrinth" | "curseforge"
    project: str | int


@dataclass
class LocalEntry:
    id: str
    kind: str                # "custom_build" | "prebuilt"
    minecraft_versions: list[str]
    dependencies: list[str]
    metadata: dict[str, Any]
    # prebuilt
    path: str | None = None            # as declared (relative to manifest dir)
    abs_path: Path | None = None
    # custom_build
    directory: str | None = None       # as declared
    abs_directory: Path | None = None
    build: dict[str, Any] | None = None


@dataclass
class Manifest:
    path: Path
    base_dir: Path
    modrinth: list[UpstreamEntry] = field(default_factory=list)
    curseforge: list[UpstreamEntry] = field(default_factory=list)
    custom_build: list[LocalEntry] = field(default_factory=list)
    prebuilt: list[LocalEntry] = field(default_factory=list)

    @property
    def upstream(self) -> list[UpstreamEntry]:
        return [*self.modrinth, *self.curseforge]

    @property
    def local(self) -> list[LocalEntry]:
        return [*self.custom_build, *self.prebuilt]

    @property
    def ids(self) -> list[str]:
        return [e.id for e in self.upstream] + [e.id for e in self.local]


def _fail(path: Path, where: str, message: str) -> ManifestError:
    return ManifestError(f"{path}: {where}: {message}")


def _require_str(path: Path, where: str, data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(path, where, f"'{key}' is required and must be a non-empty string")
    return value


def _safe_relative(path: Path, where: str, key: str, value: str) -> None:
    pure = Path(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise _fail(path, where, f"'{key}' must be a relative path inside the manifest directory (got {value!r})")


def _validate_metadata(path: Path, where: str, meta: Any) -> dict[str, Any]:
    if not isinstance(meta, dict):
        raise _fail(path, where, "'metadata' is required and must be a mapping")
    for key in ("name", "description", "version", "license"):
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip():
            hint = " (quote version numbers, e.g. \"1.0\")" if key == "version" and value is not None else ""
            raise _fail(path, where, f"metadata.{key} is required and must be a non-empty string{hint}")
    authors = meta.get("authors")
    if (
        not isinstance(authors, list)
        or not authors
        or not all(isinstance(a, str) and a.strip() for a in authors)
    ):
        raise _fail(path, where, "metadata.authors is required and must be a non-empty list of strings")
    homepage = meta.get("homepage")
    if homepage is not None and not isinstance(homepage, str):
        raise _fail(path, where, "metadata.homepage must be a string")
    return dict(meta)


def _validate_versions(path: Path, where: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise _fail(
            path, where,
            "'minecraft_versions' is required and must be a non-empty list of quoted strings "
            "(exact like \"26.3\" or families like \"26.1.x\")",
        )
    for item in value:
        try:
            versions.validate_declared(item)
        except ValueError:
            raise _fail(path, where, f"invalid Minecraft version {item!r} (use \"26.3\" or \"26.1.x\")") from None
    return list(value)


def _validate_dependencies(path: Path, where: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _fail(path, where, "'dependencies' must be a list of manifest IDs")
    return list(value)


def load(path: str | Path, *, artifact_ext: str | None = None, check_files: bool = True) -> Manifest:
    """Parse and validate the manifest at ``path``."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"{path}: cannot read manifest: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path}: invalid YAML: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: top level must be a mapping with sections {', '.join(SECTIONS)}")
    unknown = sorted(set(data) - set(SECTIONS))
    if unknown:
        raise ManifestError(f"{path}: unknown section(s) {', '.join(map(str, unknown))}; allowed: {', '.join(SECTIONS)}")

    base = path.parent
    manifest = Manifest(path=path, base_dir=base)
    seen: dict[str, str] = {}

    def register(where: str, entry_id: str) -> None:
        if entry_id in seen:
            raise _fail(path, where, f"duplicate id {entry_id!r} (already used in {seen[entry_id]})")
        seen[entry_id] = where

    for section in SECTIONS:
        items = data.get(section)
        if items is None:
            items = []
        if not isinstance(items, list):
            raise _fail(path, section, "must be a list")
        for index, raw in enumerate(items):
            where = f"{section}[{index}]"
            if not isinstance(raw, dict):
                raise _fail(path, where, "must be a mapping")
            entry_id = raw.get("id")
            if not isinstance(entry_id, str) or not ID_RE.match(entry_id):
                raise _fail(path, where, f"'id' must match {ID_RE.pattern} (got {entry_id!r})")
            where = f"{section}[{entry_id}]"
            register(where, entry_id)

            if section in UPSTREAM_SECTIONS:
                project = raw.get("project")
                if isinstance(project, bool) or not isinstance(project, (str, int)) or str(project).strip() == "":
                    raise _fail(path, where, "'project' is required (slug/ID string or numeric ID)")
                if section == "curseforge" and not str(project).isdigit():
                    raise _fail(path, where, "'project' must be a numeric CurseForge project ID")
                getattr(manifest, section).append(UpstreamEntry(entry_id, section, project))
                continue

            mc_versions = _validate_versions(path, where, raw.get("minecraft_versions"))
            deps = _validate_dependencies(path, where, raw.get("dependencies"))
            meta = _validate_metadata(path, where, raw.get("metadata"))
            if section == "prebuilt":
                rel = _require_str(path, where, raw, "path")
                _safe_relative(path, where, "path", rel)
                abs_path = base / rel
                if check_files and not abs_path.is_file():
                    raise _fail(path, where, f"prebuilt file not found: {rel}")
                if artifact_ext and not rel.lower().endswith(artifact_ext):
                    raise _fail(path, where, f"prebuilt path must end with {artifact_ext} (got {rel})")
                manifest.prebuilt.append(LocalEntry(
                    id=entry_id, kind="prebuilt", minecraft_versions=mc_versions,
                    dependencies=deps, metadata=meta, path=rel, abs_path=abs_path,
                ))
            else:
                rel = _require_str(path, where, raw, "directory")
                _safe_relative(path, where, "directory", rel)
                abs_dir = base / rel
                if check_files and not abs_dir.is_dir():
                    raise _fail(path, where, f"source directory not found: {rel}")
                build = raw.get("build")
                if not isinstance(build, dict):
                    raise _fail(path, where, "'build' is required and must be a mapping")
                image = _require_str(path, f"{where}.build", build, "builder_image")
                if "@sha256:" not in image or image.split("@sha256:", 1)[1].strip() == "":
                    raise _fail(path, f"{where}.build", "builder_image must be pinned by digest (contain '@sha256:<digest>')")
                command = build.get("command")
                if (
                    not isinstance(command, list) or not command
                    or not all(isinstance(c, str) and c for c in command)
                ):
                    raise _fail(path, f"{where}.build", "'command' is required and must be a non-empty list of strings")
                output = _require_str(path, f"{where}.build", build, "output")
                _safe_relative(path, f"{where}.build", "output", output)
                manifest.custom_build.append(LocalEntry(
                    id=entry_id, kind="custom_build", minecraft_versions=mc_versions,
                    dependencies=deps, metadata=meta, directory=rel, abs_directory=abs_dir,
                    build={"builder_image": image, "command": list(command), "output": output},
                ))

    all_ids = set(seen)
    for entry in manifest.local:
        for dep in entry.dependencies:
            if dep not in all_ids:
                raise _fail(path, f"{entry.kind}[{entry.id}]", f"dependency {dep!r} is not a manifest id")
            if dep == entry.id:
                raise _fail(path, f"{entry.kind}[{entry.id}]", "an entry cannot depend on itself")
    return manifest
