import React from 'react';
import { Box, Text } from 'ink';

function Complete({ success, checks, pythonInstallStatus }) {
  const pythonOk = checks && checks.python && checks.python.found && checks.python.ok;
  const isPythonError = !pythonOk && pythonInstallStatus && !pythonInstallStatus.success;

  if (isPythonError) {
    return React.createElement(Box, { flexDirection: 'column', padding: 1 },
      React.createElement(Text, { bold: true, color: 'red' }, 'Installation Failed'),
      React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
        React.createElement(Text, { color: 'red' }, `  ${pythonInstallStatus.message}`),
      ),
      React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
        React.createElement(Text, { color: 'gray' }, '  Please install Python 3.10+ manually:'),
        React.createElement(Text, { color: 'gray' }, '  • Windows: https://www.python.org/downloads/'),
        React.createElement(Text, { color: 'gray' }, '  • macOS:   brew install python@3.12'),
        React.createElement(Text, { color: 'gray' }, '  • Linux:   sudo apt install python3 python3-pip python3-venv'),
        React.createElement(Box, { marginTop: 1 },
          React.createElement(Text, { color: 'gray' }, '  Then run: '),
          React.createElement(Text, { bold: true, color: 'white' }, 'npm install -g openlmlib'),
        )
      )
    );
  }

  if (!pythonOk) {
    return React.createElement(Box, { flexDirection: 'column', padding: 1 },
      React.createElement(Text, { bold: true, color: 'yellow' }, '⚠  Python Not Found'),
      React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
        React.createElement(Text, { color: 'yellow' }, '  OpenLMlib requires Python 3.10+.'),
      ),
      React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
        React.createElement(Text, { color: 'gray' }, '  Please install Python and try again:'),
        React.createElement(Text, { color: 'gray' }, '  https://www.python.org/downloads/'),
      )
    );
  }

  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'green' }, '✔  OpenLMlib installed successfully!'),
    React.createElement(Box, { flexDirection: 'column', marginTop: 2 },
      React.createElement(Text, { bold: true, color: 'cyan' }, '  Quick Start:'),
      React.createElement(Box, { flexDirection: 'column', paddingLeft: 2, marginTop: 1 },
        React.createElement(Text, { color: 'gray' }, '  # Initialize your library'),
        React.createElement(Text, { color: 'white' }, '  openlmlib init'),
        React.createElement(Box, { marginTop: 1 }),
        React.createElement(Text, { color: 'gray' }, '  # Add a finding'),
        React.createElement(Text, { color: 'white' }, '  openlmlib add --project myproj --claim "..." --confidence 0.8'),
        React.createElement(Box, { marginTop: 1 }),
        React.createElement(Text, { color: 'gray' }, '  # Search findings'),
        React.createElement(Text, { color: 'white' }, '  openlmlib query "your search query"'),
        React.createElement(Box, { marginTop: 1 }),
        React.createElement(Text, { color: 'gray' }, '  # Start MCP server for IDE integration'),
        React.createElement(Text, { color: 'white' }, '  openlmlib setup'),
        React.createElement(Box, { marginTop: 1 }),
        React.createElement(Text, { color: 'gray' }, '  # Check library health'),
        React.createElement(Text, { color: 'white' }, '  openlmlib doctor'),
      ),
    ),
    React.createElement(Box, { flexDirection: 'column', marginTop: 2 },
      React.createElement(Text, { bold: true, color: 'cyan' }, '  MCP Integration:'),
      React.createElement(Text, { color: 'gray' }, '  OpenLMlib is now available as an MCP server in your IDEs.'),
      React.createElement(Text, { color: 'gray' }, '  Restart VS Code / Cursor / Claude Desktop to activate.'),
    ),
    React.createElement(Box, { marginTop: 2 },
      React.createElement(Text, { color: 'gray' }, '  Docs: https://github.com/Vedant9500/OpenLMlib'),
    ),
  );
}

export default Complete;
