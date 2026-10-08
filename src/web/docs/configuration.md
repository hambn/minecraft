# Configuration

All configuration is done with environment variables. The same variables work on every image unless noted.

## Variables

| Variable | Default | Applies to | Meaning |
| --- | --- | --- | --- |
| `EULA` | unset | Fabric, NeoForge, Paper | Must be `TRUE` to start. Setting it means you accept the Minecraft EULA. |
| `MEMORY` | `2G` | all | Heap size. Sets both `-Xms` and `-Xmx` unless `INIT_MEMORY` is set. |
| `INIT_MEMORY` | value of `MEMORY` | Java servers | Initial heap size (`-Xms`). |
| `JVM_OPTS` | empty | Java servers | Extra JVM flags, appended to the command line. |
| `PROP_<NAME>` | unset | all | Sets one `server.properties` key. |
| `MODS` | empty | Fabric, NeoForge | Comma-separated mod IDs to activate. |
| `PLUGINS` | empty | Paper, Pumpkin | Comma-separated plugin IDs to activate. |
| `ACTIVATE_ONLY` | unset | all | When `true`, activate the selection and exit with status 0 without starting the server. |

## Memory

```sh
-e MEMORY=6G                  # -Xms6G -Xmx6G
-e MEMORY=8G -e INIT_MEMORY=2G  # -Xms2G -Xmx8G
-e JVM_OPTS="-XX:+UseZGC -XX:+ZGenerational"
```

Leave headroom for the JVM itself: set the container memory limit a little above `MEMORY`.

## Server properties

`PROP_<NAME>` becomes the `server.properties` key `<name>` in lower case, with `_` replaced by `-`.

| Variable | Resulting key |
| --- | --- |
| `PROP_ONLINE_MODE=false` | `online-mode=false` |
| `PROP_MOTD=My server` | `motd=My server` |
| `PROP_MAX_PLAYERS=20` | `max-players=20` |
| `PROP_VIEW_DISTANCE=10` | `view-distance=10` |

Only the keys you set are changed on each start. Other lines in `server.properties` are left alone, and the file lives on the `/data` volume.

## Selecting mods and plugins

`MODS` and `PLUGINS` are described in [mods and plugins](mods-and-plugins.md). An empty or unset value activates nothing. `ACTIVATE_ONLY=true` is handy to test a selection quickly:

```sh
docker run --rm -v mc-data:/data -e EULA=TRUE -e MODS=lithium -e ACTIVATE_ONLY=true \
  {{image:fabric}}:<version>
```

The exit status is 0 when the selection is valid and non-zero with an error message otherwise.

## Pumpkin differences

Pumpkin is a Rust server and not a Java program, so these differ:

- There is no `EULA` requirement for the Pumpkin image, because it contains no Mojang server code.
- `MEMORY`, `INIT_MEMORY` and `JVM_OPTS` do not configure a heap. Limit memory with the container runtime instead.
- Plugins are WASM plugins selected with `PLUGINS`.
- Pumpkin builds from a single source commit, and each commit supports one Minecraft version. Only that version is published, and the other maintained releases show as pending.

## Ports and volumes

- Port `25565/tcp` is the Minecraft port.
- `/data` is the only writable location. It is declared as a volume and holds the world, `server.properties`, logs, and the managed mod or plugin directory.
