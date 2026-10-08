# minecraft

Prebuilt Minecraft server images and a documentation website. Every server image ships with its server software and a mod/plugin catalog already inside, so a container starts with no downloads. Mods and plugins are activated through environment variables.

> Status: implemented, waiting for the first CI runs. See [`.agents/plan.md`](.agents/plan.md) and [`.agents/contracts.md`](.agents/contracts.md).

## Server images

| Image | Server |
| --- | --- |
| `ghcr.io/<owner>/minecraft-server-fabric` | Fabric |
| `ghcr.io/<owner>/minecraft-server-neoforge` | NeoForge |
| `ghcr.io/<owner>/minecraft-server-paper` | Paper |
| `ghcr.io/<owner>/minecraft-server-pumpkin` | Pumpkin |

Each server keeps one manifest beside its custom files, for example `src/mc-server-images/fabric/mods/mods.yml` or `src/mc-server-images/paper/plugins/plugins.yml`. It has `modrinth` and `curseforge` for automatic stable updates, `custom_build` for source projects compiled by CI, and `prebuilt` for ready JAR or WASM files. Metadata and versions for upstream entries are fetched automatically; custom entries declare them explicitly. Exact versions, metadata, and checksums for each Minecraft target are recorded in `src/mc-server-images/<server>/locks/`.

### Tags

- Exact Minecraft version tags, including patch versions, for example `<minecraft-version>` such as `1.2.3`. The maintenance window is per server: each image maintains the three newest stable Minecraft releases that it actually has a stable server build for, and CI pushes component updates to those same tags. A newer Minecraft release a server has no stable build for yet is listed as upcoming (pending) and is not pullable. Tags that leave a server's window remain published but frozen. Pumpkin supports only one Minecraft version at a time, so its window has one entry.
- `latest`: the newest successfully built and checked active Minecraft version for each server image. Missing mod/plugin support does not block it.
- These are the only image tags; there are no separate build or mod-version tags.

Pin a version tag to get updates within that Minecraft version without moving to the next one. The documentation website lists the current versions of each image.

## Mod and plugin selection

Fabric and NeoForge use a comma-separated `MODS` list of manifest IDs; Paper and Pumpkin use `PLUGINS`. An empty list enables none. The entrypoint activates the selection and its required dependencies using only files baked into the image.

Each maintained version bundles the newest compatible stable upstream releases where available. If a project has no compatible Minecraft release, its latest stable same-loader release is kept as an inactive, unsupported fallback. The docs distinguish supported selections from those fallbacks. Explicitly selecting an unsupported artifact stops startup with a clear error before the server launches.

## Documentation website

`ghcr.io/<owner>/minecraft-web` documents what each server image contains and how to run and configure it. The site covers maintained and upcoming versions, mod/plugin metadata and compatibility, selection IDs and environment variables, startup behavior, persistent storage, and image updates.

The documentation is published to GitHub Pages and packaged as a self-hostable image built with `src/web/Dockerfile`. A dedicated `web.yml` workflow handles both destinations, and runs again after every server image publication.

The site is an [Astro](https://astro.build) project with Tailwind CSS and shadcn/ui in `src/web/`. It has no hand-written image data. `python -m server_images site-data` exports every server's loader metadata (title, description, selection variable), `status.json` and locks into one JSON file, and every page, version list and mod/plugin table is generated from it. Adding a server, changing a loader description or publishing new locks updates the site without touching web code. Guides live as Markdown in `src/web/src/content/docs/` and can use placeholders such as `{{latest:paper}}` that are filled from the same data.

```sh
cd src/web
pnpm install
pnpm dev          # exports the site data, then serves http://localhost:4321/
pnpm check        # type check
pnpm build        # static files in dist/
```

## Build automation

Fabric, NeoForge, Paper, and Pumpkin each have their own GitHub Actions workflow. Every stage uses a matrix: `plan` discovers the three newest stable Minecraft releases each server has a stable build for, `build` runs one job per release, and `push_image` currently has one GHCR registry job that publishes the tested images.

The Python tooling behind these workflows lives in `.github/scripts/`: `server_images` plans, builds, checks and publishes the images, and exports the data the documentation site is built from (`site-data`). Run it from the repository root, for example `PYTHONPATH=.github/scripts python -m server_images window --server paper`. Its offline tests run with `python -m unittest discover -s .github/scripts/tests -t .github/scripts`.

Updates are fully automatic. After an image passes its checks, the workflow pushes the tags and commits the new locks and `status.json` straight to `main`; there are no update PRs to approve.

### Repository setup

- **Settings → Pages → Source:** GitHub Actions.
- **Settings → Actions → General → Workflow permissions:** read and write.
- **Secret `CURSEFORGE_API_KEY`** (optional): needed for `curseforge` manifest entries. Without it those entries are recorded as unavailable.
- **Variable `GOOGLE_SITE_VERIFICATION`** (optional): the `content` value of Google Search Console's HTML-tag verification, added to the Pages site. Then submit `sitemap.xml` in Search Console.
- **Secret `LOCKS_PUSH_TOKEN`** (optional): a token allowed to push to `main`. Needed only if `main` is protected; otherwise `GITHUB_TOKEN` is used.
