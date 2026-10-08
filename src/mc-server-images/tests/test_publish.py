"""Offline tests for publish.py: command sequence, status transitions, gating."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import publish  # noqa: E402

FIXTURES = HERE / "fixtures" / "publish" / "artifacts"
REGISTRY = "ghcr.io/hambn"
IMAGE = f"{REGISTRY}/minecraft-server-fabric"
WINDOW = ["26.3", "26.2", "26.1.2"]
T0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 9, 6, 0, 0, tzinfo=timezone.utc)
T0S, T1S = "2026-10-08T12:00:00Z", "2026-10-09T06:00:00Z"


def digest(tag: str, salt: str = "") -> str:
    return "sha256:" + (tag.replace(".", "") + salt).ljust(64, "e")[:64]


class FakeRunner:
    """Records commands; emulates skopeo's --digestfile and optional failures."""

    def __init__(self, salt: str = "", fail=None):
        self.calls: list[list[str]] = []
        self.cwds: list = []
        self.salt = salt
        self.fail = fail or (lambda cmd, n: False)

    def __call__(self, cmd, cwd=None):
        self.calls.append(list(cmd))
        self.cwds.append(cwd)
        if self.fail(cmd, len(self.calls)):
            raise subprocess.CalledProcessError(1, cmd)
        if "--digestfile" in cmd:
            tag = cmd[-1].rsplit(":", 1)[1]
            Path(cmd[cmd.index("--digestfile") + 1]).write_text(digest(tag, self.salt) + "\n")


class PublishTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test-publish-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.artifacts = self.tmp / "artifacts"
        shutil.copytree(FIXTURES, self.artifacts)
        self.repo = self.tmp / "repo"
        self.servers = self.repo / "src" / "mc-server-images"
        self.fabric = self.servers / "fabric" / "locks"
        self.uploads: list[tuple] = []
        self.sleeps: list[float] = []

    # -- helpers
    def args(self, **kw):
        base = dict(server="fabric", artifacts=str(self.artifacts), registry=REGISTRY,
                    dry_run=False, no_commit=False)
        base.update(kw)
        return Namespace(**base)

    def run_publish(self, runner=None, window=None, now=T0, **argkw):
        runner = runner or FakeRunner()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = publish.publish_command(
                self.args(**argkw),
                run=runner,
                now=lambda: now,
                window_fn=lambda: list(window or WINDOW),
                upload_fn=lambda *a: self.uploads.append(a),
                sleep=self.sleeps.append,
                servers_dir=self.servers,
                repo_root=self.repo,
                environ={},
            )
        self.stdout = out.getvalue()
        return code, runner

    def write_artifact(self, mc, status="built", passed=True, reason=None, lock=True, tar=True):
        d = self.artifacts / f"build-fabric-{mc}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "result.json").write_text(json.dumps(
            {"server": "fabric", "minecraft": mc, "status": status, "passed": passed,
             "reason": reason, "inputs_hash": "sha256:x"}))
        if lock:
            (d / "lock.json").write_text(json.dumps(
                {"schema": 1, "server": "fabric", "image": "minecraft-server-fabric",
                 "minecraft_version": mc, "b": 1, "a": 2}))
        if tar:
            (d / "image.tar").write_bytes(b"tar " + mc.encode())

    def remove_artifact(self, mc):
        shutil.rmtree(self.artifacts / f"build-fabric-{mc}")

    def write_status(self, **status):
        self.fabric.mkdir(parents=True, exist_ok=True)
        base = {"schema": 1, "server": "fabric", "image": IMAGE, "updated_at": "2026-10-01T00:00:00Z",
                "window": WINDOW, "latest": None, "latest_outside_window": False, "targets": {}}
        base.update(status)
        (self.fabric / "status.json").write_text(json.dumps(base))

    def status(self):
        return json.loads((self.fabric / "status.json").read_text())

    @staticmethod
    def pub(tag, at="2026-10-01T00:00:00Z", salt=""):
        return {"state": "published", "digest": digest(tag, salt), "published_at": at, "lock": f"{tag}.json"}

    @staticmethod
    def skopeo_pushes(runner):
        return [c for c in runner.calls if c[0] == "skopeo" and "--digestfile" in c]


class TestHappyPath(PublishTestBase):
    def test_full_run_command_sequence(self):
        code, runner = self.run_publish()
        self.assertEqual(code, 0)
        calls = [c if "--digestfile" not in c else c[:2] + c[4:] for c in runner.calls]
        tar = self.artifacts / "build-fabric-26.3" / "image.tar"
        self.assertEqual(calls, [
            ["skopeo", "copy", f"docker-archive:{tar}", f"docker://{IMAGE}:26.3"],
            ["skopeo", "copy", "--all", f"docker://{IMAGE}:26.3", f"docker://{IMAGE}:latest"],
            ["git", "add", "src/mc-server-images/fabric/locks"],
            ["git", "-c", "user.name=github-actions[bot]",
             "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
             "commit", "-m", "chore(fabric): update locks for 26.3"],
            ["git", "pull", "--rebase", "origin", "main"],
            ["git", "push", "origin", "HEAD:main"],
        ])
        self.assertEqual(runner.cwds[2:], [self.repo] * 4)
        digestfile = runner.calls[0][3]
        self.assertEqual(runner.calls[0][2], "--digestfile")
        self.assertTrue(digestfile.endswith("digest"))

    def test_status_and_lock_files(self):
        self.run_publish()
        self.assertEqual(self.status(), {
            "schema": 1, "server": "fabric", "image": IMAGE, "updated_at": T0S,
            "window": WINDOW, "latest": "26.3", "latest_outside_window": False,
            "targets": {
                "26.3": {"state": "published", "digest": digest("26.3"),
                         "published_at": T0S, "lock": "26.3.json"},
                "26.2": {"state": "pending", "reason": "No stable Fabric loader build for 26.2 yet"},
            },
        })
        lock_text = (self.fabric / "26.3.json").read_text()
        self.assertTrue(lock_text.endswith("}\n"))
        self.assertLess(lock_text.index('"entries"'), lock_text.index('"image"'))
        self.assertLess(lock_text.index('"image"'), lock_text.index('"schema"'))
        self.assertIn('\n  "entries": []', lock_text)
        # unchanged targets do not get their lock rewritten
        self.assertFalse((self.fabric / "26.1.2.json").exists())

    def test_custom_uploads(self):
        self.run_publish()
        self.assertEqual(self.uploads, [(
            "hambn/minecraft", "custom-artifacts",
            self.artifacts / "build-fabric-26.3" / "custom" / "custom-source-mod.jar",
            "deadbeef-custom-source-mod.jar")])

    def test_github_repository_env(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            publish.publish_command(
                self.args(), run=FakeRunner(), now=lambda: T0, window_fn=lambda: WINDOW,
                upload_fn=lambda *a: self.uploads.append(a), sleep=lambda s: None,
                servers_dir=self.servers, repo_root=self.repo, environ={"GITHUB_REPOSITORY": "o/r"})
        self.assertEqual(self.uploads[0][0], "o/r")

    def test_no_commit(self):
        code, runner = self.run_publish(no_commit=True)
        self.assertEqual(code, 0)
        self.assertFalse([c for c in runner.calls if c[0] == "git"])
        self.assertTrue((self.fabric / "26.3.json").exists())


class TestWindow(PublishTestBase):
    def test_stale_target_ignored(self):
        self.write_artifact("26.1.1")  # built + passed but frozen
        code, runner = self.run_publish()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.skopeo_pushes(runner)), 1)
        self.assertNotIn("26.1.1", self.status()["targets"])
        self.assertFalse((self.fabric / "26.1.1.json").exists())
        self.assertIn("outside the current window", self.stdout)

    def test_stale_failed_target_does_not_block(self):
        self.write_artifact("26.1.1", passed=False)
        code, _ = self.run_publish()
        self.assertEqual(code, 0)

    def test_window_slide_freezes_old_and_keeps_digest(self):
        self.write_status(window=WINDOW, latest="26.3", targets={
            "26.3": self.pub("26.3"), "26.2": self.pub("26.2"), "26.1.2": self.pub("26.1.2")})
        (self.fabric / "26.1.2.json").write_text("old\n")
        self.remove_artifact("26.2")
        self.remove_artifact("26.1.2")
        window = ["26.4", "26.3", "26.2"]
        self.write_artifact("26.4")
        self.remove_artifact("26.3")
        code, runner = self.run_publish(window=window, now=T1)
        self.assertEqual(code, 0)
        st = self.status()
        self.assertEqual(st["window"], window)
        self.assertEqual(st["latest"], "26.4")
        self.assertEqual(st["targets"]["26.4"]["state"], "published")
        self.assertEqual(st["targets"]["26.3"], self.pub("26.3"))  # published, no new result
        self.assertEqual(st["targets"]["26.1.2"], {**self.pub("26.1.2"), "state": "frozen"})
        self.assertEqual((self.fabric / "26.1.2.json").read_text(), "old\n")
        self.assertIn(["skopeo", "copy", "--all", f"docker://{IMAGE}:26.4", f"docker://{IMAGE}:latest"],
                      runner.calls)
        self.assertEqual(st["updated_at"], T1S)


class TestGating(PublishTestBase):
    def test_failed_check_blocks_everything(self):
        self.write_artifact("26.2", passed=False)
        code, runner = self.run_publish()
        self.assertEqual(code, 1)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.uploads, [])
        self.assertFalse(self.fabric.exists())

    def test_no_results_fails(self):
        shutil.rmtree(self.artifacts)
        self.artifacts.mkdir()
        code, runner = self.run_publish()
        self.assertEqual(code, 1)
        self.assertEqual(runner.calls, [])

    def test_missing_image_tar_is_an_error_but_others_publish(self):
        self.write_artifact("26.2", tar=False)
        code, runner = self.run_publish()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.skopeo_pushes(runner)), 1)
        st = self.status()
        self.assertEqual(st["targets"]["26.3"]["state"], "published")
        self.assertNotIn("26.2", st["targets"])  # push failed: no state recorded

    def test_skopeo_failure_returns_nonzero_and_leaves_status(self):
        runner = FakeRunner(fail=lambda cmd, n: "--digestfile" in cmd)
        code, _ = self.run_publish(runner=runner)
        self.assertEqual(code, 1)
        self.assertFalse([c for c in runner.calls if c[0] == "git" and c[1] == "commit"])
        self.assertNotIn("26.3", self.status()["targets"])


class TestStatusTransitions(PublishTestBase):
    def test_pending_keeps_previous_published(self):
        self.write_status(latest="26.2", targets={"26.2": self.pub("26.2")})
        self.remove_artifact("26.3")
        code, runner = self.run_publish()
        self.assertEqual(code, 0)
        st = self.status()
        self.assertEqual(st["targets"]["26.2"], self.pub("26.2"))
        self.assertEqual(st["latest"], "26.2")

    def test_pending_without_previous(self):
        self.run_publish()
        self.assertEqual(self.status()["targets"]["26.2"],
                         {"state": "pending", "reason": "No stable Fabric loader build for 26.2 yet"})

    def test_pending_reason_updates(self):
        self.write_status(targets={"26.2": {"state": "pending", "reason": "old"}})
        self.run_publish()
        self.assertIn("No stable", self.status()["targets"]["26.2"]["reason"])

    def test_latest_moves_to_newer_version(self):
        self.write_status(latest="26.2", targets={"26.2": self.pub("26.2")})
        code, runner = self.run_publish()
        self.assertEqual(self.status()["latest"], "26.3")
        self.assertIn("docker://%s:latest" % IMAGE, runner.calls[1])

    def test_latest_stays_when_newer_pending_and_no_retag(self):
        self.write_status(latest="26.2", targets={"26.2": self.pub("26.2")})
        self.remove_artifact("26.3")
        _, runner = self.run_publish()
        self.assertFalse([c for c in runner.calls if c[-1].endswith(":latest")])

    def test_latest_retagged_when_rebuilt(self):
        self.write_status(latest="26.3", targets={"26.3": self.pub("26.3")})
        _, runner = self.run_publish(runner=FakeRunner(salt="ab"), now=T1)
        self.assertEqual(self.status()["targets"]["26.3"]["digest"], digest("26.3", "ab"))
        self.assertEqual(self.status()["targets"]["26.3"]["published_at"], T1S)
        self.assertIn(["skopeo", "copy", "--all", f"docker://{IMAGE}:26.3", f"docker://{IMAGE}:latest"],
                      runner.calls)

    def test_latest_outside_window(self):
        window = ["26.5", "26.4", "26.3"]
        self.write_status(latest="26.2", targets={"26.2": self.pub("26.2")})
        for mc in ("26.3", "26.2", "26.1.2"):
            self.remove_artifact(mc)
        self.write_artifact("26.5", status="pending", reason="no loader")
        _, runner = self.run_publish(window=window)
        st = self.status()
        self.assertEqual(st["latest"], "26.2")
        self.assertTrue(st["latest_outside_window"])
        self.assertEqual(st["targets"]["26.2"]["state"], "frozen")
        self.assertFalse([c for c in runner.calls if c[-1].endswith(":latest")])

    def test_latest_outside_window_clears_when_published(self):
        self.write_status(latest="26.0", latest_outside_window=True,
                          targets={"26.0": {**self.pub("26.0"), "state": "frozen"}})
        self.run_publish()
        st = self.status()
        self.assertEqual(st["latest"], "26.3")
        self.assertFalse(st["latest_outside_window"])
        self.assertEqual(st["targets"]["26.0"]["state"], "frozen")


class TestNoop(PublishTestBase):
    def test_nothing_changed_no_commit_no_updated_at_bump(self):
        self.write_status(latest="26.3", targets={
            "26.3": self.pub("26.3", at=T0S),
            "26.2": {"state": "pending", "reason": "No stable Fabric loader build for 26.2 yet"}},
            updated_at=T0S)
        self.fabric.joinpath("26.3.json").write_text(publish.canonical_json(
            {"schema": 1, "server": "fabric", "image": "minecraft-server-fabric",
             "minecraft_version": "26.3"}))
        self.write_artifact("26.3")
        (self.artifacts / "build-fabric-26.3" / "lock.json").write_text(json.dumps(
            {"schema": 1, "server": "fabric", "image": "minecraft-server-fabric",
             "minecraft_version": "26.3"}))
        before = (self.fabric / "status.json").read_text()
        code, runner = self.run_publish(now=T1)
        self.assertEqual(code, 0)
        self.assertFalse([c for c in runner.calls if c[0] == "git"])
        self.assertEqual(self.status()["updated_at"], T0S)
        self.assertEqual(json.loads(before)["targets"], self.status()["targets"])
        self.assertIn("nothing changed", self.stdout)

    def test_only_status_changed_commits_with_status_message(self):
        self.write_status(latest="26.3", targets={"26.3": self.pub("26.3")})
        for mc in ("26.3", "26.2", "26.1.2"):
            self.remove_artifact(mc)
        self.write_artifact("26.2", status="pending", reason="r")
        _, runner = self.run_publish(now=T1)
        commit = [c for c in runner.calls if "commit" in c][0]
        self.assertEqual(commit[-1], "chore(fabric): update status")
        self.assertEqual(self.status()["updated_at"], T1S)


class TestPushRetry(PublishTestBase):
    def test_retries_with_backoff(self):
        pushes = []

        def fail(cmd, n):
            if cmd[:2] == ["git", "push"]:
                pushes.append(cmd)
                return len(pushes) < 3
            return False

        code, runner = self.run_publish(runner=FakeRunner(fail=fail))
        self.assertEqual(code, 0)
        self.assertEqual(len(pushes), 3)
        self.assertEqual(len([c for c in runner.calls if c[:2] == ["git", "pull"]]), 3)
        self.assertEqual(self.sleeps, [2, 4])

    def test_gives_up_after_five(self):
        code, runner = self.run_publish(
            runner=FakeRunner(fail=lambda cmd, n: cmd[:2] == ["git", "push"]))
        self.assertEqual(code, 1)
        self.assertEqual(len([c for c in runner.calls if c[:2] == ["git", "push"]]), 5)
        self.assertEqual(len(self.sleeps), 4)


class TestDryRun(PublishTestBase):
    def test_dry_run_runs_nothing_writes_nothing(self):
        code, runner = self.run_publish(dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.uploads, [])
        self.assertFalse(self.fabric.exists())
        self.assertIn("+ skopeo copy --digestfile", self.stdout)
        self.assertIn(f"docker://{IMAGE}:26.3 docker://{IMAGE}:latest", self.stdout)
        self.assertIn("+ git push origin HEAD:main", self.stdout)
        self.assertIn("+ upload_release_asset hambn/minecraft custom-artifacts", self.stdout)
        self.assertIn('"latest": "26.3"', self.stdout)
        self.assertIn(publish.DRY_RUN_DIGEST, self.stdout)


class TestComputeStatus(unittest.TestCase):
    def test_same_digest_keeps_published_at(self):
        prev = {"targets": {"26.3": {"state": "published", "digest": digest("26.3"),
                                     "published_at": T0S, "lock": "26.3.json"}},
                "updated_at": T0S, "window": ["26.3"], "latest": "26.3", "latest_outside_window": False,
                "schema": 1, "server": "fabric", "image": IMAGE}
        new = publish.compute_status(prev, server="fabric", image_ref=IMAGE, window=["26.3"],
                                     published={"26.3": {"digest": digest("26.3")}}, pending={}, now=T1S)
        self.assertEqual(new, prev)


if __name__ == "__main__":
    unittest.main()
