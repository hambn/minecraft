"""Export everything the website shows as one JSON document (site-data command).

The website (``src/web``) is built only from this file, so adding a server,
changing a loader's description or publishing new locks changes the site
without touching any web code. Inputs per server: the loader's class
attributes, ``locks/status.json`` and ``locks/<minecraft>.json``. Offline and
standard library only; the output is deterministic for identical inputs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .config import GITHUB_REPOSITORY, SERVERS_DIR, server_locks_dir
from .loaders import SERVERS, WINDOW_SIZE, get_loader
from .util import write_json
from .versions import try_parse

SCHEMA = 1
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
STATES = ("published", "pending", "frozen")


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        print(f"warning: ignoring {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"warning: ignoring {path}: not a JSON object", file=sys.stderr)
        return None
    return data


def _versions(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return [str(v) for v in items if VERSION_RE.match(str(v))]


def _sort_key(version: str) -> tuple:
    return (try_parse(version) or (), version)


def version_state(version: str, status: dict, window: list[str], upcoming: list[str]) -> str:
    """published | pending | frozen | unlisted, from status.json."""
    if version in upcoming:
        return "pending"
    target = (status.get("targets") or {}).get(version)
    if isinstance(target, dict):
        state = str(target.get("state", ""))
        return state if state in STATES else "unlisted"
    return "pending" if version in window else "unlisted"


def server_data(server: str, owner: str, servers_dir: Path) -> dict:
    loader = get_loader(server)
    locks_dir = server_locks_dir(server, servers_dir)
    status = _read(locks_dir / "status.json") or {}
    targets = status.get("targets") if isinstance(status.get("targets"), dict) else {}
    locks = {}
    for path in sorted(locks_dir.glob("*.json")):
        if path.name != "status.json" and VERSION_RE.match(path.stem):
            lock = _read(path)
            if lock is not None:
                locks[path.stem] = lock
    window = _versions(status.get("window"))
    upcoming = _versions(status.get("upcoming"))
    names = {v for v in targets if VERSION_RE.match(str(v))} | set(locks) | set(window) | set(upcoming)

    versions = []
    for version in sorted(names, key=_sort_key, reverse=True):
        target = targets.get(version) if isinstance(targets.get(version), dict) else {}
        state = version_state(version, status, window, upcoming)
        versions.append({
            "minecraft": version,
            "state": state,
            # Rebuilt automatically whenever a component changes.
            "maintained": state == "published" and version in window,
            "digest": target.get("digest") if state in ("published", "frozen") else None,
            "published_at": target.get("published_at"),
            "reason": target.get("reason"),
            "lock": locks.get(version),
        })

    latest = status.get("latest")
    return {
        "id": server,
        "title": loader.title or server.title(),
        "description": loader.description,
        "homepage": loader.homepage or None,
        "image": f"ghcr.io/{owner}/{loader.image}",
        "loader_label": loader.loader_label or "Loader version",
        "catalog": {"kind": loader.catalog_kind, "env": loader.env_var, "dir": loader.catalog_dir},
        # Repository path that custom_build directories and prebuilt paths are relative to.
        "manifest_dir": f"src/mc-server-images/{Path(loader.manifest).parent.as_posix()}",
        "eula": loader.eula,
        "window": window,
        "upcoming": upcoming,
        "latest": str(latest) if latest and VERSION_RE.match(str(latest)) else None,
        "latest_outside_window": bool(status.get("latest_outside_window")),
        "updated_at": status.get("updated_at"),
        "versions": versions,
    }


def build(repo: str = GITHUB_REPOSITORY, servers_dir: Path = SERVERS_DIR) -> dict:
    owner = repo.split("/")[0].lower()
    servers = [server_data(s, owner, servers_dir) for s in SERVERS]
    stamps = [s["updated_at"] for s in servers if s["updated_at"]]
    return {
        "schema": SCHEMA,
        "repo": repo,
        "owner": owner,
        "window_size": WINDOW_SIZE,
        "updated_at": max(stamps) if stamps else None,
        "servers": servers,
    }


def site_data_command(args: argparse.Namespace) -> int:
    data = build(args.repo, Path(args.servers))
    write_json(args.out, data)
    print(f"wrote {args.out}: {len(data['servers'])} servers", file=sys.stderr)
    return 0
