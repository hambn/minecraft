#!/usr/bin/env python3
"""CI checks for a built server image (stdlib only, runs on the CI host).

    ci_check.py --image REF --catalog CTX/catalog/catalog.tsv --out checks.json
                [--python-image python:<running version>-slim] [--timeout 600]

Everything goes through the ``docker`` CLI. Server type, catalog env/dir and
the ready pattern come from the image labels. Containers run with
``--network none``. Result file::

    {"image", "server", "minecraft", "passed", "checks": [{"name", "passed", "blocking", "detail"}]}

Exit status 1 when a blocking check failed. The result is written even then.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LABEL_PREFIX = "io.github.hambn.minecraft."
LABEL_SERVER = LABEL_PREFIX + "server"
LABEL_ENV = LABEL_PREFIX + "catalog-env"
LABEL_DIR = LABEL_PREFIX + "catalog-dir"
LABEL_READY = LABEL_PREFIX + "ready-pattern"
LABEL_VERSION = "org.opencontainers.image.version"

MANAGED_FILE = ".catalog-managed"
USER_FILE = "user-owned.keep"
CLEAN_EXIT_CODES = (0, 143)
DETAIL_LIMIT = 2000

# runner(args_after_docker, timeout) -> CompletedProcess(returncode, stdout, stderr)
Runner = Callable[[list, "float | None"], "subprocess.CompletedProcess"]


def docker_runner(args: list, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Default runner: ``docker <args>`` with captured text output."""
    cmd = ["docker", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(cmd, 124, out, f"timed out after {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


@dataclass
class Entry:
    id: str
    status: str
    selectable: bool
    kind: str
    filename: str
    closure: list
    conflicts: list
    reason: str


def _split(value: str) -> list:
    return [p.strip() for p in value.split(",") if p.strip() and p.strip() != "-"]


def parse_catalog(path: Path) -> list:
    entries = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        cols += ["-"] * (8 - len(cols))
        eid, status, sel, kind, filename, closure, conflicts, reason = cols[:8]
        entries.append(
            Entry(
                id=eid,
                status=status,
                selectable=sel == "yes",
                kind=kind,
                filename="" if filename == "-" else filename,
                closure=_split(closure),
                conflicts=_split(conflicts),
                reason="" if reason == "-" else reason,
            )
        )
    return entries


def _clip(text: str, limit: int = DETAIL_LIMIT) -> str:
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _tail(text: str, lines: int = 25) -> str:
    return _clip("\n".join(text.strip().splitlines()[-lines:]))


class CheckFailure(Exception):
    """Raised inside a check to fail it with a message."""


def default_python_image() -> str:
    """python:<major>.<minor>-slim matching the running interpreter (see /.python-version)."""
    return f"python:{sys.version_info.major}.{sys.version_info.minor}-slim"


@dataclass
class Checker:
    image: str
    entries: list
    python_image: str = field(default_factory=lambda: default_python_image())
    runner: Runner = docker_runner
    ready_timeout: float = 600.0
    status_script: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "mc_status.py")
    sleep: Callable = time.sleep
    clock: Callable = time.monotonic
    run_id: str = field(default_factory=lambda: str(os.getpid()))
    poll_interval: float = 2.0
    ping_attempts: int = 5
    ping_delay: float = 3.0

    def __post_init__(self) -> None:
        self.checks: list = []
        self.server = ""
        self.minecraft = ""
        self.env_name = ""
        self.catalog_dir = ""
        self.ready = None
        self._containers: list = []
        self._volumes: list = []
        self._counter = 0
        self._by_id = {e.id: e for e in self.entries}
        self._catalog_files = {e.filename for e in self.entries if e.filename}

    # ------------------------------------------------------------ plumbing

    def docker(self, *args: str, timeout: float | None = 300) -> subprocess.CompletedProcess:
        return self.runner(list(args), timeout)

    def _name(self, kind: str) -> str:
        self._counter += 1
        return f"ci-check-{self.run_id}-{kind}-{self._counter}"

    def new_volume(self, kind: str) -> str:
        name = self._name(kind)
        res = self.docker("volume", "create", name)
        if res.returncode != 0:
            raise CheckFailure(f"docker volume create failed: {_clip(res.stderr)}")
        self._volumes.append(name)
        return name

    def record(self, name: str, blocking: bool, fn: Callable) -> bool:
        try:
            passed, detail = fn()
        except CheckFailure as exc:
            passed, detail = False, str(exc)
        except Exception as exc:  # a broken check must not lose the other results
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        self.checks.append({"name": name, "passed": bool(passed), "blocking": blocking, "detail": _clip(str(detail))})
        status = "PASS" if passed else ("FAIL" if blocking else "WARN")
        print(f"[ci_check] {status} {name}: {_clip(str(detail), 300)}", file=sys.stderr)
        return bool(passed)

    def _env_args(self, env: dict) -> list:
        # Offline mode: checks run with --network none, so no auth servers are reachable.
        args = ["-e", "EULA=TRUE", "-e", "MEMORY=1G", "-e", "PROP_ONLINE_MODE=false"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        return args

    # ----------------------------------------------------------- container

    def start(self, volume: str, env: dict | None = None) -> str:
        name = self._name("srv")
        res = self.docker(
            "run", "-d", "--name", name, "--network", "none",
            *self._env_args(env or {}), "-v", f"{volume}:/data", self.image,
        )
        self._containers.append(name)
        if res.returncode != 0:
            raise CheckFailure(f"docker run failed: {_clip(res.stderr or res.stdout)}")
        return name

    def logs(self, name: str) -> str:
        res = self.docker("logs", name)
        return (res.stdout or "") + (res.stderr or "")

    def wait_ready(self, name: str) -> float:
        started = self.clock()
        while True:
            text = self.logs(name)
            if self.ready.search(text):
                return self.clock() - started
            state = self.docker("inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", name)
            running, _, code = (state.stdout or "").strip().partition(" ")
            if state.returncode == 0 and running == "false":
                raise CheckFailure(f"container exited (code {code}) before ready pattern appeared:\n{_tail(text)}")
            if self.clock() - started > self.ready_timeout:
                raise CheckFailure(f"ready pattern not seen within {self.ready_timeout:.0f}s:\n{_tail(text)}")
            self.sleep(self.poll_interval)

    def stop(self, name: str) -> tuple:
        started = self.clock()
        res = self.docker("stop", "-t", "120", name, timeout=240)
        elapsed = self.clock() - started
        info = self.docker("inspect", "-f", "{{.State.ExitCode}}", name)
        try:
            code = int((info.stdout or "").strip())
        except ValueError:
            code = None
        return res.returncode, code, elapsed

    def remove_container(self, name: str) -> None:
        self.docker("rm", "-f", name)
        if name in self._containers:
            self._containers.remove(name)

    # ------------------------------------------------- one-shot containers

    def activate(self, volume: str, selection: str) -> subprocess.CompletedProcess:
        env = {"ACTIVATE_ONLY": "true", self.env_name: selection}
        return self.docker(
            "run", "--rm", "--network", "none", *self._env_args(env), "-v", f"{volume}:/data", self.image,
            timeout=300,
        )

    def _tool(self, volume: str, entrypoint: str, *args: str) -> subprocess.CompletedProcess:
        return self.docker(
            "run", "--rm", "--network", "none", "--entrypoint", entrypoint, "-v", f"{volume}:/data", self.image, *args,
            timeout=120,
        )

    def list_dir(self, volume: str, path: str) -> set:
        res = self._tool(volume, "ls", "-A1", path)
        if res.returncode != 0:
            if "No such file" in (res.stderr or ""):
                return set()
            raise CheckFailure(f"listing {path} failed: {_clip(res.stderr or res.stdout)}")
        return {line for line in (res.stdout or "").splitlines() if line}

    def read_file(self, volume: str, path: str) -> str | None:
        res = self._tool(volume, "cat", path)
        if res.returncode != 0:
            if "No such file" in (res.stderr or ""):
                return None
            raise CheckFailure(f"reading {path} failed: {_clip(res.stderr or res.stdout)}")
        return res.stdout or ""

    def managed_files(self, volume: str) -> set:
        text = self.read_file(volume, f"{self.catalog_dir}/{MANAGED_FILE}")
        return {line.strip() for line in (text or "").splitlines() if line.strip()}

    def expected_files(self, entry_id: str) -> set:
        entry = self._by_id[entry_id]
        ids = {entry_id, *entry.closure}
        return {self._by_id[i].filename for i in ids if i in self._by_id and self._by_id[i].filename}

    # -------------------------------------------------------------- checks

    def read_labels(self) -> tuple:
        res = self.docker("image", "inspect", "--format", "{{json .Config.Labels}}", self.image, timeout=60)
        if res.returncode != 0:
            raise CheckFailure(f"docker image inspect failed: {_clip(res.stderr or res.stdout)}")
        labels = json.loads(res.stdout or "null") or {}
        missing = [k for k in (LABEL_SERVER, LABEL_ENV, LABEL_DIR, LABEL_READY, LABEL_VERSION) if not labels.get(k)]
        if missing:
            raise CheckFailure("missing image labels: " + ", ".join(missing))
        self.server = labels[LABEL_SERVER]
        self.minecraft = labels[LABEL_VERSION]
        self.env_name = labels[LABEL_ENV]
        self.catalog_dir = labels[LABEL_DIR].rstrip("/")
        try:
            self.ready = re.compile(labels[LABEL_READY])
        except re.error as exc:
            raise CheckFailure(f"ready-pattern is not a valid regex: {exc}") from exc
        return True, f"server={self.server} minecraft={self.minecraft} {self.env_name} dir={self.catalog_dir}"

    def check_boot(self, volume: str, env: dict | None = None) -> tuple:
        name = self.start(volume, env)
        elapsed = self.wait_ready(name)
        return name, f"ready after {elapsed:.0f}s"

    def check_ping(self, name: str) -> tuple:
        last = ""
        for attempt in range(1, self.ping_attempts + 1):
            res = self.docker(
                "run", "--rm", "--network", f"container:{name}",
                "-v", f"{self.status_script}:/mc_status.py:ro", self.python_image,
                "python", "/mc_status.py", "127.0.0.1", "25565", "--timeout", "10",
                timeout=120,
            )
            if res.returncode == 0:
                try:
                    json.loads(res.stdout)
                except ValueError:
                    last = f"output is not JSON: {_clip(res.stdout, 300)}"
                else:
                    return True, _clip(res.stdout, 500)
            else:
                last = _clip(res.stderr or res.stdout, 500)
            if attempt < self.ping_attempts:
                self.sleep(self.ping_delay)
        raise CheckFailure(f"status ping failed after {self.ping_attempts} attempts: {last}")

    def check_empty_selection(self, volume: str) -> tuple:
        present = self.list_dir(volume, self.catalog_dir)
        active = sorted(present & self._catalog_files)
        managed = self.managed_files(volume)
        if active:
            raise CheckFailure(f"catalog files active without selection: {', '.join(active)}")
        if managed:
            raise CheckFailure(f"{MANAGED_FILE} lists files without selection: {', '.join(sorted(managed))}")
        return True, f"no catalog files in {self.catalog_dir} ({len(self._catalog_files)} bundled, all inactive)"

    def check_activate(self, volume: str, entry_id: str) -> tuple:
        res = self.activate(volume, entry_id)
        if res.returncode != 0:
            raise CheckFailure(f"activation exited {res.returncode}: {_tail((res.stderr or '') + (res.stdout or ''))}")
        expected = self.expected_files(entry_id)
        present = self.list_dir(volume, self.catalog_dir)
        active = present & self._catalog_files
        if not expected <= present:
            raise CheckFailure(f"missing after activation: {', '.join(sorted(expected - present))}")
        if active != expected:
            raise CheckFailure(f"unexpected catalog files left active: {', '.join(sorted(active - expected))}")
        managed = self.managed_files(volume)
        if managed != expected:
            raise CheckFailure(f"{MANAGED_FILE} is {sorted(managed)}, expected {sorted(expected)}")
        return True, f"activated {', '.join(sorted(expected))}"

    def check_stale_removed(self, volume: str) -> tuple:
        res = self.activate(volume, "")
        if res.returncode != 0:
            raise CheckFailure(f"activation with empty selection exited {res.returncode}: {_tail(res.stderr or res.stdout)}")
        active = sorted(self.list_dir(volume, self.catalog_dir) & self._catalog_files)
        if active:
            raise CheckFailure(f"stale catalog files remain: {', '.join(active)}")
        managed = self.managed_files(volume)
        if managed:
            raise CheckFailure(f"{MANAGED_FILE} still lists: {', '.join(sorted(managed))}")
        return True, "empty selection removed all previously managed files"

    def check_user_file_kept(self, volume: str) -> tuple:
        if USER_FILE not in self.list_dir(volume, self.catalog_dir):
            raise CheckFailure(f"unrelated file {USER_FILE} was removed")
        return True, f"{USER_FILE} survived every selection change"

    def _expect_rejected(self, volume: str, selection: str, needle: str) -> str:
        res = self.activate(volume, selection)
        output = (res.stderr or "") + (res.stdout or "")
        if res.returncode == 0:
            raise CheckFailure(f"selection {selection!r} was accepted")
        if needle not in output:
            raise CheckFailure(f"rejection message does not mention {needle!r}: {_tail(output)}")
        leaked = sorted(self.list_dir(volume, self.catalog_dir) & self._catalog_files)
        if leaked:
            raise CheckFailure(f"rejected selection {selection!r} still activated: {', '.join(leaked)}")
        return _tail(output, 3)

    def check_unknown_rejected(self, volume: str) -> tuple:
        bogus = "ci-check-no-such-entry"
        return True, self._expect_rejected(volume, bogus, bogus)

    def check_fallback_rejected(self, volume: str) -> tuple:
        fallbacks = [e for e in self.entries if e.status == "unsupported_fallback"]
        if not fallbacks:
            return True, "no unsupported fallbacks in this catalog"
        for entry in fallbacks:
            try:
                self._expect_rejected(volume, entry.id, entry.id)
            except CheckFailure as exc:
                raise CheckFailure(f"{entry.id}: {exc}") from exc
        return True, f"rejected {len(fallbacks)} unsupported fallback(s): {', '.join(e.id for e in fallbacks)}"

    def check_boot_all(self) -> tuple:
        ids = [e.id for e in self.entries if e.selectable and e.status == "compatible"]
        if not ids:
            return True, "no selectable entries"
        volume = self.new_volume("all")
        name, detail = self.check_boot(volume, {self.env_name: ",".join(ids)})
        code, exit_code, _ = self.stop(name)
        if exit_code not in CLEAN_EXIT_CODES:
            raise CheckFailure(f"booted with {len(ids)} entries but stop exit code was {exit_code}")
        return True, f"booted with {len(ids)} entries ({detail})"

    # ----------------------------------------------------------------- run

    def run(self) -> dict:
        try:
            if self.record("labels", True, self.read_labels):
                self._run_checks()
        finally:
            self.cleanup()
        return self.result()

    def _run_checks(self) -> None:
        state = {}

        def boot():
            state["volume"] = self.new_volume("base")
            state["name"], detail = self.check_boot(state["volume"])
            return True, detail

        booted = self.record("baseline-boot", True, boot)

        def ping():
            if not booted:
                raise CheckFailure("skipped: baseline boot failed")
            return self.check_ping(state["name"])

        self.record("status-ping", True, ping)

        def clean_stop():
            if "name" not in state:
                raise CheckFailure("skipped: no container was started")
            code, exit_code, elapsed = self.stop(state["name"])
            if code != 0 or exit_code not in CLEAN_EXIT_CODES:
                raise CheckFailure(f"docker stop returned {code}, container exit code {exit_code}\n{_tail(self.logs(state['name']))}")
            return True, f"stopped in {elapsed:.0f}s with exit code {exit_code}"

        self.record("clean-stop", True, clean_stop)

        def empty():
            if "volume" not in state:
                raise CheckFailure("skipped: no baseline volume")
            return self.check_empty_selection(state["volume"])

        self.record("empty-selection-inactive", True, empty)

        sel: dict = {}

        def prepare():
            sel["volume"] = self.new_volume("sel")
            res = self._tool(sel["volume"], "sh", "-c", 'mkdir -p "$1" && : > "$1/$2"', "sh", self.catalog_dir, USER_FILE)
            if res.returncode != 0:
                raise CheckFailure(f"could not create {USER_FILE}: {_clip(res.stderr or res.stdout)}")
            return True, f"created {self.catalog_dir}/{USER_FILE}"

        prepared = self.record("selection-volume-setup", True, prepare)

        for entry in self.entries:
            if not (entry.selectable and entry.status == "compatible"):
                continue

            def activate(eid=entry.id):
                if not prepared:
                    raise CheckFailure("skipped: selection volume not prepared")
                return self.check_activate(sel["volume"], eid)

            self.record(f"activate:{entry.id}", True, activate)

        def guarded(fn):
            def wrapper():
                if not prepared:
                    raise CheckFailure("skipped: selection volume not prepared")
                return fn(sel["volume"])

            return wrapper

        self.record("stale-removal", True, guarded(self.check_stale_removed))
        self.record("unrelated-files-kept", True, guarded(self.check_user_file_kept))
        self.record("unknown-id-rejected", True, guarded(self.check_unknown_rejected))
        self.record("unsupported-fallback-rejected", True, guarded(self.check_fallback_rejected))
        self.record("boot-all-selectable", False, self.check_boot_all)

    def cleanup(self) -> None:
        for name in list(self._containers):
            self.remove_container(name)
        for volume in list(self._volumes):
            self.docker("volume", "rm", "-f", volume)
            self._volumes.remove(volume)

    def result(self) -> dict:
        return {
            "image": self.image,
            "server": self.server,
            "minecraft": self.minecraft,
            "passed": bool(self.checks) and all(c["passed"] for c in self.checks if c["blocking"]),
            "checks": self.checks,
        }


def main(argv: list | None = None, runner: Runner = docker_runner) -> int:
    parser = argparse.ArgumentParser(description="CI checks for a Minecraft server image")
    parser.add_argument("--image", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--python-image", default=default_python_image())
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds to wait for the ready pattern")
    args = parser.parse_args(argv)

    result = {"image": args.image, "server": "", "minecraft": "", "passed": False, "checks": []}
    try:
        entries = parse_catalog(args.catalog)
        checker = Checker(
            image=args.image, entries=entries, python_image=args.python_image, runner=runner, ready_timeout=args.timeout
        )
        result = checker.run()
    except Exception as exc:
        result["checks"].append({"name": "ci_check", "passed": False, "blocking": True, "detail": f"{type(exc).__name__}: {exc}"})
    finally:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
