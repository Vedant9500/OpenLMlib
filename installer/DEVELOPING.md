# Developing the OpenLMlib npm package

The npm package is a self-contained installer. It ships the JavaScript installer
and a copy of the Python package, so users do not need a separate PyPI download.

## Repository layout

```text
OpenLMlib/
├── openlmlib/            Python package (CLI, MCP server, memory, collaboration)
├── pyproject.toml        Python package metadata (version is read from openlmlib/__init__.py)
├── docs/                 Documentation
├── scripts/              Maintenance and verification scripts
└── installer/            npm package
    ├── bin/              CLI entry point
    ├── src/              Installer, setup wizard, and postinstall checks
    ├── bundle-python.js  Copies the Python source into the package before packing
    ├── scripts/          Package verification
    └── package.json      npm manifest
```

## Requirements

- Node.js 18+
- Python 3.10+ with `build` and `twine` for Python releases
- A clean working tree before packaging

## Versioning

`openlmlib/__init__.py` (`__version__`) is the single source of truth for the
Python package. `installer/package.json` must always carry the same version. The
packaging check fails if the two disagree.

Do not reuse a version that has already been published to npm or PyPI. Publish
the same new version to both registries from the same commit.

## Tool count verification

The user-facing tool count must match what the package actually registers:

```bash
# From the repository root, using the environment that runs the MCP server
python scripts/count_mcp_tools.py
```

The checker verifies every expected tool by name and prints the total. Update the
expected sets in `scripts/count_mcp_tools.py` whenever tools are added or removed,
and update the README counts at the same time.

## Packaging

```bash
cd installer
npm pack
```

`prepack` performs two steps:

1. `bundle-python.js` copies `../openlmlib/` and `../pyproject.toml` into the
   package.
2. `scripts/verify-package.mjs` checks that:
   - the npm version matches `openlmlib/__init__.py`;
   - the bundled source registers the number of tools claimed in `README.md`;
   - required core, memory, collaboration, and Co-Scientist tools are present;
   - the README contains no stale release instructions or counts.

If verification fails, packaging stops. `postpack` removes the temporary bundled
source.

Install the resulting tarball to test it end to end:

```bash
npm install -g ./openlmlib-<version>.tgz
openlmlib setup
openlmlib doctor
```

## Release checklist

1. Update `openlmlib/__init__.py` and `installer/package.json` to the same new
   version.
2. Add a `CHANGELOG.md` entry for the release.
3. Run the test suite and `python scripts/count_mcp_tools.py`.
4. Build and publish the Python distribution:

   ```bash
   python -m build
   python -m twine upload dist/openlmlib-<version>*
   ```

5. Publish the npm package:

   ```bash
   cd installer
   npm publish
   ```

6. Verify both published artifacts from outside the repository:

   ```bash
   pipx install --force openlmlib==<version>
   npm install -g openlmlib@<version>
   openlmlib doctor
   ```

7. Tag the release: `git tag v<version> && git push --tags`.
8. Check the package pages on npm, PyPI, and any marketplace listings that mirror
   PyPI. Marketplace listings that track the PyPI package update after the new
   release is indexed.

## Installation sources

At install time the installer resolves the Python package in this order:

1. Bundled source inside the npm package (default, no network required)
2. Local development source when run from a repository checkout
3. GitHub tag `v<version>` — only with `OPENLMLIB_ALLOW_NETWORK_INSTALL_FALLBACK=1`
4. GitHub `main` — only with `OPENLMLIB_ALLOW_NETWORK_INSTALL_FALLBACK=1`
5. PyPI release — only with `OPENLMLIB_ALLOW_NETWORK_INSTALL_FALLBACK=1`

The network fallbacks are disabled by default so a broken package cannot silently
install an older release.

## Troubleshooting the build

- Run packaging from `installer/`, not from the repository root.
- `bundle-python.js` requires `../openlmlib/` and `../pyproject.toml` to exist.
- If a previous pack was interrupted, remove the generated `installer/openlmlib/`
  and `installer/pyproject.toml` before packing again.
- On Windows, use PowerShell or Git Bash; the scripts are plain Node.js and do
  not depend on a specific shell.
