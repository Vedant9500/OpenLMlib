import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import SelectInput from 'ink-select-input';

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

function Wizard({ config, onComplete }) {
  const [step, setStep] = useState(0);
  const [model, setModel] = useState(config.embeddingModel);
  const [backend, setBackend] = useState(config.vectorBackend);
  const [mcpClients, setMcpClients] = useState(config.mcpClients);
  const [mcpToggleIdx, setMcpToggleIdx] = useState(0);

  const allClientValues = MCP_CLIENTS.map((c) => c.value);
  const isAllSelected = allClientValues.every((v) => mcpClients.includes(v));

  const toggleMcp = (value) => {
    if (mcpClients.includes(value)) {
      setMcpClients(mcpClients.filter((c) => c !== value));
    } else {
      setMcpClients([...mcpClients, value]);
    }
  };

  const toggleAll = () => {
    if (isAllSelected) {
      setMcpClients([]);
    } else {
      setMcpClients([...allClientValues]);
    }
  };

  const handleNext = () => {
    if (step === 0) {
      setStep(1);
    } else if (step === 1) {
      setStep(2);
    } else if (step === 2) {
      setStep(3);
    } else {
      onComplete({
        embeddingModel: model,
        vectorBackend: backend,
        mcpClients,
      });
    }
  };

  useInput((input, key) => {
    if (input === 'q' || (key && key.escape)) {
      process.exit(0);
    }
    if (input === '\r' || (key && key.return)) {
      handleNext();
    }
    if (step === 2 && (input === ' ')) {
      if (mcpToggleIdx === 0) {
        toggleAll();
      } else {
        toggleMcp(MCP_CLIENTS[mcpToggleIdx - 1].value);
      }
    }
    if (step === 2 && (key && key.downArrow)) {
      setMcpToggleIdx((i) => Math.min(i + 1, MCP_CLIENTS.length));
    }
    if (step === 2 && (key && key.upArrow)) {
      setMcpToggleIdx((i) => Math.max(i - 1, 0));
    }
  });

  const steps = ['Embedding Model', 'Vector Backend', 'MCP Clients', 'Review'];

  if (step === 0) {
    return React.createElement(Box, { flexDirection: 'column', padding: 1 },
      React.createElement(Text, { bold: true, color: 'cyan' }, 'Choose Embedding Model'),
      React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
        React.createElement(SelectInput, {
          items: EMBEDDING_MODELS,
          initialIndex: EMBEDDING_MODELS.findIndex((m) => m.value === model),
          onSelect: (item) => setModel(item.value),
        })
      ),
      React.createElement(Box, { marginTop: 1 },
        React.createElement(Text, { color: 'gray' }, 'Press '),
        React.createElement(Text, { bold: true, color: 'white' }, 'Enter'),
        React.createElement(Text, { color: 'gray' }, ' to continue'),
      )
    );
  }

  if (step === 1) {
    return React.createElement(Box, { flexDirection: 'column', padding: 1 },
      React.createElement(Text, { bold: true, color: 'cyan' }, 'Choose Vector Backend'),
      React.createElement(Box, { marginTop: 1, flexDirection: 'column' },
        React.createElement(SelectInput, {
          items: VECTOR_BACKENDS,
          initialIndex: VECTOR_BACKENDS.findIndex((b) => b.value === backend),
          onSelect: (item) => setBackend(item.value),
        })
      ),
      React.createElement(Box, { marginTop: 1 },
        React.createElement(Text, { color: 'gray' }, 'Press '),
        React.createElement(Text, { bold: true, color: 'white' }, 'Enter'),
        React.createElement(Text, { color: 'gray' }, ' to continue'),
      )
    );
  }

  if (step === 2) {
    return React.createElement(Box, { flexDirection: 'column', padding: 1 },
      React.createElement(Text, { bold: true, color: 'cyan' }, 'Configure MCP Clients'),
      React.createElement(Text, { color: 'gray', marginTop: 1 }, '  Select which IDEs/clients to configure for MCP.'),
      React.createElement(Box, { flexDirection: 'column', marginTop: 1 },
        (() => {
          const allActive = mcpToggleIdx === 0;
          const allCheck = isAllSelected ? '✔' : '○';
          const allColor = isAllSelected ? 'green' : 'gray';
          return React.createElement(Box, { key: 'all' },
            React.createElement(Text, { color: allActive ? 'cyan' : 'gray' }, `  ▸ `),
            React.createElement(Text, { color: allColor }, `${allCheck} `),
            React.createElement(Text, { bold: allActive, color: allActive ? 'white' : 'gray' }, 'Install for All'),
          );
        })(),
        ...MCP_CLIENTS.map((client, i) => {
          const selected = mcpClients.includes(client.value);
          const active = i === mcpToggleIdx - 1;
          const cursor = active ? '▸' : ' ';
          const check = selected ? '✔' : '○';
          const color = selected ? 'green' : 'gray';
          return React.createElement(Box, { key: client.value },
            React.createElement(Text, { color: active ? 'cyan' : 'gray' }, `  ${cursor} `),
            React.createElement(Text, { color }, `${check} `),
            React.createElement(Text, { bold: active }, client.label),
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

  const modelName = model.split('/').pop();
  const backendLabel = VECTOR_BACKENDS.find((b) => b.value === backend)?.label.split('(')[0] || backend;
  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Configuration Summary'),
    React.createElement(Box, { flexDirection: 'column', marginTop: 1, paddingLeft: 2 },
      React.createElement(Text, {}, `  Embedding model:  ${modelName}`),
      React.createElement(Text, {}, `  Vector backend:   ${backendLabel}`),
      React.createElement(Text, {}, `  MCP clients:      ${mcpClients.length > 0 ? mcpClients.join(', ') : 'none'}`),
    ),
    React.createElement(Box, { marginTop: 2 },
      React.createElement(Text, { color: 'green', bold: true }, '  Press Enter to start installation...'),
    ),
  );
}

export default Wizard;
