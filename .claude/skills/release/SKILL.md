---
name: release
description: 'Prepare a release: changelog, version, verification and local tag.'
---

# Release

1. Update `CHANGELOG.md` (Keep a Changelog) and the version in `pyproject.toml` / `web/package.json`.
2. Run `make verify-clean`; fix anything it reports.
3. Check authorship: `git log --format='%an <%ae> | %cn <%ce>' | sort -u` lists only project maintainers.
4. Create a local annotated tag `git tag -a vX.Y.Z -m "vX.Y.Z"`. Never push tags or publish packages without maintainer approval.
5. `release.yml` builds images to GHCR when a maintainer pushes the tag.
