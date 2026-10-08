---
title: "Mods and plugins"
description: "How the baked-in mod and plugin catalog works: selecting IDs with MODS or PLUGINS, automatic dependencies, unsupported fallbacks and managed files."
order: 4
---

Each image carries a catalog of mods (Fabric, NeoForge) or plugins (Paper, Pumpkin). The catalog is baked in and inactive. You decide what runs with `MODS` or `PLUGINS`.

## Selecting entries

Set the variable to a comma-separated list of IDs:

```sh
-e MODS=lithium,ferrite-core        # Fabric, NeoForge
-e PLUGINS=luckperms,essentialsx    # Paper, Pumpkin
```

The valid IDs for an image and Minecraft version appear on its page in the Selectable table. IDs are specific to the version, since not every project supports every release. An empty or unset variable activates nothing.

## What happens at startup

Before the server launches, the entrypoint checks your selection against the catalog inside the image:

1. Every ID must exist and be selectable.
2. Required dependencies are added automatically. You do not list them. They show as dependency-only entries on the version page.
3. Conflicting selections and duplicate artifacts are rejected.
4. The needed files are copied from `/opt/catalog/files` into `/data/mods` or `/data/plugins`.

Then the server starts. If any check fails, the container prints an error naming the entry and exits before the server starts.

## Unsupported fallbacks and unavailable entries

- **Unsupported fallback.** When no release of a project supports the image's Minecraft version, the newest stable release for the same loader may still be kept for reference. It is not compatible. Selecting one is an error that names the entry, the image's Minecraft and loader versions, the versions the entry supports, and the reason. There is no override.
- **Unavailable.** The entry is not in the image at all, for example because its license does not allow redistribution or no stable release exists. The version page gives the reason.

## Managed files

The entrypoint records what it copied in a `.catalog-managed` file inside `/data/mods` or `/data/plugins`.

- On every start it removes the files listed there, then copies the current selection. Removing an ID from the variable removes its files on the next start, and new image versions replace old artifacts.
- Files you add yourself are never touched. Only files named in the managed list are removed.
- Mods or plugins you download yourself work by placing them in the same directory. The image does not manage them.

## No runtime downloads

Everything is verified at build time against a lock file with sha512 checksums. At runtime nothing is downloaded or compiled, so a container starts with no network access, and the same image tag with the same digest always contains the same files.

The per-version pages show the source, exact version, license and authors of each entry, generated from the lock files.
