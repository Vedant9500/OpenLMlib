# Fix: npm pack Installation Now Includes All 41 MCP Tools

## Problem

When installing via `npm pack` → `npm install -g openlmlib-X.X.X.tgz`, only **10 MCP tools** appeared in IDEs instead of the expected **41 tools**.

### Root Cause

The npm package (`openlmlib-X.X.X.tgz`) only contained the **JavaScript installer code**, not the **Python source code**. During installation, the postinstall script would try to fetch the Python package from:

1. GitHub tag `v0.1.6` (didn't exist ❌)
2. GitHub main branch (old version with 10 tools ⚠️)
3. PyPI (old version with 10 tools ⚠️)

Since the `feat/collab-sessions` branch (with 41 tools) hadn't been released to GitHub tags or PyPI yet, the installer fell back to an older version.

## Solution

### Changes Made

1. **Added `bundle-python.js`**: Copies Python source into the installer before packing
2. **Updated `package.json`**:
   - Added `prepack` script to auto-bundle Python source
   - Added `files` field to include bundled source in tarball
3. **Updated `src/postinstall.mjs`**: Prioritizes bundled source over external fetches

### How It Works Now

```bash
# When you run this:
cd installer
npm pack

# The prepack script automatically:
# 1. Copies D:\LMlib\openlmlib\ → D:\LMlib\installer\openlmlib\
# 2. Copies D:\LMlib\pyproject.toml → D:\LMlib\installer\pyproject.toml
# 3. Creates tarball with ALL source included (58 files)
```

The tarball now contains:
- ✅ JavaScript installer code (17 files)
- ✅ Python source code (41 files including collab module)
- ✅ `pyproject.toml` for pip install

### Installation Flow

```
npm install -g openlmlib-X.X.X.tgz
  ↓
postinstall.mjs runs
  ↓
Checks for bundled source in package
  ↓ (found!)
pip install -e <bundled_source_path>
  ↓
All 41 tools registered ✅
  ↓
Configure MCP clients
  ↓
Restart IDE to refresh cache
```

## Testing

### Verify the Package

```bash
cd installer
npm pack
# Should output: openlmlib-0.1.6.tgz (includes openlmlib/ and pyproject.toml)
```

### Verify Tool Count After Install

```bash
# After installing:
~/.openlmlib/venv/Scripts/python.exe -c "from openlmlib.mcp_server import mcp; print(len(mcp._tool_manager._tools))"
# Should output: 41
```

### Tool Breakdown

- **11 core tools**: `init_library`, `save_finding`, etc.
- **30 collab tools**: `create_session`, `send_message`, etc.

## For Users

### Fresh Install
```bash
npm install -g ./openlmlib-0.1.6.tgz
openlmlib setup
# RESTART YOUR IDE (Cursor, Claude Desktop, etc.)
```

### If Still Seeing Only 10 Tools

1. **Restart the IDE** completely (close all windows)
2. Check tool count: `openlmlib doctor`
3. Regenerate config: `openlmlib mcp-config`

## For Developers

### Making a New Release

1. Update version in:
   - `installer/package.json`
   - `../pyproject.toml`
   - `../openlmlib/__init__.py`

2. Build package:
   ```bash
   cd installer
   npm pack
   ```

3. Test install:
   ```bash
   npm install -g ./openlmlib-X.X.X.tgz
   # Verify 41 tools
   ```

4. Commit and tag:
   ```bash
   git add .
   git commit -m "release: v0.1.6"
   git tag v0.1.6
   git push origin main --tags
   ```

## Files Modified

- ✅ `installer/bundle-python.js` (new)
- ✅ `installer/src/postinstall.mjs` (updated priority logic)
- ✅ `installer/package.json` (added prepack script + files field)
- ✅ `installer/README.md` (new - documentation)
- ✅ `installer/test-install.js` (new - verification script)

## Future Improvements

- [ ] Add automated tests for npm package installation
- [ ] Create GitHub Actions workflow to build and publish packages
- [ ] Add version validation to ensure bundled source matches npm version
- [ ] Consider publishing to npm registry for easier distribution
