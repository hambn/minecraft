"""Offline tests for loaders.py and <server>/loader.py: every sources.* call is patched."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

try:  # the real sources package is written separately; stub it when absent
    from sources import github, http, mojang, registry  # noqa: F401
except ImportError:  # pragma: no cover
    pkg = types.ModuleType("sources")
    pkg.__path__ = []
    sys.modules["sources"] = pkg
    for _name, _funcs in {
        "http": ["get_json", "get_text", "download"],
        "mojang": ["stable_releases", "maintenance_window", "version_details"],
        "registry": ["resolve_digest"],
        "github": ["latest_commit", "file_at", "release_asset_url", "upload_release_asset"],
    }.items():
        _mod = types.ModuleType(f"sources.{_name}")
        for _f in _funcs:
            setattr(_mod, _f, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network")))
        if _name == "http":
            class HttpError(Exception):
                pass
            class HashMismatch(Exception):
                pass
            _mod.HttpError, _mod.HashMismatch = HttpError, HashMismatch
        setattr(pkg, _name, _mod)
        sys.modules[f"sources.{_name}"] = _mod
    from sources import github, http, mojang, registry  # noqa: E402,F401

from loaders import SERVERS, get_loader, load_module  # noqa: E402

neoforge_mod = load_module("neoforge")
pumpkin_mod = load_module("pumpkin")

DETAILS = {"java_major": 25, "server_jar": {"url": "https://piston/server.jar", "sha1": "aa", "size": 1}}


def digest(image: str) -> str:
    return "sha256:" + image.replace(":", "-")


class Base(unittest.TestCase):
    def patch(self, target: str, **kw):
        p = mock.patch(target, **kw)
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def setUp(self):
        self.patch("sources.registry.resolve_digest", side_effect=digest)
        self.patch("sources.mojang.version_details", return_value=DETAILS)


class RegistryTest(unittest.TestCase):
    def test_get_loader(self):
        for server in SERVERS:
            loader = get_loader(server)
            self.assertEqual(loader.server, server)
            self.assertIn(loader.env_var, ("MODS", "PLUGINS"))
        with self.assertRaises(ValueError):
            get_loader("forge")
        self.assertEqual(get_loader("pumpkin").artifact_ext, ".wasm")


class FabricTest(Base):
    def meta(self, games, loaders=None, installers=None):
        data = {
            "/game": games,
            "/loader": loaders or [{"version": "0.18.0", "stable": False}, {"version": "0.17.3", "stable": True}],
            "/installer": installers or [{"version": "1.2.0", "stable": False}, {"version": "1.1.0", "stable": True}],
        }
        self.patch("sources.http.get_json", side_effect=lambda url, headers=None: data[url.split("/versions")[1]])
        self.patch("sources.http.get_text", return_value="deadbeef  file\n")

    def test_available(self):
        self.meta([{"version": "26.1.2", "stable": True}])
        build = get_loader("fabric").resolve_build("26.1.2")
        self.assertEqual(build.status, "available")
        self.assertEqual(build.loader_version, "0.17.3")
        self.assertEqual(build.runtime, {"base_image": "eclipse-temurin:25-jre", "base_digest": "sha256:eclipse-temurin-25-jre", "java_major": 25})
        self.assertEqual(build.details["installer_version"], "1.1.0")
        dl = build.details["downloads"]
        self.assertEqual(dl["installer"]["sha1"], "deadbeef")
        self.assertTrue(dl["installer"]["url"].endswith("fabric-installer-1.1.0.jar"))
        self.assertEqual(dl["server"], {"url": "https://piston/server.jar", "sha1": "aa"})

    def test_pending_unknown_or_unstable_game(self):
        self.meta([{"version": "26.1.2", "stable": False}])
        self.assertEqual(get_loader("fabric").resolve_build("26.1.2").status, "pending")
        self.assertEqual(get_loader("fabric").resolve_build("26.3").status, "pending")
        self.assertIsNotNone(get_loader("fabric").resolve_build("26.3").reason)

    def test_pending_no_stable_loader(self):
        self.meta([{"version": "26.1", "stable": True}], loaders=[{"version": "1", "stable": False}])
        self.assertEqual(get_loader("fabric").resolve_build("26.1").status, "pending")


class NeoForgeTest(Base):
    XML = """<metadata><versioning><versions>
      <version>21.0.5</version><version>21.1.1</version><version>21.1.9</version><version>21.1.10</version>
      <version>21.1.11-beta</version><version>26.1.2.3-beta</version><version>26.1.2.4</version>
      <version>26.1.2.5</version><version>26.1.0.1</version><version>26.1.3.1-beta</version>
    </versions></versioning></metadata>"""

    def setUp(self):
        super().setUp()
        self.patch("sources.http.get_text", side_effect=lambda url, headers=None: "abc123\n" if url.endswith(".sha1") else self.XML)

    def test_prefix(self):
        self.assertEqual(neoforge_mod.version_prefix("26.1.2"), "26.1.2.")
        self.assertEqual(neoforge_mod.version_prefix("26.1"), "26.1.0.")
        self.assertEqual(neoforge_mod.version_prefix("1.21.1"), "21.1.")
        self.assertEqual(neoforge_mod.version_prefix("1.21"), "21.0.")

    def test_new_scheme(self):
        build = get_loader("neoforge").resolve_build("26.1.2")
        self.assertEqual(build.loader_version, "26.1.2.5")
        inst = build.details["downloads"]["installer"]
        self.assertTrue(inst["url"].endswith("/26.1.2.5/neoforge-26.1.2.5-installer.jar"))
        self.assertEqual(inst["sha1"], "abc123")

    def test_legacy_numeric_order_and_no_beta(self):
        self.assertEqual(get_loader("neoforge").resolve_build("1.21.1").loader_version, "21.1.10")

    def test_pending_only_beta(self):
        build = get_loader("neoforge").resolve_build("26.1.3")
        self.assertEqual(build.status, "pending")
        self.assertIsNone(build.loader_version)


class PaperTest(Base):
    def builds(self, value):
        self.patch("sources.http.get_json", side_effect=value if isinstance(value, Exception) else None, return_value=None if isinstance(value, Exception) else value)

    def build(self, id_, channel):
        return {"id": id_, "channel": channel, "downloads": {"server:default": {"url": f"https://fill/{id_}.jar", "checksums": {"sha256": f"h{id_}"}}}}

    def test_stable(self):
        self.builds([self.build(12, "ALPHA"), self.build(10, "STABLE"), self.build(9, "STABLE")])
        build = get_loader("paper").resolve_build("26.1.2")
        self.assertEqual(build.loader_version, "10")
        self.assertEqual(build.details["build"], 10)
        self.assertEqual(build.details["channel"], "STABLE")
        self.assertEqual(build.details["downloads"]["paper"], {"url": "https://fill/10.jar", "sha256": "h10"})

    def test_no_stable(self):
        self.builds([self.build(1, "ALPHA"), self.build(2, "BETA")])
        self.assertEqual(get_loader("paper").resolve_build("26.3").status, "pending")

    def test_unknown_version(self):
        self.builds(http.HttpError("404"))
        self.assertEqual(get_loader("paper").resolve_build("26.3").status, "pending")


class PumpkinTest(Base):
    SHA = "0123456789abcdef0123456789abcdef01234567"

    def files(self, mapping):
        def file_at(repo, ref, path):
            if path in mapping:
                return mapping[path]
            raise http.HttpError("404")
        self.patch("sources.github.latest_commit", return_value=self.SHA)
        self.patch("sources.github.file_at", side_effect=file_at)

    def test_supported(self):
        self.files({
            pumpkin_mod.VERSION_FILE_CANDIDATES[1]: 'pub const CURRENT_MC_VERSION: &str = "26.1.2";',
            "rust-toolchain.toml": '[toolchain]\nchannel = "1.92"\n',
        })
        build = get_loader("pumpkin").resolve_build("26.1.2")
        self.assertEqual(build.status, "available")
        self.assertEqual(build.loader_version, self.SHA)
        self.assertEqual(build.runtime, {"base_image": "debian:bookworm-slim", "base_digest": "sha256:debian-bookworm-slim", "java_major": None})
        d = build.details
        self.assertEqual(d["downloads"], {})
        self.assertEqual(d["source"], {"repo": "https://github.com/Pumpkin-MC/Pumpkin", "commit": self.SHA})
        self.assertEqual(d["builder_image"], "rust:1.92-bookworm@sha256:rust-1.92-bookworm")
        self.assertEqual(d["supported_minecraft"], "26.1.2")

    def test_default_rust_when_no_toolchain(self):
        self.files({pumpkin_mod.VERSION_FILE_CANDIDATES[0]: 'pub const CURRENT_MC_VERSION: &str = "26.1.2";'})
        d = get_loader("pumpkin").resolve_build("26.1.2").details
        self.assertTrue(d["builder_image"].startswith(f"rust:{pumpkin_mod.DEFAULT_RUST_VERSION}-bookworm@"))

    def test_other_version_pending(self):
        self.files({pumpkin_mod.VERSION_FILE_CANDIDATES[0]: 'pub const CURRENT_MC_VERSION: &str = "26.1.2";'})
        build = get_loader("pumpkin").resolve_build("26.3")
        self.assertEqual(build.status, "pending")
        self.assertIn("26.1.2", build.reason)

    def test_unknown_support_pending(self):
        self.files({})
        self.assertEqual(get_loader("pumpkin").resolve_build("26.1.2").status, "pending")


if __name__ == "__main__":
    unittest.main()
