"""Pumpkin: newest default-branch commit; it supports exactly one Minecraft version."""

from __future__ import annotations

import re

from loaders import Loader, ServerBuild, pending
from sources import github, http, registry

REPO = "Pumpkin-MC/Pumpkin"
REPO_URL = "https://github.com/Pumpkin-MC/Pumpkin"

# Where the supported Minecraft version is declared (generated file; the
# value is an enum variant such as JavaMinecraftVersion::V_26_3).
VERSION_FILE_CANDIDATES = [
    "crates/pumpkin-data/src/generated/packet.rs",
]
VERSION_RE = re.compile(r"CURRENT_MC_VERSION\s*:\s*JavaMinecraftVersion\s*=\s*(?:[\w:]*::)?V_(\d+(?:_\d+)*)\b")

# rust-toolchain.toml only says "stable"; the real minimum is the workspace rust-version.
TOOLCHAIN_FILES = ["rust-toolchain.toml", "rust-toolchain", "Cargo.toml"]
TOOLCHAIN_RES = [
    re.compile(r'channel\s*=\s*"(\d+\.\d+(?:\.\d+)?)"'),
    re.compile(r'(?m)^\s*rust-version\s*=\s*"(\d+\.\d+(?:\.\d+)?)"'),
]
# Without a declared minimum, the floating "1" tag (newest stable Rust) is used.
FALLBACK_RUST_VERSION = "1"
# Debian suites tried in order; the builder and runtime always share one codename.
DEBIAN_RELEASE = "https://deb.debian.org/debian/dists/{suite}/Release"
DEBIAN_SUITES = ["stable", "oldstable"]
_CODENAME_RE = re.compile(r"(?m)^Codename:\s*(\S+)")


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
                return match.group(1).replace("_", ".")
    return None


def find_rust_version(commit: str) -> str:
    for path in TOOLCHAIN_FILES:
        text = _read_optional(commit, path)
        if text:
            for regex in TOOLCHAIN_RES:
                match = regex.search(text)
                if match:
                    return match.group(1)
    return FALLBACK_RUST_VERSION


def debian_codenames() -> list[str]:
    """Codenames of the current Debian stable and oldstable releases."""
    names = []
    for suite in DEBIAN_SUITES:
        try:
            match = _CODENAME_RE.search(http.get_text(DEBIAN_RELEASE.format(suite=suite)))
        except http.HttpError:
            continue
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


class PumpkinLoader(Loader):
    server = "pumpkin"
    image = "minecraft-server-pumpkin"
    catalog_kind = "plugins"
    env_var = "PLUGINS"
    manifest = "pumpkin/plugins/plugins.yml"
    provider_loaders = {"modrinth": [], "curseforge": []}
    artifact_ext = ".wasm"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, str | None]] = {}

    def _source(self) -> tuple[str, str | None]:
        """``(commit, supported Minecraft)``, looked up once per run (the window scan asks repeatedly)."""
        if "source" not in self._cache:
            commit = github.latest_commit(REPO, github.default_branch(REPO))
            self._cache["source"] = (commit, find_supported_minecraft(commit))
        return self._cache["source"]

    def resolve_build(self, minecraft: str) -> ServerBuild:
        commit, supported = self._source()
        if supported is None:
            return pending(
                f"Could not determine the Minecraft version supported by Pumpkin commit {commit[:12]}"
            )
        if supported != minecraft:
            return pending(
                f"Pumpkin ({commit[:12]}) supports Minecraft {supported}, not {minecraft}"
            )

        rust = find_rust_version(commit)
        for codename in debian_codenames():
            builder = f"rust:{rust}-{codename}"
            runtime_base = f"debian:{codename}-slim"
            try:
                builder_image = f"{builder}@{registry.resolve_digest(builder)}"
                runtime_digest = registry.resolve_digest(runtime_base)
            except http.HttpError:
                continue  # no Rust image for this Debian release yet: try the previous one
            break
        else:
            return pending(f"No rust:{rust} builder image found for a current Debian release")

        runtime = {"base_image": runtime_base, "base_digest": runtime_digest, "java_major": None}
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
