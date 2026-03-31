# Release Process

## Versioning

- This project uses Semantic Versioning (`MAJOR.MINOR.PATCH`).
- Pre-release tags are allowed (`a`, `b`, `rc`, `dev`).
- Package version is defined in `openlmlib/__init__.py` and `pyproject.toml`.

## Update Checklist

1. Update version in `openlmlib/__init__.py` and `pyproject.toml`.
2. Add release notes to `CHANGELOG.md` under a new version heading.
3. Run tests locally:
   - `python -m unittest discover -s tests -v`
4. Commit and push to default branch.

## Tag and Publish

1. Create a tag in format `vX.Y.Z` (or `vX.Y.Zrc1` for prerelease).
2. Push tag:
   - `git tag vX.Y.Z`
   - `git push origin vX.Y.Z`
3. GitHub Actions `release.yml` builds artifacts and publishes:
   - Always publishes tagged builds to TestPyPI.
   - Publishes stable tags to PyPI.

## Trusted Publishing Setup

Configure trusted publishers in both registries:

- TestPyPI project: trust this repository/workflow for OIDC publishing
- PyPI project: trust this repository/workflow for OIDC publishing

Workflow file: `.github/workflows/release.yml`
