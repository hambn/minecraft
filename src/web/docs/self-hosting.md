# Self-hosting this site

This documentation is published to GitHub Pages and also as a container image, `ghcr.io/hambn/minecraft-web:latest`, that serves the same pages from an unprivileged web server.

## Run the published image

```sh
docker run -d --name mc-docs -p 8080:8080 ghcr.io/hambn/minecraft-web:latest
```

Open http://localhost:8080/. The site is served from the root path `/`. The container listens on port 8080 and runs as a non-root user. It needs no volumes and no network access.

## Build it locally

Run these from the repository root. The Dockerfile builds the site itself, using the lock files in `src/mc-server-images/<server>/locks`:

```sh
docker build -f src/web/Dockerfile -t minecraft-web:local .
docker run --rm -p 8080:8080 minecraft-web:local
```

The page content reflects the lock files in your checkout, so run `git pull` first for the latest published versions.

## Generate the files without Docker

The generator needs only Python 3.12 and the standard library:

```sh
python3 src/web/build.py --servers src/mc-server-images --out site --base-path /
python3 -m http.server 8080 --directory site
```

Use a different `--base-path`, such as `/minecraft/`, when you serve the site below a sub-path like GitHub Pages does.

## Docker Compose

```yaml
services:
  docs:
    image: ghcr.io/hambn/minecraft-web:latest
    ports:
      - "8080:8080"
    restart: unless-stopped
```

The image is rebuilt after documentation changes and after server images are published. Pull `latest` again to refresh it.
