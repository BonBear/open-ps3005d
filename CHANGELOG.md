# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Python 3.11: the GUI could abort ("deallocating None") after drawing graphs for a
  while, caused by a refcount bug in PySide6 6.12.0. Python 3.11 now installs
  PySide6 below 6.12.

## [0.1.0] - 2026-10-26

First release.

### Added

- Driver for the Velleman PS3005D (Korad KA3005P command set) over USB/RS232, with
  measured command pacing and fixed-size reads; built-in simulator.
- `ps3005d` CLI: ports, probe, status, set, output, OCP/OVP, memories, raw commands,
  monitor with CSV, step sequences.
- `ps3005d-gui` desktop app (PySide6, pyqtgraph): live V/A/W graphs with max values,
  immediate setpoints, OCP/OVP, memories M1–M5 without interrupting the output, step
  sequences, CSV export/logging, English/Swedish/German UI.
- `ps3005d-mcp` MCP server for AI agents with operator limits; tools for status,
  setpoints, output, protection, measurement, voltage sweeps, sequences and memories.
- MCP server hosted by the GUI over local HTTP with a bearer key, so the GUI and an AI
  can share the supply.
- Workarounds for firmware quirks: `SAV<n>` writes the active memory, a stuck OVP
  status bit, OVP tripping on voltage changes, junk byte after `ISET1?`.

[Unreleased]: https://github.com/BonBear/open-ps3005d/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BonBear/open-ps3005d/releases/tag/v0.1.0
