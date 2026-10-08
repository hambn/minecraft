"""Modrinth API v2 client."""

from __future__ import annotations

import json
import urllib.parse

from . import http
from .models import DependencyRef, FileInfo, ProjectInfo, ReleaseInfo

API = "https://api.modrinth.com/v2"
_DEP_KINDS = {
    "required": "required",
    "optional": "optional",
    "incompatible": "incompatible",
    "embedded": "embedded",
}


def _q(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


class ModrinthClient:
    name = "modrinth"

    def project(self, ref: str | int) -> ProjectInfo:
        data = http.get_json(f"{API}/project/{_q(ref)}")
        project_id = data["id"]
        missing: list[str] = []

        authors: list[str] = []
        try:
            members = http.get_json(f"{API}/project/{_q(project_id)}/members")
            authors = [m["user"]["username"] for m in members if (m.get("user") or {}).get("username")]
        except http.HttpError:
            pass
        if not authors:
            missing.append("authors")

        lic = (data.get("license") or {}).get("id") or None
        if not lic:
            missing.append("license")
        name = data.get("title") or None
        if not name:
            missing.append("name")
        description = data.get("description") or None
        if not description:
            missing.append("description")

        slug = data.get("slug") or project_id
        ptype = data.get("project_type")
        homepage = f"https://modrinth.com/{ptype}/{slug}" if ptype else None
        if not homepage:
            missing.append("homepage")

        side = data.get("server_side")
        if side not in ("required", "optional", "unsupported"):
            side = "unknown"
        return ProjectInfo(
            provider=self.name,
            project_id=project_id,
            slug=slug,
            name=name,
            description=description,
            authors=authors,
            license=lic,
            homepage=homepage,
            server_side=side,
            distribution_allowed=None,
            missing=missing,
        )

    def releases(self, project_id: str, loaders: list[str]) -> list[ReleaseInfo]:
        if not loaders:
            return []
        query = urllib.parse.urlencode({"loaders": json.dumps(list(loaders))})
        versions = http.get_json(f"{API}/project/{_q(project_id)}/version?{query}")
        return [self._release(v) for v in versions]

    def release(self, version_id: str) -> ReleaseInfo:
        return self._release(http.get_json(f"{API}/version/{_q(version_id)}"))

    def _release(self, v: dict) -> ReleaseInfo:
        files = v.get("files") or []
        chosen = next((f for f in files if f.get("primary")), files[0] if files else None)
        file = None
        if chosen:
            hashes = chosen.get("hashes") or {}
            file = FileInfo(
                filename=chosen["filename"],
                url=chosen["url"],
                sha512=hashes.get("sha512"),
                sha1=hashes.get("sha1"),
                size=chosen.get("size"),
            )
        deps: list[DependencyRef] = []
        for d in v.get("dependencies") or []:
            kind = _DEP_KINDS.get(d.get("dependency_type"))
            if kind is None:
                continue
            pid, vid = d.get("project_id"), d.get("version_id")
            if not pid and vid:
                pid = http.get_json(f"{API}/version/{_q(vid)}").get("project_id")
            if not pid:
                continue
            deps.append(DependencyRef(self.name, pid, vid, kind))
        vtype = v.get("version_type")
        return ReleaseInfo(
            provider=self.name,
            project_id=v["project_id"],
            version_id=v["id"],
            version_number=v.get("version_number") or "",
            name=v.get("name") or v.get("version_number") or "",
            release_type=vtype if vtype in ("release", "beta", "alpha") else "alpha",
            published=v.get("date_published") or "",
            game_versions=list(v.get("game_versions") or []),
            loaders=list(v.get("loaders") or []),
            file=file,
            dependencies=deps,
        )
