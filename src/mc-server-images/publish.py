"""`publish` command: push tested images, retag latest, write status.json, commit locks.

Run by the `push_image` job of each server workflow after all `build` jobs
finished. See `.agents/contracts.md` ("Workflows", "Status file").

Everything with side effects (subprocesses, clock, window lookup, release
uploads, sleeping) is injectable so the logic runs offline in tests.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = HERE.parents[1]

SCHEMA = 1
CUSTOM_RELEASE_TAG = "custom-artifacts"
DEFAULT_GITHUB_REPOSITORY = "hambn/minecraft"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
PUSH_ATTEMPTS = 5
DRY_RUN_DIGEST = "sha256:" + "0" * 64
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class PublishError(Exception):
    """A fatal problem; nothing (further) is published."""


def log(message: str) -> None:
    print(f"publish: {message}", flush=True)


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(data: Any) -> str:
    """Canonical lock form: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def status_json(data: dict) -> str:
    """Status file form: insertion order is meaningful (window first), 2-space indent."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------
# Reading build artifacts


def read_results(artifacts: Path, server: str) -> dict[str, dict]:
    """Return {minecraft: {"result": dict, "dir": Path}} for this server.

    `actions/download-artifact` creates `<artifacts>/<artifact name>/result.json`;
    nested layouts are tolerated by searching recursively.
    """
    found: dict[str, dict] = {}
    if not artifacts.is_dir():
        return found  # no build jobs ran: every target was unchanged or pending
    for path in sorted(artifacts.rglob("result.json")):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PublishError(f"unreadable {path}: {exc}") from exc
        if not isinstance(result, dict) or not result.get("minecraft"):
            log(f"ignoring {path}: not a build result")
            continue
        if result.get("server") not in (None, server):
            log(f"ignoring {path}: belongs to server {result.get('server')!r}")
            continue
        mc = str(result["minecraft"])
        if mc in found:
            log(f"warning: duplicate result for {mc}: {path} replaces {found[mc]['dir']}")
        found[mc] = {"result": result, "dir": path.parent}
    return found


def read_plan_pending(plan_dir: Path | None) -> dict[str, str]:
    """``{minecraft: reason}`` for the plan's pending targets (they get no build job)."""
    if plan_dir is None:
        return {}
    path = Path(plan_dir) / "plan.json"
    if not path.is_file():
        raise PublishError(f"plan file does not exist: {path}")
    plan = read_json(path)
    return {
        str(t["minecraft"]): t.get("reason") or "pending"
        for t in plan.get("targets") or []
        if t.get("status") == "pending"
    }


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublishError(f"cannot read {path}: {exc}") from exc


# --------------------------------------------------------------------------
# Status computation (pure)


def compute_status(
    previous: dict | None,
    *,
    server: str,
    image_ref: str,
    window: list[str],
    published: dict[str, dict],
    pending: dict[str, str],
    now: str,
    upcoming: list[str] | None = None,
) -> dict:
    """Compute the new status.json content.

    published: {mc: {"digest": str}} for targets pushed in this run.
    pending:   {mc: reason} for targets the plan reported as pending.
    upcoming:  newer releases the server has no stable build for yet.
    """
    previous = previous or {}
    prev_targets: dict[str, dict] = previous.get("targets") or {}
    upcoming = [mc for mc in upcoming or [] if mc not in window]
    in_window = set(window)
    targets: dict[str, dict] = {}

    for mc in upcoming:
        old = prev_targets.get(mc)
        if mc in pending:
            targets[mc] = {"state": "pending", "reason": pending[mc]}
        elif old and old.get("state") == "pending":
            targets[mc] = dict(old)

    for mc in window:
        old = prev_targets.get(mc)
        if mc in published:
            digest = published[mc]["digest"]
            if old and old.get("digest") == digest and old.get("state") in ("published", "frozen"):
                # Same bytes as before: keep the old timestamp to avoid churn.
                published_at = old.get("published_at", now)
            else:
                published_at = now
            targets[mc] = {
                "state": "published",
                "digest": digest,
                "published_at": published_at,
                "lock": f"{mc}.json",
            }
        elif old and old.get("digest") and old.get("state") in ("published", "frozen"):
            # Previously published (also covers a pending rebuild): keep it.
            targets[mc] = {**old, "state": "published"}
        elif mc in pending:
            targets[mc] = {"state": "pending", "reason": pending[mc]}
        elif old:
            targets[mc] = dict(old)
        # else: no information about this version yet; leave it out.

    # Versions that left the window are dropped (their locks are deleted); the
    # registry tags stay but are no longer maintained.

    latest = None
    outside = False
    for mc in window:
        if targets.get(mc, {}).get("state") == "published":
            latest = mc
            break
    if latest is None:
        latest = previous.get("latest")
        outside = latest is not None and latest not in in_window

    status = {
        "schema": SCHEMA,
        "server": server,
        "image": image_ref,
        "updated_at": now,
        "window": list(window),
        "upcoming": upcoming,
        "latest": latest,
        "latest_outside_window": outside,
        "targets": targets,
    }
    if previous and _without_updated(previous) == _without_updated(status):
        status["updated_at"] = previous.get("updated_at", now)
    return status


def _without_updated(status: dict) -> dict:
    return {k: v for k, v in status.items() if k != "updated_at"}


# --------------------------------------------------------------------------
# Default (real) side effects


def default_runner(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def default_window(server: str) -> tuple[list[str], list[str]]:
    """``(window, upcoming)`` for this server, detected the same way as ``plan``."""
    sys.path.insert(0, str(HERE)) if str(HERE) not in sys.path else None
    from loaders import get_loader, server_window  # noqa: PLC0415 - lazy: needs network

    detected = server_window(get_loader(server))
    return detected.window, detected.upcoming


def default_uploader(repo: str, tag: str, path: Path, name: str) -> None:
    sys.path.insert(0, str(HERE)) if str(HERE) not in sys.path else None
    from sources import github  # noqa: PLC0415

    github.upload_release_asset(repo, tag, path, name)


class Publisher:
    def __init__(
        self,
        args: Any,
        *,
        run: Callable[..., None] | None = None,
        now: Callable[[], datetime] | None = None,
        window_fn: Callable[[], tuple[list[str], list[str]]] | None = None,
        upload_fn: Callable[[str, str, Path, str], None] | None = None,
        sleep: Callable[[float], None] | None = None,
        servers_dir: Path | None = None,
        repo_root: Path | None = None,
        environ: dict | None = None,
    ) -> None:
        self.server: str = args.server
        self.artifacts = Path(args.artifacts)
        self.registry: str = args.registry.rstrip("/")
        self.dry_run: bool = bool(getattr(args, "dry_run", False))
        self.no_commit: bool = bool(getattr(args, "no_commit", False))
        plan_dir = getattr(args, "plan", None)
        self.plan_dir: Path | None = Path(plan_dir) if plan_dir else None
        self._run = run or default_runner
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._window_fn = window_fn or (lambda: default_window(self.server))
        self._upload_fn = upload_fn or default_uploader
        self._sleep = sleep or time.sleep
        self.repo_root = Path(repo_root) if repo_root else DEFAULT_REPO_ROOT
        self.servers_dir = Path(servers_dir) if servers_dir else HERE
        self.environ = os.environ if environ is None else environ
        self.server_locks = self.servers_dir / self.server / "locks"
        self.errors: list[str] = []

    # -- command execution -------------------------------------------------

    def run(self, cmd: list[str], *, cwd: Path | None = None, mutating: bool = True) -> bool:
        """Run (or, in dry-run mode, print) a command. Returns True when it ran."""
        if self.dry_run and mutating:
            print("+ " + " ".join(shlex.quote(part) for part in cmd), flush=True)
            return False
        self._run(cmd, cwd=cwd)
        return True

    # -- main flow ---------------------------------------------------------

    def execute(self) -> int:
        window, upcoming = self._window_fn()
        window, upcoming = [str(v) for v in window], [str(v) for v in upcoming]
        log(f"window: {', '.join(window) or '(none)'}; upcoming: {', '.join(upcoming) or '(none)'}")
        found = read_results(self.artifacts, self.server)

        built: dict[str, dict] = {}
        pending: dict[str, str] = {
            mc: reason for mc, reason in read_plan_pending(self.plan_dir).items()
            if mc in window or mc in upcoming
        }
        for mc, item in sorted(found.items()):
            result = item["result"]
            status = result.get("status")
            if mc not in window and not (status == "pending" and mc in upcoming):
                log(f"ignoring {mc}: outside the current window (stale job)")
                continue
            if status == "built":
                built[mc] = item
            elif status == "pending":
                pending[mc] = result.get("reason") or "pending"
            elif status == "unchanged":
                log(f"{mc}: unchanged, nothing to publish")
            else:
                log(f"warning: {mc}: unknown status {status!r}, ignoring")

        failed = [mc for mc, item in built.items() if not item["result"].get("passed")]
        if failed:
            raise PublishError(
                "refusing to publish: CI checks failed for " + ", ".join(sorted(failed))
            )

        image_name = self._image_name(built)
        image_ref = f"{self.registry}/{image_name}" if image_name else None
        previous = self._load_status()
        if image_ref is None:
            image_ref = (previous or {}).get("image")
        if image_ref is None:
            image_ref = f"{self.registry}/minecraft-server-{self.server}"

        # 4. Push images (window order, newest first).
        published: dict[str, dict] = {}
        for mc in window:
            if mc not in built:
                continue
            try:
                published[mc] = {"digest": self._push_image(image_ref, mc, built[mc]["dir"])}
            except (PublishError, subprocess.CalledProcessError) as exc:
                self.errors.append(f"push of {mc} failed: {exc}")
                log(f"error: {self.errors[-1]}")

        # 5. Custom build outputs.
        self._upload_custom([built[mc]["dir"] for mc in published])

        # 6. Status.
        status = compute_status(
            previous,
            server=self.server,
            image_ref=image_ref,
            window=window,
            published=published,
            pending=pending,
            now=utc_iso(self._now()),
            upcoming=upcoming,
        )

        # 7. Move latest when it changed or was rebuilt.
        latest = status["latest"]
        if (
            latest
            and not status["latest_outside_window"]
            and latest in window
            and status["targets"][latest]["state"] == "published"
            and (latest in published or latest != (previous or {}).get("latest"))
        ):
            self.run(
                [
                    "skopeo", "copy", "--all",
                    f"docker://{image_ref}:{latest}",
                    f"docker://{image_ref}:latest",
                ]
            )
            log(f"latest -> {latest}")

        # 8. Files.
        changed = self._write_files(status, previous, published, built)
        print("status.json:\n" + status_json(status), end="", flush=True)

        # 9. Commit.
        if not changed:
            log("nothing changed")
        elif self.no_commit:
            log("--no-commit: leaving changes in the working tree")
        else:
            self._commit(list(published), window)

        if self.errors:
            log(f"{len(self.errors)} error(s) occurred")
            return 1
        return 0

    # -- steps -------------------------------------------------------------

    def _image_name(self, built: dict[str, dict]) -> str | None:
        for item in built.values():
            lock_path = item["dir"] / "lock.json"
            if lock_path.is_file():
                image = read_json(lock_path).get("image")
                if image:
                    return str(image)
        return None

    def _load_status(self) -> dict | None:
        path = self.server_locks / "status.json"
        if path.is_file():
            return read_json(path)
        return None

    def _push_image(self, image_ref: str, mc: str, directory: Path) -> str:
        tar = directory / "image.tar"
        if not tar.is_file():
            raise PublishError(f"{mc}: image.tar missing in {directory}")
        if not (directory / "lock.json").is_file():
            raise PublishError(f"{mc}: lock.json missing in {directory}")
        if self.dry_run:
            digestfile = Path(tempfile.gettempdir()) / "digest-file"
        else:
            digestfile = Path(tempfile.mkdtemp(prefix="publish-")) / "digest"
        ran = self.run(
            [
                "skopeo", "copy", "--digestfile", str(digestfile),
                f"docker-archive:{tar}",
                f"docker://{image_ref}:{mc}",
            ]
        )
        if not ran:
            return DRY_RUN_DIGEST
        try:
            digest = digestfile.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PublishError(f"{mc}: skopeo wrote no digest file: {exc}") from exc
        if not DIGEST_RE.match(digest):
            raise PublishError(f"{mc}: unexpected digest {digest!r}")
        log(f"pushed {image_ref}:{mc} {digest}")
        return digest

    def _upload_custom(self, directories: list[Path]) -> None:
        repo = self.environ.get("GITHUB_REPOSITORY") or DEFAULT_GITHUB_REPOSITORY
        seen: set[str] = set()
        for directory in directories:
            results_path = directory / "custom" / "results.json"
            if not results_path.is_file():
                continue
            results = read_json(results_path)
            for entry_id, entry in sorted(results.items()):
                if entry.get("status") != "built" or not entry.get("path"):
                    continue
                path = Path(entry["path"])
                if not path.is_absolute():
                    path = results_path.parent / path
                name = f"{entry['cache_key']}-{entry['filename']}"
                if name in seen:
                    continue
                seen.add(name)
                if self.dry_run:
                    print(
                        f"+ upload_release_asset {repo} {CUSTOM_RELEASE_TAG} {path} {name}",
                        flush=True,
                    )
                    continue
                self._upload_fn(repo, CUSTOM_RELEASE_TAG, path, name)
                log(f"uploaded {name} ({entry_id})")

    def _write_files(
        self, status: dict, previous: dict | None, published: dict, built: dict
    ) -> bool:
        changed = False
        # Locks of versions that left the window are no longer needed.
        if self.server_locks.is_dir():
            for path in sorted(self.server_locks.glob("*.json")):
                if path.name == "status.json" or path.stem in status["window"]:
                    continue
                changed = True
                if not self.dry_run:
                    path.unlink()
                log(f"lock {path.name} removed (left the window)")
        for mc in published:
            lock = read_json(built[mc]["dir"] / "lock.json")
            text = canonical_json(lock)
            dest = self.server_locks / f"{mc}.json"
            if dest.is_file() and dest.read_text(encoding="utf-8") == text:
                continue
            changed = True
            if not self.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
            log(f"lock {dest.name} updated")
        if previous != status:
            changed = True
            if not self.dry_run:
                self.server_locks.mkdir(parents=True, exist_ok=True)
                (self.server_locks / "status.json").write_text(
                    status_json(status), encoding="utf-8"
                )
        return changed

    def _commit(self, versions: list[str], window: list[str]) -> None:
        try:
            rel = self.server_locks.relative_to(self.repo_root)
        except ValueError:
            rel = self.server_locks
        if versions:
            message = f"chore({self.server}): update locks for {', '.join(versions)}"
        else:
            message = f"chore({self.server}): update status"
        cwd = self.repo_root
        self.run(["git", "add", str(rel)], cwd=cwd)
        self.run(
            [
                "git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
                "commit", "-m", message,
            ],
            cwd=cwd,
        )
        last: Exception | None = None
        for attempt in range(1, PUSH_ATTEMPTS + 1):
            try:
                self.run(["git", "pull", "--rebase", "origin", "main"], cwd=cwd)
                self.run(["git", "push", "origin", "HEAD:main"], cwd=cwd)
                return
            except subprocess.CalledProcessError as exc:
                last = exc
                log(f"push attempt {attempt}/{PUSH_ATTEMPTS} failed: {exc}")
                if attempt < PUSH_ATTEMPTS:
                    self._sleep(2 ** attempt)
        raise PublishError(f"could not push to main after {PUSH_ATTEMPTS} attempts: {last}")


def publish_command(args: Any, **injected: Any) -> int:
    """Entry point used by cli.py. Returns the process exit code."""
    try:
        return Publisher(args, **injected).execute()
    except (PublishError, subprocess.CalledProcessError) as exc:
        print(f"publish: error: {exc}", file=sys.stderr, flush=True)
        return 1
