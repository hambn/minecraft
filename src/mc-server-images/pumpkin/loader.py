"""Pumpkin: newest master commit; it supports exactly one Minecraft version."""

from __future__ import annotations

import re

from loaders import Loader, ServerBuild, pending
from sources import github, registry

REPO = "Pumpkin-MC/Pumpkin"
BRANCH = "master"
REPO_URL = "https://github.com/Pumpkin-MC/Pumpkin"

# Where the supported Minecraft version is declared; tried in order.
VERSION_FILE_CANDIDATES = [
    "pumpkin-util/src/lib.rs",
    "pumpkin-protocol/src/lib.rs",
    "pumpkin-data/src/lib.rs",
    "pumpkin-data/src/packet/mod.rs",
]
VERSION_RE = re.compile(r'CURRENT_MC_VERSION\s*:\s*&(?:\s*\'static)?\s*str\s*=\s*"([^"]+)"')

TOOLCHAIN_FILES = ["rust-toolchain.toml", "rust-toolchain"]
TOOLCHAIN_RE = re.compile(r'channel\s*=\s*"(\d+\.\d+(?:\.\d+)?)"')
DEFAULT_RUST_VERSION = "1.90"
DEBIAN = "bookworm"
RUNTIME_BASE = "debian:bookworm-slim"


def _read_optional(commit: str, path: str) -> str | None:
    try:
        return github.file_at(REPO, commit, path)
    except Exception:  # missing file / API error: try the next candidate
        return None


def find_supported_minecraft(commit: str) -> str | None:
    for path in VERSION_FILE_CANDIDATES:
        text = _read_optional(commit, path)
        if text:
            match = VERSION_RE.search(text)
            if match:
                return match.group(1)
    return None


def find_rust_version(commit: str) -> str:
    for path in TOOLCHAIN_FILES:
        text = _read_optional(commit, path)
        if text:
            match = TOOLCHAIN_RE.search(text)
            if match:
                return match.group(1)
    return DEFAULT_RUST_VERSION


class PumpkinLoader(Loader):
    server = "pumpkin"
    image = "minecraft-server-pumpkin"
    catalog_kind = "plugins"
    env_var = "PLUGINS"
    manifest = "pumpkin/plugins/plugins.yml"
    provider_loaders = {"modrinth": [], "curseforge": []}
    artifact_ext = ".wasm"

    def resolve_build(self, minecraft: str) -> ServerBuild:
        commit = github.latest_commit(REPO, BRANCH)
        supported = find_supported_minecraft(commit)
        if supported is None:
            return pending(
                f"Could not determine the Minecraft version supported by Pumpkin commit {commit[:12]}"
            )
        if supported != minecraft:
            return pending(
                f"Pumpkin master ({commit[:12]}) supports Minecraft {supported}, not {minecraft}"
            )

        builder = f"rust:{find_rust_version(commit)}-{DEBIAN}"
        builder_image = f"{builder}@{registry.resolve_digest(builder)}"
        runtime = {
            "base_image": RUNTIME_BASE,
            "base_digest": registry.resolve_digest(RUNTIME_BASE),
            "java_major": None,
        }
        return ServerBuild(
            status="available",
            reason=None,
            loader_version=commit,
            runtime=runtime,
            details={
                "downloads": {},
                "source": {"repo": REPO_URL, "commit": commit},
                "builder_image": builder_image,
                "supported_minecraft": supported,
            },
        )


LOADER = PumpkinLoader()
