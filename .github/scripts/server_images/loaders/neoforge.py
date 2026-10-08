"""NeoForge: newest non-beta version in the NeoForged maven for a Minecraft release."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from . import Loader, ServerBuild, java_runtime, pending
from ..sources import http, mojang
from ..versions import parse

MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
METADATA_URL = f"{MAVEN}/maven-metadata.xml"
_STABLE_RE = re.compile(r"^\d+(?:\.\d+)+$")  # any qualifier (-beta, -alpha, ...) is not stable


def version_prefix(minecraft: str) -> str:
    """NeoForge version prefix for a Minecraft release.

    New scheme (26.x and later): MC 26.1.2 -> "26.1.2.", MC 26.1 -> "26.1.0.".
    Legacy scheme (1.A.B):       MC 1.21 -> "21.0.", MC 1.21.1 -> "21.1.".
    """
    parts = parse(minecraft)
    if len(parts) < 2:
        raise ValueError(f"unsupported Minecraft version {minecraft!r}")
    patch = parts[2] if len(parts) > 2 else 0
    if parts[0] == 1:
        return f"{parts[1]}.{patch}."
    return f"{parts[0]}.{parts[1]}.{patch}."


class NeoForgeLoader(Loader):
    server = "neoforge"
    image = "minecraft-server-neoforge"
    catalog_kind = "mods"
    env_var = "MODS"
    manifest = "neoforge/mods/mods.yml"
    provider_loaders = {"modrinth": ["neoforge"], "curseforge": ["NeoForge"]}
    artifact_ext = ".jar"

    def resolve_build(self, minecraft: str) -> ServerBuild:
        try:
            prefix = version_prefix(minecraft)
        except ValueError as exc:
            return pending(str(exc))

        root = ET.fromstring(http.get_text(METADATA_URL))
        versions = [(el.text or "").strip() for el in root.iter("version")]
        stable = [v for v in versions if v.startswith(prefix) and _STABLE_RE.match(v)]
        if not stable:
            return pending(f"No stable NeoForge build for Minecraft {minecraft} yet")
        best = max(stable, key=parse)

        details = mojang.version_details(minecraft)
        runtime = java_runtime(details["java_major"])

        url = f"{MAVEN}/{best}/neoforge-{best}-installer.jar"
        sha1 = http.get_text(url + ".sha1").strip().split()[0]
        return ServerBuild(
            status="available",
            reason=None,
            loader_version=best,
            runtime=runtime,
            details={"downloads": {"installer": {"url": url, "sha1": sha1}}},
        )


LOADER = NeoForgeLoader()
