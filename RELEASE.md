# Release Process

## Versioning

- This project uses Semantic Versioning (`MAJOR.MINOR.PATCH`). Pre-release tags
  are allowed (`a`, `b`, `rc`, `dev`).
- `openlmlib/__init__.py` (`__version__`) is the single source of truth.
  `pyproject.toml` reads the version dynamically from that attribute.
- `installer/package.json` must carry the same version; the npm packaging check
  fails when the two disagree.
- Never reuse a version that has already been published to npm or PyPI.

## Update Checklist

1. Update `__version__` in `openlmlib/__init__.py` and `version` in
   `installer/package.json` to the same new value.
2. Add release notes to `CHANGELOG.md` under a new version heading.
3. Run the tests and verify the tool surface:
   - `python -m unittest discover -s tests -v`
   - `python scripts/count_mcp_tools.py`
4. Verify the npm package before publishing:
   - `cd installer && npm run verify`
5. Commit and push to the default branch.

## Tag and Publish

1. Create a tag in the format `vX.Y.Z` (or `vX.Y.Zrc1` for a prerelease) and push
   it:
   - `git tag vX.Y.Z`
   - `git push origin vX.Y.Z`
2. GitHub Actions `release.yml` builds the distributions and checks that the tag
   matches `__version__`. It always publishes tagged builds to TestPyPI and
   publishes stable tags to PyPI. The build job fails if `dist/` contains
   anything other than `.whl` and `.tar.gz` files, so checksums and reports must
   stay outside that directory.
3. Publish the npm package from the same commit:
   - `cd installer && npm publish`
   - The `prepack` hook bundles the Python source and runs the package
     verification, so a stale or mismatched package cannot be published.
4. Verify both registries from outside the repository:
   - `pipx install --force openlmlib==X.Y.Z`
   - `npm install -g openlmlib@X.Y.Z`
   - `openlmlib doctor`
5. Marketplace listings that mirror PyPI (for example mcprush) update after the
   new release is indexed. Confirm that the version and tool count shown there
   match the release.

## Trusted Publishing Setup

Configure trusted publishers in both registries:

- TestPyPI project: trust this repository/workflow for OIDC publishing
- PyPI project: trust this repository/workflow for OIDC publishing

Workflow file: `.github/workflows/release.yml`
