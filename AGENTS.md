# AGENTS.md — Repository Working Charter

> Working charter for AI coding agents on this repository (`CLAUDE.md` maps this file for Claude Code).
>
> **Bootstrap Rule (Existing or Empty Repo)**:
> When `.agents/init_memory.sh` has not been run or Section 1 still contains `TODO:` placeholders:
> 1. Run `bash .agents/init_memory.sh` first (creates `.agents/memory/*`, updates `.gitignore`, and links `.claude/`).
> 2. **If existing files are present** (`pyproject.toml`, `package.json`, `Cargo.toml`, `CMakeLists.txt`, `Makefile`, `README.md`, etc.), inspect them and replace the `TODO:` placeholders below automatically.
> 3. **If this is a brand-new / empty repository**, ask the user what we are building and which tech stack to use (or use the description in their first prompt), scaffold the project, and fill in the `TODO:` placeholders below and `.agents/memory/project_state.md`.

---

## 1. Project Configuration & Quality Gates (All Agents)

- **Project Overview**:
  - **Name & Purpose**: `ps3005d` — cross-platform (Windows + Linux) control of the Velleman PS3005D 0–30 V / 0–5 A lab power supply over USB/RS232: set V/I, output/OVP/OCP, memory M1–M5, live graphs/logging, plus an MCP server so AI agents can drive the supply during hardware testing.
  - **Tech Stack**: Python ≥ 3.11, `pyserial` (transport), PySide6 + `pyqtgraph` (GUI, extra `gui`), official `mcp` Python SDK / FastMCP over stdio (extra `mcp`), hatchling build, venv in `.venv/`.
  - **Entrypoints / Packages**: `src/ps3005d/` — `protocol.py` (pure command build/parse, no I/O), `transport.py` (paced serial I/O), `device.py` (`PowerSupply` driver), `sim.py` (simulated supply), `controller.py` (limits + locking for remote use), `mcp_server.py` (`ps3005d-mcp`), `gui/` (`ps3005d-gui`, PySide6 worker thread + main window), `cli.py` (`ps3005d`). Tests in `tests/`. `PC_SOFTWARE/` is the vendor's LabVIEW Windows app + manual — reference only, never modify.
- **Quality Gates** (MUST pass before handing work back):
  - **Lint & Format**: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
  - **Type / Static Check**: `.venv/bin/mypy` (strict)
  - **Tests**: `.venv/bin/pytest` (GUI tests run offscreen; hardware tests are marked `@pytest.mark.hardware`, excluded by default, run with `PS3005D_PORT=/dev/ttyACM0 .venv/bin/pytest -m hardware`)
- **Domain & Safety Constraints**:
  - **Hardware safety**: never exceed 30.00 V / 5.000 A; validate every setpoint in `protocol.py` before it is sent. The MCP server must additionally enforce user-configurable lower limits (max V, max I) that an agent cannot raise.
  - **Output is off by default**: never switch the output on implicitly (on connect, on recall, on setpoint change). Set limits *before* enabling output. On error, disconnect or shutdown, prefer leaving/turning the output off.
  - **Single serial owner**: only one process may hold the port. GUI and MCP server must not open it simultaneously — share via one process or a local broker, never both opening the port.
  - **Protocol timing**: no terminators; the device garbles replies when paced too fast — keep ≥100 ms after writes and ≥40 ms after queries (measured, see `docs/protocol.md`), all port access behind one lock.
  - **Protocol quirks** are documented in `docs/protocol.md` (e.g. `SAV<n>` ignores n and writes the active memory). Keep `sim.py` faithful to verified behavior. Tests use the simulator, never real hardware, unless run with `-m hardware`.
  - **Front-panel memories are user data**: never overwrite M1–M5 without the user's consent; hardware tests must restore what they change.
  - Must run on Windows and Linux: no POSIX-only APIs; use `serial.tools.list_ports` for port discovery.
- **Documentation Map** (link instead of duplicating content):
  - `README.md` — concise project overview and quickstart.
  - `docs/protocol.md` — wire protocol and verification status.
  - `docs/` — architecture, setup, and usage documentation.
  - `PC_SOFTWARE/PS3005D user manual.pdf` — vendor manual (front panel, memories, OVP/OCP behavior).
  - `CHANGELOG.md` — update with every user-visible change (if present).
- **Git Hygiene**:
  - Commit only when explicitly asked by the user.
  - Never commit `.agents/memory/`, build artifacts, local captures, or temporary debug files.

---

## 2. Security & Secrets Policy (CRITICAL — ALWAYS ENFORCED)

- **Zero Secrets in Git**: NEVER hardcode, stage, or commit secrets, API keys, tokens, passwords, private keys, or credentials into Git.
- **Environment & Secret Files**: Store all sensitive values in `.env` or `.secrets/` (which must be git-ignored via `.gitignore`). Only commit sanitized templates with placeholder values (such as `.env.example`).
- **Agent Memories & Docs**: NEVER write raw secrets, tokens, or credentials into `.agents/memory/*.md`, artifacts, logs, or documentation.
- **Pre-Commit / Review Gate**: Always verify `git status` and `git diff` contain no secrets or unintended files before finishing or approving any task.

---

## 3. Execution Mode & Multi-Agent Orchestration

- **Direct Execution (Small Tasks)**: For single-file edits, straightforward bug fixes, or quick questions, execute the task directly in the main session while following Sections 1 and 2.
- **Team Orchestration (Complex Tasks)**: For multi-file features, architectural changes, unfamiliar subsystems, or broad audits, act as **Lead Orchestrator** and load `.agents/skills/team-orchestration/SKILL.md`.
- **Persistent Memory**: Local agent state lives in `.agents/memory/` (git-ignored). For non-trivial tasks, read `.agents/memory/project_state.md` first (run `bash .agents/init_memory.sh` if `.agents/memory/` does not exist yet).
