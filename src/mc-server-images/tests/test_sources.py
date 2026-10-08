"""Offline tests for the sources package: http.get_json (and friends) are faked."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from sources import curseforge, github, http, modrinth, mojang, registry  # noqa: E402
from sources.models import ProviderUnavailable  # noqa: E402


def fake_get(table):
    def _get(url, headers=None):
        for key, value in table.items():
            if url == key:
                return value
        raise AssertionError(f"unexpected URL {url}")

    return _get


class MojangTests(unittest.TestCase):
    MANIFEST = {
        "versions": [
            {"id": "26.2-snapshot-1", "type": "snapshot", "url": "u0", "releaseTime": "2026-09-01T00:00:00+00:00"},
            {"id": "26.1", "type": "release", "url": "u1", "releaseTime": "2026-03-01T00:00:00+00:00"},
            {"id": "26.3", "type": "release", "url": "u3", "releaseTime": "2026-09-20T00:00:00+00:00"},
            {"id": "26.2", "type": "release", "url": "u2", "releaseTime": "2026-06-01T00:00:00+00:00"},
        ]
    }

    def test_window_and_details(self):
        table = {
            mojang.MANIFEST_URL: self.MANIFEST,
            "u3": {"javaVersion": {"majorVersion": 25}, "downloads": {"server": {"url": "s", "sha1": "a", "size": 3}}},
        }
        with mock.patch.object(http, "get_json", fake_get(table)):
            self.assertEqual(mojang.maintenance_window(2), ["26.3", "26.2"])
            self.assertEqual([v["id"] for v in mojang.stable_releases()], ["26.3", "26.2", "26.1"])
            d = mojang.version_details("26.3")
            self.assertEqual(d, {"java_major": 25, "server_jar": {"url": "s", "sha1": "a", "size": 3}})
            with self.assertRaises(KeyError):
                mojang.version_details("1.0")


class ModrinthTests(unittest.TestCase):
    def test_project_and_releases(self):
        table = {
            "https://api.modrinth.com/v2/project/lithium": {
                "id": "gvQqBUqZ", "slug": "lithium", "title": "Lithium", "description": "fast",
                "license": {"id": "LGPL-3.0-only"}, "server_side": "required", "project_type": "mod",
            },
            "https://api.modrinth.com/v2/project/gvQqBUqZ/members": [{"user": {"username": "jelly"}}],
            "https://api.modrinth.com/v2/project/bare": {
                "id": "bare", "slug": "bare", "title": "Bare", "description": "", "license": {"id": ""},
                "server_side": "weird",
            },
            "https://api.modrinth.com/v2/project/bare/members": [],
            "https://api.modrinth.com/v2/project/gvQqBUqZ/version?loaders=%5B%22fabric%22%5D": [
                {
                    "id": "v1", "project_id": "gvQqBUqZ", "version_number": "0.18.0", "name": "Lithium 0.18",
                    "version_type": "release", "date_published": "2026-10-01T00:00:00Z",
                    "game_versions": ["26.3"], "loaders": ["fabric"],
                    "files": [
                        {"filename": "x.jar", "url": "ux", "hashes": {"sha512": "s5", "sha1": "s1"}, "size": 1, "primary": False},
                        {"filename": "lithium.jar", "url": "u", "hashes": {"sha512": "S5", "sha1": "S1"}, "size": 9, "primary": True},
                    ],
                    "dependencies": [
                        {"project_id": "fabric-api-id", "version_id": None, "dependency_type": "required"},
                        {"project_id": None, "version_id": "dv", "dependency_type": "optional"},
                        {"project_id": "zz", "version_id": None, "dependency_type": "weird"},
                    ],
                }
            ],
            "https://api.modrinth.com/v2/version/dv": {"project_id": "resolved"},
        }
        with mock.patch.object(http, "get_json", fake_get(table)):
            client = modrinth.ModrinthClient()
            p = client.project("lithium")
            self.assertEqual((p.project_id, p.authors, p.license, p.server_side), ("gvQqBUqZ", ["jelly"], "LGPL-3.0-only", "required"))
            self.assertEqual(p.homepage, "https://modrinth.com/mod/lithium")
            self.assertEqual(p.missing, [])
            b = client.project("bare")
            self.assertEqual(b.server_side, "unknown")
            self.assertIsNone(b.license)
            self.assertTrue({"authors", "license", "description", "homepage"} <= set(b.missing))
            (r,) = client.releases("gvQqBUqZ", ["fabric"])
            self.assertEqual(r.file.filename, "lithium.jar")
            self.assertEqual(r.file.sha512, "S5")
            self.assertEqual([(d.project_id, d.version_id, d.kind) for d in r.dependencies],
                             [("fabric-api-id", None, "required"), ("resolved", "dv", "optional")])
            self.assertEqual(client.releases("gvQqBUqZ", []), [])


class CurseForgeTests(unittest.TestCase):
    FILE = {
        "id": 555, "modId": 42, "displayName": "Mod 1.0", "fileName": "mod-1.0.jar", "releaseType": 1,
        "fileDate": "2026-10-02T00:00:00Z", "downloadUrl": "https://edge/mod.jar", "fileLength": 7,
        "hashes": [{"value": "abc", "algo": 1}, {"value": "md5v", "algo": 2}],
        "gameVersions": ["Fabric", "26.3", "Client", "26.2"],
        "dependencies": [
            {"modId": 1, "relationType": 3}, {"modId": 2, "relationType": 2},
            {"modId": 3, "relationType": 5}, {"modId": 4, "relationType": 1}, {"modId": 5, "relationType": 4},
        ],
    }

    def test_keyless_uses_proxy(self):
        seen = {}

        def get(url, headers=None):
            seen["url"], seen["headers"] = url, headers
            return {"data": {"id": 42, "slug": "mod", "name": "Mod", "authors": []}}

        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(http, "get_json", get):
            curseforge.CurseForgeClient().project(42)
        self.assertEqual(seen["url"], "https://api.curse.tools/v1/cf/mods/42")
        self.assertEqual(seen["headers"], {})

    def test_keyless_proxy_failure_is_unavailable(self):
        def get(url, headers=None):
            raise http.HttpError("down")

        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(http, "get_json", get):
            with self.assertRaises(ProviderUnavailable):
                curseforge.CurseForgeClient().project(42)

    def test_project_and_releases(self):
        forge_file = dict(self.FILE, id=556, gameVersions=["Forge", "26.3"], downloadUrl=None, releaseType=2)
        table = {
            "https://api.curseforge.com/v1/mods/42": {"data": {
                "id": 42, "slug": "mod", "name": "Mod", "summary": "s", "authors": [{"name": "a"}],
                "links": {"websiteUrl": "https://cf/mod"}, "allowModDistribution": False}},
            "https://api.curseforge.com/v1/mods/42/files?pageSize=50&index=0": {
                "data": [self.FILE, forge_file], "pagination": {"totalCount": 2}},
        }
        seen = {}

        def get(url, headers=None):
            seen["key"] = headers.get("x-api-key")
            return fake_get(table)(url, headers)

        with mock.patch.object(http, "get_json", get):
            client = curseforge.CurseForgeClient(api_key="k")
            p = client.project(42)
            self.assertIs(p.distribution_allowed, False)
            self.assertIn("license", p.missing)
            self.assertEqual(p.homepage, "https://cf/mod")
            rels = client.releases("42", ["Fabric"])
            self.assertEqual(seen["key"], "k")
        self.assertEqual([r.version_id for r in rels], ["555"])
        r = rels[0]
        self.assertEqual((r.release_type, r.game_versions, r.loaders), ("release", ["26.3", "26.2"], ["Fabric"]))
        self.assertEqual(r.file.sha1, "abc")
        self.assertEqual([(d.project_id, d.kind) for d in r.dependencies],
                         [("1", "required"), ("2", "optional"), ("3", "incompatible"), ("4", "embedded")])

    def test_release_without_download_url(self):
        r = curseforge.CurseForgeClient(api_key="k")._release(dict(self.FILE, downloadUrl=None, releaseType=3))
        self.assertIsNone(r.file)
        self.assertEqual(r.release_type, "alpha")

    def test_release_by_id(self):
        with mock.patch.object(http, "post_json", lambda url, payload, headers=None: {"data": [self.FILE]}):
            self.assertEqual(curseforge.CurseForgeClient(api_key="k").release("555").project_id, "42")


class RegistryTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(registry.parse_reference("eclipse-temurin:25-jre"),
                         ("registry-1.docker.io", "library/eclipse-temurin", "25-jre"))
        self.assertEqual(registry.parse_reference("ghcr.io/a/b:1"), ("ghcr.io", "a/b", "1"))
        self.assertEqual(registry.parse_reference("localhost:5000/x"), ("localhost:5000", "x", "latest"))
        self.assertEqual(registry.parse_reference("user/app:2"), ("registry-1.docker.io", "user/app", "2"))

    def test_token_flow(self):
        calls = []

        def req(url, *, headers=None, method="GET", data=None, retries=0):
            calls.append((url, method, (headers or {}).get("Authorization")))
            if not (headers or {}).get("Authorization"):
                return http.Response(401, {"www-authenticate":
                    'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:library/x:pull"'})
            return http.Response(200, {"docker-content-digest": "sha256:" + "a" * 64})

        with mock.patch.object(http, "request", req), \
                mock.patch.object(http, "get_json", lambda url, headers=None: {"token": "T"}):
            self.assertEqual(registry.resolve_digest("x:1"), "sha256:" + "a" * 64)
        self.assertEqual(calls[0][0], "https://registry-1.docker.io/v2/library/x/manifests/1")
        self.assertEqual(calls[1][1:], ("HEAD", "Bearer T"))

    def test_digest_passthrough(self):
        self.assertEqual(registry.resolve_digest("a/b@sha256:" + "b" * 64), "sha256:" + "b" * 64)


class GithubTests(unittest.TestCase):
    def test_asset_url_and_upload_creates_release(self):
        sent = []

        def get(url, headers=None):
            if url.endswith("/releases/tags/custom-artifacts"):
                raise http.HttpError("nf", 404)
            raise AssertionError(url)

        def req(url, *, headers=None, method="GET", data=None, retries=0):
            sent.append((method, url))
            if url.endswith("/releases"):
                return http.Response(201, {}, b'{"id": 7, "assets": []}')
            return http.Response(201, {}, b"{}")

        import tempfile
        with mock.patch.object(http, "get_json", get), mock.patch.object(http, "request", req):
            self.assertIsNone(github.release_asset_url("o/r", "custom-artifacts", "a"))
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "a.jar"
                f.write_bytes(b"x")
                github.upload_release_asset("o/r", "custom-artifacts", f, "k-a.jar")
        self.assertEqual(sent[0], ("POST", "https://api.github.com/repos/o/r/releases"))
        self.assertEqual(sent[1], ("POST", "https://uploads.github.com/repos/o/r/releases/7/assets?name=k-a.jar"))

    def test_asset_url_found(self):
        rel = {"assets": [{"name": "a", "browser_download_url": "https://dl/a"}]}
        with mock.patch.object(http, "get_json", lambda url, headers=None: rel):
            self.assertEqual(github.release_asset_url("o/r", "t", "a"), "https://dl/a")
            self.assertIsNone(github.release_asset_url("o/r", "t", "b"))


if __name__ == "__main__":
    unittest.main()
