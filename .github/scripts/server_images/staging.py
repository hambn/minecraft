"""`stage` command: produce the Docker build context from a final lock.

See ``.agents/contracts.md`` ("Docker build context", ``catalog.tsv``).
Every artifact is verified against the lock's hashes before it enters the
context; unavailable entries (no artifact) are skipped.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import SERVERS_DIR
from .loaders import get_loader
from .sources import http
from .util import read_json, sha512_file, write_json

HASH_KEYS = ("sha512", "sha256", "sha1")
TSV_HEADER = "#id\tstatus\tselectable\tkind\tfilename\tclosure\tconflicts\treason"


class StageError(Exception):
    """Fatal staging problem (missing file, checksum mismatch)."""


def log(message: str) -> None:
    print(f"stage: {message}", flush=True)


# ------------------------------------------------------------------ catalog.tsv

def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        value = ",".join(str(v) for v in value)
    text = str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    return text or "-"


def render_catalog_tsv(entries: list[dict]) -> str:
    lines = [TSV_HEADER]
    for entry in entries:
        artifact = entry.get("artifact")
        lines.append("\t".join([
            _cell(entry["id"]),
            _cell(entry.get("status")),
            _cell(bool(entry.get("selectable"))),
            _cell("declared" if entry.get("declared") else "dependency"),
            _cell(artifact["filename"] if artifact else None),
            _cell(entry.get("closure") or []),
            _cell(entry.get("conflicts") or []),
            _cell(entry.get("reason")),
        ]))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ build-args

def build_args(lock: dict) -> dict[str, str]:
    runtime = lock.get("runtime") or {}
    build = lock.get("server_build") or {}
    details = build.get("details") or {}
    base_image = runtime.get("base_image") or ""
    base_digest = runtime.get("base_digest")
    java = runtime.get("java_major")
    args = {
        "BASE_IMAGE": f"{base_image}@{base_digest}" if base_digest else base_image,
        "MINECRAFT_VERSION": lock["minecraft_version"],
        "LOADER_VERSION": build.get("loader_version") or "",
        "JAVA_MAJOR": "" if java is None else str(java),
    }
    if lock["server"] == "pumpkin":
        source = details.get("source") or {}
        args["BUILDER_IMAGE"] = details.get("builder_image") or ""
        args["PUMPKIN_REPO"] = source.get("repo") or ""
        args["PUMPKIN_COMMIT"] = source.get("commit") or ""
    if lock["server"] == "fabric":
        args["INSTALLER_VERSION"] = details.get("installer_version") or ""
    return args


def render_build_args(args: dict[str, str]) -> str:
    return "".join(f"{key}={value}\n" for key, value in args.items())


# --------------------------------------------------------------------- staging

def _verified_copy(src: Path, dest: Path, sha512: str, what: str) -> None:
    if not src.is_file():
        raise StageError(f"{what}: file not found: {src}")
    actual = sha512_file(src)
    if actual != sha512:
        raise StageError(f"{what}: sha512 mismatch for {src} (expected {sha512}, got {actual})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def _stage_downloads(lock: dict, ctx: Path) -> None:
    downloads = ((lock.get("server_build") or {}).get("details") or {}).get("downloads") or {}
    for name, spec in sorted(downloads.items()):
        suffix = Path(urlparse(spec["url"]).path).suffix
        hashes = {k: spec[k] for k in HASH_KEYS if spec.get(k)}
        if not hashes:
            raise StageError(f"download {name}: no hash in lock")
        dest = ctx / "downloads" / f"{name}{suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        http.download(spec["url"], dest, **hashes)
        log(f"downloaded {dest.name}")


def _stage_catalog_files(lock: dict, ctx: Path, custom: Path | None, manifest_dir: Path) -> None:
    files = ctx / "catalog" / "files"
    files.mkdir(parents=True, exist_ok=True)
    for entry in lock.get("entries", []):
        artifact = entry.get("artifact")
        if not artifact:
            continue
        what = f"entry {entry['id']}"
        dest = files / artifact["filename"]
        sha512 = artifact["sha512"]
        local, build = entry.get("local"), entry.get("build")
        if artifact.get("url"):
            http.download(artifact["url"], dest, sha512=sha512)
        elif local:
            _verified_copy(manifest_dir / local["path"], dest, sha512, what)
        elif build:
            if custom is None:
                raise StageError(f"{what}: custom artifact needs --custom")
            _verified_copy(custom / _custom_name(entry, custom), dest, sha512, what)
        else:
            raise StageError(f"{what}: artifact has no url, local file or build")


def _custom_name(entry: dict, custom: Path) -> str:
    results = custom / "results.json"
    if results.is_file():
        result = read_json(results).get(entry["id"]) or {}
        if result.get("path"):
            return result["path"]
    build = entry["build"]
    return f"{build['cache_key']}-{entry['artifact']['filename']}"


def _copy_server_files(ctx: Path, base: Path, server: str) -> None:
    shutil.copyfile(base / server / "Dockerfile", ctx / "Dockerfile")
    shutil.copyfile(base / server / "entrypoint.sh", ctx / "entrypoint.sh")
    (ctx / "common").mkdir(parents=True, exist_ok=True)
    for path in sorted((base / "common").glob("*.sh")):
        shutil.copyfile(path, ctx / "common" / path.name)


def stage(lock: dict, ctx: Path, custom: Path | None = None, base_dir: Path = SERVERS_DIR,
          manifest_dir: Path | None = None) -> None:
    """Write the build context for ``lock`` into ``ctx`` (replaced)."""
    base = Path(base_dir)
    manifest_dir = manifest_dir or get_loader(lock["server"]).manifest_dir
    if ctx.exists():
        shutil.rmtree(ctx)
    ctx.mkdir(parents=True)
    _copy_server_files(ctx, base, lock["server"])
    (ctx / "downloads").mkdir()
    _stage_downloads(lock, ctx)
    _stage_catalog_files(lock, ctx, custom, manifest_dir)
    catalog = ctx / "catalog"
    (catalog / "catalog.tsv").write_text(render_catalog_tsv(lock.get("entries", [])), encoding="utf-8")
    write_json(catalog / "catalog.json", {
        "server": lock["server"],
        "minecraft_version": lock["minecraft_version"],
        "loader_version": (lock.get("server_build") or {}).get("loader_version"),
        "entries": lock.get("entries", []),
    })
    write_json(catalog / "lock.json", lock)
    (ctx / "build-args.env").write_text(render_build_args(build_args(lock)), encoding="utf-8")


def stage_command(args) -> int:
    lock = read_json(args.lock)
    if lock.get("server") != args.server:
        print(f"error: lock is for {lock.get('server')!r}, not {args.server!r}", file=sys.stderr)
        return 1
    stage(lock, Path(args.out), Path(args.custom) if args.custom else None)
    log(f"context ready: {args.out}")
    return 0
