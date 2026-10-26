# PS3005D serial protocol

Korad KA3005P-compatible command set. Items marked ✅ were verified on a real unit
(`*IDN?` = `VELLEMANLABPS3005DV2.0`, 2026-10-26, Linux, `ps3005d probe` + `pytest -m hardware`).

- Link: USB CDC, VID:PID `0416:5011` ("USB Virtual COM"; `/dev/ttyACM*` on Linux,
  `COMx` on Windows) or RS232. 9600 baud, 8N1, no flow control. ✅
- Commands are ASCII with **no line terminator**; replies have none either. Numeric
  replies are 5 bytes, `STATUS?` 1 byte (read by length); `*IDN?` is read until quiet. ✅
- **Pacing matters** ✅: with too short gaps the unit returns wrong values or nothing.
  Over 150 set→read-back cycles: 0–20 ms gap → every cycle failed, 30 ms → 61 bad,
  40 ms → 35 bad, 50 ms → 1 bad; 75–100 ms after a *write* plus 30–40 ms after a
  *query* → 0 bad. Defaults: 100 ms after writes, 40 ms after queries (≈ 205 ms for
  measure + status).
- Front-panel keys are locked while the PC is connected (manual §10).

| Command | Meaning | Verified |
|---|---|---|
| `*IDN?` | identification string | ✅ |
| `VSET1:<vv.vv>` / `VSET1?` | voltage setpoint, 0–30.00 V; reply `25.00` | ✅ |
| `ISET1:<i.iii>` / `ISET1?` | current setpoint, 0–5.000 A; reply has a trailing junk byte, e.g. `0.100M` | ✅ |
| `VOUT1?` / `IOUT1?` | measured output voltage / current (`03.30`, `0.000`) | ✅ |
| `OUT1` / `OUT0` | output on / off | ✅ |
| `OVP1` / `OVP0`, `OCP1` / `OCP0` | over-voltage / over-current protection | ✅ (status bits) |
| `BEEP1` / `BEEP0` | key beep | accepted; not visible in STATUS |
| `RCL<n>` | load memory n = 1..5, make it the *active* memory, switch output off | ✅ |
| `SAV<n>` | save setpoints into the **active** memory — n is ignored! | ✅ (quirk) |
| `STATUS?` | 1 raw byte, see below | ✅ |

**Memory semantics (verified 2026-10-26).**

- The supply has one *active* memory: M1 after power-on, afterwards the last `RCL<n>`.
- `SAV<n>` writes the current setpoints into the active memory and **ignores n**
  (e.g. `RCL1`, `SAV3` → M1 changes, M3 not). To program slot n: `RCL n`, set V/I,
  `SAV n` — this is what `PowerSupply.store_memory` does (then verifies by moving the
  setpoints away and recalling n). `PowerSupply.save(n)` uses the same path.
- Remote `VSET`/`ISET` changes are **not** auto-saved into the active memory (tested
  immediately and after 6 s, for M2 and M5), unlike front-panel edits.
- `RCL<n>` only reads; recalling memories in any order returns stable values.

Early tests used a plain `SAV5` right after power-on and so overwrote M1 (original
value lost). One M5 value (5.00 V / 0.100 A) seen during testing was never explained.

`STATUS?` bits (verified): bit0 = 1 CV / 0 CC (latched: stays at last mode after
output off; reads 0 before the output was ever on), bit5 = OCP enabled,
bit6 = output on, bit7 = OVP enabled. Bits 1–4 have not been seen set.

**OVP bit quirk (verified 2026-10-26):** after `OVP0` while OCP is enabled, bit7
usually stays 1 (8 of 9 tries) until `OCP0` is sent, although OVP *is* off (front-panel
indicator goes out; `OCP0` then reads `0x01`, not `0x81`). Re-sending `OCP1`, `OVP0`,
`VSET` or `BEEP1` does not refresh it, and it survives into later sessions.
`PowerSupply.status()` therefore (1) reports OVP off once the session has sent `OVP0`,
and (2) the first time both bits read "on" without knowing the OVP state, sends `OCP0`,
reads the true OVP bit and sends `OCP1` (~0.2 s without OCP; the current limit still
applies). That also clears the stuck bit on the device. Verified across sessions; the
simulator reproduces the stuck bit.

Vendor app files in `PC_SOFTWARE/` (LabVIEW build): `1.ini` holds M1–M5 V/I
values, `2.ini` looks like a 10-step sequence table (`step, V, I, seconds`).
