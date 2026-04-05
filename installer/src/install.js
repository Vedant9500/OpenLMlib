import { execSync } from 'child_process';
import os from 'os';
import path from 'path';
import fs from 'fs';

const OPENLMLIB_HOME = process.env.OPENLMLIB_HOME || path.join(os.homedir(), '.openlmlib');
const VENV_DIR = path.join(OPENLMLIB_HOME, 'venv');
const VENV_PYTHON = os.platform() === 'win32'
  ? path.join(VENV_DIR, 'Scripts', 'python.exe')
  : path.join(VENV_DIR, 'bin', 'python');

function getPythonCmd() {
  try {
    execSync('python3 --version', { stdio: 'ignore' });
    return 'python3';
  } catch {
    try {
      execSync('py --version', { stdio: 'ignore' });
      return 'py';
    } catch {
      return null;
    }
  }
}

function getActivePythonCmd() {
  return getPythonCmd() || 'python3';
}

function ensureHomeDir() {
  if (!fs.existsSync(OPENLMLIB_HOME)) {
    fs.mkdirSync(OPENLMLIB_HOME, { recursive: true });
  }
}

function createVenv(onProgress) {
  ensureHomeDir();
  onProgress('Creating isolated Python environment...');
  execSync(`${getActivePythonCmd()} -m venv "${VENV_DIR}"`, { stdio: 'pipe' });
  onProgress('Virtual environment created.');
}

function installPackage(packageName, onProgress) {
  onProgress(`Installing ${packageName}...`);
  execSync(`"${VENV_PYTHON}" -m pip install --upgrade pip`, { stdio: 'pipe' });
  execSync(`"${VENV_PYTHON}" -m pip install "${packageName}"`, { stdio: 'pipe' });
  onProgress(`${packageName} installed.`);
}

function installFromLocal(localPath, onProgress) {
  onProgress('Installing openlmlib...');
  execSync(`"${VENV_PYTHON}" -m pip install --upgrade pip`, { stdio: 'pipe' });

  const hasLocalProject = !!localPath && (
    fs.existsSync(path.join(localPath, 'pyproject.toml')) ||
    fs.existsSync(path.join(localPath, 'setup.py'))
  );

  const candidates = [];
  if (hasLocalProject) {
    candidates.push({ kind: 'editable', value: localPath, label: `local source (${localPath})` });
  }
  if (process.env.npm_package_version) {
    candidates.push({ kind: 'package', value: `openlmlib==${process.env.npm_package_version}`, label: `openlmlib==${process.env.npm_package_version}` });
  }
  candidates.push({ kind: 'package', value: 'openlmlib', label: 'openlmlib (latest from PyPI)' });
  candidates.push({ kind: 'package', value: 'git+https://github.com/Vedant9500/OpenLMlib.git', label: 'OpenLMlib from GitHub' });

  let lastErr = null;
  for (const candidate of candidates) {
    try {
      onProgress(`Installing openlmlib (${candidate.label})...`);
      if (candidate.kind === 'editable') {
        execSync(`"${VENV_PYTHON}" -m pip install -e "${candidate.value}"`, { stdio: 'pipe' });
      } else {
        execSync(`"${VENV_PYTHON}" -m pip install "${candidate.value}"`, { stdio: 'pipe' });
      }
      onProgress('openlmlib installed.');
      return;
    } catch (err) {
      lastErr = err;
    }
  }

  throw lastErr || new Error('Unable to install openlmlib.');
}

function downloadModel(modelName, onProgress) {
  onProgress(`Downloading embedding model: ${modelName}...`);
  const script = `from sentence_transformers import SentenceTransformer; SentenceTransformer("${modelName}"); print("model-downloaded")`;
  try {
    execSync(`"${VENV_PYTHON}" -c "${script}"`, {
      stdio: 'pipe',
      encoding: 'utf-8',
      timeout: 600000,
      env: { ...process.env, TRANSFORMERS_OFFLINE: '0' },
    });
    onProgress('Embedding model downloaded.');
  } catch {
    onProgress('Warning: Model download failed. It will be downloaded on first use.');
  }
}

function runSetupWizard(config, onProgress) {
  onProgress('Configuring MCP clients...');
  const escapedHome = OPENLMLIB_HOME.replace(/\\/g, '\\\\');
  const script = [
    'from pathlib import Path',
    'from openlmlib.mcp_setup import install_or_refresh_default_client_configs',
    'from openlmlib.settings import write_default_settings, default_settings_payload',
    'import json',
    `settings_path = Path(r"${escapedHome}") / "config" / "settings.json"`,
    'write_default_settings(settings_path, force=False)',
    'payload = default_settings_payload()',
    config.vectorBackend ? `payload["vector_backend"] = "${config.vectorBackend}"` : '',
    config.embeddingModel ? `payload["embedding_model"] = "${config.embeddingModel}"` : '',
    'with open(settings_path, "w") as f:',
    '    json.dump(payload, f, indent=2)',
    'install_or_refresh_default_client_configs(settings_path=settings_path)',
    'print("setup-complete")',
  ].filter(Boolean).join('; ');

  try {
    execSync(`"${VENV_PYTHON}" -c "${script}"`, {
      stdio: 'pipe',
      encoding: 'utf-8',
    });
    onProgress('Setup complete.');
  } catch {
    onProgress('Warning: Setup wizard encountered an issue. You can run "openlmlib setup" later.');
  }
}

function getInstalledVersion() {
  try {
    return execSync(`"${VENV_PYTHON}" -c "import openlmlib; print(openlmlib.__version__)"`, {
      stdio: 'pipe',
      encoding: 'utf-8',
    }).trim();
  } catch {
    return null;
  }
}

function checkPythonVersion() {
  try {
    const pythonCmd = getPythonCmd();
    if (!pythonCmd) return { found: false };
    const version = execSync(`${pythonCmd} --version`, { stdio: 'pipe', encoding: 'utf-8' }).trim();
    const match = version.match(/Python (\d+)\.(\d+)/);
    if (match) {
      const major = parseInt(match[1], 10);
      const minor = parseInt(match[2], 10);
      return { found: true, version, major, minor, ok: major >= 3 && minor >= 10 };
    }
    return { found: false };
  } catch {
    return { found: false };
  }
}

function checkPip() {
  try {
    const pythonCmd = getPythonCmd();
    if (!pythonCmd) return false;
    execSync(`${pythonCmd} -m pip --version`, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function checkVenv() {
  try {
    const pythonCmd = getPythonCmd();
    if (!pythonCmd) return false;
    execSync(`${pythonCmd} -m venv --help`, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

export {
  OPENLMLIB_HOME,
  VENV_DIR,
  VENV_PYTHON,
  ensureHomeDir,
  createVenv,
  installPackage,
  installFromLocal,
  downloadModel,
  runSetupWizard,
  getInstalledVersion,
  checkPythonVersion,
  checkPip,
  checkVenv,
  getPythonCmd,
  getActivePythonCmd,
};
