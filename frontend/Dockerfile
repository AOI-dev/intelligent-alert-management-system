FROM nginx:1.27-alpine

COPY public /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# nginx:alpine auto-runs envsubst over everything in
# /etc/nginx/templates/*.template into /etc/nginx/conf.d/ at container
# start (docker-entrypoint.d/20-envsubst-on-templates.sh, built into the
# image since 1.19) -- PLATFORM_UPSTREAM below is what it substitutes.
ENV PLATFORM_UPSTREAM=monitoring-platform:8100
