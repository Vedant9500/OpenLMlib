import React from 'react';
import { Box, Text, useInput } from 'ink';

const LOGO = [
  '    ███████    ███████████  ██████████ ██████   █████ █████       ██████   ██████ █████       █████ ███████████',
  '  ███░░░░░███ ░░███░░░░░███░░███░░░░░█░░██████ ░░███ ░░███       ░░██████ ██████ ░░███       ░░███ ░░███░░░░░███',
  ' ███     ░░███ ░███    ░███ ░███  █ ░  ░███░███ ░███  ░███        ░███░█████░███  ░███        ░███  ░███    ░███',
  '░███      ░███ ░██████████  ░██████    ░███░░███░███  ░███        ░███░░███ ░███  ░███        ░███  ░██████████',
  '░███      ░███ ░███░░░░░░   ░███░░█    ░███ ░░██████  ░███        ░███ ░░░  ░███  ░███        ░███  ░███░░░░░███',
  '░░███     ███  ░███         ░███ ░   █ ░███  ░░█████  ░███      █ ░███      ░███  ░███      █ ░███  ░███    ░███',
  ' ░░░███████░   █████        ██████████ █████  ░░█████ ███████████ █████     █████ ███████████ █████ ███████████',
  '   ░░░░░░░    ░░░░░        ░░░░░░░░░░ ░░░░░    ░░░░░ ░░░░░░░░░░░ ░░░░░     ░░░░░ ░░░░░░░░░░░ ░░░░░ ░░░░░░░░░░░',
];

function Welcome({ onNext }) {
  useInput((input, key) => {
    if (input === 'q' || (key && key.escape)) {
      process.exit(0);
    }
    if (input || key) {
      onNext();
    }
  });

  return React.createElement(Box, {
    flexDirection: 'column',
    padding: 1,
  },
    React.createElement(Box, { marginBottom: 2 },
      React.createElement(Text, { color: 'cyan' }, LOGO.join('\n')),
    ),
    React.createElement(Box, { marginBottom: 1 },
      React.createElement(Text, { bold: true, color: 'white' }, '  AI-Powered Knowledge Library for LLM Agents'),
    ),
    React.createElement(Box, { flexDirection: 'column', paddingLeft: 2 },
      React.createElement(Text, { color: 'gray' }, '  Store, manage, and retrieve findings with semantic search.'),
      React.createElement(Text, { color: 'gray' }, '  Integrates with VS Code, Cursor, Claude Desktop & more via MCP.'),
    ),
    React.createElement(Box, { marginTop: 2, flexDirection: 'column' },
      React.createElement(Text, { color: 'green', bold: true }, '  What you get:'),
      React.createElement(Text, { color: 'gray' }, '  • Dual-index retrieval (semantic + lexical BM25)'),
      React.createElement(Text, { color: 'gray' }, '  • Cross-encoder reranking & query expansion'),
      React.createElement(Text, { color: 'gray' }, '  • Context packing & document decomposition'),
      React.createElement(Text, { color: 'gray' }, '  • Write gate validation & contradiction detection'),
      React.createElement(Text, { color: 'gray' }, '  • Maintenance engine with staleness tracking'),
    ),
    React.createElement(Box, { marginTop: 2 },
      React.createElement(Text, { color: 'yellow', bold: true }, '  Press any key to begin installation...'),
    ),
    React.createElement(Box, { marginTop: 1 },
      React.createElement(Text, { color: 'gray' }, '  Press '),
      React.createElement(Text, { bold: true, color: 'white' }, 'Q'),
      React.createElement(Text, { color: 'gray' }, ' to quit'),
    )
  );
}

export default Welcome;
