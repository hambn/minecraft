---
title: "Docker Compose"
description: "Run the Minecraft server images with Docker Compose, with a complete compose.yaml, mods and plugins, memory limits, several servers side by side, updates and backups."
order: 2
---

Docker Compose keeps the whole server definition (image tag, ports, settings and storage) in one `compose.yaml` that you can commit and reuse. Every example below works with any of the images; change the image and the selection variable to match your server.

## A complete compose.yaml

```yaml
services:
  minecraft:
    image: {{image:paper}}:{{latest:paper}}
    ports:
      - "25565:25565"
    environment:
      EULA: "TRUE"            # accepts the Minecraft EULA (Java servers only)
      MEMORY: "4G"            # heap size, -Xms and -Xmx
      PLUGINS: "luckperms,essentialsx"
      PROP_MOTD: "My server"  # any server.properties key, see Configuration
      PROP_MAX_PLAYERS: "20"
    volumes:
      - minecraft-data:/data
    stop_grace_period: 2m     # time to save the world on shutdown
    restart: unless-stopped

volumes:
  minecraft-data:
```

Start it, follow the log, and stop it:

```sh
docker compose up -d
docker compose logs -f minecraft
docker compose down
```

`docker compose down` sends SIGTERM and waits up to `stop_grace_period` while the server saves the world. The named volume `minecraft-data` survives `down`. Only `docker compose down -v` deletes it.

## Choose the image and tag

{{images-table}}

Use an exact Minecraft version tag rather than `latest`. A version tag gets every automatic rebuild for that release (loader, base image and mod updates) but never moves your world to a newer Minecraft version. The image pages list the versions each image maintains.

## Enable mods or plugins

Everything in the image's catalog is inactive until you list its ID. The valid IDs for each version are on that version's page.

```yaml
services:
  minecraft:
    image: {{image:fabric}}:{{latest:fabric}}
    environment:
      EULA: "TRUE"
      MEMORY: "6G"
      MODS: "lithium,ferrite-core,spark"
```

Required dependencies are added automatically. If an ID is unknown or unsupported, the container prints an error and exits before the server starts. Check the result with `docker compose logs minecraft`.

## Keep settings in an env file

Move the settings out of `compose.yaml` into a `.env`-style file that you can keep out of version control:

```sh
# minecraft.env
EULA=TRUE
MEMORY=4G
PLUGINS=luckperms,essentialsx,worldedit
PROP_MOTD=My server
PROP_ONLINE_MODE=true
```

```yaml
services:
  minecraft:
    image: {{image:paper}}:{{latest:paper}}
    env_file: minecraft.env
    ports:
      - "25565:25565"
    volumes:
      - minecraft-data:/data
    stop_grace_period: 2m
    restart: unless-stopped

volumes:
  minecraft-data:
```

## Limit memory and CPU

`MEMORY` sets the Java heap. Give the container a limit a little above it, so the JVM has room for its own memory:

```yaml
services:
  minecraft:
    image: {{image:paper}}:{{latest:paper}}
    environment:
      EULA: "TRUE"
      MEMORY: "4G"
    deploy:
      resources:
        limits:
          memory: 5G
          cpus: "2"
```

Pumpkin is a native binary, so `MEMORY` does not apply to it. Use the container limit alone.

## Use a host directory instead of a volume

The containers run as UID and GID 1000. Make a bind-mounted directory writable by that user first:

```sh
mkdir -p ./data && sudo chown 1000:1000 ./data
```

```yaml
services:
  minecraft:
    image: {{image:paper}}:{{latest:paper}}
    volumes:
      - ./data:/data
```

The world, `server.properties`, logs and the `mods` or `plugins` directory then live in `./data` on the host.

## Run several servers

Give every server its own host port and its own volume:

```yaml
services:
  survival:
    image: {{image:paper}}:{{latest:paper}}
    ports:
      - "25565:25565"
    environment:
      EULA: "TRUE"
      PLUGINS: "luckperms,coreprotect"
    volumes:
      - survival-data:/data
    stop_grace_period: 2m
    restart: unless-stopped

  modded:
    image: {{image:fabric}}:{{latest:fabric}}
    ports:
      - "25566:25565"
    environment:
      EULA: "TRUE"
      MEMORY: "6G"
      MODS: "lithium,ferrite-core"
    volumes:
      - modded-data:/data
    stop_grace_period: 2m
    restart: unless-stopped

volumes:
  survival-data:
  modded-data:
```

Players join the second server at `your-host:25566`.

## Use the server console

The Java servers read console commands from standard input. Keep it open, then attach:

```yaml
services:
  minecraft:
    stdin_open: true
    tty: true
```

```sh
docker attach "$(docker compose ps -q minecraft)"
```

Type commands such as `say hello` or `op <player>`. Detach with `Ctrl-P` followed by `Ctrl-Q`. `Ctrl-C` would stop the server.

## Update

Images are rebuilt automatically whenever a component of a maintained version changes. To get the newest build of your tag:

```sh
docker compose pull
docker compose up -d
```

To control exactly when the server changes, pin the digest as well, for example `{{image:paper}}:{{latest:paper}}@sha256:<digest>`. Each version page shows its current digest. To move to a newer Minecraft release, back up `/data` first, because a world cannot be downgraded. Then change the tag. See [tags and updates](tags-and-updates.md).

## Back up the world

Stop the server so the world is saved and consistent, archive the volume, and start it again:

```sh
docker compose stop minecraft
docker run --rm --volumes-from "$(docker compose ps -aq minecraft)" \
  -v "$PWD:/backup" alpine \
  tar czf "/backup/minecraft-$(date +%F).tar.gz" -C /data .
docker compose start minecraft
```

To restore, extract the archive into an empty volume or directory with the same command, using `tar xzf` instead of `tar czf`.
