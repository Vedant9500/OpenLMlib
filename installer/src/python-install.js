import { execSync } from 'child_process';
import os from 'os';

function detectPackageManager() {
  const platform = os.platform();
  if (platform === 'win32') {
    try {
      execSync('winget --version', { stdio: 'ignore' });
      return { name: 'winget', command: 'winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements' };
    } catch {
      return null;
    }
  }
  if (platform === 'darwin') {
    try {
      execSync('brew --version', { stdio: 'ignore' });
      return { name: 'brew', command: 'brew install python@3.12' };
    } catch {
      return null;
    }
  }
  try {
    execSync('apt --version', { stdio: 'ignore' });
    return { name: 'apt', command: 'sudo apt update && sudo apt install -y python3 python3-pip python3-venv' };
  } catch {
    try {
      execSync('dnf --version', { stdio: 'ignore' });
      return { name: 'dnf', command: 'sudo dnf install -y python3 python3-pip' };
    } catch {
      try {
        execSync('pacman --version', { stdio: 'ignore' });
        return { name: 'pacman', command: 'sudo pacman -S --noconfirm python python-pip' };
      } catch {
        return null;
      }
    }
  }
}

function installPython(callback) {
  const pm = detectPackageManager();
  if (!pm) {
    callback(null, {
      success: false,
      message: 'Could not find a supported package manager to install Python automatically.\nPlease install Python 3.10+ manually from https://www.python.org/downloads/',
    });
    return;
  }

  try {
    execSync(pm.command, { stdio: 'inherit' });
    callback(null, {
      success: true,
      manager: pm.name,
      message: `Python installed successfully via ${pm.name}.`,
    });
  } catch (err) {
    callback(null, {
      success: false,
      manager: pm.name,
      message: `Failed to install Python via ${pm.name}. Please install manually from https://www.python.org/downloads/`,
      error: err.message,
    });
  }
}

export {
  detectPackageManager,
  installPython,
};
