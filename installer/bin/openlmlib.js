#!/usr/bin/env node
'use strict';

const { execFileSync } = require('child_process');
const os = require('os');
const path = require('path');
const fs = require('fs');

const OPENLMLIB_HOME = process.env.OPENLMLIB_HOME || path.join(os.homedir(), '.openlmlib');
const VENV_PYTHON = os.platform() === 'win32'
  ? path.join(OPENLMLIB_HOME, 'venv', 'Scripts', 'python.exe')
  : path.join(OPENLMLIB_HOME, 'venv', 'bin', 'python');

if (!fs.existsSync(VENV_PYTHON)) {
  process.stderr.write('error: OpenLMlib is not installed.\n');
  process.stderr.write('Run: npm install -g openlmlib\n');
  process.exit(1);
}

try {
  execFileSync(VENV_PYTHON, ['-m', 'openlmlib', ...process.argv.slice(2)], {
    stdio: 'inherit',
  });
} catch (err) {
  process.exit(err.status || 1);
}
