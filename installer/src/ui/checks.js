import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';

function Checks({ checks }) {
  if (!checks) {
    return React.createElement(Box, { padding: 1 },
      React.createElement(Spinner, { type: 'dots' }),
      React.createElement(Text, { color: 'gray' }, '  Running prerequisite checks...')
    );
  }

  const renderCheck = (label, ok, detail) => {
    const icon = ok ? '✔' : '✖';
    const color = ok ? 'green' : 'red';
    return React.createElement(Box, { key: label },
      React.createElement(Text, { color }, `  ${icon} `),
      React.createElement(Text, { bold: true }, `${label}`),
      detail ? React.createElement(Text, { color: 'gray' }, ` — ${detail}`) : null,
    );
  };

  const pythonOk = checks.python && checks.python.found && checks.python.ok;

  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Prerequisite Checks'),
    React.createElement(Box, { flexDirection: 'column', marginTop: 1 },
      renderCheck(
        'Python',
        pythonOk,
        checks.python.found
          ? `${checks.python.version}${checks.python.ok ? '' : ' (requires 3.10+)'}`
          : 'not found'
      ),
      renderCheck('pip', checks.pip),
      renderCheck('venv', checks.venv),
    ),
    !pythonOk && React.createElement(Box, { flexDirection: 'column', marginTop: 2 },
      React.createElement(Text, { color: 'yellow', bold: true }, '  ⚠ Python 3.10+ not found.'),
      React.createElement(Text, { color: 'gray' }, '  Attempting automatic installation...'),
    ),
  );
}

export default Checks;
