"""Resolve container image references to manifest digests (anonymous access)."""

from __future__ import annotations

import hashlib
import re
import urllib.parse

from . import http

ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
DOCKER_HUB = "registry-1.docker.io"


def parse_reference(image: str) -> tuple[str, str, str]:
    """Return ``(registry_host, repository, tag_or_digest)``."""
    name, reference = image, "latest"
    if "@" in name:
        name, reference = name.split("@", 1)
    else:
        last = name.rsplit("/", 1)[-1]
        if ":" in last:
            name, reference = name.rsplit(":", 1)
    parts = name.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        host, repo = parts[0], "/".join(parts[1:])
    else:
        host, repo = "docker.io", name
    if host in ("docker.io", "index.docker.io"):
        host = DOCKER_HUB
        if "/" not in repo:
            repo = f"library/{repo}"
    return host, repo, reference


def _parse_challenge(header: str) -> tuple[str, dict[str, str]]:
    scheme, _, rest = header.strip().partition(" ")
    return scheme.lower(), dict(re.findall(r'(\w+)="([^"]*)"', rest))


def _token(challenge: str, repo: str) -> str | None:
    scheme, params = _parse_challenge(challenge)
    if scheme != "bearer" or "realm" not in params:
        return None
    query = {"scope": params.get("scope") or f"repository:{repo}:pull"}
    if params.get("service"):
        query["service"] = params["service"]
    resp = http.get_json(f"{params['realm']}?{urllib.parse.urlencode(query)}")
    return resp.get("token") or resp.get("access_token")


def resolve_digest(image: str) -> str:
    host, repo, reference = parse_reference(image)
    if reference.startswith("sha256:"):
        return reference
    url = f"https://{host}/v2/{repo}/manifests/{reference}"
    headers = {"Accept": ACCEPT}
    resp = http.request(url, headers=headers, method="HEAD")
    if resp.status == 401:
        token = _token(resp.header("www-authenticate") or "", repo)
        if token is None:
            raise http.HttpError(f"{image}: registry requires unsupported authentication", 401, url)
        headers["Authorization"] = f"Bearer {token}"
        resp = http.request(url, headers=headers, method="HEAD")
    if resp.status >= 400:
        raise http.HttpError(f"{image}: HTTP {resp.status} resolving manifest", resp.status, url)
    digest = resp.header("docker-content-digest")
    if not digest:
        resp = http.request(url, headers=headers, method="GET")
        if resp.status >= 400:
            raise http.HttpError(f"{image}: HTTP {resp.status} resolving manifest", resp.status, url)
        digest = resp.header("docker-content-digest") or "sha256:" + hashlib.sha256(resp.body).hexdigest()
    return digest
