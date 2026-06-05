#!/usr/bin/env node
/**
 * Smoke test: inspect the packed tarball, install it into a temp project, then
 * verify the npm bin and Python MCP server import from the generated venv.
 */

import { execFileSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function run(command, args, options = {}) {
  return execFileSync(command, args, {
    stdio: options.stdio || 'pipe',
    encoding: options.encoding || 'utf-8',
    env: { ...process.env, ...options.env },
    cwd: options.cwd,
  });
}

const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json'), 'utf8'));
const version = pkg.version;
const tarball = path.join(__dirname, `openlmlib-${version}.tgz`);

if (!fs.existsSync(tarball)) {
  console.error('Tarball not found:', tarball);
  console.error('Run: npm pack first');
  process.exit(1);
}

console.log('Testing installation from tarball');
console.log('Tarball:', tarball);
console.log('Size:', (fs.statSync(tarball).size / 1024).toFixed(1), 'KB');

const contents = run('tar', ['-tzf', tarball]);
const pyFiles = contents.split('\n').filter((file) => file.includes('openlmlib/') && file.endsWith('.py'));
const requiredFiles = [
  'package/openlmlib/mcp_server.py',
  'package/openlmlib/collab/collab_mcp.py',
  'package/pyproject.toml',
];
const missing = requiredFiles.filter((file) => !contents.includes(file));

console.log(`Found ${pyFiles.length} Python files in tarball`);
if (missing.length > 0) {
  console.error('Tarball is missing required files:', missing.join(', '));
  process.exit(1);
}

const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'openlmlib-install-'));
const projectDir = path.join(tmpRoot, 'project');
const openlmlibHome = path.join(tmpRoot, 'home');
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
fs.mkdirSync(projectDir, { recursive: true });
fs.writeFileSync(path.join(projectDir, 'package.json'), '{"private":true}\n');

console.log('Installing tarball into temp project:', projectDir);
run(npmCommand, ['install', tarball], {
  cwd: projectDir,
  stdio: 'inherit',
  env: { OPENLMLIB_HOME: openlmlibHome },
});

const openlmlibBin = path.join(projectDir, 'node_modules', 'openlmlib', 'bin', 'openlmlib.js');
run(process.execPath, [openlmlibBin, '--help'], { stdio: 'inherit', env: { OPENLMLIB_HOME: openlmlibHome } });

const venvPython = process.platform === 'win32'
  ? path.join(openlmlibHome, 'venv', 'Scripts', 'python.exe')
  : path.join(openlmlibHome, 'venv', 'bin', 'python');
run(venvPython, [
  '-c',
  'import openlmlib.mcp_server as m; assert hasattr(m, "init_library"); assert hasattr(m, "save_finding"); print("mcp-import-ok")',
], { stdio: 'inherit' });

console.log('Installer smoke test passed');
