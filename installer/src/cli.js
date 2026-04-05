import { execSync, spawn } from 'child_process';
import os from 'os';
import path from 'path';
import fs from 'fs';

const OPENLMLIB_HOME = process.env.OPENLMLIB_HOME || path.join(os.homedir(), '.openlmlib');
const VENV_PYTHON_WIN = path.join(OPENLMLIB_HOME, 'venv', 'Scripts', 'python.exe');
const VENV_PYTHON_UNIX = path.join(OPENLMLIB_HOME, 'venv', 'bin', 'python');

function getVenvPython() {
  return os.platform() === 'win32' ? VENV_PYTHON_WIN : VENV_PYTHON_UNIX;
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
