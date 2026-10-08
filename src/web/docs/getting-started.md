# Getting started

Run a prebuilt Minecraft server image with one command. Mods and plugins are already inside the image and are switched on with an environment variable, so the container never downloads anything when it starts.

## Pick an image

| Image | Server | Selection variable |
| --- | --- | --- |
| `ghcr.io/hambn/minecraft-server-fabric` | Fabric | `MODS` |
| `ghcr.io/hambn/minecraft-server-neoforge` | NeoForge | `MODS` |
| `ghcr.io/hambn/minecraft-server-paper` | Paper | `PLUGINS` |
| `ghcr.io/hambn/minecraft-server-pumpkin` | Pumpkin | `PLUGINS` |

Every image has one tag per Minecraft release, for example `ghcr.io/hambn/minecraft-server-paper:26.2`. Only the tags listed on the overview and image pages are published. A release marked pending has no image yet. See [tags and updates](tags-and-updates.md).

## Run with Docker

```sh
docker run -d --name mc \
  -p 25565:25565 \
  -v mc-data:/data \
  -e EULA=TRUE \
  -e MEMORY=4G \
  ghcr.io/hambn/minecraft-server-paper:<version>
```

Replace `<version>` with a published Minecraft version tag.

- `-p 25565:25565` exposes the Minecraft port.
- `-v mc-data:/data` keeps the world, configuration and logs. Without a volume the world is lost when the container is removed.
- `-e EULA=TRUE` accepts the [Minecraft EULA](https://www.minecraft.net/en-us/eula). The Java servers (Fabric, NeoForge, Paper) refuse to start without it. Pumpkin does not use it.

The container runs as UID 1000. When you bind-mount a host directory instead of a named volume, make it writable by that user:

```sh
mkdir -p ./data && sudo chown 1000:1000 ./data
docker run -d -p 25565:25565 -v "$PWD/data:/data" -e EULA=TRUE ghcr.io/hambn/minecraft-server-paper:<version>
```

Follow the log and stop the server cleanly:

```sh
docker logs -f mc
docker stop -t 120 mc
```

The server saves the world on SIGTERM, so give it time to stop.

## Run with Docker Compose

```yaml
services:
  minecraft:
    image: ghcr.io/hambn/minecraft-server-fabric:<version>
    ports:
      - "25565:25565"
    environment:
      EULA: "TRUE"
      MEMORY: "4G"
      MODS: "lithium,ferrite-core"
      PROP_MOTD: "My server"
      PROP_VIEW_DISTANCE: "10"
    volumes:
      - mc-data:/data
    stop_grace_period: 2m
    restart: unless-stopped

volumes:
  mc-data:
```

## Enable mods or plugins

Everything bundled in an image is inactive until you select it. Fabric and NeoForge read `MODS`, Paper and Pumpkin read `PLUGINS`. Both take a comma-separated list of IDs:

```sh
docker run -d -p 25565:25565 -v mc-data:/data -e EULA=TRUE \
  -e MODS=lithium,ferrite-core \
  ghcr.io/hambn/minecraft-server-fabric:<version>
```

The IDs you can use for each image and Minecraft version are listed on that version's page, which is linked from the overview. See [mods and plugins](mods-and-plugins.md) for the rules.

## Next steps

- [Configuration](configuration.md) lists every environment variable.
- [Mods and plugins](mods-and-plugins.md) explains selection, dependencies and rejected entries.
- [Tags and updates](tags-and-updates.md) explains how to follow a version safely.
