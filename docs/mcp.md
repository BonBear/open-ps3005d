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
- **Duration cap** — one `measure`/`sweep_voltage` call may run at most
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
| `recall_memory(slot)` | load M1–M5 (switches output off) |
| `store_memory(slot, volts, amps)` | only with `--allow-memory-write` |
| `release_port` | output off, close port |

## Setup

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
