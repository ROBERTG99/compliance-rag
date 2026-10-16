# Static SPA: node build stage, non-root nginx runtime (BUILD.md §16).
FROM node:22-slim AS build
ARG HTTPS_PROXY
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH CI=1
RUN npm install -g pnpm@10.28.0 --no-fund --no-audit
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY web/ ./
RUN pnpm exec vite build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /web/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD wget -qO- http://127.0.0.1:8080/nginx-health >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]
