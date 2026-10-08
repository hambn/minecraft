# minecraft-web: the documentation site served by an unprivileged nginx on port 8080.
# The site is generated here with base path "/", so the build context is the repository root.
#
#   docker build -f src/web/Dockerfile -t minecraft-web:local .
#   docker run --rm -p 8080:8080 minecraft-web:local      # http://localhost:8080/

FROM python:3.12.11-slim-bookworm AS builder
# build.py and markdown_lite.py use only the standard library; no pip install needed.
WORKDIR /build
COPY src/web/ ./web/
COPY src/mc-server-images/fabric/locks/ ./servers/fabric/locks/
COPY src/mc-server-images/neoforge/locks/ ./servers/neoforge/locks/
COPY src/mc-server-images/paper/locks/ ./servers/paper/locks/
COPY src/mc-server-images/pumpkin/locks/ ./servers/pumpkin/locks/
RUN python web/build.py --servers servers --out /site --base-path / \
    && test -s /site/index.html

FROM nginxinc/nginx-unprivileged:1.29-alpine
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
