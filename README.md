# ps3005d

Cross-platform (Windows + Linux) control software for the **Velleman PS3005D**
0–30 V / 0–5 A programmable lab power supply over USB/RS232.

Planned components:

- **Driver** (`ps3005d.protocol`, device/transport layer) — set voltage/current,
  output on/off, OVP/OCP, memory M1–M5 save/recall, readback.
- **GUI** — live V/I/P graphs, setpoint control, memory management, CSV logging.
- **MCP server** — exposes the supply to AI agents for automated hardware testing,
  with enforced safety limits.

## CLI

```bash
ps3005d ports                      # list serial ports, marks the likely PS3005D
ps3005d --port /dev/ttyACM0 probe  # read-only protocol check (raw replies)
ps3005d status
ps3005d set -v 5 -i 0.5
ps3005d output on
ps3005d store 3 12 1.0             # program M3 without applying it
ps3005d recall 3                   # (switches output off, per manual)
ps3005d monitor --interval 0.5 --csv log.csv
ps3005d sequence steps.csv --repeat 3   # output ON; volts,amps,seconds per row
ps3005d --sim status               # built-in simulator, no hardware
```

The port can also be set with `PS3005D_PORT`. On Linux, your user must be in
`dialout`; see [docs/udev/99-ps3005d.rules](docs/udev/99-ps3005d.rules) to stop
ModemManager from probing the supply.

## GUI

```bash
ps3005d-gui                    # pick the port in the window
ps3005d-gui --port /dev/ttyACM0 --connect
ps3005d-gui --sim --connect    # simulator with a 10 Ω load
ps3005d-gui --lang de          # English (en), Swedish (sv) or German (de)
```

Live V / A / W graphs (30 s – all), max V / A / W since connect (with reset), OCP/OVP,
CSV export and continuous CSV logging.
Language: English, Swedish or German via the **Language** menu (applies at once and is
remembered); the default follows the system language. Translations live in
`src/ps3005d/gui/i18n.py`; `tests/test_i18n.py` fails if a GUI string lacks one.
Polls at ~4–5 Hz (limited by the supply's command pacing).

- Voltage / current limit are sent as soon as you change them (arrows, or Enter after
  typing). The mouse wheel only acts on a focused field.
- Memories M1–M5 are read on connect (if the output is off). **Recall** sets the stored
  values directly, so a running output is not interrupted. **Store** updates the label
  at once; with the output on, the label says "not saved yet – saved when output is turned off"
  and the write happens when you switch the output off,
  because the firmware can only store by recalling the slot, which cuts the output.
  The store confirmation has "Don't show again"; re-enable it under **Settings**.
- **Sequence** tab: a table of steps (voltage, current limit, seconds), rounds (∞
  possible), optional "leave output on". Start switches the output on; Stop or a trip
  (output switching off) ends the run. The table is remembered; open/save as CSV
  (`volts,amps,seconds`) or load the vendor app's step table (`2.ini`). If OVP is on,
  you're offered to switch it off for the run, because this supply often trips OVP
  when the voltage setpoint changes (see [docs/protocol.md](docs/protocol.md)).
- Closing the window switches the output off (and writes waiting memories) unless
  "Output off on exit" is unchecked.

Only one program can use the serial port. To let an AI test hardware while you watch
in the GUI, enable **AI (MCP)** in the GUI instead of starting `ps3005d-mcp`: the GUI
then serves the MCP tools on `http://127.0.0.1:8765/mcp` with a key
([docs/mcp.md](docs/mcp.md)).

## MCP server (AI agents)

```bash
ps3005d-mcp --port /dev/ttyACM0 --max-volts 12 --max-amps 1
```

Tools, safety model and client setup: [docs/mcp.md](docs/mcp.md).

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,mcp,gui]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
PS3005D_PORT=/dev/ttyACM0 .venv/bin/pytest -m hardware   # real unit, no load connected
```

The original Windows vendor software and the user manual (from the PS3005D's CD or
Velleman's website) go in `PC_SOFTWARE/` for reference. They are Velleman's copyright
and not in git. Protocol notes: [docs/protocol.md](docs/protocol.md).
