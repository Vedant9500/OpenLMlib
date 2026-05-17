import { execSync, spawn } from 'child_process';
import os from 'os';
import path from 'path';
import fs from 'fs';

import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const OPENLMLIB_HOME = process.env.OPENLMLIB_HOME || path.join(os.homedir(), '.openlmlib');

function getVenvPython() {
  if (process.env.OPENLMLIB_HOME) {
    const pyPath = os.platform() === 'win32'
      ? path.join(process.env.OPENLMLIB_HOME, 'venv', 'Scripts', 'python.exe')
      : path.join(process.env.OPENLMLIB_HOME, 'venv', 'bin', 'python');
    if (fs.existsSync(pyPath)) return pyPath;
  }

  const installerDir = path.dirname(path.dirname(__filename));
  const repoRoot = path.dirname(installerDir);
  const devVenv = os.platform() === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python');
  if (fs.existsSync(devVenv)) return devVenv;

  return os.platform() === 'win32'
    ? path.join(OPENLMLIB_HOME, 'venv', 'Scripts', 'python.exe')
    : path.join(OPENLMLIB_HOME, 'venv', 'bin', 'python');
}

function isInstalled() {
  return fs.existsSync(getVenvPython());
}

function runPython(args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(getVenvPython(), args, {
      stdio: opts.stdio || 'inherit',
      env: { ...process.env, ...opts.env },
    });
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`python exited with code ${code}`));
    });
    child.on('error', reject);
  });
}

function runPythonSync(args, opts = {}) {
  return execSync(`${getVenvPython()} ${args.join(' ')}`, {
    stdio: opts.stdio || 'pipe',
    encoding: 'utf-8',
    env: { ...process.env, ...opts.env },
  });
}

export {
  OPENLMLIB_HOME,
  getVenvPython,
  isInstalled,
  runPython,
  runPythonSync,
};
