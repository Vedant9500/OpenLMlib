#!/usr/bin/env node

import path from 'path';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';
import os from 'os';
import fs from 'fs';
import chalk from 'chalk';
import ora from 'ora';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ─── Helpers ───────────────────────────────────────────────

function getPythonCmd() {
  // Try python3 first (Unix), then py (Windows)
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

function getActivePythonCmd() {
  return getPythonCmd() || 'python3';
}

function detectPackageManager() {
  const platform = process.platform;
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

function hasPythonProject(dirPath) {
  return fs.existsSync(path.join(dirPath, 'pyproject.toml')) || fs.existsSync(path.join(dirPath, 'setup.py'));
}

function installOpenLMlib(VENV_PYTHON, spinner) {
  execSync(`"${VENV_PYTHON}" -m pip install --upgrade pip`, { stdio: 'pipe' });

  const candidateSpecs = [];
  const localSourceCandidates = [
    path.resolve(__dirname, '..', '..'),
    path.resolve(__dirname, '..'),
  ];

  for (const localPath of localSourceCandidates) {
    if (hasPythonProject(localPath)) {
      candidateSpecs.push({
        kind: 'editable',
        value: localPath,
        label: `local source (${localPath})`,
      });
      break;
    }
  }

  if (process.env.npm_package_version) {
    candidateSpecs.push({
      kind: 'package',
      value: `git+https://github.com/Vedant9500/OpenLMlib.git@v${process.env.npm_package_version}`,
      label: `OpenLMlib GitHub tag v${process.env.npm_package_version}`,
    });
  }
  candidateSpecs.push({ kind: 'package', value: 'git+https://github.com/Vedant9500/OpenLMlib.git', label: 'OpenLMlib from GitHub (main branch)' });

  if (process.env.npm_package_version) {
    candidateSpecs.push({ kind: 'package', value: `openlmlib==${process.env.npm_package_version}`, label: `openlmlib==${process.env.npm_package_version}` });
  }
  candidateSpecs.push({ kind: 'package', value: 'openlmlib', label: 'openlmlib (latest from PyPI)' });

  let lastError = null;
  for (const spec of candidateSpecs) {
    try {
      spinner.text = `Installing openlmlib (${spec.label})...`;
      if (spec.kind === 'editable') {
        execSync(`"${VENV_PYTHON}" -m pip install -e "${spec.value}"`, { stdio: 'pipe' });
      } else {
        execSync(`"${VENV_PYTHON}" -m pip install "${spec.value}"`, { stdio: 'pipe' });
      }
      return;
    } catch (err) {
      lastError = err;
    }
  }

  throw lastError || new Error('Unable to install openlmlib.');
}

async function runNonInteractive() {
  const LOGO = [
    chalk.cyan('    ███████    ███████████  ██████████ ██████   █████ █████       ██████   ██████ █████       █████ ███████████'),
    chalk.cyan('  ███░░░░░███ ░░███░░░░░███░░███░░░░░█░░██████ ░░███ ░░███       ░░██████ ██████ ░░███       ░░███ ░░███░░░░░███'),
    chalk.cyan(' ███     ░░███ ░███    ░███ ░███  █ ░  ░███░███ ░███  ░███        ░███░█████░███  ░███        ░███  ░███    ░███'),
    chalk.cyan('░███      ░███ ░██████████  ░██████    ░███░░███░███  ░███        ░███░░███ ░███  ░███        ░███  ░██████████'),
    chalk.cyan('░███      ░███ ░███░░░░░░   ░███░░█    ░███ ░░██████  ░███        ░███ ░░░  ░███  ░███        ░███  ░███░░░░░███'),
    chalk.cyan('░░███     ███  ░███         ░███ ░   █ ░███  ░░█████  ░███      █ ░███      ░███  ░███      █ ░███  ░███    ░███'),
    chalk.cyan(' ░░░███████░   █████        ██████████ █████  ░░█████ ███████████ █████     █████ ███████████ █████ ███████████'),
    chalk.cyan('   ░░░░░░░    ░░░░░        ░░░░░░░░░░ ░░░░░    ░░░░░ ░░░░░░░░░░░ ░░░░░     ░░░░░ ░░░░░░░░░░░ ░░░░░ ░░░░░░░░░░░'),
  ];

  console.log('');
  for (const line of LOGO) {
    console.log(line);
  }
  console.log('');
  console.log(chalk.bold.white('  AI-Powered Knowledge Library for LLM Agents'));
  console.log('');

  // Step 1: Check prerequisites
  console.log(chalk.bold.cyan('  Prerequisite Checks'));
  const pythonCheck = checkPythonVersion();
  const pipOk = checkPip();
  const venvOk = checkVenv();

  const check = (label, ok, detail) => {
    const icon = ok ? chalk.green('✔') : chalk.red('✖');
    const detailStr = detail ? chalk.gray(` — ${detail}`) : '';
    console.log(`  ${icon} ${chalk.bold(label)}${detailStr}`);
  };

  check('Python', pythonCheck.found && pythonCheck.ok,
    pythonCheck.found ? `${pythonCheck.version}${pythonCheck.ok ? '' : ' (requires 3.10+)'}` : 'not found');
  check('pip', pipOk);
  check('venv', venvOk);

  if (!pythonCheck.found || !pythonCheck.ok) {
    console.log('');
    console.log(chalk.yellow.bold('  ⚠ Python 3.10+ not found.'));
    console.log(chalk.gray('  Please install Python from https://www.python.org/downloads/'));
    console.log(chalk.gray('  Then run: npm install -g openlmlib'));
    console.log('');
    process.exit(1);
  }

  // Step 2: Create venv
  console.log('');
  const spinner1 = ora('Creating virtual environment...').start();
  const OPENLMLIB_HOME = process.env.OPENLMLIB_HOME || path.join(os.homedir(), '.openlmlib');
  const VENV_DIR = path.join(OPENLMLIB_HOME, 'venv');
  const VENV_PYTHON = os.platform() === 'win32'
    ? path.join(VENV_DIR, 'Scripts', 'python.exe')
    : path.join(VENV_DIR, 'bin', 'python');

  if (!fs.existsSync(OPENLMLIB_HOME)) {
    fs.mkdirSync(OPENLMLIB_HOME, { recursive: true });
  }

  execSync(`${getActivePythonCmd()} -m venv "${VENV_DIR}"`, { stdio: 'pipe' });
  spinner1.succeed('Virtual environment created.');

  // Step 3: Install openlmlib
  const spinner2 = ora('Installing openlmlib...').start();
  installOpenLMlib(VENV_PYTHON, spinner2);
  spinner2.succeed('openlmlib installed.');

  // Step 4: Skip model warmup during npm install to keep install time reasonable.
  // The model will download lazily on first retrieval/query call.
  const spinner3 = ora('Preparing embedding model setup...').start();
  spinner3.succeed('Model warmup skipped (will download on first use).');

  // Step 5: Configure
  const spinner4 = ora('Configuring MCP clients...').start();
  const configScriptPath = path.join(OPENLMLIB_HOME, '_config_mcp.py');
  const configScript = `from pathlib import Path
from openlmlib.mcp_setup import install_or_refresh_default_client_configs
from openlmlib.settings import write_default_settings
settings_path = Path(r"${OPENLMLIB_HOME}") / "config" / "settings.json"
write_default_settings(settings_path, force=False)
install_or_refresh_default_client_configs(settings_path=settings_path)
print("ok")`;
  fs.writeFileSync(configScriptPath, configScript);

  try {
    execSync(`"${VENV_PYTHON}" "${configScriptPath}"`, { stdio: 'pipe', encoding: 'utf-8' });
    spinner4.succeed('MCP clients configured.');
  } catch {
    spinner4.warn('MCP config skipped (run "openlmlib mcp-config" later).');
  } finally {
    try { fs.unlinkSync(configScriptPath); } catch {}
  }

  // Done
  console.log(chalk.green.bold('  ✔  OpenLMlib installed successfully!'));
  console.log('');
  console.log(chalk.bold.cyan('  Quick Start:'));
  console.log(chalk.gray('    openlmlib init'));
  console.log(chalk.gray('    openlmlib add --project myproj --claim "..." --confidence 0.8'));
  console.log(chalk.gray('    openlmlib query "your search query"'));
  console.log(chalk.gray('    openlmlib mcp'));
  console.log(chalk.gray('    openlmlib doctor'));
  console.log('');
  console.log(chalk.gray('  Restart VS Code / Cursor / Claude Desktop to activate MCP.'));
  console.log('');
}

// ─── Interactive installer (Ink) ───────────────────────────

async function runInteractive() {
  const { render } = await import('ink');
  const React = await import('react');
  const { default: App } = await import('./ui/app.js');

  render(
    React.default.createElement(App, {
      pythonCheck: checkPythonVersion(),
      hasPackageManager: !!detectPackageManager(),
      installerDir: __dirname,
    })
  );
}

// ─── Main ──────────────────────────────────────────────────

const isTTY = process.stdin.isTTY;

if (isTTY) {
  await runInteractive();
} else {
  await runNonInteractive();
}
