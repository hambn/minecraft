"""Lock schema helpers: ``inputs_hash``, dependency graph, finalize (the ``lock`` command)."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .config import SERVERS_DIR
from .util import read_json, write_json

SCHEMA = 1

# Reason prefix used for failed custom builds; the planner retries these.
BUILD_FAILED_PREFIX = "custom build failed"


def _compact(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sort_entries(lock: dict) -> dict:
    lock["entries"] = sorted(lock.get("entries", []), key=lambda e: e["id"])
    return lock


def write_lock(path: str | Path, lock: dict) -> None:
    write_json(path, sort_entries(lock))


# ------------------------------------------------------------------ inputs_hash

def _normalized_for_hash(lock: dict) -> dict:
    """Lock view hashed for ``inputs_hash``.

    The hash must be identical for a draft (custom artifacts not built yet) and
    for the finalized lock built from the same inputs, otherwise nothing would
    ever be ``unchanged``.  So everything the custom-build step fills in (or
    that derives from it) is neutralised: build entries lose artifact, status,
    reason, selectable and storage, and so do entries that depend on them
    (selectable and a derived reason).
    """
    view = copy.deepcopy(lock)
    view.pop("inputs_hash", None)
    entries = view.get("entries", [])
    build_ids = {e["id"] for e in entries if e.get("build")}
    for entry in entries:
        build = entry.get("build")
        if build:
            entry["artifact"] = None
            entry["status"] = "draft"
            entry["reason"] = None
            entry["selectable"] = None
            build["storage"] = None
        elif build_ids & set(entry.get("closure", [])):
            entry["selectable"] = None
            if entry.get("status") == "compatible":
                entry["reason"] = None
    return view


def _hash_files(server: str, base_dir: Path) -> list[Path]:
    files = [Path(server) / "Dockerfile", Path(server) / "entrypoint.sh"]
    common = base_dir / "common"
    if common.is_dir():
        files += sorted(Path("common") / p.name for p in common.iterdir() if p.is_file() and p.name.endswith(".sh"))
    return sorted(files, key=lambda p: p.as_posix())


def compute_inputs_hash(lock: dict, base_dir: str | Path = SERVERS_DIR) -> str:
    """sha256 over the normalized lock plus Dockerfile, entrypoint.sh and common/*.sh."""
    base = Path(base_dir)
    digest = hashlib.sha256()
    digest.update(_compact(_normalized_for_hash(lock)))
    for rel in _hash_files(lock["server"], base):
        digest.update(b"\0" + rel.as_posix().encode("utf-8") + b"\0")
        file = base / rel
        if file.is_file():
            data = file.read_bytes()
            digest.update(str(len(data)).encode() + b"\0" + data)
        else:
            digest.update(b"missing")
    return "sha256:" + digest.hexdigest()


# ------------------------------------------------------------------------ graph

def recompute_graph(entries: list[dict]) -> None:
    """Recompute ``closure``, ``selectable`` and dependency-derived reasons in place."""
    by_id = {e["id"]: e for e in entries}

    def required(entry: dict) -> list[str]:
        return [d["id"] for d in entry.get("dependencies", []) if d.get("kind", "required") == "required"]

    for entry in entries:
        seen: set[str] = set()
        stack = [entry["id"]]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in by_id:
                stack.extend(required(by_id[current]))
        entry["closure"] = sorted(seen)

    for entry in entries:
        blockers = []
        for member in entry["closure"]:
            if member == entry["id"]:
                continue
            dep = by_id.get(member)
            if dep is None:
                blockers.append(f"dependency {member} is not in the catalog")
            elif dep["status"] != "compatible":
                why = dep.get("reason") or dep["status"]
                blockers.append(f"dependency {member} is {dep['status']}: {why}")
        entry["selectable"] = entry["status"] == "compatible" and not blockers
        if entry["status"] == "compatible":
            entry["reason"] = None if not blockers else "; ".join(blockers)


# --------------------------------------------------------------------- finalize

def apply_custom_results(lock: dict, results: dict, custom_dir: str | Path | None = None) -> None:
    """Merge ``build-custom`` results into the draft entries (in place)."""
    for entry in lock["entries"]:
        build = entry.get("build")
        if not build:
            continue
        result = results.get(entry["id"])
        if result is None:
            if entry.get("artifact"):
                continue  # already finalized (idempotent re-run)
            result = {"status": "failed", "reason": "no build result recorded"}
        status = result.get("status")
        if status in ("built", "cached") and result.get("filename") and result.get("sha512"):
            size = None
            if custom_dir and result.get("path"):
                candidate = Path(custom_dir) / result["path"]
                if candidate.is_file():
                    size = candidate.stat().st_size
            entry["artifact"] = {
                "filename": result["filename"], "url": None,
                "sha512": result["sha512"], "size": size,
            }
            build["cache_key"] = result.get("cache_key") or build.get("cache_key")
            build["storage"] = {
                "release": "custom-artifacts",
                "asset": f"{build['cache_key']}-{result['filename']}",
            }
            entry["status"] = "compatible"
            entry["reason"] = None
        else:
            why = result.get("reason") or f"build result status {status!r}"
            entry["status"] = "unavailable"
            entry["reason"] = f"{BUILD_FAILED_PREFIX}: {why}"
            entry["artifact"] = None
            build["storage"] = None


def finalize(draft: dict, results: dict | None, base_dir: str | Path = SERVERS_DIR,
             custom_dir: str | Path | None = None) -> dict:
    lock = copy.deepcopy(draft)
    apply_custom_results(lock, results or {}, custom_dir)
    sort_entries(lock)
    recompute_graph(lock["entries"])
    lock["inputs_hash"] = compute_inputs_hash(lock, base_dir)
    return lock


def finalize_command(args) -> int:
    plan_dir = Path(args.plan)
    draft_path = plan_dir / f"{args.minecraft}.json"
    if not draft_path.is_file():
        print(f"error: no draft lock {draft_path}", file=sys.stderr)
        return 1
    draft = read_json(draft_path)
    results: dict = {}
    custom_dir = args.custom
    if custom_dir:
        results_path = Path(custom_dir) / "results.json"
        if results_path.is_file():
            results = read_json(results_path)
    lock = finalize(draft, results, custom_dir=custom_dir)
    write_json(args.out, lock)
    print(f"wrote {args.out} ({len(lock['entries'])} entries, {lock['inputs_hash']})")
    return 0
