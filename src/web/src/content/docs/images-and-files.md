---
title: "Image layout"
description: "What is inside each Minecraft server image: directories, the /data volume, startup steps, OCI labels and how to inspect the bundled catalog."
order: 6
---

What is inside the images and what happens when a container starts.

## Directories

| Path | Contents | Writable |
| --- | --- | --- |
| `/opt/server` | Server files: the vanilla server, loader or patched Paper jar, or the Pumpkin binary. | no |
| `/opt/catalog` | The mod or plugin catalog: `files/`, `catalog.tsv`, `catalog.json`, `lock.json`. | no |
| `/opt/scripts` | `entrypoint.sh` and shared shell helpers. | no |
| `/data` | World, `server.properties`, logs, and the `mods` or `plugins` directory. Declared as a volume and used as the working directory. | yes |

The container runs as UID and GID 1000 and exposes port 25565. The catalog lives outside any directory the server scans, which is why nothing in it is loaded until it is activated.

## Startup behaviour

1. Check `EULA` (Java servers).
2. Apply `PROP_*` variables to `/data/server.properties`.
3. Resolve `MODS` or `PLUGINS` against `/opt/catalog/catalog.tsv`, add dependencies, and refuse the start on any problem.
4. Remove files previously activated by the entrypoint and copy the current selection into `/data/mods` or `/data/plugins`.
5. Build the JVM memory arguments from `MEMORY`, `INIT_MEMORY` and `JVM_OPTS` (Java servers).
6. Replace the shell with the server process using `exec`, so `docker stop` delivers SIGTERM to the server, which saves the world and exits.

With `ACTIVATE_ONLY=true` the process ends after step 4 with exit status 0.

## Network and downloads

Nothing is fetched during startup. The Minecraft server, loader and every mod or plugin were downloaded and checked when the image was built. A container can run with `--network none`, apart from players being unable to connect.

## Image labels

Images carry OCI labels, including `org.opencontainers.image.source`, `org.opencontainers.image.version` (the Minecraft version), `io.github.hambn.minecraft.server`, `io.github.hambn.minecraft.catalog-env` and `io.github.hambn.minecraft.catalog-dir`. Inspect them with:

```sh
docker inspect --format '{{json .Config.Labels}}' {{image:paper}}:<version>
```

To see the exact catalog inside an image:

```sh
docker run --rm --entrypoint cat {{image:paper}}:<version> /opt/catalog/catalog.tsv
```
