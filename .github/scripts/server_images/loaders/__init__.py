"""Server-specific version and support rules.

Each server's rules live in ``loaders/<server>.py`` and expose a module-level
``LOADER``.  A loader decides, for one exact Minecraft release, whether a
stable server build exists and which downloads/base image it needs.  Missing
builds are reported as ``pending``.

The maintenance window is per server: the newest ``WINDOW_SIZE`` stable
Minecraft releases that the server has a stable build for.  Newer releases the
server does not support yet are reported as ``upcoming`` (pending).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from ..config import SERVERS_DIR
from ..sources import registry

SERVERS = ["fabric", "neoforge", "paper", "pumpkin"]
WINDOW_SIZE = 3
# How many of the newest Mojang releases are checked when looking for supported ones.
MAX_SCAN = 15


@dataclass
class ServerBuild:
    status: str  # available | pending
    reason: str | None
    loader_version: str | None
    runtime: dict
    details: dict = field(default_factory=dict)


class Loader:
    server: ClassVar[str] = ""
    image: ClassVar[str] = ""
    catalog_kind: ClassVar[str] = ""  # mods | plugins
    env_var: ClassVar[str] = ""  # MODS | PLUGINS
    manifest: ClassVar[str] = ""  # relative to SERVERS_DIR, e.g. "fabric/mods/mods.yml"
    provider_loaders: ClassVar[dict[str, list[str]]] = {}
    artifact_ext: ClassVar[str] = ".jar"

    @property
    def manifest_dir(self) -> Path:
        """Directory the manifest's relative paths (prebuilt files, sources) resolve against."""
        return SERVERS_DIR / Path(self.manifest).parent

    def resolve_build(self, minecraft: str) -> ServerBuild:
        raise NotImplementedError


@dataclass
class ServerWindow:
    window: list[str]  # supported releases to maintain, newest first
    upcoming: list[str]  # newer releases without a stable server build yet
    builds: dict[str, ServerBuild]  # resolved builds for window + upcoming


def server_window(loader: Loader, count: int = WINDOW_SIZE, releases: list[str] | None = None) -> ServerWindow:
    """Find the newest ``count`` Mojang releases this server has a stable build for."""
    if releases is None:
        from ..sources import mojang

        releases = mojang.release_ids()
    window: list[str] = []
    upcoming: list[str] = []
    builds: dict[str, ServerBuild] = {}
    for mc in releases[:MAX_SCAN]:
        build = loader.resolve_build(mc)
        if build.status == "available":
            window.append(mc)
            builds[mc] = build
            if len(window) >= count:
                break
        elif not window:
            upcoming.append(mc)
            builds[mc] = build
    if not window:
        for mc in upcoming[count:]:
            builds.pop(mc, None)
        upcoming = upcoming[:count]
    return ServerWindow(window=window, upcoming=upcoming, builds=builds)


def empty_runtime() -> dict:
    return {"base_image": None, "base_digest": None, "java_major": None}


def pending(reason: str, runtime: dict | None = None) -> ServerBuild:
    return ServerBuild(
        status="pending",
        reason=reason,
        loader_version=None,
        runtime=runtime if runtime is not None else empty_runtime(),
    )


def java_runtime(java_major: int) -> dict:
    """Pinned Temurin JRE runtime for a Java server."""
    base = f"eclipse-temurin:{int(java_major)}-jre"
    return {
        "base_image": base,
        "base_digest": registry.resolve_digest(base),
        "java_major": int(java_major),
    }


def get_loader(server: str) -> Loader:
    if server not in SERVERS:
        raise ValueError(f"unknown server {server!r}; expected one of {SERVERS}")
    return importlib.import_module(f".{server}", __name__).LOADER
