# minecraft-web: the documentation site served by an unprivileged nginx on port 8080.
# Built from the repository root, because the site is generated from the server locks:
#
#   docker build -f src/web/Dockerfile -t minecraft-web:local .
#   docker run --rm -p 8080:8080 minecraft-web:local      # http://localhost:8080/

# 1. Export loaders, status and locks as the site's input (standard library only).
FROM python:3-slim AS data
WORKDIR /build
COPY .github/scripts/server_images/ .github/scripts/server_images/
COPY src/mc-server-images/ src/mc-server-images/
# Owner/name for image refs and links; CI passes --build-arg REPO=$GITHUB_REPOSITORY.
ARG REPO=hambn/minecraft
RUN PYTHONPATH=.github/scripts python -m server_images site-data --repo "$REPO" --out /site-data.json

# 2. Build the static site, served from "/".
FROM node:24-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /web
COPY src/web/package.json src/web/pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile
COPY src/web/ ./
COPY --from=data /site-data.json src/data/site-data.json
# Canonical public URL (the GitHub Pages site), so self-hosted copies point search engines there.
ARG SITE_URL=
ENV SITE_URL=$SITE_URL BASE_PATH=/
RUN pnpm build && test -s dist/index.html

# 3. Serve it.
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY src/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist/ /usr/share/nginx/html/
EXPOSE 8080
# The base image already runs as the unprivileged "nginx" user (UID 101).
USER 101
