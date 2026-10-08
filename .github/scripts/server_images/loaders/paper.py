"""Paper: newest STABLE-channel build from the Fill API v3."""

from __future__ import annotations

from . import Loader, ServerBuild, java_runtime, pending
from ..sources import http, mojang

API = "https://fill.papermc.io/v3/projects/paper/versions"


class PaperLoader(Loader):
    server = "paper"
    image = "minecraft-server-paper"
    catalog_kind = "plugins"
    env_var = "PLUGINS"
    manifest = "paper/plugins/plugins.yml"
    provider_loaders = {
        "modrinth": ["paper", "spigot", "bukkit"],
        "curseforge": ["Paper", "Spigot", "Bukkit"],
    }
    artifact_ext = ".jar"

    def resolve_build(self, minecraft: str) -> ServerBuild:
        try:
            builds = http.get_json(f"{API}/{minecraft}/builds")
        except http.HttpError:
            return pending(f"Paper has no builds for Minecraft {minecraft} yet")

        candidates = []
        for build in builds or []:
            if build.get("channel") != "STABLE":
                continue
            download = (build.get("downloads") or {}).get("server:default")
            sha256 = ((download or {}).get("checksums") or {}).get("sha256")
            if download and download.get("url") and sha256:
                candidates.append((build["id"], build, download, sha256))
        if not candidates:
            return pending(f"No STABLE Paper build for Minecraft {minecraft} yet")
        build_id, build, download, sha256 = max(candidates, key=lambda c: c[0])

        details = mojang.version_details(minecraft)
        runtime = java_runtime(details["java_major"])
        return ServerBuild(
            status="available",
            reason=None,
            loader_version=str(build_id),
            runtime=runtime,
            details={
                "downloads": {"paper": {"url": download["url"], "sha256": sha256}},
                "build": build_id,
                "channel": build.get("channel", "STABLE"),
            },
        )


LOADER = PaperLoader()
