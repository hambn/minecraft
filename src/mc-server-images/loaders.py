"""Shared base for the server-specific version and support rules.

Each server's rules live in ``<server>/loader.py`` next to its Dockerfile and
expose a module-level ``LOADER``.

Each loader decides, for one exact Minecraft release, whether a stable server
build exists and which downloads/base image it needs.  Missing builds are
reported as ``pending``; an older Minecraft version is never substituted.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sources import registry

SERVERS = ["fabric", "neoforge", "paper", "pumpkin"]
BASE_DIR = Path(__file__).resolve().parent


@dataclass
class ServerBuild:
    status: str  # available | pending
    reason: str | None
    loader_version: str | None
    runtime: dict
    details: dict = field(default_factory=dict)


class Loader:
    server: str = ""
    image: str = ""
    catalog_kind: str = ""
    env_var: str = ""
    manifest: str = ""
    provider_loaders: dict = {}
    artifact_ext: str = ".jar"

    def resolve_build(self, minecraft: str) -> ServerBuild:
        raise NotImplementedError


def empty_runtime() -> dict:
    return {"base_image": None, "base_digest": None, "java_major": None}


def pending(reason: str, runtime: dict | None = None) -> ServerBuild:
    return ServerBuild(
        status="pending",
        reason=reason,
        loader_version=None,
        runtime=runtime if runtime is not None else empty_runtime(),
        details={},
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
    return load_module(server).LOADER


def load_module(server: str):
    """Import ``<server>/loader.py`` (server dirs are not packages) as ``<server>_loader``."""
    name = f"{server}_loader"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, BASE_DIR / server / "loader.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]
