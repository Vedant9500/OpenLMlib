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
  if (fs.existsSync(VENV_PYTHON)) {
    onProgress('Using existing virtual environment.');
    return;
  }

  if (fs.existsSync(VENV_DIR)) {
    try {
      fs.rmSync(VENV_DIR, { recursive: true, force: true });
    } catch {
      // Best effort cleanup; creation may still succeed.
    }
  }

  try {
    execSync(`${getActivePythonCmd()} -m venv "${VENV_DIR}"`, { stdio: 'pipe' });
    onProgress('Virtual environment created.');
  } catch (err) {
    if (fs.existsSync(VENV_PYTHON)) {
      onProgress('Reusing existing virtual environment (creation failed).');
      return;
    }
    throw err;
  }
}

function installPackage(packageName, onProgress) {
  onProgress(`Installing ${packageName}...`);
  execSync(`"${VENV_PYTHON}" -m pip install --upgrade pip`, { stdio: 'pipe' });
  execSync(`"${VENV_PYTHON}" -m pip install "${packageName}"`, { stdio: 'pipe' });
  onProgress(`${packageName} installed.`);
}

function hasOpenLMlibProject(dirPath) {
  if (!dirPath) return false;
  const pyprojectPath = path.join(dirPath, 'pyproject.toml');
  const packageDir = path.join(dirPath, 'openlmlib');
  if (!fs.existsSync(pyprojectPath) || !fs.existsSync(packageDir)) return false;
  try {
    const content = fs.readFileSync(pyprojectPath, 'utf-8');
    return content.includes('name = "openlmlib"');
  } catch {
    return false;
  }
}

function discoverLocalSourceCandidates(seedPath) {
  const paths = [
    seedPath,
    process.cwd(),
    path.resolve(process.cwd(), '..'),
    path.resolve(process.cwd(), '..', '..'),
  ].filter(Boolean);
  return [...new Set(paths)];
}

function validateInstalledOpenLMlib() {
  const scriptPath = path.join(os.tmpdir(), `openlmlib-validate-${Date.now()}.py`);
  const script = [
    'import openlmlib.mcp_server as m',
    'required_core = ["init_library", "save_finding", "retrieve_findings", "health"]',
    'required_collab = ["create_session", "help_collab"]',
    'missing_core = [name for name in required_core if not hasattr(m, name)]',
    'missing_collab = [name for name in required_collab if not hasattr(m, name)]',
    'if missing_core:',
    '    raise SystemExit("missing_core_mcp_tools:" + ",".join(missing_core))',
    'if missing_collab:',
    '    print("missing_collab_mcp_tools:" + ",".join(missing_collab))',
    'print("ok")',
  ].join('\n');
  fs.writeFileSync(scriptPath, script, { encoding: 'utf-8' });
  try {
    const output = execSync(`"${VENV_PYTHON}" "${scriptPath}"`, { stdio: 'pipe', encoding: 'utf-8' });
    if (output && output.includes('missing_collab_mcp_tools:')) {
      const warningLine = output.split('\n').find((line) => line.startsWith('missing_collab_mcp_tools:'));
      if (warningLine) {
        return { status: 'warn', message: warningLine };
      }
    }
    return { status: 'ok' };
  } finally {
    try {
      fs.unlinkSync(scriptPath);
    } catch {
      // Best effort cleanup.
    }
  }
}

function installFromLocal(localPath, onProgress) {
  onProgress('Installing openlmlib...');
  execSync(`"${VENV_PYTHON}" -m pip install --upgrade pip`, { stdio: 'pipe' });

  const localSourceCandidates = discoverLocalSourceCandidates(localPath);

  const candidates = [];
  for (const candidatePath of localSourceCandidates) {
    const hasLocalProject = fs.existsSync(path.join(candidatePath, 'pyproject.toml')) || fs.existsSync(path.join(candidatePath, 'setup.py'));
    if (hasLocalProject && hasOpenLMlibProject(candidatePath)) {
      candidates.push({ kind: 'editable', value: candidatePath, label: `local source (${candidatePath})` });
      break;
    }
  }
  if (process.env.npm_package_version) {
    candidates.push({
      kind: 'package',
      value: `git+https://github.com/Vedant9500/OpenLMlib.git@v${process.env.npm_package_version}`,
      label: `OpenLMlib GitHub tag v${process.env.npm_package_version}`,
    });
  }
  candidates.push({ kind: 'package', value: 'git+https://github.com/Vedant9500/OpenLMlib.git', label: 'OpenLMlib from GitHub (main branch)' });
  if (process.env.npm_package_version) {
    candidates.push({ kind: 'package', value: `openlmlib==${process.env.npm_package_version}`, label: `openlmlib==${process.env.npm_package_version}` });
  }
  candidates.push({ kind: 'package', value: 'openlmlib', label: 'openlmlib (latest from PyPI)' });

  let lastErr = null;
  for (const candidate of candidates) {
    try {
      onProgress(`Installing openlmlib (${candidate.label})...`);
      if (candidate.kind === 'editable') {
        execSync(`"${VENV_PYTHON}" -m pip install -e "${candidate.value}"`, { stdio: 'pipe' });
      } else {
        execSync(`"${VENV_PYTHON}" -m pip install "${candidate.value}"`, { stdio: 'pipe' });
      }
      const validation = validateInstalledOpenLMlib();
      if (validation?.status === 'warn') {
        onProgress(`Warning: ${validation.message}`);
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
    'write_default_settings(settings_path)',
    'payload = default_settings_payload()',
    config.vectorBackend ? `payload["vector_backend"] = "${config.vectorBackend}"` : '',
    config.embeddingModel ? `payload["embedding_model"] = "${config.embeddingModel}"` : '',
    'with open(settings_path, "w") as f:',
    '    json.dump(payload, f, indent=2)',
    'install_or_refresh_default_client_configs(settings_path=settings_path)',
    'print("setup-complete")',
  ].filter(Boolean).join('\n');

  const scriptPath = path.join(os.tmpdir(), `openlmlib-setup-${Date.now()}.py`);
  fs.writeFileSync(scriptPath, script, { encoding: 'utf-8' });

  try {
    execSync(`"${VENV_PYTHON}" "${scriptPath}"`, {
      stdio: 'pipe',
      encoding: 'utf-8',
    });
    onProgress('Setup complete.');
  } catch {
    onProgress('Warning: Setup wizard encountered an issue. You can run "openlmlib setup" later.');
  } finally {
    try {
      fs.unlinkSync(scriptPath);
    } catch {
      // Best effort cleanup.
    }
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
