---
name: release
description: 'Prepare a release: changelog, version, verification and local tag.'
---

# Release

1. Update `CHANGELOG.md` (Keep a Changelog) and the version in `pyproject.toml` / `web/package.json`.
2. Run `make verify-clean`; record results in `docs/verification.md`.
3. Check authorship: `git log --format='%an <%ae> | %cn <%ce>' | sort -u` lists only the maintainer.
4. Create a local annotated tag `git tag -a vX.Y.Z -m "vX.Y.Z"`. Never push tags or publish packages without the maintainer.
5. `release.yml` builds images to GHCR when the maintainer pushes the tag.
