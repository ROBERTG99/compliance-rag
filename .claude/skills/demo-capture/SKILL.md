---
name: demo-capture
description: 'Capture screenshots and the demo video of the running stack with Playwright.'
---

# Demo capture

1. `make up` (stack healthy and seeded).
2. `pnpm -C web exec playwright test --project=screenshots` writes `docs/images/<screen>-<theme>.png` for every screen in light and dark.
3. The demo spec records `docs/images/demo.webm` following the main user journey (ask, stream, open evidence, thumbs up).
4. Use Chromium from `/opt/pw-browsers` in the cloud (never `playwright install`).
5. Commit the images; reference them from `README.md`.
