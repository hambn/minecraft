---
title: "Tags and updates"
description: "How the Minecraft version tags, the auto-updated version window and latest work, and how to pin digests or follow rebuilds with Flux."
order: 5
---

## Version tags

Each image has one tag per exact Minecraft release, patch releases included, for example `{{window:paper}}` for Paper. A tag is rebuilt in place when its components update, such as the base image, the loader or a bundled mod, so the digest behind a tag changes over time while the Minecraft version does not.

There are no timestamp, build, loader or mod-version tags.

## The three-version window

Each image maintains the three newest stable Minecraft releases (no snapshots or pre-releases) that it actually has a stable server build for. The window is per server, not shared: for example Paper currently maintains `{{window:paper}}`, NeoForge `{{window:neoforge}}`, Fabric `{{window:fabric}}` and Pumpkin `{{window:pumpkin}}`. Pumpkin supports only one Minecraft version at a time, so its window is short.

- **Published.** The tag exists and is rebuilt when its inputs change.
- **Pending.** A newer Minecraft release this server has no stable build for yet; not pullable. These are listed as upcoming on the image page, and the tag appears once a stable server build exists.
- **Dropped.** When a release leaves a server's window, it disappears from this site and from the repository. Its tag stays in the registry but is never rebuilt.

The overview and image pages show the state of every tag, taken from the published status data.

## latest

`latest` points at the newest release in that image's window that built successfully and passed the server checks (boot, status ping, clean stop). It moves to a new Minecraft version when one becomes available, which can change your world version. For a running server, use a version tag instead.

## Pin a version, follow the rebuilds

Use `{{image:paper}}:{{latest:paper}}` to stay on Minecraft {{latest:paper}} and receive rebuilds. You never jump to a newer Minecraft release until you change the tag.

To control exactly when the image changes, pin the digest as well:

```sh
docker pull {{image:paper}}:{{latest:paper}}@sha256:<digest>
```

Digests are shown on the image pages. With a digest the reference is immutable, and you update it deliberately.

## Flux example

Flux image automation can follow the digest of a fixed tag. This policy keeps a deployment on `{{latest:paper}}` and updates whenever the tag is rebuilt:

```yaml
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageRepository
metadata:
  name: minecraft-paper
  namespace: flux-system
spec:
  image: {{image:paper}}
  interval: 30m
---
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImagePolicy
metadata:
  name: minecraft-paper
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: minecraft-paper
  filterTags:
    pattern: '^{{latestregex:paper}}$'
  policy:
    alphabetical:
      order: asc
  digestReflectionPolicy: Always
```

Reference the result in a manifest with an image setter marker, for example `image: {{image:paper}}:{{latest:paper}}@sha256:<digest> # {"$imagepolicy": "flux-system:minecraft-paper"}`. Check the `digestReflectionPolicy` field against your Flux version.

## Tags that left the window

When a release leaves a server's window, its lock file is deleted and it is no longer listed here. The registry tag remains pullable, but it receives no security or mod updates. Plan a move to a newer release, and back up `/data` first, because worlds cannot be downgraded.

## Rollback

Tags are overwritten on rebuild, so record the digest of a version you know works, for example from `docker image inspect` or your Flux status. To roll back, deploy the old `tag@sha256:<digest>` reference. This only works while the registry still keeps that digest, so make sure your registry or mirror retention does not delete it. Rolling back the image does not roll back world data, so keep a backup of `/data`.
