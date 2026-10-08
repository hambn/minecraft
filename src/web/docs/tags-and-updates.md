# Tags and updates

## Version tags

Each image has one tag per exact Minecraft release, patch releases included, for example `26.3`, `26.2` or `26.1.2`. A tag is rebuilt in place when its components update, such as the base image, the loader or a bundled mod, so the digest behind a tag changes over time while the Minecraft version does not.

There are no timestamp, build, loader or mod-version tags.

## The three-version window

Only the three newest stable Minecraft releases (no snapshots or pre-releases) are maintained. The window is shared by all four images.

- **Published.** The tag exists and is rebuilt when its inputs change.
- **Pending.** The release is in the window but no stable server build exists yet, so there is nothing to pull. Pumpkin often has only one buildable version.
- **Frozen.** The release left the window. The tag stays in the registry but is never rebuilt.

The overview and image pages show the state of every tag, taken from the published status data.

## latest

`latest` points at the newest release in the window that built successfully and passed the server checks (boot, status ping, clean stop). It moves to a new Minecraft version when one becomes available, which can change your world version. For a running server, use a version tag instead.

## Pin a version, follow the rebuilds

Use `ghcr.io/hambn/minecraft-server-paper:26.3` to stay on Minecraft 26.3 and receive rebuilds. You never jump to 26.4 until you change the tag.

To control exactly when the image changes, pin the digest as well:

```sh
docker pull ghcr.io/hambn/minecraft-server-paper:26.3@sha256:<digest>
```

Digests are shown on the image pages. With a digest the reference is immutable, and you update it deliberately.

## Flux example

Flux image automation can follow the digest of a fixed tag. This policy keeps a deployment on `26.3` and updates whenever the tag is rebuilt:

```yaml
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageRepository
metadata:
  name: minecraft-paper
  namespace: flux-system
spec:
  image: ghcr.io/hambn/minecraft-server-paper
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
    pattern: '^26\.3$'
  policy:
    alphabetical:
      order: asc
  digestReflectionPolicy: Always
```

Reference the result in a manifest with an image setter marker, for example `image: ghcr.io/hambn/minecraft-server-paper:26.3@sha256:<digest> # {"$imagepolicy": "flux-system:minecraft-paper"}`. Check the `digestReflectionPolicy` field against your Flux version.

## Frozen tags

When a release leaves the window, its tag is frozen. It remains pullable, but it receives no security or mod updates. Plan a move to a newer release, and back up `/data` first, because worlds cannot be downgraded.

## Rollback

Tags are overwritten on rebuild, so record the digest of a version you know works, for example from `docker image inspect` or your Flux status. To roll back, deploy the old `tag@sha256:<digest>` reference. This only works while the registry still keeps that digest, so make sure your registry or mirror retention does not delete it. Rolling back the image does not roll back world data, so keep a backup of `/data`.
