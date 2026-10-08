# minecraft-web: the documentation site served by an unprivileged nginx on port 8080.
# The site is generated here with base path "/", so the build context is the repository root.
#
#   docker build -f src/web/Dockerfile -t minecraft-web:local .
#   docker run --rm -p 8080:8080 minecraft-web:local      # http://localhost:8080/

FROM python:3-slim AS builder
# The generator uses only the standard library; no pip install needed.
# The repository layout is kept so its default paths resolve.
WORKDIR /build
COPY .github/scripts/website/ .github/scripts/website/
COPY src/web/ src/web/
# Every server dir is copied; the generator only reads <server>/locks/*.json.
COPY src/mc-server-images/ src/mc-server-images/
# Owner/name for image refs and links; CI passes --build-arg REPO=$GITHUB_REPOSITORY.
ARG REPO=hambn/minecraft
RUN PYTHONPATH=.github/scripts python -m website --out /site --base-path / --repo "$REPO" \
    && test -s /site/index.html

FROM nginxinc/nginx-unprivileged:stable-alpine
# Replace the default server block: static files, 404 page, caching.
RUN printf '%s\n' \
    'server {' \
    '    listen 8080;' \
    '    server_name _;' \
    '    root /usr/share/nginx/html;' \
    '    index index.html;' \
    '    absolute_redirect off;' \
    '    server_tokens off;' \
    '    error_page 404 /404.html;' \
    '    add_header X-Content-Type-Options nosniff always;' \
    '    add_header Referrer-Policy no-referrer always;' \
    '    location / {' \
    '        try_files $uri $uri/ =404;' \
    '        add_header Cache-Control "no-cache" always;' \
    '        add_header X-Content-Type-Options nosniff always;' \
    '        add_header Referrer-Policy no-referrer always;' \
    '    }' \
    '    location /static/ {' \
    '        add_header Cache-Control "public, max-age=31536000, immutable" always;' \
    '        add_header X-Content-Type-Options nosniff always;' \
    '        add_header Referrer-Policy no-referrer always;' \
    '    }' \
    '}' > /etc/nginx/conf.d/default.conf
COPY --from=builder /site/ /usr/share/nginx/html/
EXPOSE 8080
# The base image already runs as the unprivileged "nginx" user (UID 101).
USER 101
