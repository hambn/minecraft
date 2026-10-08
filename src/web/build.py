#!/usr/bin/env python3
"""Static site generator for the Minecraft server images documentation.

    python src/web/build.py --servers src/mc-server-images --out site \
        --base-path /minecraft/ [--docs src/web/docs] [--repo hambn/minecraft]

Reads ``<server>/locks/status.json`` and ``<server>/locks/<minecraft>.json``
and renders plain HTML files (no JavaScript, no external assets). Python 3.12,
standard library only. The output is deterministic for identical inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path
from string import Template
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import markdown_lite  # noqa: E402

SERVERS = ["fabric", "neoforge", "paper", "pumpkin"]

SERVER_INFO: dict[str, dict[str, Any]] = {
    "fabric": {
        "title": "Fabric",
        "env": "MODS",
        "kind": "mods",
        "catalog_dir": "/data/mods",
        "eula": True,
        "loader_label": "Fabric loader",
        "blurb": "Fabric loader on the vanilla server. Server-side mods are selected with MODS.",
    },
    "neoforge": {
        "title": "NeoForge",
        "env": "MODS",
        "kind": "mods",
        "catalog_dir": "/data/mods",
        "eula": True,
        "loader_label": "NeoForge version",
        "blurb": "NeoForge on the vanilla server. Mods are selected with MODS.",
    },
    "paper": {
        "title": "Paper",
        "env": "PLUGINS",
        "kind": "plugins",
        "catalog_dir": "/data/plugins",
        "eula": True,
        "loader_label": "Paper build",
        "blurb": "Paper, patched at build time. Plugins are selected with PLUGINS.",
    },
    "pumpkin": {
        "title": "Pumpkin",
        "env": "PLUGINS",
        "kind": "plugins",
        "catalog_dir": "/data/plugins",
        "eula": False,
        "loader_label": "Pumpkin commit",
        "blurb": "Pumpkin, a Rust server built from source (no Mojang code). WASM plugins are selected with PLUGINS.",
    },
}

DOC_ORDER = [
    "getting-started",
    "configuration",
    "mods-and-plugins",
    "images-and-files",
    "tags-and-updates",
    "self-hosting",
]

SOURCE_LABELS = {
    "modrinth": "Modrinth",
    "curseforge": "CurseForge",
    "custom_build": "Custom build",
    "prebuilt": "Prebuilt",
}

VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
AVAILABLE_STATES = ("published", "frozen")
DASH = "—"


def e(value: Any) -> str:
    """Escape any value for HTML text or attribute context."""
    return html.escape("" if value is None else str(value), quote=True)


def version_key(version: str) -> tuple:
    nums = tuple(int(x) for x in re.findall(r"\d+", version))
    return (nums, version)


def normalize_base(base: str) -> str:
    base = "/" + base.strip().strip("/") + "/"
    return "/" if base == "//" else base


def safe_http_url(url: Any) -> str | None:
    if isinstance(url, str) and re.match(r"^https?://", url.strip(), re.I):
        return url.strip()
    return None


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        print(f"warning: ignoring {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"warning: ignoring {path}: not a JSON object", file=sys.stderr)
        return None
    return data


class ImageData:
    """Status and locks for one server image."""

    def __init__(self, server: str, servers_dir: Path):
        self.server = server
        self.info = SERVER_INFO[server]
        directory = servers_dir / server / "locks"
        self.status = read_json(directory / "status.json") or {}
        raw_targets = self.status.get("targets")
        self.targets: dict[str, dict] = {}
        if isinstance(raw_targets, dict):
            for version, target in raw_targets.items():
                if VERSION_RE.match(str(version)) and isinstance(target, dict):
                    self.targets[str(version)] = target
        self.locks: dict[str, dict] = {}
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                if path.name == "status.json" or not VERSION_RE.match(path.stem):
                    continue
                lock = read_json(path)
                if lock is not None:
                    self.locks[path.stem] = lock
        self.has_status = bool(self.status)

    @property
    def image_ref(self) -> str:
        return self.status.get("image") or f"ghcr.io/{{owner}}/minecraft-server-{self.server}"

    @property
    def window(self) -> list[str]:
        return [str(v) for v in as_list(self.status.get("window")) if VERSION_RE.match(str(v))]

    @property
    def latest(self) -> str | None:
        latest = self.status.get("latest")
        return str(latest) if latest and VERSION_RE.match(str(latest)) else None

    def versions(self) -> list[str]:
        names = set(self.targets) | set(self.locks) | set(self.window)
        return sorted(names, key=version_key, reverse=True)

    def state(self, version: str) -> str:
        target = self.targets.get(version)
        if target is not None:
            state = str(target.get("state", ""))
            if state in ("published", "pending", "frozen"):
                return state
            return "unlisted"
        if version in self.window:
            return "pending"
        return "unlisted"

    def available(self, version: str) -> bool:
        return self.state(version) in AVAILABLE_STATES

    def by_state(self, state: str) -> list[str]:
        return [v for v in self.versions() if self.state(v) == state]


# ---------------------------------------------------------------------------
# Site rendering
# ---------------------------------------------------------------------------

class Site:
    def __init__(self, servers: Path, out: Path, base: str, docs: Path, repo: str):
        self.servers_dir = servers
        self.out = out
        self.base = normalize_base(base)
        self.docs_dir = docs
        self.repo = repo
        self.owner = repo.split("/")[0].lower() if "/" in repo else repo.lower()
        self.images = {s: ImageData(s, servers) for s in SERVERS}
        for image in self.images.values():
            if "{owner}" in image.image_ref:
                image.status.setdefault("image", f"ghcr.io/{self.owner}/minecraft-server-{image.server}")
        self.templates = {p.stem: Template(p.read_text(encoding="utf-8")) for p in (HERE / "templates").glob("*.html")}
        css = (HERE / "static" / "style.css").read_bytes()
        self.css_version = hashlib.sha256(css).hexdigest()[:10]
        self.docs: list[dict] = []
        self.written: list[str] = []

    # -- helpers --------------------------------------------------------
    def url(self, path: str = "") -> str:
        return self.base + path.lstrip("/")

    def link(self, path: str, text: str, cls: str = "") -> str:
        attr = f' class="{cls}"' if cls else ""
        return f'<a{attr} href="{e(self.url(path))}">{e(text)}</a>'

    def write(self, rel: str, content: str) -> None:
        target = self.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        self.written.append(rel)

    def updated_at(self) -> str | None:
        stamps = [str(i.status["updated_at"]) for i in self.images.values() if i.status.get("updated_at")]
        return max(stamps) if stamps else None

    def nav(self, section: str) -> str:
        items = [("", "Overview", "home")]
        items += [(f"images/{s}/", SERVER_INFO[s]["title"], f"image-{s}") for s in SERVERS]
        items.append(("docs/", "Docs", "docs"))
        parts = []
        for path, label, key in items:
            cur = ' aria-current="page"' if key == section else ""
            parts.append(f'<a href="{e(self.url(path))}"{cur}>{e(label)}</a>')
        parts.append(f'<a href="https://github.com/{e(self.repo)}" rel="noopener">GitHub</a>')
        return "\n".join(parts)

    def footer(self) -> str:
        text = (
            f'Generated from the lock files in <a href="https://github.com/{e(self.repo)}" rel="noopener">{e(self.repo)}</a>. '
            "Not affiliated with Mojang or Microsoft. Minecraft is a trademark of Mojang AB."
        )
        stamp = self.updated_at()
        if stamp:
            text += f" Image status last updated {e(stamp)}."
        return text

    def page(self, rel: str, title: str, content: str, *, section: str = "", description: str = "") -> None:
        full_title = f"{title} - Minecraft server images" if title else "Minecraft server images"
        out = self.templates["base"].safe_substitute(
            title=e(full_title),
            description=e(description or "Prebuilt Minecraft server images with a baked-in mod and plugin catalog."),
            base=e(self.base),
            css_version=self.css_version,
            nav=self.nav(section),
            content=content,
            footer=self.footer(),
        )
        self.write(rel, out)

    def badge(self, state: str, text: str | None = None, href: str | None = None) -> str:
        label = text if text is not None else state
        cls = f"badge {e(state)}"
        if href:
            return f'<a class="{cls}" href="{e(self.url(href))}">{e(label)}</a>'
        return f'<span class="{cls}">{e(label)}</span>'

    # -- build ----------------------------------------------------------
    def build(self) -> None:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self.copy_static()
        self.load_docs()
        self.render_index()
        for server in SERVERS:
            self.render_image(self.images[server])
            for version in self.images[server].versions():
                if self.images[server].available(version) and version in self.images[server].locks:
                    self.render_version(self.images[server], version)
        self.render_docs()
        self.render_404()
        self.write(".nojekyll", "")

    def copy_static(self) -> None:
        dest = self.out / "static"
        shutil.copytree(HERE / "static", dest)

    # -- index ----------------------------------------------------------
    def version_badges(self, image: ImageData) -> str:
        versions = image.versions()
        if not versions:
            return '<span class="muted">No published images yet</span>'
        parts = []
        for v in versions:
            state = image.state(v)
            href = f"images/{image.server}/{v}/" if image.available(v) and v in image.locks else None
            parts.append(self.badge(state, f"{v} · {state}", href))
        return "".join(parts)

    def render_index(self) -> None:
        cards = []
        for server in SERVERS:
            image = self.images[server]
            latest = f"<code>{e(image.latest)}</code>" if image.latest and image.available(image.latest) else "none yet"
            cards.append(self.templates["image_card"].safe_substitute(
                href=e(self.url(f"images/{server}/")),
                title=e(image.info["title"]),
                blurb=e(image.info["blurb"]),
                image=e(image.image_ref),
                latest=latest,
                versions=self.version_badges(image),
            ))

        windows = [i.window for i in self.images.values() if i.window]
        window_html = ""
        if windows:
            window_html = ("<p>The currently maintained Minecraft releases are "
                           + ", ".join(f"<code>{e(v)}</code>" for v in windows[0]) + ".</p>")
        any_published = any(i.by_state("published") or i.by_state("frozen") for i in self.images.values())
        empty = ""
        if not any_published:
            empty = '<div class="notice warn"><strong>No published images yet.</strong> Nothing below can be pulled until a build has been published.</div>'

        content = f"""
<h1>Minecraft server images</h1>
<p class="lead">Four prebuilt server images &mdash; Fabric, NeoForge, Paper and Pumpkin &mdash; each with the server software and a catalog of mods or plugins already inside. Containers start without downloading anything; mods and plugins are switched on with an environment variable.</p>
{empty}
<h2 id="images">Images</h2>
<div class="cards">
{"".join(cards)}
</div>
<h2 id="window">Maintained versions</h2>
{window_html}
<p>Only the three newest stable Minecraft releases are rebuilt. Each release has its own tag, and <code>latest</code> points at the newest one that built and passed its checks.</p>
<ul>
<li>{self.badge("published")} the tag exists in the registry and is rebuilt when its components update.</li>
<li>{self.badge("pending")} the release is in the window but no stable server build exists yet. It is <strong>not</strong> pullable.</li>
<li>{self.badge("frozen")} the release left the window. The tag stays published but is no longer updated.</li>
</ul>
<p>Next: {self.link("docs/getting-started/", "getting started")}, {self.link("docs/mods-and-plugins/", "choosing mods and plugins")} or {self.link("docs/tags-and-updates/", "tags and updates")}.</p>
"""
        self.page("index.html", "", content, section="home")

    # -- per image ------------------------------------------------------
    def render_image(self, image: ImageData) -> None:
        info = image.info
        server = image.server
        ref = image.image_ref
        versions = image.versions()
        parts = [f"""
<p class="crumbs">{self.link("", "Overview")} / {e(info["title"])}</p>
<h1>{e(info["title"])} image</h1>
<p class="lead">{e(info["blurb"])}</p>
<p>Image: <code>{e(ref)}</code></p>
"""]
        published = [v for v in versions if image.available(v)]
        if not published:
            parts.append('<div class="notice warn"><strong>No published images yet.</strong> There is nothing to pull for this server.</div>')
        latest = image.latest
        if latest and image.available(latest):
            parts.append(f"<p>Latest: <code>{e(latest)}</code> (<code>{e(ref)}:latest</code>)</p>")
            if image.status.get("latest_outside_window"):
                parts.append('<div class="notice warn"><code>latest</code> points at a release that is outside the maintained window because no newer target has built yet.</div>')
        if image.window:
            parts.append("<p>Active window: " + ", ".join(f"<code>{e(v)}</code>" for v in image.window) + ".</p>")
        if image.status.get("updated_at"):
            parts.append(f'<p class="muted">Status updated {e(image.status["updated_at"])}.</p>')

        if versions:
            rows = []
            for v in versions:
                state = image.state(v)
                target = image.targets.get(v, {})
                digest = target.get("digest") if state in AVAILABLE_STATES else None
                digest_html = f'<code title="{e(digest)}">{e(str(digest)[:19])}&hellip;</code>' if digest else DASH
                if state in AVAILABLE_STATES and v in image.locks:
                    contents = self.link(f"images/{server}/{v}/", "View contents")
                elif state in AVAILABLE_STATES:
                    contents = '<span class="muted">lock file not available</span>'
                elif state == "pending":
                    contents = f'<span class="muted">{e(target.get("reason") or "Waiting for a stable server build.")}</span>'
                else:
                    contents = '<span class="muted">not recorded as published</span>'
                pull = f"<code>{e(ref)}:{e(v)}</code>" if state in AVAILABLE_STATES else DASH
                rows.append(
                    f"<tr><td><code>{e(v)}</code></td><td>{self.badge(state)}</td><td>{pull}</td>"
                    f"<td>{digest_html}</td><td>{e(target.get('published_at') or '') or DASH}</td><td>{contents}</td></tr>"
                )
            parts.append(f"""
<h2 id="versions">Minecraft versions</h2>
<div class="table-wrap"><table>
<thead><tr><th>Version</th><th>State</th><th>Image reference</th><th>Digest</th><th>Published</th><th>Contents</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody></table></div>
""")

        if published:
            newest = latest if latest and image.available(latest) else published[0]
            digest = image.targets.get(newest, {}).get("digest")
            run_cmd = (f"docker run -d --name mc -p 25565:25565 -v mc-data:/data "
                       f"{'-e EULA=TRUE ' if info['eula'] else ''}{ref}:{newest}")
            parts.append(f'<h2 id="run">Run it</h2><pre><code class="language-sh">{e(run_cmd)}</code></pre>')
            if digest:
                pin = f"# pin the exact build\ndocker pull {ref}:{newest}@{digest}"
                parts.append(f'<pre><code class="language-sh">{e(pin)}</code></pre>')
            if info["eula"]:
                parts.append(f'<p>Setting <code>EULA=TRUE</code> means you accept the {self.eula_link()}.</p>')
            parts.append(f'<p>See {self.link("docs/getting-started/", "getting started")} and {self.link("docs/configuration/", "configuration")} for all options.</p>')
        self.page(f"images/{server}/index.html", f"{info['title']} image", "\n".join(parts),
                  section=f"image-{server}", description=info["blurb"])

    def eula_link(self) -> str:
        return '<a href="https://www.minecraft.net/en-us/eula" rel="noopener">Minecraft EULA</a>'

    # -- per image + version --------------------------------------------
    def render_version(self, image: ImageData, version: str) -> None:
        lock = image.locks[version]
        info = image.info
        server = image.server
        ref = image.image_ref
        state = image.state(version)
        target = image.targets.get(version, {})
        env = info["env"]
        runtime = lock.get("runtime") if isinstance(lock.get("runtime"), dict) else {}
        build = lock.get("server_build") if isinstance(lock.get("server_build"), dict) else {}
        entries = [x for x in as_list(lock.get("entries")) if isinstance(x, dict)]
        entries.sort(key=lambda x: str(x.get("id", "")))

        parts = [f"""
<p class="crumbs">{self.link("", "Overview")} / {self.link(f"images/{server}/", info["title"])} / {e(version)}</p>
<h1>{e(info["title"])} {e(version)} {self.badge(state)}</h1>
"""]
        if state == "frozen":
            parts.append('<div class="notice warn">This release left the maintained window. The tag stays published, but it is frozen and no longer updated.</div>')
        pull = [f"docker pull {ref}:{version}"]
        digest = target.get("digest")
        if digest:
            pull.append(f"docker pull {ref}:{version}@{digest}")
        parts.append(f'<h2 id="pull">Pull</h2><pre><code class="language-sh">{e(chr(10).join(pull))}</code></pre>')

        facts = [
            ("Minecraft version", f"<code>{e(version)}</code>"),
            (info["loader_label"], f"<code>{e(build.get('loader_version'))}</code>" if build.get("loader_version") else DASH),
            ("Base image", f"<code>{e(runtime.get('base_image'))}</code>" if runtime.get("base_image") else DASH),
            ("Base image digest", f"<code>{e(runtime.get('base_digest'))}</code>" if runtime.get("base_digest") else DASH),
            ("Java", e(runtime.get("java_major")) if runtime.get("java_major") else DASH),
        ]
        if digest:
            facts.append(("Image digest", f"<code>{e(digest)}</code>"))
        if target.get("published_at"):
            facts.append(("Published", e(target["published_at"])))
        if lock.get("inputs_hash"):
            facts.append(("Inputs hash", f"<code>{e(lock['inputs_hash'])}</code>"))
        details = build.get("details") if isinstance(build.get("details"), dict) else {}
        downloads = details.get("downloads") if isinstance(details.get("downloads"), dict) else {}
        for name in sorted(downloads):
            item = downloads[name]
            if isinstance(item, dict):
                for algo in ("sha512", "sha256", "sha1"):
                    if item.get(algo):
                        facts.append((f"Download {name} {algo}", f"<code>{e(item[algo])}</code>"))
                        break
        for key, value in flatten({k: v for k, v in details.items() if k != "downloads"}):
            facts.append((key.replace("_", " "), f"<code>{e(value)}</code>"))
        parts.append('<h2 id="server">Server and runtime</h2><dl class="facts">'
                     + "".join(f"<dt>{e(k)}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>")

        selectable = [x for x in entries if x.get("declared", True) and x.get("status") == "compatible" and x.get("selectable")]
        blocked = [x for x in entries if x.get("declared", True) and x.get("status") == "compatible" and not x.get("selectable")]
        fallbacks = [x for x in entries if x.get("declared", True) and x.get("status") == "unsupported_fallback"]
        unavailable = [x for x in entries if x.get("declared", True) and x.get("status") == "unavailable"]
        known = {"compatible", "unsupported_fallback", "unavailable"}
        unknown = [x for x in entries if x.get("declared", True) and x.get("status") not in known]
        dependencies = [x for x in entries if not x.get("declared", True)]

        kind = info["kind"]
        parts.append(f"""
<h2 id="catalog">Bundled {e(kind)}</h2>
<p>Everything below is baked into the image and <strong>inactive by default</strong>. Activate entries with the <code>{e(env)}</code> environment variable, a comma-separated list of IDs. Required dependencies are activated automatically. See {self.link("docs/mods-and-plugins/", "selecting " + kind)}.</p>
<p>{len(selectable)} selectable, {len(fallbacks)} unsupported fallback(s), {len(unavailable)} unavailable, {len(dependencies)} dependency-only.</p>
""")

        parts.append('<h3 id="selectable">Selectable</h3>')
        if selectable:
            sample = ",".join(str(x.get("id")) for x in selectable[:3])
            run = f"docker run -d -p 25565:25565 -v mc-data:/data {'-e EULA=TRUE ' if info['eula'] else ''}-e {env}={sample} {ref}:{version}"
            parts.append(f'<p>Example:</p><pre><code class="language-sh">{e(run)}</code></pre>')
            parts.append(f'<p>Or in a Compose file: <code>{e(env)}: "{e(sample)}"</code>.</p>')
            parts.append(self.entry_table(selectable, extra=[("Requires", self.col_requires)]))
        else:
            parts.append(f"<p>No {e(kind)} are selectable in this image.</p>")

        if blocked:
            parts.append('<h3 id="blocked">Compatible but not selectable</h3><p>Compatible with this release, but a dependency prevents activation.</p>')
            parts.append(self.entry_table(blocked, extra=[("Reason", self.col_reason)]))

        parts.append('<h3 id="fallbacks">Bundled unsupported fallbacks</h3>')
        if fallbacks:
            parts.append(f"<p>No release compatible with Minecraft {e(version)} exists, so the newest stable release for the same loader is kept for reference. These are <strong>not</strong> compatible. Selecting one makes the container refuse to start.</p>")
            parts.append(self.entry_table(fallbacks, extra=[("Supports Minecraft", self.col_supported), ("Reason", self.col_reason)]))
        else:
            parts.append("<p>None.</p>")

        parts.append('<h3 id="unavailable">Unavailable</h3>')
        if unavailable:
            parts.append("<p>Not bundled in this image, with the reason for each.</p>")
            parts.append(self.entry_table(unavailable, extra=[("Reason", self.col_reason)]))
        else:
            parts.append("<p>None.</p>")

        if unknown:
            parts.append('<h3 id="other">Other entries</h3>')
            parts.append(self.entry_table(unknown, extra=[("Status", self.col_status), ("Reason", self.col_reason)]))

        parts.append('<h3 id="dependencies">Dependency-only entries</h3>')
        if dependencies:
            parts.append("<p>Pulled in automatically when a selected entry requires them. They are not listed in the manifest.</p>")
            parts.append(self.entry_table(dependencies, extra=[("Status", self.col_status), ("Reason", self.col_reason)]))
        else:
            parts.append("<p>None.</p>")

        self.page(f"images/{server}/{version}/index.html", f"{info['title']} {version}", "\n".join(parts),
                  section=f"image-{server}",
                  description=f"Contents of {ref}:{version}: server build and bundled {kind}.")

    # entry table columns -------------------------------------------------
    @staticmethod
    def col_requires(entry: dict) -> str:
        deps = [str(d) for d in as_list(entry.get("closure")) if str(d) != str(entry.get("id"))]
        return ", ".join(f"<code>{e(d)}</code>" for d in deps) if deps else DASH

    @staticmethod
    def col_reason(entry: dict) -> str:
        return e(entry.get("reason")) or DASH

    @staticmethod
    def col_supported(entry: dict) -> str:
        versions = [str(v) for v in as_list(entry.get("supported_minecraft_versions"))]
        return e(", ".join(versions)) if versions else DASH

    @staticmethod
    def col_status(entry: dict) -> str:
        return e(str(entry.get("status") or "").replace("_", " ")) or DASH

    def entry_table(self, entries: list[dict], extra: list[tuple[str, Any]]) -> str:
        head = ["ID", "Name", "Description", "Authors", "Version", "License", "Source", "Homepage"] + [h for h, _ in extra]
        rows = []
        for entry in entries:
            meta = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            authors = ", ".join(str(a) for a in as_list(meta.get("authors")))
            home = safe_http_url(meta.get("homepage"))
            homepage = f'<a href="{e(home)}" rel="noopener">link</a>' if home else DASH
            source = SOURCE_LABELS.get(str(entry.get("source")), str(entry.get("source") or ""))
            cells = [
                f"<code>{e(entry.get('id'))}</code>",
                e(meta.get("name")) or DASH,
                f'<span class="desc">{e(meta.get("description"))}</span>' if meta.get("description") else DASH,
                e(authors) or DASH,
                e(meta.get("version")) or DASH,
                e(meta.get("license")) or DASH,
                e(source) or DASH,
                homepage,
            ] + [fn(entry) for _, fn in extra]
            classes = ["", "", "desc", "", "", "", "", ""] + ["reason" if h == "Reason" else "" for h, _ in extra]
            rows.append("<tr>" + "".join(
                (f'<td class="{c}">{cell}</td>' if c else f"<td>{cell}</td>") for cell, c in zip(cells, classes)
            ) + "</tr>")
        header = "".join(f"<th>{e(h)}</th>" for h in head)
        return f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead>\n<tbody>\n' + "\n".join(rows) + "\n</tbody></table></div>"

    # -- docs -----------------------------------------------------------
    def load_docs(self) -> None:
        if not self.docs_dir.is_dir():
            return
        files = {p.stem: p for p in self.docs_dir.glob("*.md") if VERSION_RE.match(p.stem)}
        order = [s for s in DOC_ORDER if s in files] + sorted(s for s in files if s not in DOC_ORDER)
        for slug in order:
            text = files[slug].read_text(encoding="utf-8")
            title = markdown_lite.first_heading(text) or slug.replace("-", " ").title()
            self.docs.append({"slug": slug, "text": text, "title": title})

    def rewrite_link(self, url: str) -> str:
        if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) or url.startswith("#") or url.startswith("//"):
            return url
        if url.startswith("/"):
            return self.url(url)
        m = re.match(r"^(?:\./)?([A-Za-z0-9_-]+)\.md(#.*)?$", url)
        if m:
            return self.url(f"docs/{m.group(1)}/") + (m.group(2) or "")
        return url

    def render_docs(self) -> None:
        if not self.docs:
            return
        items = []
        for doc in self.docs:
            summary = markdown_lite.first_paragraph(doc["text"])
            summary_html = f"<p>{markdown_lite.inline_html(summary, self.rewrite_link)}</p>" if summary else ""
            items.append(f'<li><a href="{e(self.url("docs/" + doc["slug"] + "/"))}">{e(doc["title"])}</a>{summary_html}</li>')
        content = ('<h1>Documentation</h1><p class="lead">How to run, configure and update the server images.</p>'
                   '<ul class="doc-list">' + "".join(items) + "</ul>")
        self.page("docs/index.html", "Documentation", content, section="docs")

        for idx, doc in enumerate(self.docs):
            sidebar = []
            for other in self.docs:
                cur = ' aria-current="page"' if other is doc else ""
                sidebar.append(f'<li><a href="{e(self.url("docs/" + other["slug"] + "/"))}"{cur}>{e(other["title"])}</a></li>')
            prev_link = next_link = ""
            if idx > 0:
                p = self.docs[idx - 1]
                prev_link = f'<a href="{e(self.url("docs/" + p["slug"] + "/"))}">&larr; {e(p["title"])}</a>'
            if idx + 1 < len(self.docs):
                n = self.docs[idx + 1]
                next_link = f'<a href="{e(self.url("docs/" + n["slug"] + "/"))}">{e(n["title"])} &rarr;</a>'
            body = markdown_lite.convert(doc["text"], self.rewrite_link)
            layout = self.templates["docs_layout"].safe_substitute(
                sidebar="\n".join(sidebar), body=body, prev=prev_link, next=next_link)
            self.page(f"docs/{doc['slug']}/index.html", doc["title"], layout, section="docs",
                      description=markdown_lite.first_paragraph(doc["text"])[:200])

    def render_404(self) -> None:
        content = self.templates["not_found"].safe_substitute(base=e(self.base))
        self.page("404.html", "Page not found", content)


def flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key in sorted(data):
        value = data[key]
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out += flatten(value, f"{name} ")
        elif isinstance(value, list):
            out.append((name, ", ".join(str(v) for v in value)))
        elif value is not None:
            out.append((name, str(value)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--servers", required=True, type=Path, help="directory holding <server>/locks/ (src/mc-server-images)")
    parser.add_argument("--out", required=True, type=Path, help="output directory (replaced)")
    parser.add_argument("--base-path", default="/", help="URL prefix, e.g. /minecraft/ for GitHub Pages or / for root")
    parser.add_argument("--docs", type=Path, default=HERE / "docs", help="markdown documentation directory")
    parser.add_argument("--repo", default="hambn/minecraft", help="GitHub owner/name used for links and image refs")
    args = parser.parse_args(argv)

    site = Site(args.servers, args.out, args.base_path, args.docs, args.repo)
    site.build()
    print(f"wrote {len(site.written)} files to {args.out} (base path {site.base})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
