#!/usr/bin/env node
/**
 * Verify the npm package before publishing.
 *
 * Runs after bundle-python.js has copied the Python source into installer/.
 * Fails the pack/publish when the package metadata, the bundled MCP tool
 * surface, and the README disagree.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const INSTALLER_DIR = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(INSTALLER_DIR, '..');

const errors = [];
const notes = [];

function fail(message) {
  errors.push(message);
}

function read(filePath) {
  return fs.readFileSync(filePath, 'utf-8');
}

// --- Version consistency -------------------------------------------------

const packageJson = JSON.parse(read(path.join(INSTALLER_DIR, 'package.json')));
const initSource = read(path.join(REPO_ROOT, 'openlmlib', '__init__.py'));
const initVersion = (initSource.match(/^__version__\s*=\s*["']([^"']+)["']/m) || [])[1];

if (!initVersion) {
  fail('Could not read __version__ from openlmlib/__init__.py');
} else if (initVersion !== packageJson.version) {
  fail(
    `Version mismatch: installer/package.json is ${packageJson.version} but ` +
      `openlmlib/__init__.py is ${initVersion}`,
  );
} else {
  notes.push(`version ${packageJson.version}`);
}

// --- Bundled tool surface -------------------------------------------------

const mcpServerPath = path.join(INSTALLER_DIR, 'openlmlib', 'mcp_server.py');
if (!fs.existsSync(mcpServerPath)) {
  fail('Bundled source is missing: installer/openlmlib/mcp_server.py (run bundle-python.js first)');
}

let toolNames = new Set();
let toolCount = 0;

if (fs.existsSync(mcpServerPath)) {
  const source = read(mcpServerPath);
  const collabRegistrations = [...source.matchAll(/mcp\.tool\(\)\((\w+)\)/g)].map((m) => m[1]);
  const decoratedTools = [...source.matchAll(/@mcp\.tool\(\)\s*\n\s*(?:async\s+)?def\s+(\w+)/g)].map(
    (m) => m[1],
  );

  toolNames = new Set([...collabRegistrations, ...decoratedTools]);
  toolCount = toolNames.size;

  if (toolNames.size !== collabRegistrations.length + decoratedTools.length) {
    fail('Duplicate tool registration detected in mcp_server.py');
  }
}

// --- README claims --------------------------------------------------------

const readmePath = path.join(INSTALLER_DIR, 'README.md');
const readme = read(readmePath);

if (!/^#\s+OpenLMlib\s*$/m.test(readme)) {
  fail('README.md must start with a "# OpenLMlib" heading');
}

const claimedCounts = [...readme.matchAll(/(\d+)\s+MCP\s+tools|(\d+)\s+tools\b/gi)].map((m) =>
  Number(m[1] ?? m[2]),
);
const distinctClaims = [...new Set(claimedCounts)];
for (const claim of distinctClaims) {
  if (claim !== toolCount) {
    fail(`README claims ${claim} tools but the bundled package registers ${toolCount}`);
  }
}

const groupClaims = {
  core: /Core library\s*\|\s*(\d+)/,
  memory: /Memory\s*\|\s*(\d+)/,
  collaboration: /Collaboration\s*\|\s*(\d+)/,
};
let groupTotal = 0;
for (const [group, pattern] of Object.entries(groupClaims)) {
  const match = readme.match(pattern);
  if (!match) {
    fail(`README tool table is missing the ${group} group`);
    continue;
  }
  groupTotal += Number(match[1]);
}
if (groupTotal && groupTotal !== toolCount) {
  fail(`README tool groups total ${groupTotal} but the bundled package registers ${toolCount}`);
}

const descriptionClaim = (packageJson.description || '').match(/(\d+)-tool/);
if (descriptionClaim && Number(descriptionClaim[1]) !== toolCount) {
  fail(
    `package.json description claims ${descriptionClaim[1]} tools but the bundled package registers ${toolCount}`,
  );
}

// --- Required tools -------------------------------------------------------

const requiredTools = [
  'init_library',
  'save_finding',
  'search_findings',
  'retrieve_findings',
  'session_start',
  'session_recap',
  'create_session',
  'send_message',
  'create_co_scientist_run',
  'submit_hypothesis',
  'submit_verification',
  'create_co_scientist_final_report',
];

for (const name of requiredTools) {
  if (!toolNames.has(name)) {
    fail(`Required tool is not registered by the bundled source: ${name}`);
  }
}

// --- Installer gate -------------------------------------------------------

const postinstallPath = path.join(INSTALLER_DIR, 'src', 'postinstall.mjs');
const postinstall = read(postinstallPath);
const gateMatch = postinstall.match(/len\(tools\)\s*<\s*(\d+)/);
if (!gateMatch) {
  fail('src/postinstall.mjs no longer contains an MCP tool-count gate');
} else if (Number(gateMatch[1]) !== toolCount) {
  fail(
    `src/postinstall.mjs requires at least ${gateMatch[1]} tools but the package registers ${toolCount}`,
  );
}

// --- Stale release text ---------------------------------------------------

const staleMarkers = [
  { pattern: /Should output:/i, reason: 'contains a hardcoded expected tool count' },
  { pattern: /THIS IS NEW/i, reason: 'contains release scratch notes' },
  { pattern: /Only seeing \d+ tools/i, reason: 'contains an old troubleshooting heading' },
  { pattern: /\bopenlmlib-\d+\.\d+\.\d+\.tgz\b/i, reason: 'references a hardcoded tarball name' },
  { pattern: /\bD:\\LMlib\\/i, reason: 'contains a local Windows path' },
];

for (const { pattern, reason } of staleMarkers) {
  if (pattern.test(readme)) {
    fail(`README.md ${reason}`);
  }
}

// --- Result ---------------------------------------------------------------

if (errors.length > 0) {
  console.error('\nPackage verification failed:\n');
  for (const error of errors) {
    console.error(`  - ${error}`);
  }
  console.error('\nFix the issues above before packing or publishing.\n');
  process.exit(1);
}

console.log(
  `Package verification passed: openlmlib ${packageJson.version}, ${toolCount} MCP tools, README consistent.`,
);
