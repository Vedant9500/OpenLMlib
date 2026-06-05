# OpenLMlib Installer

## Development Workflow

### Creating a New Release Package

1. **Ensure you're on the right branch** with all changes committed:
   ```bash
   git status
   ```

2. **Update version** in:
   - `installer/package.json`
   - `../pyproject.toml`
   - `../openlmlib/__init__.py`

3. **Build and pack**:
   ```bash
   cd installer
   npm pack
   ```

   This automatically:
   - Bundles the Python source code from the repo root
   - Creates `openlmlib-X.X.X.tgz` with all source included

4. **Test the package**:
   ```bash
   npm install -g ./openlmlib-X.X.X.tgz
   ```

5. **Verify all tools are registered**:
   ```bash
   python -c "from openlmlib import mcp_server as m; m._register_memory_tools(); m._register_collab_tools(); print(len(m.mcp._tool_manager._tools))"
   ```

   Run this from outside the repo checkout, or use `installer\verify-tools.cmd` on Windows. It should output at least `76`.

6. **Restart your IDE** to refresh MCP tool cache.

### Installing From The Package

```bash
npm install -g ./openlmlib-0.2.7.tgz
openlmlib setup
```

Then restart your IDE to see all 76 MCP tools.

## How It Works

The installer has a two-stage installation:

1. The npm package contains:
   - JavaScript installer code (CLI, UI, wizards)
   - Bundled Python source code (`openlmlib/` and `pyproject.toml`)

2. The postinstall script:
   - Creates a virtual environment at `~/.openlmlib/venv`
   - Installs the Python package from bundled source via `pip install -e`
   - Verifies the full MCP tool surface, including Co-Scientist tools
   - Configures MCP clients
   - Sets up settings and paths

### Installation Priority

The installer tries these sources in order:

1. Bundled source from the npm package
2. Local development source, if running from a repo checkout
3. GitHub tag `v{version}`, only when `OPENLMLIB_ALLOW_NETWORK_INSTALL_FALLBACK=1`
4. GitHub main branch, only when `OPENLMLIB_ALLOW_NETWORK_INSTALL_FALLBACK=1`
5. PyPI release, only when `OPENLMLIB_ALLOW_NETWORK_INSTALL_FALLBACK=1`

This keeps the npm package self-contained by default and prevents silent fallback to stale external releases.

## Troubleshooting

### Missing MCP tools in an IDE

1. Restart the IDE; it may be caching an old tool list.
2. Run `openlmlib doctor` to verify installation.
3. Check the startup-equivalent tool count from outside the repo checkout:
   ```bash
   ~/.openlmlib/venv/Scripts/python.exe -c "from openlmlib import mcp_server as m; m._register_memory_tools(); m._register_collab_tools(); print(len(m.mcp._tool_manager._tools))"
   ```
4. On Windows, run `installer\verify-tools.cmd` after installing the package.

### Build fails

Make sure you are running from the `installer/` directory and the repo root has the Python source:

```text
D:\LMlib/
+-- openlmlib/          # Python source
+-- pyproject.toml      # Python package config
`-- installer/          # npm package
```

## Files

- `bundle-python.js` - copies Python source into installer before packing
- `src/postinstall.mjs` - main installation script
- `src/run-setup.mjs` - MCP setup wizard
- `package.json` - npm package manifest, including the `prepack` hook
