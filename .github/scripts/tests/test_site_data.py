"""site-data export: loader metadata, version states and locks for the website."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from server_images import site_data
from server_images.loaders import SERVERS


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class SiteDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.servers = Path(self.tmp.name)
        locks = self.servers / "paper" / "locks"
        write(locks / "status.json", {
            "window": ["26.2", "26.1.2", "1.21.11"],
            "upcoming": ["26.3"],
            "latest": "26.2",
            "updated_at": "2026-10-08T13:06:26Z",
            "targets": {
                "26.3": {"state": "pending", "reason": "No STABLE Paper build"},
                "26.2": {"state": "published", "digest": "sha256:aa", "lock": "26.2.json"},
                "26.1.2": {"state": "published", "digest": "sha256:bb", "lock": "26.1.2.json"},
                "1.21.11": {"state": "published", "digest": "sha256:cc", "lock": "1.21.11.json"},
                "1.21.10": {"state": "frozen", "digest": "sha256:dd"},
            },
        })
        for mc in ("26.2", "26.1.2", "1.21.11"):
            write(locks / f"{mc}.json", {"minecraft_version": mc, "entries": []})
        self.data = site_data.build("Owner/minecraft", self.servers)
        self.paper = next(s for s in self.data["servers"] if s["id"] == "paper")

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_server_is_exported_with_loader_metadata(self):
        self.assertEqual([s["id"] for s in self.data["servers"]], SERVERS)
        self.assertEqual(self.paper["title"], "Paper")
        self.assertEqual(self.paper["image"], "ghcr.io/owner/minecraft-server-paper")
        self.assertEqual(self.paper["catalog"], {"kind": "plugins", "env": "PLUGINS", "dir": "/data/plugins"})
        self.assertTrue(self.paper["eula"])
        self.assertEqual(self.paper["manifest_dir"], "src/mc-server-images/paper/plugins")
        pumpkin = next(s for s in self.data["servers"] if s["id"] == "pumpkin")
        self.assertFalse(pumpkin["eula"])
        self.assertEqual(pumpkin["versions"], [])

    def test_versions_are_sorted_newest_first_with_states(self):
        states = [(v["minecraft"], v["state"], v["maintained"]) for v in self.paper["versions"]]
        self.assertEqual(states, [
            ("26.3", "pending", False),
            ("26.2", "published", True),
            ("26.1.2", "published", True),
            ("1.21.11", "published", True),
            ("1.21.10", "frozen", False),
        ])

    def test_locks_and_digests(self):
        by_mc = {v["minecraft"]: v for v in self.paper["versions"]}
        self.assertEqual(by_mc["26.2"]["lock"]["minecraft_version"], "26.2")
        self.assertIsNone(by_mc["1.21.10"]["lock"])
        self.assertEqual(by_mc["1.21.10"]["digest"], "sha256:dd")
        self.assertIsNone(by_mc["26.3"]["digest"])
        self.assertEqual(by_mc["26.3"]["reason"], "No STABLE Paper build")

    def test_site_wide_fields(self):
        self.assertEqual(self.data["owner"], "owner")
        self.assertEqual(self.data["window_size"], 3)
        self.assertEqual(self.data["updated_at"], "2026-10-08T13:06:26Z")


if __name__ == "__main__":
    unittest.main()
