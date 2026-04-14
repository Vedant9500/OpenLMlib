# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

## [0.2.5] - 2026-04-14

### Added
- **MCP CLI Integration**: Global MCP configuration for 6 popular CLI coding tools
  - Claude Code (`~/.claude.json`)
  - Gemini CLI (`~/.gemini/settings.json`)
  - Qwen Code (`~/.qwen/settings.json`)
  - OpenCode (`~/.config/opencode/opencode.json`)
  - Codex CLI (`~/.codex/config.toml` with TOML support)
  - Aider (`~/.aider.conf.yml`)
- **Memory System MCP Tools**: 10 new memory tools exposed via MCP
  - `memory_session_start`, `memory_session_end` - Session lifecycle
  - `memory_log_observation` - Tool execution logging
  - `memory_search`, `memory_timeline`, `memory_get_observations` - Progressive retrieval (3-layer)
  - `memory_inject_context`, `memory_quick_recap`, `memory_detailed_context` - Context injection
  - `memory_retroactive_ingest` - Git history ingestion (no manual logging!)
- **TOML Support**: Native TOML parsing and serialization for Codex CLI configuration
- **Documentation**: Complete memory system guide, updated MCP tools reference (52 tools)

### Changed
- **Version bump**: 0.2.0 → 0.2.5
- **MCP tool count**: Fixed from 41 to 52 (11 core + 10 memory + 31 collab)
- **Documentation structure**: Moved memory docs to `docs/`, cleaned up internal implementation docs
- **requirements.txt**: Aligned version constraints with `pyproject.toml`
- **README.md**: Updated installation instructions for npm package workflow

### Removed
- Internal implementation summaries (`MEMORY_*`, `CAVEMAN_*`, `IMPLEMENTATION_PLAN.md`)
- Temporary test/refactor scripts

### Fixed
- `count_mcp_tools.py` now expects 52 tools and tracks memory tools separately
- CLI help text updated to include all 16 supported clients
- `package.json` at root marked as private (actual npm package in `installer/`)

## [0.2.0] - 2026-04-08

### Added
- **Collaborative Sessions System**: Full multi-user collaboration with real-time messaging
  - Collaboration database (`collab/db.py`) with SQLite backend
  - Message bus for asynchronous communication between agents
  - Session management with lifecycle tracking
  - Artifact store for sharing files and documents
  - State manager for persistent session state
  - Context compiler for efficient context assembly
- **MCP Server Integration**: Complete MCP server for collaboration tools
  - 20+ MCP tools for session management, messaging, and artifacts
  - FastMCP-based server with proper error handling
- **Collaboration TUI**: Interactive terminal UI for managing sessions
  - Session browser and viewer
  - Real-time message display
  - Participant management
- **Multi-Session Support**: Manage multiple concurrent collaboration sessions
- **Security & Access Control**: 
  - Permission system for session operations
  - Role-based access (owner, admin, participant, viewer)
  - Input validation and sanitization
- **Rules Engine**: Configurable rules for session behavior and message handling
- **Compaction System**: Automatic session history compaction for performance
- **Prompt Templates**: Built-in prompt templates for collaboration scenarios
- **Error Handling Framework**: Comprehensive error types and validation
- **OpenRouter Integration**: Client for external LLM integration
- **Export Bridge**: Export collaboration artifacts to main library
- **Templates System**: Session templates for common collaboration patterns
- **CLI Commands**: New collaboration commands in main CLI
  - Session creation, joining, and management
  - Message operations and artifact handling
- **Comprehensive Test Suite**: Unit, integration, live, and benchmark tests
- **Example Scripts**: Collaboration session usage examples
- **Installer Improvements**: 
  - Python bundling support
  - Enhanced setup wizard
  - Verification tools for Windows
  - Better cross-platform support
- **MCP Diagnostic Scripts**: Tools for troubleshooting MCP configuration

### Changed
- Enhanced CLI with 494+ new lines of collaboration commands
- Updated MCP server setup with new collaboration tools
- Improved installer with better UX and reliability
- Expanded package entry points with new CLI tools

### Technical
- Added 33 new modules in `openlmlib/collab/` package
- 12,000+ lines of production code added
- Full test coverage with 4 test files and benchmarks

## [0.1.2] - 2026-04-01

### Added
- MCP setup module (`mcp_setup.py`) to manage client specifications and configuration paths for various IDEs.
- Interactive TUI setup (`tui_setup.py`) allowing users to select IDEs for MCP installation.
- Health check tests for vector store validation.
- MCP setup tests to ensure correct installation and configuration.
- Release workflow for TestPyPI and PyPI publishing with trusted publishing.
- CLI safety commands: `backup` and `restore`.
- CLI `--version` output and package version constant.
- Library backup and restore operations with pre-restore backup support.

### Changed
- Release and maintenance process documented in README.

## [0.1.0] - 2026-03-31

### Added
- Core OpenLMlib schema, write pipeline, storage, and MCP server.
- Dual-index retrieval with filtering and safe context rendering.
- Onboarding flow with setup, doctor, installer scripts, and CI workflow.
