---
title: "Self-hosting this site"
description: "Run this documentation site yourself from the minecraft-web container image, build it locally, or generate it without Docker."
order: 7
---

This documentation is published to GitHub Pages and also as a container image, `ghcr.io/{{owner}}/minecraft-web:latest`, that serves the same pages from an unprivileged web server.

## Run the published image

```sh
docker run -d --name mc-docs -p 8080:8080 ghcr.io/{{owner}}/minecraft-web:latest
```

Open http://localhost:8080/. The site is served from the root path `/`. The container listens on port 8080 and runs as a non-root user. It needs no volumes and no network access.

## Build it locally

Run these from the repository root. The Dockerfile builds the site itself, using the lock files in `src/mc-server-images/<server>/locks`:

```sh
docker build -f src/web/Dockerfile -t minecraft-web:local .
docker run --rm -p 8080:8080 minecraft-web:local
```

The page content reflects the lock files in your checkout, so run `git pull` first for the latest published versions.

## Build it without Docker

The site is an [Astro](https://astro.build) project in `src/web`. It needs Python 3, Node.js 22 or newer and pnpm. `pnpm site-data` exports the lock files as the site's input, and `pnpm build` writes static files to `src/web/dist`:

```sh
cd src/web
pnpm install
pnpm site-data
BASE_PATH=/ pnpm build
pnpm preview
```

Set `BASE_PATH`, such as `/minecraft/`, when you serve the site below a sub-path like GitHub Pages does. `SITE_URL` sets the public address used for canonical links and the sitemap. `pnpm dev` starts a live-reloading development server.

## Docker Compose

```yaml
services:
  docs:
    image: ghcr.io/{{owner}}/minecraft-web:latest
    ports:
      - "8080:8080"
    restart: unless-stopped
```

The image is rebuilt after documentation changes and after server images are published. Pull `latest` again to refresh it.
