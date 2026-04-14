import React, { useState, useEffect } from 'react';
import { Box, Text, useApp } from 'ink';
import Spinner from 'ink-spinner';

import Welcome from './welcome.js';
import Checks from './checks.js';
import Progress from './progress.js';
import Wizard from './wizard.js';
import Complete from './complete.js';

import {
  checkPythonVersion,
  checkPip,
  checkVenv,
  createVenv,
  installFromLocal,
  downloadModel,
  runSetupWizard,
} from '../install.js';

import { installPython } from '../python-install.js';
import path from 'path';

function App({ pythonCheck, hasPackageManager, installerDir }) {
  const { exit } = useApp();
  const [screen, setScreen] = useState('welcome');
  const [checks, setChecks] = useState(null);
  const [pythonInstallStatus, setPythonInstallStatus] = useState(null);
  const [installSteps, setInstallSteps] = useState([]);
  const [wizardConfig, setWizardConfig] = useState({
    embeddingModel: 'sentence-transformers/all-MiniLM-L6-v2',
    vectorBackend: 'numpy',
    mcpClients: ['vscode', 'claude_code', 'gemini_cli', 'qwen_code', 'opencode'],
  });

  useEffect(() => {
    if (screen === 'checks') {
      const results = {
        python: checkPythonVersion(),
        pip: checkPip(),
        venv: checkVenv(),
      };
      setChecks(results);

      if (!results.python.found && hasPackageManager) {
        setTimeout(() => setScreen('python-install'), 1500);
      } else if (!results.python.found) {
        setTimeout(() => setScreen('complete'), 1500);
      } else if (!results.python.ok) {
        setTimeout(() => {
          if (hasPackageManager) {
            setScreen('python-install');
          } else {
            setScreen('complete');
          }
        }, 1500);
      } else {
        setTimeout(() => setScreen('installing'), 1500);
      }
    }
  }, [screen]);

  useEffect(() => {
    if (screen === 'python-install') {
      installPython((err, result) => {
        setPythonInstallStatus(result);
        if (result.success) {
          setTimeout(() => setScreen('installing'), 2000);
        } else {
          setTimeout(() => setScreen('complete'), 2000);
        }
      });
    }
  }, [screen]);

  useEffect(() => {
    if (screen === 'installing') {
      const steps = [];

      const addStep = (label) => {
        steps.push({ label, status: 'pending' });
        setInstallSteps([...steps]);
        return steps.length - 1;
      };

      const updateStep = (index, status) => {
        steps[index] = { ...steps[index], status };
        setInstallSteps([...steps]);
      };

      const run = async () => {
        try {
          const s1 = addStep('Creating virtual environment...');
          updateStep(s1, 'running');
          createVenv((msg) => updateStep(s1, 'done'));
          updateStep(s1, 'done');

          const s2 = addStep('Installing openlmlib...');
          updateStep(s2, 'running');
          installFromLocal(path.resolve(installerDir, '..', '..'), (msg) => updateStep(s2, 'done'));
          updateStep(s2, 'done');

          const s3 = addStep('Downloading embedding model...');
          updateStep(s3, 'running');
          downloadModel(wizardConfig.embeddingModel, (msg) => updateStep(s3, 'done'));
          updateStep(s3, 'done');

          const s4 = addStep('Configuring MCP clients...');
          updateStep(s4, 'running');
          runSetupWizard(wizardConfig, (msg) => updateStep(s4, 'done'));
          updateStep(s4, 'done');

          setTimeout(() => setScreen('complete'), 1000);
        } catch (err) {
          const sErr = addStep(`Error: ${err.message}`);
          updateStep(sErr, 'error');
          setTimeout(() => setScreen('complete'), 2000);
        }
      };

      run();
    }
  }, [screen]);

  if (screen === 'welcome') {
    return React.createElement(Welcome, { onNext: () => setScreen('checks') });
  }

  if (screen === 'checks') {
    return React.createElement(Checks, { checks });
  }

  if (screen === 'python-install') {
    return React.createElement(Box, { flexDirection: 'column', padding: 1 },
      React.createElement(Text, { bold: true, color: 'cyan' }, 'Installing Python...'),
      React.createElement(Box, { marginTop: 1 },
        React.createElement(Spinner, { type: 'dots' }),
        React.createElement(Text, { color: 'gray' }, ' ',
          pythonInstallStatus ? pythonInstallStatus.message : 'Detecting package manager...')
      )
    );
  }

  if (screen === 'installing') {
    return React.createElement(Progress, { steps: installSteps });
  }

  if (screen === 'wizard') {
    return React.createElement(Wizard, {
      config: wizardConfig,
      onComplete: (config) => {
        setWizardConfig(config);
        setScreen('installing');
      },
    });
  }

  if (screen === 'complete') {
    const success = checks && checks.python && checks.python.found && checks.python.ok;
    return React.createElement(Complete, {
      success,
      checks,
      pythonInstallStatus,
    });
  }

  return React.createElement(Text, { color: 'red' }, 'Unknown screen');
}

export default App;
