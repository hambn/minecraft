"""GitHub REST API helpers (GITHUB_TOKEN optional)."""

from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path

from . import http

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra or {})
    return headers


def _q(value: str, safe: str = "") -> str:
    return urllib.parse.quote(value, safe=safe)


def default_branch(repo: str) -> str:
    return http.get_json(f"{API}/repos/{repo}", headers=_headers())["default_branch"]


def latest_commit(repo: str, branch: str) -> str:
    return http.get_json(f"{API}/repos/{repo}/commits/{_q(branch, '/')}", headers=_headers())["sha"]


def file_at(repo: str, ref: str, path: str) -> str:
    url = f"{API}/repos/{repo}/contents/{_q(path, '/')}?ref={_q(ref, '/')}"
    return http.get_text(url, headers=_headers({"Accept": "application/vnd.github.raw+json"}))


def _release_by_tag(repo: str, tag: str) -> dict | None:
    try:
        return http.get_json(f"{API}/repos/{repo}/releases/tags/{_q(tag, '/')}", headers=_headers())
    except http.HttpError as exc:
        if exc.status == 404:
            return None
        raise


def release_asset_url(repo: str, tag: str, asset: str) -> str | None:
    release = _release_by_tag(repo, tag)
    for item in (release or {}).get("assets") or []:
        if item.get("name") == asset:
            return item["browser_download_url"]
    return None


def _send(url: str, method: str, data: bytes | None, content_type: str) -> dict | None:
    resp = http.request(url, headers=_headers({"Content-Type": content_type}), method=method, data=data)
    if resp.status >= 400:
        raise http.HttpError(f"HTTP {resp.status} for {method} {url}: {resp.body[:300]!r}", resp.status, url)
    return json.loads(resp.body) if resp.body else None


def upload_release_asset(repo: str, tag: str, path: Path, name: str) -> None:
    """Upload ``path`` as asset ``name`` of release ``tag``, creating the release if missing."""
    release = _release_by_tag(repo, tag)
    if release is None:
        payload = json.dumps({"tag_name": tag, "name": tag, "body": "Generated custom build artifacts.", "prerelease": False})
        release = _send(f"{API}/repos/{repo}/releases", "POST", payload.encode("utf-8"), "application/json")
    assert release is not None
    for item in release.get("assets") or []:
        if item.get("name") == name:  # replace an existing asset of the same name
            _send(f"{API}/repos/{repo}/releases/assets/{item['id']}", "DELETE", None, "application/json")
    url = f"{UPLOADS}/repos/{repo}/releases/{release['id']}/assets?name={_q(name)}"
    _send(url, "POST", Path(path).read_bytes(), "application/octet-stream")
