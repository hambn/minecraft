"""Repository locations and project-wide constants."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
# Per-server Dockerfile, entrypoint.sh, manifest and committed locks; common/*.sh.
SERVERS_DIR = REPO_ROOT / "src" / "mc-server-images"
LICENSES_FILE = SERVERS_DIR / "licenses.yml"

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY") or "hambn/minecraft"
# GitHub release holding built custom artifacts, named ``<cache_key>-<filename>``.
CUSTOM_RELEASE_TAG = "custom-artifacts"


def server_locks_dir(server: str, servers_dir: Path = SERVERS_DIR) -> Path:
    """Committed locks and status.json of one server."""
    return Path(servers_dir) / server / "locks"
