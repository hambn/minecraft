---
title: "Getting started"
description: "Run a Minecraft server in Docker in one command with the prebuilt server images, and switch on the bundled mods and plugins with one environment variable."
order: 1
---

Run a prebuilt Minecraft server image with one command. Mods and plugins are already inside the image and are switched on with an environment variable, so the container never downloads anything when it starts.

## Pick an image

Each server has its own image. {{servers}} are available:

{{images-table}}

Every image has one tag per Minecraft release, for example `{{image:paper}}:{{latest:paper}}`. Only the tags listed on the overview and image pages are published. A release marked pending is a newer Minecraft release that server has no stable build for yet, so there is no image to pull. See [tags and updates](tags-and-updates.md).

## Run with Docker

```sh
docker run -d --name mc \
  -p 25565:25565 \
  -v mc-data:/data \
  -e EULA=TRUE \
  -e MEMORY=4G \
  {{image:paper}}:<version>
```

Replace `<version>` with a published Minecraft version tag, for example `{{latest:paper}}`. The versions differ per image; each image page lists its own.

- `-p 25565:25565` exposes the Minecraft port.
- `-v mc-data:/data` keeps the world, configuration and logs. Without a volume the world is lost when the container is removed.
- `-e EULA=TRUE` accepts the [Minecraft EULA](https://www.minecraft.net/en-us/eula). The Java servers (Fabric, NeoForge, Paper) refuse to start without it. Pumpkin does not use it.

The container runs as UID 1000. When you bind-mount a host directory instead of a named volume, make it writable by that user:

```sh
mkdir -p ./data && sudo chown 1000:1000 ./data
docker run -d -p 25565:25565 -v "$PWD/data:/data" -e EULA=TRUE {{image:paper}}:<version>
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
    image: {{image:paper}}:{{latest:paper}}
    ports:
      - "25565:25565"
    environment:
      EULA: "TRUE"
      MEMORY: "4G"
    volumes:
      - minecraft-data:/data
    stop_grace_period: 2m
    restart: unless-stopped

volumes:
  minecraft-data:
```

Save it as `compose.yaml` and run `docker compose up -d`. The [Docker Compose guide](docker-compose.md) covers mods, memory limits, several servers, updates and backups.

## Enable mods or plugins

Everything bundled in an image is inactive until you select it. Fabric and NeoForge read `MODS`, Paper and Pumpkin read `PLUGINS`. Both take a comma-separated list of IDs:

```sh
docker run -d -p 25565:25565 -v mc-data:/data -e EULA=TRUE \
  -e MODS=lithium,ferrite-core \
  {{image:fabric}}:<version>
```

The IDs you can use for each image and Minecraft version are listed on that version's page, which is linked from the overview. See [mods and plugins](mods-and-plugins.md) for the rules.

## Next steps

- [Configuration](configuration.md) lists every environment variable.
- [Mods and plugins](mods-and-plugins.md) explains selection, dependencies and rejected entries.
- [Tags and updates](tags-and-updates.md) explains how to follow a version safely.
