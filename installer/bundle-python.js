#!/usr/bin/env node
/**
 * Build script: Bundle Python source code into the installer package.
 * 
 * This copies the openlmlib Python package into the installer directory
 * so it gets included in the npm pack tarball.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const INSTALLER_DIR = __dirname;
const PYTHON_SRC = path.resolve(__dirname, '..'); // D:\LMlib (repo root)
const PYTHON_PACKAGE_SRC = path.join(PYTHON_SRC, 'openlmlib');
const PYTHON_PACKAGE_DST = path.join(INSTALLER_DIR, 'openlmlib');
const PYPROJECT_SRC = path.join(PYTHON_SRC, 'pyproject.toml');
const PYPROJECT_DST = path.join(INSTALLER_DIR, 'pyproject.toml');

function copyDirRecursive(src, dst, filterFn = null) {
  if (!fs.existsSync(dst)) {
    fs.mkdirSync(dst, { recursive: true });
  }
  
  const entries = fs.readdirSync(src, { withFileTypes: true });
  
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const dstPath = path.join(dst, entry.name);
    
    // Apply filter if provided
    if (filterFn && !filterFn(srcPath)) {
      continue;
    }
    
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, dstPath, filterFn);
    } else {
      fs.copyFileSync(srcPath, dstPath);
    }
  }
}

function removeDirRecursive(dirPath) {
  if (!fs.existsSync(dirPath)) return;
  
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      removeDirRecursive(fullPath);
    } else {
      fs.unlinkSync(fullPath);
    }
  }
  fs.rmdirSync(dirPath);
}

function bundlePython() {
  console.log('📦 Bundling Python source code into installer...\n');

  // Check if Python source exists
  if (!fs.existsSync(PYTHON_PACKAGE_SRC)) {
    console.error('❌ Python source not found:', PYTHON_PACKAGE_SRC);
    process.exit(1);
  }

  // Copy openlmlib Python package
  console.log('  Copying openlmlib/ package...');
  if (fs.existsSync(PYTHON_PACKAGE_DST)) {
    removeDirRecursive(PYTHON_PACKAGE_DST);
    console.log('    Removed old bundle');
  }
  
  copyDirRecursive(PYTHON_PACKAGE_SRC, PYTHON_PACKAGE_DST, (srcPath) => {
    // Exclude Python cache files
    return !srcPath.includes('__pycache__') && 
           !srcPath.endsWith('.pyc') &&
           !srcPath.endsWith('.pyo');
  });

  // Copy pyproject.toml (needed for pip install -e)
  console.log('  Copying pyproject.toml...');
  fs.copyFileSync(PYPROJECT_SRC, PYPROJECT_DST);

  console.log('\n✅ Python source bundled successfully!');
  console.log('   Run: npm pack\n');
  console.log('   ℹ️  Note: The openlmlib/ and pyproject.toml files');
  console.log('      in this directory are temporary build artifacts');
  console.log('      and will be cleaned up after npm pack\n');
}

function cleanupBundledFiles() {
  console.log('🧹 Cleaning up bundled Python files...\n');
  
  if (fs.existsSync(PYTHON_PACKAGE_DST)) {
    removeDirRecursive(PYTHON_PACKAGE_DST);
    console.log('  ✓ Removed openlmlib/');
  }
  
  if (fs.existsSync(PYPROJECT_DST)) {
    fs.unlinkSync(PYPROJECT_DST);
    console.log('  ✓ Removed pyproject.toml');
  }
  
  console.log('\n✅ Cleanup complete!\n');
}

// Check if we're being called from prepack (bundle) or postpack (cleanup)
const command = process.argv[2];
if (command === '--cleanup') {
  cleanupBundledFiles();
} else {
  bundlePython();
}
