"""Offline tests for staging.py: catalog.tsv, build-args, file staging with mocked downloads."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import staging  # noqa: E402


def sha512(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def entry(id_, **kw):
    base = {
        "id": id_, "declared": True, "status": "compatible", "reason": None,
        "selectable": True, "closure": [id_], "conflicts": [], "artifact": None,
        "local": None, "build": None,
    }
    base.update(kw)
    return base


def make_lock(entries, server="fabric"):
    return {
        "schema": 1, "server": server, "image": f"minecraft-server-{server}",
        "minecraft_version": "26.3", "inputs_hash": "sha256:x",
        "runtime": {"base_image": "eclipse-temurin:25-jre", "base_digest": "sha256:abc", "java_major": 25},
        "server_build": {"status": "available", "reason": None, "loader_version": "0.17.3", "details": {
            "installer_version": "1.0.1",
            "downloads": {"installer": {"url": "https://x.test/fabric-installer-1.0.1.jar", "sha512": "aa"}},
        }},
        "entries": entries,
    }


class CatalogTsvTest(unittest.TestCase):
    def test_render(self):
        entries = [
            entry("fabric-api", declared=False, closure=["fabric-api"],
                  artifact={"filename": "fabric-api.jar", "sha512": "x"}),
            entry("lithium", closure=["fabric-api", "lithium"],
                  artifact={"filename": "lithium.jar", "sha512": "x"}),
            entry("bad", status="unavailable", selectable=False,
                  reason="no\ttabs\nhere", closure=["bad"]),
        ]
        lines = staging.render_catalog_tsv(entries).splitlines()
        self.assertEqual(lines[0], "#id\tstatus\tselectable\tkind\tfilename\tclosure\tconflicts\treason")
        self.assertEqual(lines[1], "fabric-api\tcompatible\tyes\tdependency\tfabric-api.jar\tfabric-api\t-\t-")
        self.assertEqual(lines[2], "lithium\tcompatible\tyes\tdeclared\tlithium.jar\tfabric-api,lithium\t-\t-")
        self.assertEqual(lines[3], "bad\tunavailable\tno\tdeclared\t-\tbad\t-\tno tabs here")
        for line in lines[1:]:
            self.assertEqual(len(line.split("\t")), 8)


class BuildArgsTest(unittest.TestCase):
    def test_fabric(self):
        args = staging.build_args(make_lock([]))
        self.assertEqual(args, {
            "BASE_IMAGE": "eclipse-temurin:25-jre@sha256:abc", "MINECRAFT_VERSION": "26.3",
            "LOADER_VERSION": "0.17.3", "JAVA_MAJOR": "25", "INSTALLER_VERSION": "1.0.1",
        })

    def test_pumpkin(self):
        lock = make_lock([], "pumpkin")
        lock["runtime"]["java_major"] = None
        lock["server_build"]["details"] = {
            "downloads": {}, "builder_image": "rust:1@sha256:d",
            "source": {"repo": "https://github.com/Pumpkin-MC/Pumpkin", "commit": "abc"},
        }
        args = staging.build_args(lock)
        self.assertEqual(args["JAVA_MAJOR"], "")
        self.assertEqual(args["PUMPKIN_COMMIT"], "abc")
        self.assertEqual(args["BUILDER_IMAGE"], "rust:1@sha256:d")
        self.assertNotIn("INSTALLER_VERSION", args)
        self.assertIn("PUMPKIN_REPO=https://github.com/Pumpkin-MC/Pumpkin\n", staging.render_build_args(args))


class StageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        base = self.tmp / "base"
        (base / "fabric").mkdir(parents=True)
        (base / "common").mkdir()
        (base / "fabric" / "Dockerfile").write_text("FROM x\n")
        (base / "fabric" / "entrypoint.sh").write_text("#!/bin/sh\n")
        (base / "common" / "lib.sh").write_text("# lib\n")
        (base / "common" / "mc_status.py").write_text("# py\n")
        (base / "common" / "ci_check.py").write_text("# not copied\n")
        self.base = base
        self.manifest_dir = self.tmp / "mods"
        (self.manifest_dir / "jars").mkdir(parents=True)
        self.local_bytes = b"prebuilt"
        (self.manifest_dir / "jars" / "p.jar").write_bytes(self.local_bytes)
        self.custom = self.tmp / "custom"
        self.custom.mkdir()
        self.custom_bytes = b"built"
        (self.custom / "key-c.jar").write_bytes(self.custom_bytes)
        (self.custom / "results.json").write_text(json.dumps({"c": {"path": "key-c.jar"}}))

    def fake_download(self, url, dest, **hashes):
        dest.write_bytes(b"remote:" + url.encode())
        self.downloaded.append((url, dict(hashes)))
        return "x"

    def test_stage(self):
        self.downloaded = []
        entries = [
            entry("up", artifact={"filename": "up.jar", "url": "https://cdn.test/up.jar", "sha512": "ff"}),
            entry("pre", artifact={"filename": "p.jar", "url": None, "sha512": sha512(self.local_bytes)},
                  local={"path": "jars/p.jar", "sha512": sha512(self.local_bytes)}),
            entry("c", artifact={"filename": "c.jar", "url": None, "sha512": sha512(self.custom_bytes)},
                  build={"cache_key": "key"}),
            entry("gone", status="unavailable", selectable=False, reason="x"),
        ]
        lock = make_lock(entries)
        ctx = self.tmp / "ctx"
        with mock.patch.object(staging, "_download", self.fake_download):
            staging.stage(lock, ctx, self.custom, self.base, self.manifest_dir)

        self.assertEqual(self.downloaded[0], ("https://x.test/fabric-installer-1.0.1.jar", {"sha512": "aa"}))
        self.assertIn(("https://cdn.test/up.jar", {"sha512": "ff"}), self.downloaded)
        self.assertTrue((ctx / "downloads" / "installer.jar").is_file())
        files = ctx / "catalog" / "files"
        self.assertEqual(sorted(p.name for p in files.iterdir()), ["c.jar", "p.jar", "up.jar"])
        self.assertEqual((files / "p.jar").read_bytes(), self.local_bytes)
        self.assertEqual((files / "c.jar").read_bytes(), self.custom_bytes)
        self.assertEqual(sorted(p.name for p in (ctx / "common").iterdir()), ["lib.sh", "mc_status.py"])
        self.assertTrue((ctx / "Dockerfile").is_file() and (ctx / "entrypoint.sh").is_file())
        self.assertIn("gone\tunavailable\tno\tdeclared\t-", (ctx / "catalog" / "catalog.tsv").read_text())
        catalog = json.loads((ctx / "catalog" / "catalog.json").read_text())
        self.assertEqual(catalog["loader_version"], "0.17.3")
        self.assertEqual(len(catalog["entries"]), 4)
        self.assertTrue((ctx / "catalog" / "lock.json").is_file())
        env = (ctx / "build-args.env").read_text()
        self.assertIn("BASE_IMAGE=eclipse-temurin:25-jre@sha256:abc\n", env)
        self.assertIn("LOADER_VERSION=0.17.3\n", env)

    def test_local_checksum_mismatch(self):
        self.downloaded = []
        lock = make_lock([entry("pre", artifact={"filename": "p.jar", "url": None, "sha512": "00"},
                                local={"path": "jars/p.jar", "sha512": "00"})])
        with mock.patch.object(staging, "_download", self.fake_download):
            with self.assertRaises(staging.StageError):
                staging.stage(lock, self.tmp / "ctx", None, self.base, self.manifest_dir)


if __name__ == "__main__":
    unittest.main()
