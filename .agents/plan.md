# Plan

Working plan for this repository. Update it as decisions are made; the README stays the user-facing summary.

## Goal

1. Four server images with everything baked in, so a container starts with no downloads.
2. One web image that serves everything a player needs to join: the client mods, the launcher, and the loader installers.
3. Automation that rebuilds the images when the base image, the loader, or a mod gets a stable update, and that moves `latest` to a new Minecraft version only when everything supports it.

## Server images

| Image | Server | Bundled extras |
| --- | --- | --- |
| `minecraft-server-fabric` | Fabric loader + vanilla server | Mods from `mods/fabric.yaml` |
| `minecraft-server-neoforge` | NeoForge + vanilla server | Mods from `mods/neoforge.yaml` |
| `minecraft-server-paper` | Paper (patched at build time) | Plugins from `plugins/paper.yaml` |
| `minecraft-server-pumpkin` | Pumpkin (Rust, built from source) | Plugins from `plugins/pumpkin.yaml` |

Registry: `ghcr.io/hambn/<image>`. The cluster pulls through the mirror `ghcr.hamdocker.ir/hambn/<image>`.

### Tags

- One tag per Minecraft version: `26.1`, `26.2`, `26.3`, ... Rebuilds for that version overwrite the same tag.
- `latest` points at the highest Minecraft version that passes the support check below.
- Consumers pin a version tag by digest (Flux `ImagePolicy` with `pattern: '^26\.3$'` and `digestReflectionPolicy: Always`). That gives "update within 26.3, never jump to 26.4 until I change the tag".
- Proposed addition (open decision): also push an immutable tag per build, for example `26.3-20261008.1`, so a bad rebuild can be rolled back by tag instead of by digest.

### Which Minecraft versions get built

For each image, walk Mojang's release versions (type `release`, no snapshots) from newest to oldest. A version is supported when all of these hold:

1. **Loader:** a stable build exists for it.
   - Fabric: a `stable: true` loader in Fabric meta, and the game version is listed as stable.
   - NeoForge: a non-`-beta` version in the NeoForged maven for that Minecraft version.
   - Paper: a build in the `STABLE` channel of the Paper Fill API.
   - Pumpkin: no stable releases exist (pre-1.0). It supports one protocol per commit. See open decisions.
2. **Mods/plugins:** every entry in the image's list has a `release` version on Modrinth for that game version and loader (or is marked optional, see open decisions). Required dependencies are resolved the same way.
3. **Base image:** the Java runtime satisfies `javaVersion.majorVersion` from the Mojang version manifest (for example Java 25 for `26.x`).

Build the newest supported version and up to 3 previous supported ones (configurable). `latest` = the newest. Tags for versions that fall out of the window stay in the registry, frozen.

### Lock files

The resolver writes what it chose into `locks/<image>/<minecraft-version>.json`: base image digest, loader version, server jar hash, and every mod/plugin with its Modrinth version ID, file URL, `sha512`, and license. Builds read only the lock file, so a build is reproducible, and every update is a visible Git diff.

### Build

- Base: `eclipse-temurin:<java>-jre` (pinned by digest in the lock), non-root UID `1000`.
- Fabric: `fabric-installer server -mcversion <v> -loader <l> -downloadMinecraft` at build time.
- NeoForge: `neoforge-<v>-installer.jar --install-server` at build time.
- Paper: `java -Dpaperclip.patchonly=true -jar paper.jar` at build time, so the patched jar is in the image.
- Pumpkin: multi-stage Rust build; plugins compiled to `wasm32-wasip2` in a builder stage.
- Mods and plugins: downloaded at build time and verified against the lock's `sha512`.
- Server files live in `/opt/server` (read-only image layer). The world and runtime config go to the `/data` volume. A small entrypoint links or copies what the server expects into `/data` on start and handles `EULA`, memory, and `server.properties` settings from environment variables.

### CI checks before push

- Start the image with `--network none` and wait for the server's ready line. This fails the build if anything tries to download at runtime.
- Ping the server with a status query, then stop it cleanly.
- Push the version tag, and `latest` if this is the newest supported version.

## Update automation (GitHub Actions)

1. `resolve` (scheduled, for example every 6 hours, plus manual trigger): query Mojang, the loader APIs, Modrinth, and the base image digest; regenerate the lock files; open a PR (or commit to `main`, open decision) when something changed.
2. `build` (on lock file changes in `main`): build only the changed `<image>/<version>` pairs, run the CI checks, push.

This covers the three update cases:

- New base image digest that still satisfies the Java requirement → rebuild all versions of that image.
- New stable mod/plugin version for a game version → rebuild that version.
- New Minecraft version that the loader, every mod, and the base image support → new tag, and `latest` moves.

## Web image

`minecraft-web`: a static site served by an unprivileged web server, built from the same lock files.

- Landing page: simple and clean, one section per server type, showing the server address and what to download.
- Downloads, all served from inside the image (no external links):
  - Client-side mods per loader and Minecraft version (current + 3 previous), each listed separately and as one zip.
  - Launcher: Prism Launcher (GPL-3.0), latest stable, for Windows, macOS, and Linux.
  - Loader installers: Fabric, NeoForge, and Forge, for the current + 3 previous versions.
  - A ready Prism instance export per server (loader + mods preconfigured) so a player imports one file.
- Rebuilt whenever a server lock changes, so the page always matches the servers.

## Constraints to settle before building

- **Mojang game files.** The Minecraft EULA does not allow redistributing the game. The Fabric, NeoForge, and Paper images contain the vanilla server jar. Publishing them as public packages redistributes Mojang's server software. Pumpkin contains no Mojang code and is not affected. Options: keep those three packages private (needs a pull secret, and the `ghcr.hamdocker.ir` mirror must support authenticated pulls, which is unverified), or push them to a private registry the cluster can reach.
- **Client game files.** Serving the Minecraft client jar, libraries, and assets from the web page publicly redistributes the game itself. This is out of scope. The page serves the launcher, loader installers, mods, and instance files. The launcher fetches the game files from Mojang the first time each version is used.
- **Mod licenses.** Bundling a mod in a public image or serving it from the page is redistribution. The resolver records each mod's license from Modrinth. Mods under `All Rights Reserved` or similar licenses (for example, Sodium's Polyform Shield) are blocked unless an allowlist entry records the author's permission.

## Open decisions

- Mod and plugin lists per image (start from the NeoForge list in `bn0-configs`).
- Does one unsupported optional mod block a Minecraft version, or is it dropped from that version's image? Proposed: each entry is `required: true` (blocks) or `required: false` (dropped and noted in the lock).
- Pumpkin "stable": build from tagged releases only (none exist yet), or from `master` commits that pass the CI checks, tagged by the protocol version they support.
- Immutable per-build tags in addition to the version tags.
- `resolve` opens PRs (reviewed) or commits directly to `main` (fully automatic).
- Private vs public packages for the images that contain Mojang server software.
- Forge appears on the download page but has no server image. Add `minecraft-server-forge`, or keep Forge client-only?

## Phases

1. Repository, README, and this plan. **Done.**
2. Settle the constraints and open decisions above.
3. Resolver and lock files (Python, standard library only).
4. Server images, one at a time: Fabric, then NeoForge, then Paper, then Pumpkin. CI checks included.
5. `resolve` and `build` workflows.
6. `minecraft-web` image.
7. Switch `bn0-configs` (`kubernetes/apps/games/minecraft` and `pumpkin`) to these images with version-tag image policies.
