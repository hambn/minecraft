"""CurseForge API v1 client.

With CURSEFORGE_API_KEY set it calls the official API. Without a key it uses the
keyless curse.tools proxy, a drop-in mirror of the same API. CURSEFORGE_API_BASE
overrides the base URL (for example a self-hosted proxy).
"""

from __future__ import annotations

import os
import re
import urllib.parse

from . import http
from .models import DependencyRef, FileInfo, ProjectInfo, ProviderUnavailable, ReleaseInfo

API = "https://api.curseforge.com/v1"
PROXY_API = "https://api.curse.tools/v1/cf"
GAME_ID = 432  # Minecraft
PAGE_SIZE = 50

# Loader names CurseForge puts into a file's ``gameVersions`` (lower-case -> canonical).
LOADER_NAMES = {
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
    "paper": "Paper",
    "bukkit": "Bukkit",
    "spigot": "Spigot",
    "purpur": "Purpur",
    "folia": "Folia",
    "sponge": "Sponge",
}
RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}
RELATION_KINDS = {3: "required", 2: "optional", 5: "incompatible", 1: "embedded"}
_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")


class CurseForgeClient:
    name = "curseforge"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("CURSEFORGE_API_KEY") or None
        base = os.environ.get("CURSEFORGE_API_BASE") or (API if self.api_key else PROXY_API)
        self.base = base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}

    def _get(self, path: str) -> dict:
        try:
            return http.get_json(f"{self.base}{path}", headers=self._headers())
        except http.HttpError as exc:
            if self.api_key:
                raise
            raise ProviderUnavailable(f"keyless CurseForge proxy {self.base} failed: {exc}") from exc

    def project(self, ref: str | int) -> ProjectInfo:
        text = str(ref)
        if text.isdigit():
            data = self._get(f"/mods/{text}")["data"]
        else:
            query = urllib.parse.urlencode({"gameId": GAME_ID, "slug": text})
            found = self._get(f"/mods/search?{query}").get("data") or []
            match = next((m for m in found if m.get("slug") == text), None)
            if match is None:
                raise http.HttpError(f"CurseForge project {text!r} not found", 404)
            data = match
        missing = ["license", "server_side"]  # the API reports neither
        authors = [a["name"] for a in data.get("authors") or [] if a.get("name")]
        if not authors:
            missing.append("authors")
        name = data.get("name") or None
        if not name:
            missing.append("name")
        description = data.get("summary") or None
        if not description:
            missing.append("description")
        homepage = (data.get("links") or {}).get("websiteUrl") or None
        if not homepage:
            missing.append("homepage")
        allow = data.get("allowModDistribution")
        return ProjectInfo(
            provider=self.name,
            project_id=str(data["id"]),
            slug=data.get("slug") or str(data["id"]),
            name=name,
            description=description,
            authors=authors,
            license=None,
            homepage=homepage,
            server_side="unknown",
            distribution_allowed=allow if isinstance(allow, bool) else None,
            missing=missing,
        )

    def releases(self, project_id: str, loaders: list[str]) -> list[ReleaseInfo]:
        if not loaders:
            return []
        wanted = {LOADER_NAMES.get(x.lower(), x).lower() for x in loaders}
        out: list[ReleaseInfo] = []
        index = 0
        while True:
            page = self._get(f"/mods/{urllib.parse.quote(str(project_id), safe='')}/files?pageSize={PAGE_SIZE}&index={index}")
            files = page.get("data") or []
            for f in files:
                rel = self._release(f)
                if {x.lower() for x in rel.loaders} & wanted:
                    out.append(rel)
            total = (page.get("pagination") or {}).get("totalCount", 0)
            index += PAGE_SIZE
            if not files or index >= total:
                break
        return out

    def release(self, version_id: str) -> ReleaseInfo:
        """``version_id`` is a CurseForge file id."""
        resp = http.post_json(f"{self.base}/mods/files", {"fileIds": [int(version_id)]}, headers=self._headers())
        files = (resp or {}).get("data") or []
        if not files:
            raise http.HttpError(f"CurseForge file {version_id} not found", 404)
        return self._release(files[0])

    def _release(self, f: dict) -> ReleaseInfo:
        tags = list(f.get("gameVersions") or [])
        game_versions = [t for t in tags if _VERSION_RE.match(t)]
        loaders = [LOADER_NAMES[t.lower()] for t in tags if t.lower() in LOADER_NAMES]
        file = None
        if f.get("downloadUrl"):
            sha1 = sha512 = None
            for h in f.get("hashes") or []:
                if h.get("algo") == 1:
                    sha1 = h.get("value")
            file = FileInfo(
                filename=f.get("fileName") or "",
                url=f["downloadUrl"],
                sha512=sha512,
                sha1=sha1,
                size=f.get("fileLength"),
            )
        deps = [
            DependencyRef(self.name, str(d["modId"]), None, RELATION_KINDS[d["relationType"]])
            for d in f.get("dependencies") or []
            if d.get("relationType") in RELATION_KINDS
        ]
        return ReleaseInfo(
            provider=self.name,
            project_id=str(f["modId"]),
            version_id=str(f["id"]),
            version_number=f.get("fileName") or str(f["id"]),
            name=f.get("displayName") or f.get("fileName") or str(f["id"]),
            release_type=RELEASE_TYPES.get(f.get("releaseType"), "alpha"),
            published=f.get("fileDate") or "",
            game_versions=game_versions,
            loaders=loaders,
            file=file,
            dependencies=deps,
        )
