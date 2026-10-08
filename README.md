# minecraft

Prebuilt Minecraft server images and a player download page. Every image ships with the server, the loader, and its mods already inside, so a container starts with no downloads.

> Status: planning. Nothing is built yet. See [`.agents/plan.md`](.agents/plan.md).

## Server images

| Image | Server |
| --- | --- |
| `ghcr.io/hambn/minecraft-server-fabric` | Fabric |
| `ghcr.io/hambn/minecraft-server-neoforge` | NeoForge |
| `ghcr.io/hambn/minecraft-server-paper` | Paper |
| `ghcr.io/hambn/minecraft-server-pumpkin` | Pumpkin |

### Tags

- `26.1`, `26.2`, `26.3`, ...: one tag per Minecraft version. Updates to the base image, the loader, or the mods are pushed to the same tag.
- `latest`: the newest Minecraft version that the loader, every bundled mod, and the base image support with stable releases.

Pin a version tag (for example `26.3`) to get updates within that Minecraft version without moving to the next one.

## Download page

`ghcr.io/hambn/minecraft-web` serves the client mods for each server, the launcher, and the loader installers from inside the image.
