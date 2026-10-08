"""Mojang version manifest client."""

from __future__ import annotations

import functools
from typing import Any

from . import http

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


@functools.lru_cache(maxsize=1)
def _manifest() -> dict:
    # One fetch per process: the window scan asks for details of several releases.
    return http.get_json(MANIFEST_URL)


def stable_releases() -> list[dict]:
    """Release versions, newest first by release time: ``[{id, release_time, url}]``."""
    manifest = _manifest()
    items = [
        {"id": v["id"], "release_time": v["releaseTime"], "url": v["url"]}
        for v in manifest.get("versions", [])
        if v.get("type") == "release"
    ]
    items.sort(key=lambda v: v["release_time"], reverse=True)
    return items


def release_ids() -> list[str]:
    """Stable release IDs, newest first."""
    return [v["id"] for v in stable_releases()]


def version_details(mc: str) -> dict:
    """``{"java_major": int, "server_jar": {"url", "sha1", "size"}}`` for a release."""
    entry = next((v for v in stable_releases() if v["id"] == mc), None)
    if entry is None:
        raise KeyError(f"Minecraft release {mc!r} not found in the Mojang manifest")
    detail: dict[str, Any] = http.get_json(entry["url"])
    server = (detail.get("downloads") or {}).get("server")
    if not server:
        raise KeyError(f"Minecraft {mc} has no server download")
    java = (detail.get("javaVersion") or {}).get("majorVersion", 8)
    return {
        "java_major": int(java),
        "server_jar": {"url": server["url"], "sha1": server.get("sha1"), "size": server.get("size")},
    }
