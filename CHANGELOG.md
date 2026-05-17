# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [0.2.6] - 2026-05-17

### Added
- **Unified Benchmark Suite**: Added a comprehensive benchmark suite for performance evaluation of core tools, collaboration, and memory systems.
- **Local Dev Support**: CLI now automatically detects and uses a local `.venv` when running from source, streamlining the developer workflow.
- **Analytics & Metrics**: Implemented tool usage analytics and metrics tracking to monitor performance and reliability in real-time.

### Changed
- **Collaborative Subsystem Upgrade**: 
  - Implemented **thread-local connection pooling** for high-concurrency database access.
  - Added **model-aware contexts** and **atomic task claims** for more reliable multi-agent coordination.
  - Rewrote agent instructions for **parallel execution** and zero-ack behavior.
- **MCP Tool Optimization**:
  - **Verb-Object Refactor**: Renamed all 50+ tools to a clean `verb_object` pattern (e.g., `search_findings` instead of `openlmlib_search_fts`).
  - **Behavioral Triggers**: Optimized tool descriptions with explicit workflow context and automatic triggers to improve LLM reasoning.
- **Memory System Performance**:
  - Implemented **bulk storage updates** for observation compression, resolving N+1 disk sync bottlenecks.
  - Optimized knowledge extraction to capture all file paths from tool history using advanced regex scanning.
  - Improved search performance with escaped SQLite LIKE queries.
- **Installation & Startup Speed**:
  - **Deferred Model Download**: Moved embedding model download from initial `npm install` to the interactive `openlmlib setup` phase.
  - **Memoized Python Checks**: Cached Python binary resolution to eliminate redundant subprocess calls during startup.

### Fixed
- **Concurrency**: Resolved `ProgrammingError` by allowing SQLite connection sharing across worker threads with proper locking.
- **CI Robustness**: Improved `run_ci_checks.ps1` to handle pip warnings and bypass uninstallation issues via `--ignore-installed`.
- **Test Compatibility**: Refactored test suite to use `unittest` (removing `pytest` dependency) to fix cross-platform CI failures.
- **MCP Setup**: Fixed `Claude Desktop` configuration errors on non-Windows platforms and aligned config keys with official specs.

## [0.2.5] - 2026-04-14

### Added
- **Memory Injection System**: Full implementation of long-lived session memory.
  - **Progressive Disclosure**: 3-layer retrieval (Search -> Timeline -> Full Details) for context efficiency.
  - **Caveman Compression**: Ultra-aggressive token reduction (up to 60%) for large context blocks.
  - **Git History Ingestion**: Retroactive ingestion of session activity from git logs.
  - **Privacy Filtering**: Automated sanitization of sensitive data (API keys, passwords) before storage.
- **MCP CLI Integration**: Native MCP support for 6 popular CLI coding tools:
  - Claude Code, Gemini CLI, Qwen Code, OpenCode, Codex CLI (TOML), and Aider.
- **Documentation**: Added Memory Quickstart and comprehensive guide for the 58+ available tools.

### Changed
- **Version bump**: 0.2.0 → 0.2.5
- **Tool count**: Expanded to 58 tools (17 core, 10 memory, 31 collab).
- **TOML Support**: Integrated native TOML parsing for Codex CLI configuration.

## [0.2.0] - 2026-04-08

### Added
- **Collaborative Sessions System**: Multi-agent collaboration with real-time messaging, artifact sharing, and state management.
- **Collaboration TUI**: Interactive terminal UI for browsing and participating in active sessions.
- **Multi-Session Support**: Capability to manage and coordinate multiple concurrent research sessions.
- **Security Framework**: Permission system and input validation for multi-agent environments.
- **Installer Improvements**: Python bundling support and enhanced setup wizard for Windows/Unix.

## [0.1.2] - 2026-04-01

### Added
- **MCP Setup Module**: Specification-based configuration for major IDEs (VS Code, Cursor, Zed, etc.).
- **Interactive Onboarding**: TUI-based setup for IDE integration.
- **Safety Operations**: Added `backup` and `restore` commands for library data.

## [0.1.0] - 2026-03-31

### Added
- Core OpenLMlib schema, dual-index retrieval (semantic + keyword), and initial MCP server.
