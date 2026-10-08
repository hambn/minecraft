"""Fabric: stable loader from Fabric meta + vanilla server jar from Mojang."""

from __future__ import annotations

from . import Loader, ServerBuild, java_runtime, pending
from ..sources import http, mojang

META = "https://meta.fabricmc.net/v2/versions"
MAVEN = "https://maven.fabricmc.net/net/fabricmc/fabric-installer"


def _first_stable(items: list[dict]) -> dict | None:
    # Fabric meta lists newest first.
    for item in items:
        if item.get("stable"):
            return item
    return None


class FabricLoader(Loader):
    server = "fabric"
    image = "minecraft-server-fabric"
    catalog_kind = "mods"
    env_var = "MODS"
    manifest = "fabric/mods/mods.yml"
    provider_loaders = {"modrinth": ["fabric"], "curseforge": ["Fabric"]}
    artifact_ext = ".jar"

    def resolve_build(self, minecraft: str) -> ServerBuild:
        games = http.get_json(f"{META}/game")
        game = next((g for g in games if g.get("version") == minecraft), None)
        if game is None or not game.get("stable"):
            return pending(f"Fabric meta does not list Minecraft {minecraft} as a stable game version yet")

        loader = _first_stable(http.get_json(f"{META}/loader"))
        if loader is None:
            return pending("No stable Fabric loader build is available")
        installer = _first_stable(http.get_json(f"{META}/installer"))
        if installer is None:
            return pending("No stable Fabric installer build is available")

        details = mojang.version_details(minecraft)
        runtime = java_runtime(details["java_major"])
        server_jar = details["server_jar"]

        installer_version = installer["version"]
        installer_url = f"{MAVEN}/{installer_version}/fabric-installer-{installer_version}.jar"
        installer_sha1 = http.get_text(installer_url + ".sha1").strip().split()[0]

        return ServerBuild(
            status="available",
            reason=None,
            loader_version=loader["version"],
            runtime=runtime,
            details={
                "downloads": {
                    "installer": {"url": installer_url, "sha1": installer_sha1},
                    "server": {"url": server_jar["url"], "sha1": server_jar["sha1"]},
                },
                "installer_version": installer_version,
            },
        )


LOADER = FabricLoader()
