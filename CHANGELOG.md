# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

## [0.1.1] - 2026-04-01

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
