"""`build-custom` command: build or fetch custom source artifacts for one target.

Reads the draft lock ``<plan>/<minecraft>.json`` and, for every ``custom_build``
entry, either downloads the already built artifact from the ``custom-artifacts``
release (``cached``) or builds it in the pinned builder image (``built``).
Build problems never fail the command: the entry is recorded as ``failed`` and
``locks.apply_custom_results`` marks it unavailable. Corrupt cached artifacts
(checksum mismatch) raise, so CI fails.

See ``.agents/contracts.md`` ("CLI", ``build-custom`` results.json).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .config import CUSTOM_RELEASE_TAG, GITHUB_REPOSITORY
from .loaders import get_loader
from .sources import github, http
from .util import read_json, sha512_file, write_json

BUILD_TIMEOUT = 40 * 60


def log(message: str) -> None:
    print(f"build-custom: {message}", flush=True)


def _docker_command(build: dict, work: Path, version: str, targets: dict) -> list[str]:
    return [
        "docker", "run", "--rm",
        "-v", f"{work}:/src", "-w", "/src",
        "-e", f"ARTIFACT_VERSION={version}",
        "-e", f"MINECRAFT_VERSION={targets.get('minecraft') or ''}",
        "-e", f"LOADER={targets.get('loader') or ''}",
        "-e", f"LOADER_VERSION={targets.get('loader_version') or ''}",
        build["builder_image"], *build["command"],
    ]


def _result(status: str, **fields: Any) -> dict:
    base = {"status": status, "filename": None, "sha512": None, "cache_key": None,
            "path": None, "uploaded": False, "reason": None}
    base.update(fields)
    return base


def build_one(entry: dict, minecraft: str, out: Path, repo: str, manifest_dir: Path) -> dict:
    build = entry["build"]
    targets = build.get("targets") or {}
    if not targets or targets.get("minecraft") != minecraft:
        return _result("skipped", cache_key=build.get("cache_key"),
                       reason=f"not declared for Minecraft {minecraft}")

    cache_key = build["cache_key"]
    filename = Path(build["output"]).name
    local_name = f"{cache_key}-{filename}"
    dest = out / local_name

    asset_url = github.release_asset_url(repo, CUSTOM_RELEASE_TAG, local_name)
    if asset_url:
        expected = (entry.get("artifact") or {}).get("sha512")
        hashes = {"sha512": expected} if expected else {}
        # HashMismatch and HttpError propagate: a broken cache must fail CI.
        http.download(asset_url, dest, **hashes)
        if not dest.is_file() or dest.stat().st_size == 0:
            raise RuntimeError(f"{entry['id']}: cached artifact {local_name} is empty")
        log(f"{entry['id']}: cached {local_name}")
        return _result("cached", filename=filename, sha512=sha512_file(dest),
                       cache_key=cache_key, path=local_name)

    try:
        source = manifest_dir / build["directory"]
        if not source.is_dir():
            return _result("failed", cache_key=cache_key, reason=f"source directory not found: {build['directory']}")
        version = (entry.get("metadata") or {}).get("version") or ""
        with tempfile.TemporaryDirectory(prefix="custom-build-") as tmp:
            work = Path(tmp) / "src"
            shutil.copytree(source, work, symlinks=True, ignore=shutil.ignore_patterns(".git"))
            cmd = _docker_command(build, work, version, targets)
            log(f"{entry['id']}: building ({build['builder_image']})")
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, timeout=BUILD_TIMEOUT)
            if proc.returncode != 0:
                tail = "\n".join((proc.stdout or "").strip().splitlines()[-15:])
                return _result("failed", cache_key=cache_key,
                               reason=f"build command exited with {proc.returncode}: {tail}"[:2000])
            output = work / build["output"]
            if not output.is_file():
                return _result("failed", cache_key=cache_key,
                               reason=f"build output not found: {build['output']}")
            shutil.copyfile(output, dest)
        digest = sha512_file(dest)
        log(f"{entry['id']}: built {local_name}")
        return _result("built", filename=filename, sha512=digest, cache_key=cache_key, path=local_name)
    except subprocess.TimeoutExpired:
        return _result("failed", cache_key=cache_key, reason=f"build timed out after {BUILD_TIMEOUT}s")
    except (OSError, KeyError, ValueError) as exc:
        return _result("failed", cache_key=cache_key, reason=f"{type(exc).__name__}: {exc}")


def build_custom_command(args) -> int:
    plan_dir = Path(args.plan)
    draft_path = plan_dir / f"{args.minecraft}.json"
    if not draft_path.is_file():
        print(f"error: no draft lock {draft_path}", file=sys.stderr)
        return 1
    draft = read_json(draft_path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_dir = get_loader(args.server).manifest_dir

    results: dict[str, dict] = {}
    for entry in draft.get("entries", []):
        if entry.get("build"):
            results[entry["id"]] = build_one(entry, args.minecraft, out, GITHUB_REPOSITORY, manifest_dir)

    write_json(out / "results.json", results)
    counts: dict[str, int] = {}
    for result in results.values():
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    log(f"{len(results)} custom entries: {counts or 'none'}")
    return 0
