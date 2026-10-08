# Plan

Working plan for this repository. Update it as decisions are made; the README stays the user-facing summary.

## Goal

1. Four server images with the server and a catalog of mods/plugins baked in, so a container starts with no downloads. Only mods/plugins selected through environment variables are activated.
2. A documentation website published to GitHub Pages, plus a web image serving the same documentation for self-hosting. Document how to run and configure the server images and what each image contains.
3. Automatically maintain exactly the three newest stable Minecraft releases. Update base images, matching loader/server builds, upstream mods/plugins, and changed custom artifacts within those Minecraft version tags. Older published tags remain frozen. Publish only Minecraft version tags and `latest`.

## Repository layout

The Python build tooling lives in `.github/scripts/` (`server_images`, which also exports the website's data). Mod/plugin lists, custom artifacts and source projects, Dockerfiles, startup scripts, and generated locks live together in `src/mc-server-images/`. Website pages, templates and its Dockerfile live in `src/web/`.

```text
.github/
  scripts/
    server_images/ # Build tooling: plan, lock, stage, CI checks, publish
      loaders/     # Server-specific version and support rules
      sources/     # Upstream API clients
    tests/
  workflows/
    fabric.yml
    neoforge.yml
    paper.yml
    pumpkin.yml
    scripts.yml    # Unit tests for .github/scripts
    web.yml
src/
  mc-server-images/
    licenses.yml
    common/        # Shared startup helpers (lib.sh)
    fabric/
      locks/       # Generated, committed locks per Minecraft version, plus status.json
      Dockerfile
      entrypoint.sh
      mods/
        mods.yml   # Modrinth, CurseForge, custom builds, and prebuilt mods
        jars/      # Custom prebuilt mods
        src/       # Custom mod source projects, one directory per project
    neoforge/
      locks/       # Generated, committed locks per Minecraft version, plus status.json
      Dockerfile
      entrypoint.sh
      mods/
        mods.yml
        jars/
        src/
    paper/
      locks/       # Generated, committed locks per Minecraft version, plus status.json
      Dockerfile
      entrypoint.sh
      plugins/
        plugins.yml
        jars/      # Custom prebuilt plugins
        src/       # Custom plugin source projects
    pumpkin/
      locks/       # Generated, committed locks per Minecraft version, plus status.json
      Dockerfile
      entrypoint.sh
      plugins/
        plugins.yml
        wasm/      # Custom prebuilt WASM plugins
        src/       # Custom plugin source projects
  web/             # Astro site: Dockerfile, nginx.conf, package.json
    src/
      content/docs/  # Server usage and configuration documentation (Markdown)
      components/    # UI components (shadcn/ui in components/ui/)
      layouts/
      lib/           # site-data types, snippets, SEO helpers
      pages/         # Routes: overview, images/<server>/<version>, docs, sitemap, social cards
```

Each server keeps one YAML manifest beside its custom artifacts and source projects: `mods/mods.yml` for Fabric and NeoForge, or `plugins/plugins.yml` for Paper and Pumpkin. Each manifest has `modrinth`, `curseforge`, `custom_build`, and `prebuilt` sections. Paths inside a manifest are relative to the directory containing that manifest. Bundle declared entries and their resolved dependencies; dropping an undeclared file into a directory does not add it to an image. The resolver generates and commits locks under `src/mc-server-images/<server>/locks/`; both server builds and website generation consume those files.

## Server images

| Image | Server | Bundled extras |
| --- | --- | --- |
| `minecraft-server-fabric` | Fabric loader + vanilla server | `src/mc-server-images/fabric/mods/mods.yml` |
| `minecraft-server-neoforge` | NeoForge + vanilla server | `src/mc-server-images/neoforge/mods/mods.yml` |
| `minecraft-server-paper` | Paper (patched at build time) | `src/mc-server-images/paper/plugins/plugins.yml` |
| `minecraft-server-pumpkin` | Pumpkin (Rust, built from source) | `src/mc-server-images/pumpkin/plugins/plugins.yml` |

Registry: `ghcr.io/hambn/<image>`. The cluster pulls through the mirror `ghcr.hamdocker.ir/hambn/<image>`.

### Mod and plugin sources

The resolver reads four sections from each server's manifest:

- `modrinth`: identify a project and automatically select its newest compatible stable release. Resolve required dependencies too. Keep upstream API clients separate so other release sources can be added later.
- `curseforge`: identify a project and automatically select its newest compatible stable release and resolve required dependencies through the CurseForge provider.
- `custom_build`: identify a committed source directory, a build command, an explicit output path, and a builder image pinned by digest. CI builds the project for declared Minecraft and loader targets and stores its verified output in the image's inactive catalog.
- `prebuilt`: identify a ready artifact by repository path. Java mods and plugins use JAR files; Pumpkin uses WASM plugins. CI verifies its checksum and stores it in the image's inactive catalog without compiling it.

Every entry has a unique ID used for environment-variable selection. Resolved artifacts have metadata containing their name, description, authors, artifact version, and license, plus a homepage when available. The artifact version is separate from Minecraft and loader compatibility. All listed mods/plugins are catalog entries, inactive by default; an unsupported entry does not block maintaining a Minecraft release.

For Modrinth and CurseForge entries, the user supplies project identity and a stable selection ID. Do not require user-provided metadata or artifact versions in these sections. Automation fetches metadata, compatibility, dependencies, and exact release versions from the provider and writes them into each Minecraft target's lock. Different targets can select different releases. Provider updates change locks without rewriting metadata into the user-maintained manifests. Missing provider metadata must be recorded explicitly rather than invented; missing license permission blocks redistribution until resolved.

Custom build and prebuilt entries declare their metadata, version, compatibility, and dependencies explicitly. Their version is fixed until the maintainer changes it. They have no upstream auto-update lookup; changes to committed artifacts, sources, metadata, or recipes trigger CI resolution.

Example shape for `src/mc-server-images/fabric/mods/mods.yml`, with illustrative project names and versions:

```yaml
modrinth:
  - id: upstream-mod
    project: example-project-id
curseforge:
  - id: another-upstream-mod
    project: 123456

custom_build:
  - id: custom-source-mod
    directory: src/custom-source-mod
    minecraft_versions: ["26.3"]
    dependencies: []
    metadata:
      name: Custom source mod
      description: A server mod compiled by CI.
      authors: [Example author]
      version: "0.1.0"
      license: MIT
    build:
      builder_image: "<builder-image>@sha256:<digest>"
      command: ["./gradlew", "--no-daemon", "build"]
      output: build/libs/custom-source-mod.jar

prebuilt:
  - id: custom-ready-mod
    path: jars/custom-ready-mod-1.0.0.jar
    minecraft_versions: ["26.3"]
    dependencies: []
    metadata:
      name: Custom ready mod
      description: A server mod supplied as a ready JAR.
      authors: [Example author]
      version: "1.0.0"
      license: MIT
```

Use the same sections and metadata fields in `plugins.yml`. Build commands run in the source directory, and output paths are relative to that directory. Source projects must pin their tools and dependencies and accept their declared artifact version and target Minecraft/loader versions from CI. Where the artifact format exposes version and compatibility metadata, validate it against the custom manifest. For other artifacts, the manifest is the explicit compatibility declaration. Record whether each artifact supports the image's target without automatically activating it.

### Artifact selection for each maintained Minecraft version

1. For each upstream project, select the newest stable, server-appropriate release compatible with the image's exact Minecraft version and loader. Use provider compatibility metadata and publication order, not the mod's filename or its own version number.
2. If there is no compatible release for that Minecraft version, bundle the project's newest stable, server-appropriate release for the same loader as an inactive fallback. Record its actual supported versions and the reason it is unsupported in this image. Never label the fallback compatible merely because it was bundled.
3. If there is no usable release for the loader, or redistribution is not permitted, omit the artifact and record the reason. Do not substitute a Forge mod into a Fabric image, for example.
4. For prebuilt custom files, keep the explicitly supplied version and mark its declared target compatibility. For custom sources, build only declared targets; a missing target or failed custom build makes that entry unavailable for the image and is recorded without blocking the baseline server image. Invalid manifests and checksum failures still fail CI.
5. Resolve required dependencies for each catalog entry and record its dependency closure and constraints. An entry is selectable only when its dependencies can also be activated for the image's target. Do not activate all bundled dependencies by default.

Expand an explicitly declared compatibility family such as `26.1.x` to matching concrete Minecraft releases, including `26.1.2`, using version components rather than string-prefix matching. Modrinth exposes supported `game_versions` and `loaders` as lists; use those authoritative values when a website label summarizes them as `26.1.x`. A family label in a title or filename alone is not proof of support. See the [Modrinth version API](https://docs.modrinth.com/api/operations/getprojectversions/).

Using the illustrative maintained window `26.3`, `26.2`, and `26.1.2`: a project such as `tab-was-taken` gets its newest compatible release independently for each image. A release supporting the `26.1.x` family can be selected for `26.1.2` when its declared compatibility covers that version. If a project has no compatible release for `26.3`, that image carries its latest stable same-loader fallback, inactive and documented as unsupported. These are examples, not assertions about current upstream releases.

### Tags

- One tag per exact Minecraft release, including patch versions: `26.3`, `26.2`, `26.1.2`, ... Rebuilds overwrite that same tag.
- `latest` points at the newest release in the active three-version window for that image that has successfully built and passed its server CI checks. An unsupported catalog mod/plugin does not prevent moving `latest`.
- Consumers pin a version tag by digest (Flux `ImagePolicy` with `pattern: '^26\.3$'` and `digestReflectionPolicy: Always`). That gives "update within 26.3, never jump to 26.4 until I change the tag".
- No immutable build, timestamp, loader, or mod-version tags. Consumers can record digests for rollback; registry retention must preserve those digests if rollback is required.

### Which Minecraft versions get built

Read Mojang's release manifest, filter to stable releases (`type: release`, no snapshots or prereleases), and order by release time. Patch releases count separately. Each server type has its own maintenance window: the newest three of those releases for which that server has a stable build (see the loader rules below). Nothing is hardcoded; the window is detected on every run. Mod support does not affect the window.

For example, if Mojang's newest releases are `26.3`, `26.2`, `26.1.2`, `26.1.1` and NeoForge has no stable build for `26.3` yet, NeoForge maintains `26.2`, `26.1.2` and `26.1.1`, and reports `26.3` as **upcoming** (pending). Once a stable NeoForge build for `26.3` appears, `26.3` enters the window and `26.1.1` leaves it: its lock file and status entry are deleted and it is never rebuilt (the registry tag is left as is). Releases older than the newest supported one that a server skipped are simply not maintained. Pumpkin supports one Minecraft version per commit, so its window has a single entry.

Within the active window, each server image needs:

1. **Loader:** a stable build exists for it.
   - Fabric: a `stable: true` loader in Fabric meta, and the game version is listed as stable.
   - NeoForge: a non-`-beta` version in the NeoForged maven for that Minecraft version.
   - Paper: a build in the `STABLE` channel of the Paper Fill API.
   - Pumpkin: no stable releases exist (pre-1.0). It supports one protocol per commit. See open decisions.
2. **Base image:** the Java runtime satisfies `javaVersion.majorVersion` from the Mojang version manifest for Java servers; use the appropriate pinned runtime base for Pumpkin.
3. **Server checks:** the baseline server starts offline, answers a status query, and stops cleanly. Mods/plugins remain unselected for this baseline check.

If a server has no usable build for a Mojang release newer than its window, record that release as upcoming/pending and retry automatically. Do not invent a server build. Keep `latest` on the newest successful active target until a newer one passes. If no active target is available, retain the last published `latest` and explicitly report it as outside the maintained window.

### Lock files

The resolver writes what it chose into `src/mc-server-images/<server>/locks/<minecraft-version>.json`: base image digest, loader/server build version, server jar hash, and every bundled mod/plugin with its source type, identity, name, description, authors, exact artifact version, license, dependencies, compatibility, and final artifact `sha512`. Record the same metadata for automatically resolved dependencies. Include whether each entry is compatible, an unsupported fallback, or unavailable, its activation eligibility, and any incompatibility or omission reason. Bundled does not mean enabled.

- Upstream entries also record the provider's version ID and download URL.
- Local entries record the repository path and file checksum.
- Source entries record the source-tree hash, build command, output path, builder digest, target Minecraft/loader versions, and resulting artifact checksum and storage reference.

CI builds custom source artifacts before finalizing the lock. Retain those outputs by content hash so image builds consume the same verified artifacts and later rebuilds can retrieve them. The artifact storage mechanism is an open decision below. Image builds use the lock and its referenced artifacts without selecting newer dependencies or rebuilding unpinned source. Every update is a visible Git diff.

### Build

- Base: `eclipse-temurin:<java>-jre` (pinned by digest in the lock), non-root UID `1000`.
- Fabric: `fabric-installer server -mcversion <v> -loader <l> -downloadMinecraft` at build time.
- NeoForge: `neoforge-<v>-installer.jar --install-server` at build time.
- Paper: `java -Dpaperclip.patchonly=true -jar paper.jar` at build time, so the patched jar is in the image.
- Pumpkin: multi-stage Rust build; source plugins compiled to `wasm32-wasip2` in a builder stage, with prebuilt plugins consumed as locked WASM artifacts.
- Mods and plugins: fetch locked upstream artifacts, copy locked local artifacts, or retrieve the locked outputs of custom source builds. Verify every artifact against the lock's `sha512` before adding it to the image. Compile custom sources in CI builder stages, never at container startup.
- Server files live in `/opt/server`; mod/plugin catalog artifacts live outside any loader-scanned directory, under `/opt/catalog` in the read-only image layer. The world and runtime config go to the `/data` volume. A small entrypoint handles `EULA`, memory, server properties, and activation of the selected catalog entries.

### Runtime mod and plugin selection

- Fabric and NeoForge accept `MODS`, a comma-separated list of manifest IDs, for example `MODS=tab-was-taken,custom-source-mod`. Paper and Pumpkin accept the equivalent `PLUGINS` list.
- Empty or unset lists activate no catalog mods/plugins. Every catalog entry, including compatible entries and unsupported fallbacks, stays inactive until selected.
- Before launching the server, resolve selected IDs against the image's baked catalog and activate their required dependencies. Validate Minecraft/loader compatibility, available dependency versions, conflicts, and duplicate artifacts using only baked metadata and files. No runtime downloads or builds.
- Unknown or unavailable IDs and unresolved dependency conflicts produce a clear startup error. If a user explicitly selects an unsupported fallback, reject it before launching the server. The error identifies the entry, the image's Minecraft/loader versions, its declared supported versions, and the incompatibility reason. There is no warning-only bypass.
- Link or copy only the validated selection and its required dependencies into `/data/mods` or `/data/plugins`. On restart, remove stale links/copies previously managed by the entrypoint so removed selections or older image artifacts do not remain active. Track managed files and preserve unrelated user data.
- The docs list selection IDs and show environment-variable examples. Separate supported/selectable entries from bundled unsupported fallbacks and unavailable entries, with reasons for each.

### CI checks before push

- Start the image with `--network none` and wait for the server's ready line. This fails the build if anything tries to download at runtime.
- Ping the server with a status query, then stop it cleanly.
- Check that an empty selection leaves the bundled catalog inactive. Exercise selected compatible entries and their dependencies, selection changes on a reused `/data` volume, and rejection of invalid selections. Compatibility metadata alone does not guarantee arbitrary combinations of mods work together.
- Before pushing, recheck that the Minecraft release is still in the current three-version window so a stale CI job cannot overwrite a frozen tag. Push the exact version tag, and `latest` only after the newest eligible target passes.

## Update automation (GitHub Actions)

Use a separate workflow for each server: `.github/workflows/fabric.yml`, `neoforge.yml`, `paper.yml`, and `pumpkin.yml`. Keep shared logic in the server tooling so these workflows use the same release-selection and artifact rules. There is no shared top-level `resolve.yml` or `build.yml` replacing the per-server workflows.

Every stage uses a job matrix, including stages with one entry. Each server workflow has these stages in order:

1. **`plan`** uses a single-entry server matrix, such as `server: [fabric]` in `fabric.yml`. Query Mojang for the three newest stable release IDs using the shared maintenance-window rule. For this server, resolve current loader/server builds, base digests, upstream compatible releases or fallbacks, prebuilt files, and custom source build recipes. Emit a JSON build matrix with exactly three Minecraft targets and their planned inputs. Include unavailable loader/server targets as pending instead of substituting older releases. Upload the plan and input snapshot as workflow artifacts.
2. **`build`** depends on `plan` and uses its JSON output as a dynamic Minecraft-version matrix. For an illustrative window of `26.3`, `26.2`, and `26.1.2`, this creates three parallel jobs, one per image version. Use `fail-fast: false`. Each available target builds or reuses verified custom artifacts, finalizes its lock, builds the server image, and runs the CI checks. A pending target reports its status without creating a fake image. Successful jobs upload the tested image as an OCI/image archive, its final lock, and check results. No registry pushes happen in this stage.
3. **`push_image`** depends on `plan` and the completed `build` matrix and uses `registry: [ghcr]`. This is one job for now, consuming all tested version artifacts for that server. Verify their provenance and checks, recheck the active three-version window, and push each eligible image to its exact Minecraft tag in GHCR. Then update `latest` to the newest eligible successful active target. Do not rebuild images while pushing, and do not publish temporary or per-build image tags. Future registries can be added as entries in this matrix without duplicating the version builds.

Use job outputs and `fromJSON` for the dynamic build matrix, following [GitHub's matrix documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations). Transfer images and locks through workflow artifacts so the push job publishes the bytes tested by the build jobs.

Trigger each workflow on a schedule, for example every six hours, manual dispatch, and changes to its own manifests, custom files, active locks, or build/startup code. Shared tooling changes trigger all affected server workflows. Every run plans the server's active releases but creates build jobs only for targets whose inputs changed; unchanged and pending targets are passed to `push_image` through `plan.json`. Releases outside the window never enter a build matrix.

Automatically persist validated generated locks and trigger documentation updates without waiting for manual review. Preserve historical locks without refreshing them. Persist only the current workflow's generated lock changes, and coordinate concurrent server workflows so one cannot overwrite another's updates. Avoid workflow loops caused by generated lock commits. The automatic Git update mechanism remains an open decision below.

Unplanned build/check failures prevent that workflow run from publishing and leave existing tags unchanged. A planned pending target does not block the other available targets. Serialize publication per server image and prevent stale runs from overwriting newer published results. Publishing permissions belong to the push stage; PR validation can plan and build without publishing.

This covers the update cases:

- New compatible base image digest → rebuild all active versions using that base.
- New stable loader or server implementation build for an exact maintained Minecraft release → rebuild that version without changing its Minecraft tag.
- New stable mod/plugin version for a game version → rebuild that version.
- Changed custom JAR/WASM file → update its checksum and rebuild the affected images.
- Changed custom source project or build recipe → build and lock the new artifact, then rebuild the affected images.
- New stable Minecraft release → slide the three-version window, delete the outgoing release's lock, build available server targets for the incoming release, and move `latest` after successful checks. Mod support does not delay the window shift.

## Web image

`minecraft-web`: a static documentation site served by an unprivileged web server. Its sources and Dockerfile live in `src/web/`; the site builds from those documentation sources and the `server_images site-data` export of the loaders and the locks in `src/mc-server-images/<server>/locks/`, so it never hard-codes image data.

`.github/workflows/web.yml` publishes the documentation to GitHub Pages and packages it into `ghcr.io/hambn/minecraft-web` for self-hosting. `src/web/Dockerfile` must also support a documented local build and run without requiring GitHub Pages hosting.

The web workflow follows the same matrix convention:

1. `plan` uses a single-entry site matrix and snapshots the documentation inputs and server lock/publication metadata. Emit build targets for `pages` and `docker`.
2. `build` uses that target matrix to generate and check the documentation for both destinations. The Pages target produces a Pages deployment artifact. The Docker target uses `src/web/Dockerfile` to package equivalent documentation into an unprivileged web-server image and exports the tested image artifact.
3. `publish_pages` uses a single-entry `destination: [github-pages]` matrix, consumes the Pages artifact, and deploys through GitHub's Pages workflow integration. Use the `github-pages` environment and the required `pages: write` and `id-token: write` permissions.
4. `push_image` uses `registry: [ghcr]`, consumes the tested Docker artifact, and publishes the self-hostable web image. Keep its package-publishing permissions separate from the Pages deploy job.

Both destinations use the same documentation inputs and per-version catalog metadata. Handle GitHub Pages repository subpaths and self-hosted root paths correctly. Use the [GitHub Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) when implementing artifact upload and deployment. The web image uses `latest`; Minecraft-version tag rules apply to the server images.

- Overview of Fabric, NeoForge, Paper, and Pumpkin images, the three actively maintained releases, and pending builds.
- Contents per image and Minecraft version: server, loader where applicable, bundled mods or plugins, names, descriptions, authors, exact artifact versions, licenses, and source type. Include upstream, prebuilt, and source-built artifacts. Generate metadata and artifact details from each version's lock file.
- Per-version supported/selectable catalog with `MODS` or `PLUGINS` examples. Clearly identify bundled unsupported fallbacks and unavailable entries so players know which IDs can be enabled.
- Usage examples for running the images with Docker and Docker Compose, including image references, ports, selected mod/plugin lists, and the persistent `/data` volume.
- Configuration reference for environment variables, EULA acceptance where applicable, memory settings, server properties, and mod/plugin selection and dependency behavior.
- Explanation of startup behavior, files baked into `/opt/server`, writable world and configuration files in `/data`, and operation without runtime downloads.
- Tag and update documentation covering version tags, `latest`, digest pinning, the supported-version window, and rollback.
- Rebuilt when documentation or web sources change and after successful server image publication. Reflect the actually published server versions and distinguish pending builds from published images; never describe an unpublished planned image as available.

## Constraints to settle before building

- **Mojang game files.** The Minecraft EULA does not allow redistributing the game. The Fabric, NeoForge, and Paper images contain the vanilla server jar. Publishing them as public packages redistributes Mojang's server software. Pumpkin contains no Mojang code and is not affected. Options: keep those three packages private (needs a pull secret, and the `ghcr.hamdocker.ir` mirror must support authenticated pulls, which is unverified), or push them to a private registry the cluster can reach.
- **Mod and plugin licenses.** Bundling a mod or plugin in a public server image is redistribution. The resolver records upstream licenses from the provider and custom artifact licenses from their manifest entries. Artifacts under `All Rights Reserved` or similarly restrictive licenses are blocked unless an allowlist entry records the author's permission.

## Decisions

File formats, CLI commands, and module interfaces are pinned in [`contracts.md`](contracts.md).

- Mod and plugin lists: NeoForge starts from the `bn0-configs` list; Fabric and Paper use equivalent server-side sets; Pumpkin starts empty.
- Pumpkin "stable": build from the newest commit of the upstream default branch that passes the CI checks, tagged by the Minecraft version it supports. Its window is that one version. The Rust toolchain comes from the upstream `rust-version` (newest stable Rust if undeclared); the builder and runtime use the current Debian stable codename, falling back to oldstable while no Rust image exists for it.
- Automatic updates: the publish job commits validated locks and `status.json` directly to `main`, with no PR or approval. Each server writes only its own `<server>/locks/` directory and retries with `git pull --rebase`. Set the `LOCKS_PUSH_TOKEN` secret only if `main` is protected.
- Custom source-build artifacts: assets of the `custom-artifacts` GitHub Release, named by the build-input cache key.
- Unchanged targets (same `inputs_hash` as the committed lock) are not rebuilt or re-pushed, so tags only move when something changed.

## Open decisions

- Private vs public packages for the images that contain Mojang server software. The workflows push to GHCR either way; visibility is a package setting.

## Phases

1. Repository, README, and this plan. **Done.**
2. Settle the constraints and open decisions above. **Done**, except package visibility.
3. YAML manifests, resolver, custom artifact preparation, and lock files (Python with a YAML parser; the rest uses the standard library). **Written; first CI run pending.**
4. Server images, one at a time: Fabric, then NeoForge, then Paper, then Pumpkin. Include upstream, local, and source-built mods/plugins and CI checks. **Written; first CI run pending.**
5. Per-server `plan`, `build`, and `push_image` matrix workflows for Fabric, NeoForge, Paper, and Pumpkin. **Written.**
6. Server documentation, the `web.yml` matrix workflow, GitHub Pages deployment, and the self-hostable `minecraft-web` image. **Written.**
7. Switch `bn0-configs` (`kubernetes/apps/games/minecraft` and `pumpkin`) to these images with version-tag image policies.
