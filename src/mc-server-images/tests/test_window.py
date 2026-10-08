"""Per-server window detection and upcoming (unsupported newer) releases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import test_loaders  # noqa: E402,F401 - installs offline stubs for the sources package when needed
from loaders import ServerBuild, empty_runtime, pending, server_window  # noqa: E402
import publish  # noqa: E402


class FakeLoader:
    def __init__(self, supported):
        self.supported = set(supported)
        self.calls = []

    def resolve_build(self, mc):
        self.calls.append(mc)
        if mc in self.supported:
            return ServerBuild("available", None, "1", empty_runtime())
        return pending(f"no build for {mc}")


RELEASES = ["26.3", "26.2", "26.1.2", "26.1.1", "26.1", "1.21.11"]


class ServerWindowTests(unittest.TestCase):
    def test_skips_unsupported_newest(self):
        loader = FakeLoader({"26.2", "26.1.2", "26.1.1", "26.1"})
        w = server_window(loader, releases=RELEASES)
        self.assertEqual(w.window, ["26.2", "26.1.2", "26.1.1"])
        self.assertEqual(w.upcoming, ["26.3"])
        self.assertEqual(loader.calls, ["26.3", "26.2", "26.1.2", "26.1.1"])
        self.assertEqual(set(w.builds), {"26.3", "26.2", "26.1.2", "26.1.1"})

    def test_gaps_are_not_upcoming(self):
        w = server_window(FakeLoader({"26.3", "26.1.2", "26.1"}), releases=RELEASES)
        self.assertEqual(w.window, ["26.3", "26.1.2", "26.1"])
        self.assertEqual(w.upcoming, [])

    def test_single_version_server(self):
        w = server_window(FakeLoader({"26.3"}), releases=RELEASES)
        self.assertEqual(w.window, ["26.3"])

    def test_nothing_supported(self):
        w = server_window(FakeLoader(set()), releases=RELEASES)
        self.assertEqual(w.window, [])
        self.assertEqual(w.upcoming, ["26.3", "26.2", "26.1.2"])


class UpcomingStatusTests(unittest.TestCase):
    def test_upcoming_pending_and_old_window_frozen(self):
        prev = {"targets": {
            "26.3": {"state": "pending", "reason": "old"},
            "26.2": {"state": "published", "digest": "sha256:a", "published_at": "t", "lock": "26.2.json"},
        }, "latest": "26.2"}
        st = publish.compute_status(prev, server="neoforge", image_ref="img", window=["26.2", "26.1.2"],
                                    published={"26.1.2": {"digest": "sha256:b"}},
                                    pending={"26.3": "no build"}, now="t1", upcoming=["26.3"])
        self.assertEqual(st["upcoming"], ["26.3"])
        self.assertEqual(st["targets"]["26.3"], {"state": "pending", "reason": "no build"})
        self.assertEqual(list(st["targets"])[:3], ["26.3", "26.2", "26.1.2"])
        self.assertEqual(st["latest"], "26.2")


if __name__ == "__main__":
    unittest.main()
