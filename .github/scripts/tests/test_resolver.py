"""Offline tests for resolver.py using fake providers, loaders and manifests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace as NS


from server_images import locks, resolver, util
from server_images import manifest as manifest_mod

LICENSES = {"allowed": ["MIT", "LGPL-3.0-only", "Apache-2.0"],
            "permissions": [{"provider": "modrinth", "project": "arr-ok", "note": "granted"}]}
KNOWN = ["26.3", "26.2", "26.1.2", "26.1.1", "26.1"]


def info(pid, slug=None, license="MIT", side="required", dist=None, provider="modrinth"):
    slug = slug or pid
    return NS(provider=provider, project_id=pid, slug=slug, name=slug.title(), description="d", authors=["a"],
              license=license, homepage=None, server_side=side, distribution_allowed=dist, missing=[])


def rel(pid, vid, mcs, published, deps=(), type="release", loaders=("fabric",), provider="modrinth"):
    file = NS(filename=f"{pid}-{vid}.jar", url=f"https://x/{pid}/{vid}.jar", sha512="s" * 128, sha1=None, size=1)
    return NS(provider=provider, project_id=pid, version_id=vid, version_number=vid, name=vid, release_type=type,
              published=published, game_versions=list(mcs), loaders=list(loaders), file=file,
              dependencies=[NS(provider=provider, project_id=p, version_id=None, kind=k) for p, k in deps])


class FakeProvider:
    def __init__(self, projects, releases, name="modrinth"):
        self.name, self.projects, self.rels = name, {p.project_id: p for p in projects}, releases
        self.by_slug = {p.slug: p for p in projects}
        self.project_calls = 0

    def project(self, ref):
        self.project_calls += 1
        found = self.projects.get(str(ref)) or self.by_slug.get(str(ref))
        if found is None:
            raise resolver.HttpError(f"404 {ref}")
        return found

    def releases(self, project_id, loaders):
        return list(self.rels.get(project_id, []))


def fake_loader(build_status="available"):
    def resolve_build(mc):
        if mc in ("26.2",) and build_status == "pending":
            return NS(status="pending", reason="No loader for 26.2", loader_version=None, runtime={}, details={})
        return NS(status="available", reason=None, loader_version="0.17.3", details={},
                  runtime={"base_image": "eclipse-temurin:25-jre", "base_digest": "sha256:" + "a" * 64, "java_major": 25})
    return NS(server="fabric", image="minecraft-server-fabric", manifest="fabric/mods/mods.yml", artifact_ext=".jar",
              provider_loaders={"modrinth": ["fabric"], "curseforge": ["Fabric"]}, resolve_build=resolve_build)


def make_manifest(base, modrinth=(), curseforge=(), local=()):
    m = manifest_mod.Manifest(path=Path(base) / "mods.yml", base_dir=Path(base))
    m.modrinth = [manifest_mod.UpstreamEntry(i, "modrinth", p) for i, p in modrinth]
    m.curseforge = [manifest_mod.UpstreamEntry(i, "curseforge", p) for i, p in curseforge]
    for e in local:
        (m.prebuilt if e.kind == "prebuilt" else m.custom_build).append(e)
    return m


def by_id(lock):
    return {e["id"]: e for e in lock["entries"]}


class SpdxTests(unittest.TestCase):
    def test_expressions(self):
        allowed = {"mit", "apache-2.0"}
        f = resolver.spdx_allowed
        self.assertTrue(f("MIT", allowed))
        self.assertTrue(f("MIT OR GPL-9.0", allowed))
        self.assertFalse(f("MIT AND GPL-9.0", allowed))
        self.assertTrue(f("Apache-2.0 WITH LLVM-exception", allowed))
        self.assertFalse(f("LicenseRef-All-Rights-Reserved", allowed))
        self.assertTrue(f("(MIT OR X) AND Apache-2.0", allowed))
        self.assertFalse(f(None, allowed))


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def resolver(self, providers, manifest):
        return resolver.Resolver("fabric", fake_loader(), manifest, providers=providers, licenses=LICENSES,
                                 known_releases=KNOWN)

    def test_modrinth_selection_deps_fallback_license_conflict(self):
        projects = [info("lithium"), info("fabric-api", "fabric-api"), info("old"), info("arr", license="LicenseRef-All-Rights-Reserved"),
                    info("arr-ok", license="LicenseRef-All-Rights-Reserved"), info("client", side="unsupported"),
                    info("a"), info("b"), info("nothing")]
        releases = {
            "lithium": [rel("lithium", "1", ["26.2"], "2026-01-01"), rel("lithium", "3", ["26.3"], "2026-03-01", deps=[("fabric-api", "required"), ("b", "incompatible")]),
                        rel("lithium", "4b", ["26.3"], "2026-04-01", type="beta"), rel("lithium", "2", ["26.3"], "2026-02-01", loaders=("forge",))],
            "fabric-api": [rel("fabric-api", "0.9", ["26.3"], "2026-03-02")],
            "old": [rel("old", "1", ["26.1", "26.1.1"], "2026-01-01"), rel("old", "2", ["26.1.2", "26.1"], "2026-02-01")],
            "arr": [rel("arr", "1", ["26.3"], "2026-01-01")], "arr-ok": [rel("arr-ok", "1", ["26.3"], "2026-01-01")],
            "client": [rel("client", "1", ["26.3"], "2026-01-01")],
            "a": [rel("a", "1", ["26.3"], "2026-01-01")], "b": [rel("b", "1", ["26.3"], "2026-01-01")],
        }
        mani = make_manifest(self.base, modrinth=[(i, i) for i in ["lithium", "old", "arr", "arr-ok", "client", "nothing", "b"]])
        r = self.resolver({"modrinth": FakeProvider(projects, releases)}, mani)
        lock = r.resolve_target("26.3", fake_loader().resolve_build("26.3"), self.base)
        e = by_id(lock)
        self.assertEqual(e["lithium"]["status"], "compatible")
        self.assertEqual(e["lithium"]["identity"]["version_id"], "3")
        self.assertEqual(e["lithium"]["dependencies"], [{"id": "fabric-api", "kind": "required"}])
        self.assertFalse(e["fabric-api"]["declared"])
        self.assertEqual(e["lithium"]["closure"], ["fabric-api", "lithium"])
        self.assertTrue(e["lithium"]["selectable"])
        self.assertEqual(e["lithium"]["conflicts"], ["b"])
        self.assertEqual(e["b"]["conflicts"], ["lithium"])
        self.assertEqual(e["old"]["status"], "unsupported_fallback")
        self.assertEqual(e["old"]["identity"]["version_id"], "2")
        self.assertEqual(e["old"]["reason"], "supports Minecraft 26.1, 26.1.2 (fabric); this image is Minecraft 26.3 (fabric 0.17.3)")
        self.assertFalse(e["old"]["selectable"])
        self.assertEqual(e["arr"]["status"], "unavailable")
        self.assertIsNone(e["arr"]["artifact"])
        self.assertEqual(e["arr-ok"]["status"], "compatible")  # permission recorded
        self.assertEqual(e["client"]["status"], "unavailable")
        self.assertEqual(e["nothing"]["status"], "unavailable")
        self.assertTrue(lock["inputs_hash"].startswith("sha256:"))

    def test_dependency_reuses_declared_and_blocked_reason(self):
        projects = [info("x"), info("lib", "lib")]
        releases = {"x": [rel("x", "1", ["26.3"], "2026-01-01", deps=[("lib", "required")])],
                    "lib": [rel("lib", "1", ["26.1"], "2026-01-01")]}
        mani = make_manifest(self.base, modrinth=[("x", "x"), ("library", "lib")])
        lock = self.resolver({"modrinth": FakeProvider(projects, releases)}, mani).resolve_target(
            "26.3", fake_loader().resolve_build("26.3"), self.base)
        e = by_id(lock)
        self.assertEqual(set(e), {"x", "library"})
        self.assertEqual(e["x"]["dependencies"], [{"id": "library", "kind": "required"}])
        self.assertFalse(e["x"]["selectable"])
        self.assertIn("dependency library is unsupported_fallback", e["x"]["reason"])

    def test_dependency_id_collision_gets_prefix(self):
        projects = [info("x"), info("other-proj", "lib"), info("lib-id", "lib")]
        releases = {"x": [rel("x", "1", ["26.3"], "2026-01-01", deps=[("lib-id", "required")])],
                    "lib-id": [rel("lib-id", "1", ["26.3"], "2026-01-01")],
                    "other-proj": [rel("other-proj", "1", ["26.3"], "2026-01-01")]}
        mani = make_manifest(self.base, modrinth=[("x", "x"), ("lib", "other-proj")])
        lock = self.resolver({"modrinth": FakeProvider(projects, releases)}, mani).resolve_target(
            "26.3", fake_loader().resolve_build("26.3"), self.base)
        self.assertIn("modrinth-lib", by_id(lock))
        self.assertEqual(by_id(lock)["x"]["dependencies"][0]["id"], "modrinth-lib")

    def test_curseforge_unavailable_does_not_crash(self):
        cf = resolver.ProviderUnavailable("CURSEFORGE_API_KEY is not set")
        mani = make_manifest(self.base, curseforge=[("cfmod", "123")])
        lock = self.resolver({"modrinth": FakeProvider([], {}), "curseforge": cf}, mani).resolve_target(
            "26.3", fake_loader().resolve_build("26.3"), self.base)
        entry = by_id(lock)["cfmod"]
        self.assertEqual(entry["status"], "unavailable")
        self.assertIn("CURSEFORGE_API_KEY", entry["reason"])

    def test_curseforge_distribution_disallowed_and_dep_prefix(self):
        projects = [info("1", "blocked", dist=False, provider="curseforge"), info("2", "ok", dist=True, provider="curseforge"),
                    info("3", "libx", dist=True, provider="curseforge")]
        rels = {"2": [rel("2", "20", ["26.3"], "2026-01-01", deps=[("3", "required")], loaders=("Fabric",), provider="curseforge")],
                "3": [rel("3", "30", ["26.3"], "2026-01-01", loaders=("Fabric",), provider="curseforge")],
                "1": [rel("1", "10", ["26.3"], "2026-01-01", loaders=("Fabric",), provider="curseforge")]}
        mani = make_manifest(self.base, curseforge=[("blocked", "1"), ("ok", "2")])
        lock = self.resolver({"curseforge": FakeProvider(projects, rels, "curseforge")}, mani).resolve_target(
            "26.3", fake_loader().resolve_build("26.3"), self.base)
        e = by_id(lock)
        self.assertEqual(e["blocked"]["status"], "unavailable")
        self.assertEqual(e["ok"]["status"], "compatible")
        self.assertEqual(e["ok"]["dependencies"], [{"id": "cf-libx", "kind": "required"}])
        self.assertEqual(e["cf-libx"]["identity"]["file_id"], "30")

    def test_local_entries(self):
        (self.base / "jars").mkdir()
        (self.base / "jars" / "p.jar").write_bytes(b"jar")
        (self.base / "src").mkdir()
        (self.base / "src" / "f.txt").write_text("hi")
        meta = {"name": "N", "description": "D", "authors": ["a"], "version": "1.0", "license": "MIT"}
        pre = manifest_mod.LocalEntry(id="pre", kind="prebuilt", minecraft_versions=["26.1.x"], dependencies=[], metadata=meta,
                                      path="jars/p.jar", abs_path=self.base / "jars" / "p.jar")
        cb = manifest_mod.LocalEntry(id="cb", kind="custom_build", minecraft_versions=["26.3"], dependencies=["pre"], metadata=meta,
                                     directory="src", abs_directory=self.base / "src",
                                     build={"builder_image": "img@sha256:" + "b" * 64, "command": ["make"], "output": "o.jar"})
        mani = make_manifest(self.base, local=[pre, cb])
        r = self.resolver({"modrinth": FakeProvider([], {})}, mani)
        lock = r.resolve_target("26.3", fake_loader().resolve_build("26.3"), self.base)
        e = by_id(lock)
        self.assertEqual(e["pre"]["status"], "unsupported_fallback")
        self.assertEqual(e["pre"]["supported_minecraft_versions"], ["26.1", "26.1.1", "26.1.2"])
        self.assertEqual(e["pre"]["local"]["path"], "jars/p.jar")
        self.assertEqual(e["pre"]["artifact"]["filename"], "p.jar")
        self.assertEqual(e["cb"]["status"], "compatible")
        self.assertIsNone(e["cb"]["artifact"])
        self.assertIsNone(e["cb"]["build"]["storage"])
        self.assertEqual(len(e["cb"]["build"]["cache_key"]), 64)
        self.assertEqual(e["cb"]["build"]["targets"], {"minecraft": "26.3", "loader": "fabric", "loader_version": "0.17.3"})
        self.assertFalse(e["cb"]["selectable"])  # depends on a fallback
        lock2 = r.resolve_target("26.2", fake_loader().resolve_build("26.2"), self.base)
        self.assertEqual(by_id(lock2)["cb"]["status"], "unavailable")


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        self.projects = [info("lithium")]
        self.releases = {"lithium": [rel("lithium", "1", ["26.3", "26.1.2"], "2026-01-01")]}

    def run_plan(self, loader, force=False):
        mani = make_manifest(self.base, modrinth=[("lithium", "lithium")])
        r = resolver.Resolver("fabric", loader, mani, providers={"modrinth": FakeProvider(self.projects, self.releases)},
                              licenses=LICENSES, known_releases=KNOWN)
        return resolver.plan("fabric", self.root / "out", force=force, window=["26.3", "26.2", "26.1.2"], loader=loader,
                             manifest=mani, resolver=r, servers_dir=self.root)

    def test_plan_pending_unchanged_and_matrix(self):
        result = self.run_plan(fake_loader("pending"))
        states = {t["minecraft"]: t["status"] for t in result["targets"]}
        self.assertEqual(states, {"26.3": "build", "26.2": "pending", "26.1.2": "build"})
        out = self.root / "out"
        self.assertTrue((out / "plan.json").is_file())
        self.assertTrue((out / "26.3.json").is_file())
        self.assertFalse((out / "26.2.json").exists())
        self.assertEqual(json.loads((out / "plan.json").read_text())["targets"][1]["reason"], "No loader for 26.2")
        self.assertEqual([j["minecraft"] for j in resolver.matrix(result)["include"]], ["26.3", "26.1.2"])

        # Commit the 26.3 lock and mark it published: next plan reports unchanged.
        lock = util.read_json(out / "26.3.json")
        locks.write_lock(self.root / "fabric" / "locks" / "26.3.json", lock)
        util.write_json(self.root / "fabric" / "locks" / "status.json", {"targets": {"26.3": {"state": "published"}}})
        again = self.run_plan(fake_loader("pending"))
        states = {t["minecraft"]: t["status"] for t in again["targets"]}
        self.assertEqual(states["26.3"], "unchanged")
        self.assertEqual(states["26.1.2"], "build")
        forced = self.run_plan(fake_loader("pending"), force=True)
        self.assertEqual({t["minecraft"]: t["status"] for t in forced["targets"]}["26.3"], "build")

    def test_github_output(self):
        result = self.run_plan(fake_loader())
        out_file = self.root / "gh_output"
        old = os.environ.get("GITHUB_OUTPUT")
        os.environ["GITHUB_OUTPUT"] = str(out_file)
        try:
            args = Namespace(server="fabric", out=str(self.root / "o2"), force=False, github_output=True)
            orig = resolver.plan
            resolver.plan = lambda *a, **k: result
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(resolver.plan_command(args), 0)
            finally:
                resolver.plan = orig
        finally:
            if old is None:
                del os.environ["GITHUB_OUTPUT"]
            else:
                os.environ["GITHUB_OUTPUT"] = old
        line, has_builds = out_file.read_text().strip().splitlines()
        self.assertTrue(line.startswith("matrix="))
        self.assertEqual(len(json.loads(line[7:])["include"]), 3)
        self.assertEqual(has_builds, "has_builds=true")


if __name__ == "__main__":
    unittest.main()
