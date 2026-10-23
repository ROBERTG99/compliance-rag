# Static SPA: node build stage, non-root nginx runtime.
FROM node:26.11.1-slim@sha256:193fe51b64e77981119c98c2002c9e32a70e2f006fb4d25068ce0558998917f0 AS build
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

FROM nginx:1.30.6-alpine@sha256:970364228b1e4f932abc22d321932816782cca8a20b85a77552a7cfe9acfb3b5
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
