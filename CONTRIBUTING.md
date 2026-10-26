# Contributing

Issues and pull requests are welcome. Reports from other supplies (Korad, Tenma, RND and
similar) are especially useful. Please include the output of `ps3005d probe`.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev,gui]"
```

## Before opening a pull request

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
```

CI runs these checks on Linux and Windows with Python 3.11–3.13.

## Guidelines

- **Hardware safety first.** Never switch the output on implicitly, validate every
  setpoint before sending it, and switch the output off on errors and shutdown.
- **Tests use the simulator.** Tests that need a real supply are marked
  `@pytest.mark.hardware`, are skipped by default, and must restore any setpoints and
  memories they change.
- **Keep the simulator faithful.** When you find new device behaviour, document it in
  [docs/protocol.md](docs/protocol.md) and reproduce it in `src/ps3005d/sim.py`.
- **Translations.** Every GUI text goes through `tr()` and needs Swedish and German
  entries in `src/ps3005d/gui/i18n.py`; `tests/test_i18n.py` checks this.
- **Changelog.** Add user-visible changes to [CHANGELOG.md](CHANGELOG.md) under
  *Unreleased*.
