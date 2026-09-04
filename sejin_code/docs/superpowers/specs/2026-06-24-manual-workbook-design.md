# Manual Workbook Design — `scripts/cloudchaser_workbook.py`

**Date:** 2026-06-24  
**Goal:** A single Python file used as a copy-paste workbook in an IPython terminal.  
Not a runnable script — each section is an independently paste-able block.

---

## Problem Being Solved

Current pain points with `session.py` / `manual.py`:
1. Changing any parameter (IP, channel, freq, gain) requires editing `bench.toml` or restarting
2. `start()` hides all bring-up steps inside a black box
3. For ad-hoc mid-session tweaks (switch channel, change gain, re-run test) there is no single clear place to look

**Core use case:** During an op1db sweep that looks wrong, the user wants to:
- Switch channel (`h1` → `h3`) with one paste
- Tweak gain code and re-run peak
- Start a different test — all without restarting the session

---

## File Location

```
scripts/cloudchaser_workbook.py
```

Not part of the package (no `__init__.py`). Runs from the repo root in an IPython session.

---

## Architecture

The file is **pure workbook** — no `if __name__ == "__main__"`, no argparse, no `code.interact()`.  
It re-uses existing CloudChaser infrastructure:
- `cloudchaser.bench.Bench` — instrument management
- `cloudchaser.board.bringup` — chip init and bring-up
- `cloudchaser.manual.build_namespace` — helper function set (rd/wr/chan/rf/peak/…)
- `cloudchaser.session` globals overridden to enable test items (op1db/evm/…)

IP override mechanism: `Bench.from_toml()` is called first (for stable rail configs),  
then `bench.psu1.host`, `bench.sg.host`, etc. are overridden before `connect_all()`.  
This works because `ScpiSocket.connect()` reads `self.host` at connection time.

---

## Section Structure

### `[PARAMETERS]` — edit only here

```python
# Instrument IPs
PSU1_IP   = "192.168.5.18"
PSU2_IP   = "192.168.5.19"
SG_IP     = "192.168.5.14"
SA_IP     = "192.168.5.12"
SCPI_PORT = 5025

# Chip / Board
CHIP        = "tx"        # "tx" (Stampede2731) or "rx" (Blueway)
CHANNELS    = ["h1"]      # healthy TX: h1/h3/v1/v2/v3; broken: h0/v0/h2
BEAM        = "b0"        # "b0" or "b1"
CAL_FREQ    = 0x0         # cal_freq_sel code (datasheet table; 0x0 = default)
COMMON_GAIN = 0x00        # 6-bit attenuation: 0x00=max gain, 0x3F=max atten
CH_GAIN     = {"h1": 0x08}   # per-channel gain_control code (TX only)
CH_ATTEN    = {"h1": 0x00}   # per-channel *_attn_cal code

# SG
FREQ_HZ   = 28.0e9
LEVEL_DBM = -20.0         # chip input level [dBm] (path loss auto-applied)
RF_ON     = False

# SA
SA_SPAN   = 100e6
SA_REF    = 20.0
SA_RBW    = 1e6
SA_ATTEN  = 10.0

# Misc
FAKE = False              # True = dry-run without hardware
```

---

### `[STEP 1]` CONNECT INSTRUMENTS

Actions:
1. `Bench.from_toml()` — selects `bench_rx.toml` if `CHIP="rx"`, else `bench.toml`
2. Override all IPs and board config from PARAMETERS
3. `bench.connect_all()` — open TCP sockets, drain error queues
4. Print confirmation with IPs

Exports: `bench`, `sg`, `sa`

---

### `[STEP 2]` POWER UP RAILS

Actions:
1. `bench.power_up()` — ramp in order: CORE_1V0→DIG_1V8→IO_1V3→FE2_1V8→FE3_1V8→FE1_4V0
2. Print V/I per rail

Standalone sub-block `[STEP 2b] READ RAIL V/I`:
- `bench.read_all_vi()` loop — can be pasted any time during session

---

### `[STEP 3]` CHIP INIT + BRING-UP + HELPERS

Actions:
1. `make_chip()` / `make_chip_rx()` — create sivers_api chip object
2. `bring_up_tx()` / `bring_up_rx()` — init, version check, centerbias_en ON, channels, cal_freq, gain, atten, commit
3. `build_namespace()` — create all helpers
4. Explicit assignments: `rd=, wr=, gain=, chan=, rf=, peak=, ...` (one per line, not `_ns["x"]`)

Exports: `chip`, and all helpers unpacked by name

Standalone sub-blocks (paste any time, no restart):

**`[STEP 3b] CHANGE CHANNEL`**  
`chan("h1")` — disable all → centerbias ON → route one channel → RTPS zero → max gain.  
Includes which SA port to connect to.

**`[STEP 3c] CHANGE GAIN (common)`**  
`gain(0x00)` with comment table: 0x00/0x08/0x10/0x20/0x3F → what each means.  
`latch()` reminder.

**`[STEP 3d] CHANGE GAIN (per-channel)`**  
`chgain("h1", 0x08)` with note on TX-only usage.

**`[STEP 3e] CHANGE ATTENUATION`**  
`atten("h1", 0x00)` — per-channel-beam digital attenuation.

---

### `[STEP 4]` SG / SA SETUP + SIGNAL CHECK

Actions:
1. `rf(True, freq=FREQ_HZ, level=LEVEL_DBM)` — path loss auto-applied
2. `saconf(center=FREQ_HZ, span=SA_SPAN, ref=SA_REF, rbw=SA_RBW, atten_db=SA_ATTEN)`
3. `peak()` — print and return dBm

Each function documented inline with all parameter names and valid values.

One-liners box:
```python
# level(-15)        change SG level only (no SA reconfigure)
# rf(False)         RF off
# peak()            re-measure
# vi()              print all rail V/I
```

---

### `[STEP 5]` REGISTER TWEAKS

Sub-blocks:

**`[STEP 5a] READ / WRITE FIELDS`**  
`rd("b0_common_gain")` / `wr("b0_common_gain", 0x10)` / `latch()`.  
Table of common field names.

**`[STEP 5b] ENABLE / DISABLE CHANNELS`**  
`enable("h1")` / `disable()` / `paths()` one-liners.

**`[STEP 5c] CENTERBIAS`**  
`wr("centerbias_en", 1)` / `wr("centermirror_en", 1)` — manual override when needed.

**`[STEP 5d] BIAS STAGE DIAGNOSTICS`**  
`biasscan("h1")` — sweeps PTAT 0→63, prints delta-I per stage; "NO RESPONSE" = dead stage.

**`[STEP 5e] LOAD GOLDEN REGISTERS`**  
`load_golden()` — loads known-good register state from `docs/golden_h0b0_25g.json`.

---

### `[STEP 6]` TEST ITEMS

All commented out by default. Each has:
- Brief description of what it measures
- Key parameters with examples
- `params("test_id")` call reminder for full parameter list

Tests included:
- `op1db` — CW power sweep → OP1dB (TX)
- `gain_index_accuracy` — sweep common / per-path gain codes
- `channel_gain_alignment` — output level spread across channels (interactive cable move)
- `evm` — 5G NR modulation quality vs output power
- `acp` — adjacent channel power ratio vs output power
- `ip1db` — input 1dB compression point (RX/Blueway only)

Session globals wired up so test functions work without restarting:
```python
import cloudchaser.session as _sess
_sess.B = bench;  _sess.C = chip;  _sess._fake = FAKE
_sess._ns = _ns;  _sess._chip_kind = CHIP
from cloudchaser.session import op1db, gain_index_accuracy, channel_gain_alignment, evm, acp, ip1db
```

---

### `[STEP 7]` SHUTDOWN

```python
rfoff()        # RF off first
shutdown()     # ramp all rails to 0V in reverse order
bench.close_all()
```

---

## Comments Policy

- Every parameter in PARAMETERS has:
  - inline comment with type/units, valid values, concrete examples
  - note on which values are dangerous (broken HW channels, high gain codes)
- Every function call in steps has:
  - what it does in one line
  - parameter table (name → valid values → example)
- Section dividers use `# ======` banners for easy visual scanning
- Standalone sub-blocks have `# [STEP Xb]` headers so user can locate them quickly

---

## What This File Does NOT Do

- Does not run top-to-bottom (no `main()`, no script guard)
- Does not replace `session.py` or `manual.py` — those remain unchanged
- Does not auto-inject into IPython namespace — user explicitly assigns helpers
- Does not read TOML for anything other than stable rail configs and defaults

---

## Relationship to Existing Code

| Existing file | Role in workbook |
|---|---|
| `config/bench.toml` | Rail voltages/limits (stable, not edited per session) |
| `config/bench_rx.toml` | Same for RX board |
| `cloudchaser/bench.py` | `Bench` object — used directly |
| `cloudchaser/board/bringup.py` | `make_chip`, `bring_up_tx/rx` — called explicitly |
| `cloudchaser/manual.py` | `build_namespace()` — helpers extracted then unpacked by name |
| `cloudchaser/session.py` | `op1db`, `evm`, etc. — imported after wiring session globals |
| `cloudchaser/test_items/` | Not imported directly — accessed through session |
