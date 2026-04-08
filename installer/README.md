# OpenLMlib Installer

## Development Workflow

### Creating a New Release Package

1. **Ensure you're on the right branch** with all changes committed:
   ```bash
   git status
   ```

2. **Update version** in both:
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
   python -c "from openlmlib.mcp_server import mcp; print(len(mcp._tool_manager._tools))"
   ```
   
   Should output: `41`

6. **Restart your IDE** (Cursor, Claude Desktop, etc.) to refresh MCP tool cache

### Installing from the Package

```bash
npm install -g ./openlmlib-0.1.6.tgz
openlmlib setup
```

Then **restart your IDE** to see all 41 MCP tools.

## How It Works

The installer has a **two-stage installation**:

1. **npm package** contains:
   - JavaScript installer code (CLI, UI, wizards)
   - **Bundled Python source code** (`openlmlib/` and `pyproject.toml`)

2. **Postinstall script** does:
   - Creates virtual environment at `~/.openlmlib/venv`
   - Installs Python package from **bundled source** via `pip install -e`
   - Configures MCP clients (VS Code, Cursor, Claude, etc.)
   - Sets up settings and paths

### Installation Priority

The installer tries these sources in order:
1. ✅ **Bundled source** (from npm package) - **THIS IS NEW**
2. Local development source (if running from repo)
3. GitHub tag `v{version}`
4. GitHub main branch
5. PyPI release

This ensures the npm package is **self-contained** and doesn't depend on external releases.

## Troubleshooting

### Only seeing 10 tools in IDE?

1. **Restart your IDE** - it may be caching an old tool list
2. **Run**: `openlmlib doctor` to verify installation
3. **Check tool count**: 
   ```bash
   ~/.openlmlib/venv/Scripts/python.exe -c "from openlmlib.mcp_server import mcp; print(len(mcp._tool_manager._tools))"
   ```

### Build fails?

Make sure you're running from the `installer/` directory and the repo root has the Python source:
```
D:\LMlib/
├── openlmlib/          ← Python source (must exist)
├── pyproject.toml      ← Python package config (must exist)
└── installer/          ← You are here
    ├── package.json
    └── bundle-python.js
```

## Files

- `bundle-python.js` - Copies Python source into installer before packing
- `src/postinstall.mjs` - Main installation script
- `src/run-setup.mjs` - MCP setup wizard
- `package.json` - npm package manifest (includes `prepack` hook)
