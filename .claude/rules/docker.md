---
paths: ["docker/**", "compose*.yaml", ".devcontainer/**"]
---
# Docker

- Host ports 8600–8699 only (see BUILD.md §6). Every service has a healthcheck; dependants use `condition: service_healthy`.
- Images pinned by tag; no `apt-get`; non-root users; `ARG HTTPS_PROXY` in every stage that downloads packages; build with `network: host`.
- Containers stay offline at runtime.
