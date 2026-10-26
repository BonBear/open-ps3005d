# MCP server

`ps3005d-mcp` exposes the supply to AI agents over MCP (stdio transport), for
automated hardware testing.

## Safety model

- **Operator limits** — `--max-volts` / `--max-amps` are required and cannot be raised
  by any tool. Setpoints, sweeps and stored memories above them are refused, and the
  output cannot be switched on if the *active* setpoints (e.g. from the front panel or a
  recalled memory) exceed them.
- **Output off by default** — only `set_output(on=true)` and `sweep_voltage` energize
  the output. The output is switched off when the server exits, on `release_port`,
  after a sweep (unless `leave_output_on`), and when a sweep detects a trip.
- **Sequences** — every step is checked against the limits before the output is
  switched on. With OVP enabled the supply often trips when the voltage changes; the
  result says so and suggests `set_protection(ovp=false)`.
- **Duration cap** — one `measure`/`sweep_voltage`/`run_sequence` call may run at most
  `--max-duration-s` (default 300 s).
- **Memory writes disabled** — `store_memory` is only offered with
  `--allow-memory-write`, because the memories belong to whoever uses the front panel.
- The server holds the serial port while it runs; `release_port` frees it for other
  programs (the next tool call reopens it).

## Tools

| Tool | Effect |
|---|---|
| `get_info` | identity, hardware max, operator limits |
| `get_status` | output, CV/CC, OVP/OCP, setpoints, measured V/I/P |
| `set_voltage_current(volts?, amps?)` | setpoints (output unchanged) |
| `set_output(on)` | output on/off |
| `set_protection(ocp?, ovp?)` | enable/disable OCP / OVP |
| `measure(samples, interval_s)` | samples + min/max/mean |
| `sweep_voltage(start, stop, step, current_limit, dwell_s, leave_output_on)` | step voltage, measure each point (I-V curve, brown-out) |
| `run_sequence(steps, repeat, leave_output_on, sample_interval_s)` | steps of `{volts, amps, seconds}`; min/max/mean V/A/W and CC per step; output off after (and on trip) |
| `recall_memory(slot)` | load M1–M5 (switches output off) |
| `store_memory(slot, volts, amps)` | only with `--allow-memory-write` |
| `release_port` | output off, close port |

## From the GUI (GUI and AI at the same time)

Only one program can own the serial port, so instead of running `ps3005d-mcp` next to
the GUI, let the GUI host the same tools: **AI (MCP)** tab → *Allow AI control*. The
server listens on `http://127.0.0.1:8765/mcp` (local only; port configurable) and
requires the bearer key shown in the tab. **Copy Claude Code command** gives:

```bash
claude mcp add --transport http ps3005d http://127.0.0.1:8765/mcp --header "Authorization: Bearer <key>"
```

- The AI's limits (max V / A / duration per call) and whether it may overwrite
  memories are set in the tab; limit changes apply to the next call.
- You see everything live in the graphs; the toolbar shows **AI: <tool>** while a tool
  runs. The output button and Stop always work.
- While the GUI runs a sequence, state-changing AI calls are refused (reading works).
- `release_port` only switches the output off; the GUI keeps the port.
- *New key* invalidates the old one at once. The key is stored in the GUI's user
  settings (not in the repository).
- Long tools (e.g. `run_sequence`) answer when done; make sure the client's timeout is
  longer than the sequence.

## Setup (standalone, without the GUI)

Claude Code (Linux):

```bash
claude mcp add ps3005d -- /path/to/repo/.venv/bin/ps3005d-mcp --port /dev/ttyACM0 --max-volts 12 --max-amps 1
```

Windows: use `C:\path\to\repo\.venv\Scripts\ps3005d-mcp.exe` and `--port COM3`.

Generic MCP client config (`mcpServers` JSON):

```json
{
  "mcpServers": {
    "ps3005d": {
      "command": "/path/to/repo/.venv/bin/ps3005d-mcp",
      "args": ["--port", "/dev/ttyACM0", "--max-volts", "12", "--max-amps", "1"]
    }
  }
}
```

Try it without hardware: `ps3005d-mcp --sim --sim-load-ohms 100 --max-volts 12 --max-amps 1`.
