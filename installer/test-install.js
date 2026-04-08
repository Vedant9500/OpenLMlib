#!/usr/bin/env node
/**
 * Test script: Simulate npm install from the packed tarball
 */

import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const tarball = path.join(__dirname, 'openlmlib-0.1.6.tgz');

if (!fs.existsSync(tarball)) {
  console.error('❌ Tarball not found:', tarball);
  console.error('Run: npm pack first');
  process.exit(1);
}

console.log('🧪 Testing installation from tarball...\n');
console.log('Tarball:', tarball);
console.log('Size:', (fs.statSync(tarball).size / 1024).toFixed(1), 'KB\n');

// Check if bundled source is in tarball
const { execSync } = await import('child_process');
const contents = execSync(`tar -tzf "${tarball}"`, { encoding: 'utf-8' });
const pyFiles = contents.split('\n').filter(f => f.includes('openlmlib/') && f.endsWith('.py'));

console.log(`✓ Found ${pyFiles.length} Python files in tarball`);

const hasCollabMcp = contents.includes('openlmlib/collab/collab_mcp.py');
const hasPyproject = contents.includes('pyproject.toml');
const hasMcpServer = contents.includes('openlmlib/mcp_server.py');

console.log(hasCollabMcp ? '✓ collab_mcp.py included' : '✗ collab_mcp.py MISSING');
console.log(hasPyproject ? '✓ pyproject.toml included' : '✗ pyproject.toml MISSING');
console.log(hasMcpServer ? '✓ mcp_server.py included' : '✗ mcp_server.py MISSING');

if (hasCollabMcp && hasPyproject && hasMcpServer) {
  console.log('\n✅ Tarball contains all necessary files for 41 tools!');
  console.log('\nTo test actual installation:');
  console.log('  npm install -g ./openlmlib-0.1.6.tgz');
  console.log('  Then restart your IDE to refresh MCP tool cache\n');
} else {
  console.log('\n❌ Tarball is missing required files!');
  process.exit(1);
}
