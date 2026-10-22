# Static SPA: node build stage, non-root nginx runtime.
FROM node:22.23.3-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS build
ARG HTTPS_PROXY
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH CI=1
RUN npm install -g pnpm@10.28.0 --no-fund --no-audit
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY web/ ./
# the dev persona switcher is compiled in only when asked for (compose sets 1 for the local stack)
ARG VITE_DEV_PERSONAS=0
ENV VITE_DEV_PERSONAS=$VITE_DEV_PERSONAS
RUN pnpm exec vite build

FROM nginx:1.31.0-alpine@sha256:2f07d83bf561b506400dc183b1b2003803e39efbd22451f848adaba14d28c7c7
# the SPA needs none of the dynamic modules: dropping them removes 38 packages (gd, fontconfig, libexpat,
# libxml2, ...) and their CVEs; works offline (no package index needed)
RUN apk del --no-network nginx-module-acme nginx-module-geoip nginx-module-image-filter nginx-module-njs \
      nginx-module-xslt
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /web/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD wget -qO- http://127.0.0.1:8080/nginx-health >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]
