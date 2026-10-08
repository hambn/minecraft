---
name: web-ui
description: Rules, architecture and checklists for the documentation website in src/web (Astro + Tailwind + shadcn/ui, generated from the server image data). Use for any change to the web UI, its pages, components, styles, docs content, SEO, the site-data export, the web Dockerfile or web.yml.
---

# Web UI (src/web)

The site documents the Minecraft server images: what each image contains, which versions are maintained, and how to run them. It is published to GitHub Pages and as the `ghcr.io/<owner>/minecraft-web` image. Follow everything below on every change; these are the owner's explicit requirements, not suggestions.

## Requirements from the owner

1. **Synced with the project, nothing hard-coded.** Every server, version, tag, digest, mod/plugin and count comes from the generated data. Changing images, loaders or locks must update the site with no web edits. Never type a server name, version number, image reference or mod list into a page or component. If the site needs a new fact, export it from the Python side (see "Data flow").
2. **Highlight the auto-updated versions.** The newest `window_size` (3) published versions per image (`maintained: true`) get the green pulsing `LiveDot` + "Auto-updated" treatment everywhere they appear. Pending/upcoming versions are dashed "soon"; frozen ones are muted. Never describe an unpublished version as available.
3. **A mods/plugins list per maintained version.** Image pages show every declared entry across the maintained versions with the exact bundled version per version. Version pages list the full catalog grouped as selectable, not selectable, unsupported fallbacks, unavailable, dependency-only.
4. **Source links on every entry.** Each mod/plugin shows where it comes from: Modrinth or CurseForge project (version pages link the exact release), Source (custom_build directory on GitHub), Prebuilt file (committed jar/wasm on GitHub), Homepage (when not Modrinth/CurseForge), and Download .jar/.wasm for the bundled file on version pages. Use `entryLinks()` in `lib/site-data.ts`; extend it rather than building links in components.
5. **Docker Compose docs.** `docs/docker-compose.md` is the full guide; every image and version page also has generated `docker run` / `compose.yaml` (/ `docker pull`) tabs with a copy button (`lib/snippets.ts`).
6. **Look: shadcn, modern, simple, minimal.** Neutral shadcn palette (radix-nova preset, Geist / Geist Mono), one green accent (`success`) used only for "auto-updated/selectable", light + dark mode, generous whitespace, rounded-xl bordered surfaces. No decorative clutter.
7. **No horizontal scrolling, anywhere, at any width.** No wide tables. Data is shown as lists/cards that stack on small screens (`grid` with `lg:grid-cols-[minmax(0,1fr)_<n>rem]`), long values use `break-all`/`overflow-wrap:anywhere`, docs tables wrap, code wraps on phones (`globals.css`). Mobile nav and the docs sidebar are collapsible `<details>` menus, never scrolling strips.
8. **No layout jank.** Boxes fit their content (no empty space under short tabs); switching tabs must not move content above it (the hero is `items-start`). No focus outline box on clicked tabs (underline only).
9. **Best possible SEO** (see "SEO").
10. **Clean code and file structure** following Astro/shadcn conventions (see "Structure" and "Conventions").

## Stack

Astro 7 (static output, `trailingSlash: "always"`), Tailwind CSS v4 (`@tailwindcss/vite`, `@tailwindcss/typography`), shadcn/ui (Radix base, components in `src/components/ui`, `cn` from the `cn` package via `@/lib/utils`), React 19 for components, Shiki for highlighting, Sätteri for Markdown (Astro 7 default; plugins via `@astrojs/markdown-satteri`, not remark), satori + resvg for social cards, pnpm, TypeScript strict (TS 5.x because `@astrojs/check` needs it), Prettier with astro + tailwind plugins (printWidth 140).

## Data flow

```
src/mc-server-images/<server>/locks/{status.json,<mc>.json}   (written by CI publish)
.github/scripts/server_images/loaders/<server>.py              (title, description, homepage, loader_label, catalog_dir, eula, env_var, catalog_kind, manifest)
        │  python -m server_images site-data   (site_data.py, stdlib only)
        ▼
src/web/src/data/site-data.json   (generated, gitignored; `pnpm site-data`)
        │  typed by src/web/src/lib/site-data.ts
        ▼
pages, components, docs placeholders, sitemap, OG cards
```

- New fact needed → add it to `site_data.py` (and the `Loader` class if it is per-server presentation), update `tests/test_site_data.py`, the TS types in `lib/site-data.ts`, and the "Website" section of `.agents/contracts.md` together.
- Version state logic (`published|pending|frozen|unlisted`, `maintained`) lives in `site_data.py`; TS only groups and formats.
- Lock entry fields used by the UI: `id, declared, source, status, selectable, reason, closure, metadata{name,description,authors,version,license,homepage}, supported_minecraft_versions, identity{project_id,slug,version_id,file_id}, artifact{filename,url,size}, local{path}, build{directory}`; `server.manifest_dir` is the repo path those relative paths resolve against.

## Structure

```
src/web/
  astro.config.ts        reads site-data.json (repo), SITE_URL / BASE_PATH env, Sätteri plugin, Shiki themes
  Dockerfile, nginx.conf python stage (site-data) → node stage (build, BASE_PATH=/) → nginx-unprivileged :8080
  src/
    content.config.ts    docs collection: frontmatter title, description (SEO, 120–160 chars), order
    content/docs/*.md    guides; plain Markdown that also reads well on GitHub
    data/                generated site-data.json (never commit)
    layouts/             base-layout (head, header, footer, theme script), docs-layout (sidebar/menu + TOC)
    pages/               index, images/[server]/index, images/[server]/[version], docs/index, docs/[id], 404,
                         sitemap.xml.ts, robots.txt.ts, og/[slug].png.ts, apple-touch-icon.png.ts
    components/          feature components (kebab-case); ui/ = shadcn primitives (add via `pnpm dlx shadcn@latest add <name>`)
      layout/            site-header, site-footer, theme-toggle, github-icon
    lib/                 site-data (types + selectors + entryLinks), site (url/canonical/format helpers),
                         snippets (docker run/compose text), highlight (Shiki), markdown-site (docs plugin), og
    scripts/copy-code.ts copy buttons for [data-copyable] pre
    styles/globals.css   shadcn tokens + success/warning, prose-site utility, Shiki dark mode, phone code wrapping
```

## Conventions

- **Astro ↔ React boundary.** React components used from `.astro` render to static HTML (no `client:*`) and take **props only**. Never pass children/slots from Astro into a React component (Astro wraps them in `<astro-static-slot>`, which breaks tables and `asChild`). For links styled as buttons use `<a class={buttonVariants(...)}>`. Composite views (lists, cards, badges) are self-contained TSX.
- **JavaScript is opt-in.** Only `CodeTabs` hydrates (`client:visible`). Theme toggle, copy buttons and menus are tiny scripts or `<details>`. Docs pages ship no React.
- **Radix Tabs:** put `dangerouslySetInnerHTML` on an inner div, not on `TabsContent`.
- **Grids:** single-column grids that hold wide content use `grid-cols-1` / `minmax(0,1fr)` and children `min-w-0`, or they overflow on phones.
- **Big version numbers** use the sans font with `tabular-nums`, not Geist Mono (its dots render as "26 . 3").
- **Paths:** always build internal URLs with `url()` from `lib/site.ts` (handles the `/minecraft/` base); canonical/absolute with `canonical()`.
- **Docs Markdown:** quote frontmatter strings (descriptions contain colons). Link sibling docs as `other-doc.md#anchor`. Live values come from placeholders handled by `lib/markdown-site.ts`: `{{owner}} {{repo}} {{windowsize}} {{servers}}`, per server `{{image:paper}} {{latest:paper}} {{latestregex:paper}} {{window:paper}} {{upcoming:paper}}`, and a paragraph containing only `{{images-table}}`. Add new placeholders there instead of hard-coding. Docker's own `{{json .Config.Labels}}` is left alone.
- **Copy text style:** short, plain, factual sentences; no marketing fluff; numbers from data (`data.window_size`, counts).
- Run `pnpm format` before finishing; keep comments sparse and explanatory like the existing code.

## SEO

- Unique `<title>` (≤ ~65 chars) and meta description per page via `Seo` props; home uses `fullTitle`. One `<h1>` per page, semantic sections, breadcrumbs (with BreadcrumbList JSON-LD).
- Canonical always points at the public site (`SITE_URL`), also in the self-hosted image, so copies never compete.
- JSON-LD: WebSite on every page; ItemList (home), SoftwareApplication (image pages), TechArticle (version and doc pages). Escape `<` in JSON-LD.
- `sitemap.xml` built from data with `lastmod` from `published_at`/`updated_at`; `robots.txt` points at it. New page types must be added to the sitemap and get an OG card in `pages/og/[slug].png.ts`.
- OG cards: satori uses content-box sizing, so padding goes on an inner element (otherwise content falls off the 630px canvas).
- Optional `PUBLIC_GOOGLE_SITE_VERIFICATION` (repo variable `GOOGLE_SITE_VERIFICATION` in web.yml).
- Self-hosted fonts, no external requests, minimal JS for Core Web Vitals.

## Commands (run in src/web)

```sh
pnpm install
pnpm site-data         # regenerate src/data/site-data.json from the locks
pnpm dev               # live dev server (runs site-data first)
pnpm check             # astro check, must be 0 errors/warnings
pnpm format            # prettier; CI runs format:check
pnpm build             # dist/; set BASE_PATH=/ for root hosting
pnpm astro preview --host 0.0.0.0 --port 4321   # serves dist at http://localhost:4321/minecraft/ (daemonizes; stop with `pnpm astro preview stop`; if 4321 is taken it silently picks 4322)
```

Python side (repo root): `python3 -m unittest discover -s .github/scripts/tests -t .github/scripts`.
Docker: `docker build -f src/web/Dockerfile -t minecraft-web:local .` then `docker run --rm -p 8080:8080 minecraft-web:local`.

## CI and deploy

`.github/workflows/web.yml`: plan (snapshot inputs, `actions/configure-pages` for the public URL incl. custom domains) → build matrix `pages` (site-data, check, format:check, build with `SITE_URL`/`BASE_PATH`) and `docker` (Dockerfile + smoke test: non-root, `/`, `/docs/`, sitemap, real 404) → publish to Pages and push `minecraft-web:latest` on main. It reruns after every server workflow (`workflow_run`) and on changes to `src/web/**`, locks or `.github/scripts/server_images/**`. Dependabot covers npm in `src/web`.

## Verify every change (live, not just the build)

1. `pnpm check`, `pnpm format:check`, `pnpm build` pass; Python tests pass if `site_data.py`/loaders changed.
2. Serve the build and open it in the browser preview; look at the changed pages in light and dark mode, desktop (1280) and phone (390).
3. No horizontal scroll: in the browser, load every sitemap URL in a 360px iframe and assert `documentElement.scrollWidth <= 360` and no element with `overflow-x:auto|scroll` has `scrollWidth > clientWidth`.
4. Link crawl: follow every internal `href`/`src` from `/minecraft/` and assert 200s and existing `#anchors`.
5. Interactions: theme toggle persists, tabs switch without moving content above, copy buttons copy exact text, mobile menus open.
6. Give the user the local URL (`http://localhost:4321/minecraft/` and the LAN address) so they can review it too.
