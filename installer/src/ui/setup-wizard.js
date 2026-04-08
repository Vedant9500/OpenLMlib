import React, { useState, useEffect } from 'react';
import { Box, Text, useApp, useInput } from 'ink';
import SelectInput from 'ink-select-input';
import Spinner from 'ink-spinner';
import { execSync } from 'child_process';
import os from 'os';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const EMBEDDING_MODELS = [
  { label: 'all-MiniLM-L6-v2 (fast, 384d) — Recommended', value: 'sentence-transformers/all-MiniLM-L6-v2' },
  { label: 'all-mpnet-base-v2 (accurate, 768d)', value: 'sentence-transformers/all-mpnet-base-v2' },
  { label: 'paraphrase-MiniLM-L3-v2 (tiny, 384d)', value: 'sentence-transformers/paraphrase-MiniLM-L3-v2' },
];

const VECTOR_BACKENDS = [
  { label: 'NumPy (no extra deps, good for <10k findings) — Recommended', value: 'numpy' },
  { label: 'FAISS (fast ANN, requires faiss-cpu)', value: 'faiss' },
  { label: 'HNSW (lightweight ANN, requires hnswlib)', value: 'hnswlib' },
];

const MCP_CLIENTS = [
  { label: 'VS Code', value: 'vscode' },
  { label: 'Cursor', value: 'cursor' },
  { label: 'Claude Desktop', value: 'claude_desktop' },
  { label: 'Claude Code', value: 'claude_code' },
  { label: 'Kiro', value: 'kiro' },
  { label: 'Antigravity', value: 'antigravity' },
  { label: 'Windsurf', value: 'windsurf' },
  { label: 'Zed', value: 'zed' },
  { label: 'Cline', value: 'cline' },
  { label: 'OpenClaw', value: 'openclaw' },
];

const STEPS = ['Embedding Model', 'Vector Backend', 'MCP Clients', 'Review', 'Install'];

function getVenvPython() {
  // 1. Check OPENLMLIB_HOME environment variable
  if (process.env.OPENLMLIB_HOME) {
    const pyPath = os.platform() === 'win32'
      ? path.join(process.env.OPENLMLIB_HOME, 'venv', 'Scripts', 'python.exe')
      : path.join(process.env.OPENLMLIB_HOME, 'venv', 'bin', 'python');
    if (fs.existsSync(pyPath)) {
      return pyPath;
    }
  }

  // 2. Check for development .venv in repository root (parent of installer's parent)
  const moduleDir = path.dirname(fileURLToPath(import.meta.url));
  const installerDir = path.dirname(path.dirname(moduleDir));
  const repoRoot = path.dirname(installerDir);
  const devVenv = os.platform() === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python');
  if (fs.existsSync(devVenv)) {
    return devVenv;
  }

  // 3. Fall back to ~/.openlmlib/venv (installed location)
  const home = path.join(os.homedir(), '.openlmlib');
  return os.platform() === 'win32'
    ? path.join(home, 'venv', 'Scripts', 'python.exe')
    : path.join(home, 'venv', 'bin', 'python');
}

function runPythonScript(script) {
  const python = getVenvPython();
  const tmpPath = path.join(os.tmpdir(), `openlmlib-setup-${Date.now()}-${Math.random().toString(36).slice(2)}.py`);
  fs.writeFileSync(tmpPath, script);
  try {
    return execSync(`"${python}" "${tmpPath}"`, {
      stdio: ['pipe', 'pipe', 'pipe'],
      encoding: 'utf-8',
      timeout: 60000,
    });
  } catch (error) {
    const errorMsg = error.stderr ? error.stderr.toString() : error.message;
    console.error('Python script error:', errorMsg);
    throw error;
  } finally {
    try { fs.unlinkSync(tmpPath); } catch {}
  }
}

function StepIndicator({ current }) {
  return React.createElement(Box, { marginBottom: 1 },
    ...STEPS.map((s, i) => {
      const color = i < current ? 'green' : i === current ? 'cyan' : 'gray';
      const icon = i < current ? '✔' : i === current ? '●' : '○';
      return React.createElement(Text, { key: i, color, bold: i === current },
        ` ${icon} ${s} `
      );
    })
  );
}

function WelcomeScreen({ onNext }) {
  useInput(() => onNext());

  const BANNER = [
    '    ███████    ███████████  ██████████ ██████   █████ █████       ██████   ██████ █████       █████ ███████████',
    '  ███░░░░░███ ░░███░░░░░███░░███░░░░░█░░██████ ░░███ ░░███       ░░██████ ██████ ░░███       ░░███ ░░███░░░░░███',
    ' ███     ░░███ ░███    ░███ ░███  █ ░  ░███░███ ░███  ░███        ░███░█████░███  ░███        ░███  ░███    ░███',
    '░███      ░███ ░██████████  ░██████    ░███░░███░███  ░███        ░███░░███ ░███  ░███        ░███  ░██████████',
    '░███      ░███ ░███░░░░░░   ░███░░█    ░███ ░░██████  ░███        ░███ ░░░  ░███  ░███        ░███  ░███░░░░░███',
    '░░███     ███  ░███         ░███ ░   █ ░███  ░░█████  ░███      █ ░███      ░███  ░███      █ ░███  ░███    ░███',
    ' ░░░███████░   █████        ██████████ █████  ░░█████ ███████████ █████     █████ ███████████ █████ ███████████',
    '   ░░░░░░░    ░░░░░        ░░░░░░░░░░ ░░░░░    ░░░░░ ░░░░░░░░░░░ ░░░░░     ░░░░░ ░░░░░░░░░░░ ░░░░░ ░░░░░░░░░░░',
  ].join('\n');

  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Box, { marginBottom: 1 },
      React.createElement(Text, { color: 'cyan', bold: true }, BANNER),
    ),
    React.createElement(Box, { marginBottom: 1 },
      React.createElement(Text, { bold: true, color: 'white' }, '  Setup Wizard'),
    ),
    React.createElement(Box, { flexDirection: 'column', paddingLeft: 2 },
      React.createElement(Text, { color: 'gray' }, '  Configure your embedding model, vector backend, and MCP clients.'),
    ),
    React.createElement(Box, { marginTop: 2 },
      React.createElement(Text, { color: 'yellow', bold: true }, '  Press any key to begin...'),
    ),
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { color: 'gray' }, '  Press '),
      React.createElement(Text, { bold: true, color: 'white' }, 'Q'),
      React.createElement(Text, { color: 'gray' }, ' to quit'),
    )
  );
}

function ModelSelect({ value, onSelect, onNext }) {
  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Choose Embedding Model'),
    React.createElement(StepIndicator, { current: 0 }),
    React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
      React.createElement(SelectInput, {
        items: EMBEDDING_MODELS,
        initialIndex: EMBEDDING_MODELS.findIndex((m) => m.value === value),
        onSelect: (item) => {
          onSelect(item.value);
          onNext();
        },
      })
    ),
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { color: 'gray' }, 'Use '),
      React.createElement(Text, { bold: true, color: 'white' }, '↑↓'),
      React.createElement(Text, { color: 'gray' }, ' to navigate, '),
      React.createElement(Text, { bold: true, color: 'white' }, 'Enter'),
      React.createElement(Text, { color: 'gray' }, ' to select'),
    )
  );
}

function BackendSelect({ value, onSelect, onNext }) {
  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Choose Vector Backend'),
    React.createElement(StepIndicator, { current: 1 }),
    React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
      React.createElement(SelectInput, {
        items: VECTOR_BACKENDS,
        initialIndex: VECTOR_BACKENDS.findIndex((b) => b.value === value),
        onSelect: (item) => {
          onSelect(item.value);
          onNext();
        },
      })
    ),
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { color: 'gray' }, 'Use '),
      React.createElement(Text, { bold: true, color: 'white' }, '↑↓'),
      React.createElement(Text, { color: 'gray' }, ' to navigate, '),
      React.createElement(Text, { bold: true, color: 'white' }, 'Enter'),
      React.createElement(Text, { color: 'gray' }, ' to select'),
    )
  );
}

function McpMultiSelect({ selected, onComplete }) {
  const allClientValues = MCP_CLIENTS.map((c) => c.value);
  const [selectedIds, setSelectedIds] = useState(new Set(selected));
  const [cursorIdx, setCursorIdx] = useState(0);

  const isAllSelected = allClientValues.every((v) => selectedIds.has(v));

  useInput((input, key) => {
    if (key.upArrow) {
      setCursorIdx((i) => Math.max(0, i - 1));
    } else if (key.downArrow) {
      setCursorIdx((i) => Math.min(MCP_CLIENTS.length, i + 1));
    } else if (input === ' ') {
      if (cursorIdx === 0) {
        if (isAllSelected) {
          setSelectedIds(new Set());
        } else {
          setSelectedIds(new Set(allClientValues));
        }
      } else {
        const id = MCP_CLIENTS[cursorIdx - 1].value;
        const next = new Set(selectedIds);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setSelectedIds(next);
      }
    } else if (key.return) {
      onComplete([...selectedIds]);
    }
  });

  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Configure MCP Clients'),
    React.createElement(StepIndicator, { current: 2 }),
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { color: 'gray' }, 'Select which IDEs/clients to configure for MCP.'),
    ),
    React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
      (() => {
        const allCursor = cursorIdx === 0;
        const allCheck = isAllSelected ? '✔' : '○';
        const allColor = isAllSelected ? 'green' : 'gray';
        return React.createElement(Box, { key: 'all' },
          React.createElement(Text, { color: allCursor ? 'cyan' : 'gray' }, `  ▸ `),
          React.createElement(Text, { color: allColor }, `${allCheck} `),
          React.createElement(Text, { bold: true, color: allCursor ? 'white' : 'gray' }, 'Install for All'),
        );
      })(),
      ...MCP_CLIENTS.map((client, i) => {
        const isSelected = selectedIds.has(client.value);
        const isCursor = i === cursorIdx - 1;
        const cursor = isCursor ? '▸' : ' ';
        const check = isSelected ? '✔' : '○';
        const color = isSelected ? 'green' : 'gray';
        return React.createElement(Box, { key: client.value },
          React.createElement(Text, { color: isCursor ? 'cyan' : 'gray' }, `  ${cursor} `),
          React.createElement(Text, { color }, `${check} `),
          React.createElement(Text, { bold: isCursor, color: isCursor ? 'white' : 'gray' }, client.label),
        );
      })
    ),
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { color: 'gray' }, 'Press '),
      React.createElement(Text, { bold: true, color: 'white' }, 'Space'),
      React.createElement(Text, { color: 'gray' }, ' to toggle, '),
      React.createElement(Text, { bold: true, color: 'white' }, 'Enter'),
      React.createElement(Text, { color: 'gray' }, ' to continue'),
    )
  );
}

function ReviewScreen({ config, onConfirm }) {
  useInput((input, key) => {
    if (key.return) {
      onConfirm();
    }
  });

  const modelName = config.embeddingModel.split('/').pop();
  const backendLabel = VECTOR_BACKENDS.find((b) => b.value === config.vectorBackend)?.label.split('(')[0] || config.vectorBackend;

  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Configuration Summary'),
    React.createElement(StepIndicator, { current: 3 }),
    React.createElement(Box, { flexDirection: 'column', marginTop: 1, paddingLeft: 2 },
      React.createElement(Text, { color: 'white' }, `  Embedding model:  ${modelName}`),
      React.createElement(Text, { color: 'white' }, `  Vector backend:   ${backendLabel}`),
      React.createElement(Text, { color: 'white' }, `  MCP clients:      ${config.mcpClients.length > 0 ? config.mcpClients.join(', ') : 'none'}`),
    ),
    React.createElement(Box, { marginTop: 2 },
      React.createElement(Text, { color: 'green', bold: true }, '  Press Enter to install...'),
    ),
  );
}

function InstallScreen({ config, onDone }) {
  const [steps, setSteps] = useState([
    { label: 'Writing settings...', status: 'pending', error: null },
    { label: 'Initializing library...', status: 'pending', error: null },
    { label: 'Configuring MCP clients...', status: 'pending', error: null },
  ]);

  useEffect(() => {
    const updateStep = (idx, status, error = null) => {
      setSteps((prev) => {
        const next = [...prev];
        next[idx] = { ...next[idx], status, error };
        return next;
      });
    };

    try {
      updateStep(0, 'running');
      const settingsScript = [
        'import json',
        'from pathlib import Path',
        'from openlmlib.settings import write_default_settings, default_settings_payload',
        'from openlmlib.mcp_setup import global_settings_path',
        'settings_path = global_settings_path()',
        'settings_path.parent.mkdir(parents=True, exist_ok=True)',
        'payload = default_settings_payload()',
        `payload['embedding_model'] = '${config.embeddingModel}'`,
        `payload['vector_backend'] = '${config.vectorBackend}'`,
        'with open(settings_path, "w") as f:',
        '    json.dump(payload, f, indent=2)',
        "print('ok')",
      ].join('\n');
      try {
        runPythonScript(settingsScript);
        updateStep(0, 'done');
      } catch (err) {
        const errMsg = err.stderr?.toString() || err.message || 'Unknown error';
        console.error('Settings error:', errMsg);
        updateStep(0, 'error', errMsg);
        setTimeout(() => onDone(false), 2000);
        return;
      }

      updateStep(1, 'running');
      const initScript = [
        'from pathlib import Path',
        'from openlmlib.library import init_library',
        'from openlmlib.mcp_setup import global_settings_path',
        'result = init_library(global_settings_path())',
        "print(result.get('status', 'error'))",
      ].join('\n');
      try {
        runPythonScript(initScript);
        updateStep(1, 'done');
      } catch (err) {
        const errMsg = err.stderr?.toString() || err.message || 'Unknown error';
        console.error('Init error:', errMsg);
        updateStep(1, 'error', errMsg);
        setTimeout(() => onDone(false), 2000);
        return;
      }

      if (config.mcpClients.length > 0) {
        updateStep(2, 'running');
        const clientsJson = JSON.stringify(config.mcpClients);
        const mcpScript = [
          'from pathlib import Path',
          'from openlmlib.mcp_setup import available_clients, install_client_configs, global_settings_path',
          'import json',
          `clients = ${clientsJson}`,
          'supported = {client.id for client in available_clients()}',
          'filtered = [client_id for client_id in clients if client_id in supported]',
          'skipped = [client_id for client_id in clients if client_id not in supported]',
          'if skipped:',
          '    print(json.dumps({"skipped": skipped}))',
          'result = install_client_configs(filtered, settings_path=global_settings_path())',
          "print(result.get('status', 'error'))",
        ].join('\n');
        try {
          runPythonScript(mcpScript);
          updateStep(2, 'done');
        } catch (err) {
          const errMsg = err.stderr?.toString() || err.message || 'Unknown error';
          console.error('MCP error:', errMsg);
          updateStep(2, 'error', errMsg);
          setTimeout(() => onDone(false), 2000);
          return;
        }
      } else {
        setSteps((prev) => {
          const next = [...prev];
          next[2] = { ...next[2], label: 'MCP config skipped', status: 'done' };
          return next;
        });
      }

      setTimeout(() => onDone(true), 1000);
    } catch (err) {
      const idx = steps.findIndex((s) => s.status === 'running');
      updateStep(idx >= 0 ? idx : 0, 'error');
      setTimeout(() => onDone(false), 2000);
    }
  }, []);

  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Installing...'),
    React.createElement(StepIndicator, { current: 4 }),
    React.createElement(Box, { flexDirection: 'column', marginTop: 1 },
      ...steps.map((step, i) => {
        let icon;
        let color;
        if (step.status === 'running') {
          icon = React.createElement(Spinner, { type: 'dots' });
          color = 'yellow';
        } else if (step.status === 'done') {
          icon = React.createElement(Text, { color: 'green' }, '✔');
          color = 'green';
        } else if (step.status === 'error') {
          icon = React.createElement(Text, { color: 'red' }, '✖');
          color = 'red';
        } else {
          icon = React.createElement(Text, { color: 'gray' }, '·');
          color = 'gray';
        }
        return React.createElement(Box, { key: i, flexDirection: 'column' },
          React.createElement(Box, {},
            icon,
            React.createElement(Text, { color }, ` ${step.label}`),
          ),
          step.error ? React.createElement(Text, { color: 'red', paddingLeft: 2 }, `  Error: ${step.error}`) : null,
        );
      })
    ),
  );
}

function CompleteScreen({ success }) {
  if (success) {
    return React.createElement(Box, { flexDirection: 'column', padding: 1 },
      React.createElement(Text, { bold: true, color: 'green' }, '✔  Setup complete!'),
      React.createElement(Box, { flexDirection: 'column', marginTop: 2 },
        React.createElement(Text, { bold: true, color: 'cyan' }, '  Quick Start:'),
        React.createElement(Box, { flexDirection: 'column', paddingLeft: 2, marginTop: 1 },
          React.createElement(Text, { color: 'gray' }, '  openlmlib add --project myproj --claim "..." --confidence 0.8'),
          React.createElement(Text, { color: 'gray' }, '  openlmlib query "your search query"'),
          React.createElement(Text, { color: 'gray' }, '  openlmlib mcp'),
          React.createElement(Text, { color: 'gray' }, '  openlmlib doctor'),
        ),
      ),
      React.createElement(Box, { marginTop: 2 },
        React.createElement(Text, { color: 'gray' }, '  Restart VS Code / Cursor / Claude Desktop to activate MCP.'),
      ),
    );
  }

  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'red' }, '✖  Setup failed'),
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { color: 'gray' }, '  Check the error output above and try again.'),
    ),
  );
}

function SetupWizard() {
  const { exit } = useApp();
  const [screen, setScreen] = useState('welcome');
  const [config, setConfig] = useState({
    embeddingModel: 'sentence-transformers/all-MiniLM-L6-v2',
    vectorBackend: 'numpy',
    mcpClients: ['vscode'],
  });
  const [installSuccess, setInstallSuccess] = useState(null);

  if (screen === 'welcome') {
    return React.createElement(WelcomeScreen, { onNext: () => setScreen('model') });
  }

  if (screen === 'model') {
    return React.createElement(ModelSelect, {
      value: config.embeddingModel,
      onSelect: (v) => setConfig((c) => ({ ...c, embeddingModel: v })),
      onNext: () => setScreen('backend'),
    });
  }

  if (screen === 'backend') {
    return React.createElement(BackendSelect, {
      value: config.vectorBackend,
      onSelect: (v) => setConfig((c) => ({ ...c, vectorBackend: v })),
      onNext: () => setScreen('mcp'),
    });
  }

  if (screen === 'mcp') {
    return React.createElement(McpMultiSelect, {
      selected: config.mcpClients,
      onComplete: (clients) => {
        setConfig((c) => ({ ...c, mcpClients: clients }));
        setScreen('review');
      },
    });
  }

  if (screen === 'review') {
    return React.createElement(ReviewScreen, {
      config,
      onConfirm: () => setScreen('install'),
    });
  }

  if (screen === 'install') {
    return React.createElement(InstallScreen, {
      config,
      onDone: (success) => {
        setInstallSuccess(success);
        setScreen('complete');
      },
    });
  }

  if (screen === 'complete') {
    return React.createElement(CompleteScreen, { success: installSuccess });
  }

  return React.createElement(Text, { color: 'red' }, 'Unknown screen');
}

export default SetupWizard;
