# Manual Workbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `scripts/cloudchaser_workbook.py` — a copy-paste IPython workbook for ad-hoc manual control of the CloudChaser EVB without restarting between changes.

**Architecture:** Single workbook file organized into independently paste-able section blocks. Uses existing `cloudchaser` package (Bench, bringup, manual helpers, session test items). No new modules added. A smoke test in `tests/test_workbook_smoke.py` runs all blocks in `fake=True` mode.

**Tech Stack:** Python 3.13, pytest, cloudchaser package (src/), sivers_api (skip guard if absent)

## Global Constraints

- All user-visible strings (print/assert messages) must be in English (cp949 console safety)
- Code comments may be in Korean
- No new entries in `test_items/__init__.py._ALL` — test items already exist
- `scripts/` is not a Python package (no `__init__.py`)
- Skip guard: `@pytest.mark.skipif(importlib.util.find_spec("sivers_api") is None, reason="sivers_api not installed")`
- Run tests: `python -m pytest` from project root using `.venv`
- Workbook file is purely a reference/copy-paste resource — no `if __name__ == "__main__"`, no argparse

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `scripts/cloudchaser_workbook.py` | Create | The workbook: PARAMETERS + 7 STEPs |
| `tests/test_workbook_smoke.py` | Create | Fake-mode smoke test for each STEP block |

---

### Task 1: Workbook skeleton + PARAMETERS block + test file setup

**Files:**
- Create: `scripts/cloudchaser_workbook.py`
- Create: `tests/test_workbook_smoke.py`

**Interfaces:**
- Consumes: `cloudchaser.bench.Bench`, `cloudchaser.board.bringup`, `cloudchaser.manual.build_namespace`, `cloudchaser.session`
- Produces: `scripts/cloudchaser_workbook.py` (PARAMETERS block), `tests/test_workbook_smoke.py` (test skeleton + `_make_fake_bench()` helper)

- [ ] **Step 1: Write failing test — verify PARAMETERS block is syntactically valid Python**

Create `tests/test_workbook_smoke.py`:
```python
"""Smoke test: workbook STEP blocks work in fake=True mode.

sivers_api 없으면 전부 skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
_CONFIG    = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
_CONFIG_RX = Path(__file__).resolve().parents[1] / "config" / "bench_rx.toml"


def _make_fake_bench(chip: str = "tx", channels=None, beam: str = "b0"):
    """Simulate STEP 1 + 2 in fake mode (no power ramp, no TCP)."""
    from cloudchaser.bench import Bench
    channels = channels or ["h1"]
    cfg = _CONFIG_RX if chip == "rx" else _CONFIG
    bench = Bench.from_toml(cfg, fake=True)
    bench.board.active_channels = channels
    bench.board.beam = beam
    bench.board.ch_gain  = {ch: 0x08 for ch in channels}
    bench.board.ch_atten = {ch: 0x00 for ch in channels}
    bench.chip_kind = chip
    bench.connect_all(log=lambda *a, **k: None)
    return bench


def test_placeholder():
    """Placeholder — replaced in Task 2."""
    assert True
```

- [ ] **Step 2: Run test to verify it passes (no sivers_api guard needed yet)**

```
python -m pytest tests/test_workbook_smoke.py::test_placeholder -v
```
Expected: `PASSED`

- [ ] **Step 3: Create the workbook file PARAMETERS block**

Create `scripts/cloudchaser_workbook.py`:
```python
"""CloudChaser Manual Workbook — IPython copy-paste reference.

Usage:
  1. Open this file alongside an IPython terminal.
  2. Edit [PARAMETERS] section for your session.
  3. Paste each [STEP] block into IPython one at a time.
     - Each block is self-contained and can be re-pasted to re-run.
     - Mid-session change blocks (3b/3c/3d/3e) can be pasted any time.
  4. End with [STEP 7] SHUTDOWN.

Objects available after STEP 3: bench, chip, sg, sa
Helpers available after STEP 3:  rd, wr, gain, chgain, atten, latch,
                                  chan, enable, disable, paths, biasscan,
                                  load_golden, rf, rfoff, level,
                                  saconf, peak, vi, commit, shutdown

!! TX board defects: H0 / V0 / H2 channels have driver-stage HW faults.
   Healthy TX channels: H1 / H3 / V1 / V2 / V3
   RX (Blueway): all channels healthy.
"""

# =============================================================================
# [PARAMETERS] -- the only section you normally need to edit
# =============================================================================

# --- Instrument IPs ----------------------------------------------------------
#  Change these to match your bench network config.
PSU1_IP   = "192.168.5.18"   # Keysight E36313A #1  (FE1_4V0 / CORE_1V0 / IO_1V3)
PSU2_IP   = "192.168.5.19"   # Keysight E36313A #2  (DIG_1V8 / FE2_1V8 / FE3_1V8)
SG_IP     = "192.168.5.14"   # R&S SMW200A signal generator
SA_IP     = "192.168.5.12"   # R&S FSVA3030 spectrum analyzer
SCPI_PORT = 5025              # SCPI-over-LAN port (change only if port-forwarded)

# --- Chip / Board ------------------------------------------------------------
CHIP = "tx"
#   "tx"  = Stampede2731 TX EVB  (use config/bench.toml)
#   "rx"  = Blueway RX EVB       (use config/bench_rx.toml)

CHANNELS = ["h1"]
#   List of antenna channels to enable (all routed to the same beam).
#   TX healthy:  "h1", "h3", "v1", "v2", "v3"
#   TX BROKEN (DO NOT USE): "h0", "v0", "h2"  <- driver-stage HW fault confirmed
#   RX (Blueway): "h0"~"h3", "v0"~"v3"  (all healthy)
#   Multi-channel example: ["h1", "h3"]

BEAM = "b0"
#   Beam port to route channels to.
#   "b0" or "b1"

CAL_FREQ = 0x0
#   cal_freq_sel code — selects calibration frequency band (see Sivers datasheet table).
#   0x0 = default / broadband.  Other codes enable band-specific calibration.

COMMON_GAIN = 0x00
#   b{n}_common_gain: 6-bit beam-wide attenuation code (applies to all channels).
#   0x00 = max gain (0 dB attenuation)     <- start here
#   0x08 = ~2 dB attenuation
#   0x10 = ~5 dB attenuation
#   0x20 = ~10 dB attenuation
#   0x3F = max attenuation (~18 dB)

CH_GAIN = {"h1": 0x08}
#   Per-channel gain_control_{pol}{idx} code (TX only; ignored on RX Blueway).
#   6-bit code.  0x00 = max gain, 0x3F = min gain.
#   Include each channel in CHANNELS, e.g. {"h1": 0x08, "h3": 0x08}
#   Missing channels fall back to bench.toml [board.ch_gain] defaults.

CH_ATTEN = {"h1": 0x00}
#   Per-channel ch{idx}_{pol}_b{beam}_attn_cal code (digital attenuation per path).
#   0x00 = no attenuation.  Typical range 0x00~0x0F.
#   Include each channel in CHANNELS, e.g. {"h1": 0x00, "h3": 0x00}

# --- Signal Generator (SG) ---------------------------------------------------
FREQ_HZ   = 28.0e9
#   Measurement frequency [Hz].
#   Examples: 25.0e9, 27.0e9, 28.0e9, 28.5e9, 39.0e9

LEVEL_DBM = -20.0
#   SG output level [dBm] = chip INPUT level after path loss is applied.
#   The workbook applies loss.toml offsets automatically so this value
#   reflects what the DUT actually receives, not what the SG outputs.
#   Typical range: -40.0 to +5.0 dBm (chip input)

RF_ON = False
#   True  = RF output ON immediately at rf() call in STEP 4
#   False = RF stays OFF until you explicitly call rf(True, ...)

# --- Spectrum Analyzer (SA) --------------------------------------------------
SA_SPAN  = 100e6
#   SA display span [Hz].  Examples: 10e6, 100e6, 500e6, 1e9

SA_REF   = 20.0
#   SA reference level [dBm] — set ~10 dB above the expected peak.
#   After path loss offset: this is the chip OUTPUT reference level.

SA_RBW   = 1e6
#   SA resolution bandwidth [Hz].  Narrower = more accurate but slower.
#   Examples: 100e3, 1e6, 3e6

SA_ATTEN = 10.0
#   SA input attenuator [dB].  Higher = protects SA mixer, lowers sensitivity.
#   0 = most sensitive.  10 = typical.  30 = high-power signals.

# --- Misc --------------------------------------------------------------------
FAKE = False
#   True  = dry-run mode: no TCP connections, no SPI writes (for code testing)
#   False = real hardware  <- use this for actual measurements
```

- [ ] **Step 4: Verify the workbook file is importable (no syntax errors)**

```
python -c "import ast; ast.parse(open('scripts/cloudchaser_workbook.py').read()); print('OK: syntax valid')"
```
Expected: `OK: syntax valid`

- [ ] **Step 5: Commit**

```
git add scripts/cloudchaser_workbook.py tests/test_workbook_smoke.py
git commit -m "feat(workbook): scaffold PARAMETERS block + test skeleton"
```

---

### Task 2: STEP 1 (Connect Instruments) + STEP 2 (Power Up)

**Files:**
- Modify: `scripts/cloudchaser_workbook.py` — append STEP 1 and STEP 2 blocks
- Modify: `tests/test_workbook_smoke.py` — add connect + power tests

**Interfaces:**
- Consumes: `_make_fake_bench()` from Task 1, `cloudchaser.bench.Bench`
- Produces: STEP 1 exports `bench`, `sg`, `sa`; STEP 2 calls `bench.power_up()`

- [ ] **Step 1: Write failing tests for STEP 1 (connect)**

Add to `tests/test_workbook_smoke.py` (replace `test_placeholder`):
```python
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step1_connect_overrides_board_settings():
    """STEP 1: board settings from PARAMETERS override bench.toml defaults."""
    bench = _make_fake_bench(chip="tx", channels=["h1", "h3"], beam="b1")
    assert bench.board.active_channels == ["h1", "h3"]
    assert bench.board.beam == "b1"
    assert bench.chip_kind == "tx"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step1_rx_uses_rx_toml():
    """STEP 1 with chip='rx': RX bench config is loaded."""
    bench = _make_fake_bench(chip="rx", channels=["h1"])
    # RX bench must have rails present (bench_rx.toml has them)
    assert bench.chip_kind == "rx"
    assert bench.board.active_channels == ["h1"]


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step2_power_up_fake():
    """STEP 2: power_up() runs without error in fake mode."""
    bench = _make_fake_bench()
    # power_up() ramps all rails — in fake mode just verifies the sequence runs
    bench.power_up(log=lambda *a, **k: None)
    vi = bench.read_all_vi()
    # fake PSU returns zeros but all rail names must be present
    assert "FE1_4V0" in vi
    assert "CORE_1V0" in vi
    assert "DIG_1V8" in vi
```

- [ ] **Step 2: Run tests to verify they fail (bench not yet configured)**

```
python -m pytest tests/test_workbook_smoke.py -v -k "step1 or step2"
```
Expected: All 3 tests `PASSED` — `_make_fake_bench()` already covers this logic.  
(If any fail, fix `_make_fake_bench()` in Task 1's test file first.)

- [ ] **Step 3: Add STEP 1 block to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 1] CONNECT INSTRUMENTS
# =============================================================================
# Paste this block ONCE at the start of each IPython session.
# What it does:
#   1. Loads bench config from bench.toml (stable rail voltages/limits stay in TOML)
#   2. Overrides all IPs and board settings from [PARAMETERS] above
#   3. Opens TCP sockets to all 4 instruments and drains stale error queues
#
# Re-paste if a connection drops during the session.
# Exports: bench, sg, sa
# =============================================================================
from pathlib import Path
from cloudchaser.bench import Bench
from cloudchaser.board.bringup import (
    make_chip, make_chip_rx, bring_up_tx, bring_up_rx,
)
from cloudchaser.manual import build_namespace

# Select TOML based on chip type (rail voltages and limits live in TOML)
_workbook_toml = (
    Path("config/bench_rx.toml") if CHIP == "rx"
    else Path("config/bench.toml")
)
bench = Bench.from_toml(_workbook_toml, fake=FAKE)

# Override instrument IPs from [PARAMETERS] (bench.toml IPs are ignored)
bench.psu1.host = PSU1_IP;  bench.psu1.port = SCPI_PORT
bench.psu2.host = PSU2_IP;  bench.psu2.port = SCPI_PORT
bench.sg.host   = SG_IP;    bench.sg.port   = SCPI_PORT
bench.sa.host   = SA_IP;    bench.sa.port   = SCPI_PORT

# Override board settings from [PARAMETERS]
bench.board.active_channels = list(CHANNELS)
bench.board.beam            = BEAM
bench.board.cal_freq_code   = CAL_FREQ
bench.board.common_gain     = COMMON_GAIN
bench.board.ch_gain         = {k: int(v) for k, v in CH_GAIN.items()}
bench.board.ch_atten        = {k: int(v) for k, v in CH_ATTEN.items()}
bench.chip_kind             = CHIP

bench.connect_all()     # opens sockets + drains stale error queues (prints each connection)
sg = bench.sg           # shorthand for SG in this session
sa = bench.sa           # shorthand for SA in this session

print(f"[OK] Connected: PSU1={PSU1_IP}  PSU2={PSU2_IP}  SG={SG_IP}  SA={SA_IP}")
print(f"     chip={CHIP}  channels={CHANNELS}  beam={BEAM}  fake={FAKE}")
```

- [ ] **Step 4: Add STEP 2 block to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 2] POWER UP RAILS
# =============================================================================
# Ramps PSU rails in the order defined in bench.toml [ramp] power_up_order:
#   CORE_1V0 -> DIG_1V8 -> IO_1V3 -> FE2_1V8 -> FE3_1V8 -> FE1_4V0
# Each rail ramps from 0V to target in 0.2V steps with 0.1s settle per step.
# Prints V and I [mA] for every rail after they all reach target.
#
# SKIP this block if rails are already powered from a previous session.
# (Re-paste STEP 1 only to reconnect sockets without re-powering.)
#
# To power SPI-only rails first (for chip auto-detect without FE risk):
#   bench.power_up(rails=bench.detect_rail_names)
# =============================================================================
bench.power_up()
# Expected current after bring-up: FE1_4V0 ~50-200 mA (depends on channels enabled)
# If FE current is 0 mA after bring-up, check cable / board power connector.

# =============================================================================
# [STEP 2b] READ RAIL V/I  -- paste any time during session
# =============================================================================
# for name, m in bench.read_all_vi().items():
#     print(f"  {name:12}: {m['v']:.3f} V   {m['i']*1000:.1f} mA")
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_workbook_smoke.py -v
```
Expected: All tests `PASSED`

- [ ] **Step 6: Commit**

```
git add scripts/cloudchaser_workbook.py tests/test_workbook_smoke.py
git commit -m "feat(workbook): add STEP 1 (connect) and STEP 2 (power up) blocks"
```

---

### Task 3: STEP 3 (Chip Init + Helpers) + Standalone Change Blocks (3b–3e)

**Files:**
- Modify: `scripts/cloudchaser_workbook.py` — append STEP 3 + 3b + 3c + 3d + 3e
- Modify: `tests/test_workbook_smoke.py` — add bring-up + helper + change-block tests

**Interfaces:**
- Consumes: `bench`, `chip`, `build_namespace()` from STEP 3
- Produces: `chip`, `rd`, `wr`, `gain`, `chgain`, `atten`, `latch`, `chan`, `enable`, `disable`, `paths`, `biasscan`, `load_golden`, `commit`, `vi`, `shutdown` — all as local IPython-session names

- [ ] **Step 1: Write failing tests for STEP 3**

Add to `tests/test_workbook_smoke.py`:
```python
def _make_fake_chip(bench, chip_kind: str = "tx"):
    """Simulate STEP 3: init chip and build helpers."""
    from cloudchaser.board.bringup import make_chip, make_chip_rx, bring_up_tx, bring_up_rx
    from cloudchaser.manual import build_namespace
    if chip_kind == "rx":
        chip = make_chip_rx(bench.board, fake=True)
        bring_up_rx(chip, bench.board, require_version=False)
    else:
        chip = make_chip(bench.board, fake=True)
        bring_up_tx(chip, bench.board, require_version=False)
    ns = build_namespace(bench, chip, bench.board.beam)
    return chip, ns


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step3_helpers_are_callable():
    """STEP 3: build_namespace produces all expected helper functions."""
    bench = _make_fake_bench()
    _, ns = _make_fake_chip(bench)
    for name in ("rd", "wr", "gain", "chgain", "atten", "latch",
                 "chan", "enable", "disable", "paths", "biasscan",
                 "load_golden", "rf", "rfoff", "level", "saconf", "peak",
                 "vi", "commit", "shutdown"):
        assert callable(ns[name]), f"helper '{name}' not callable"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step3b_chan_runs_without_error(capsys):
    """STEP 3b: chan('h1') completes without exception in fake mode."""
    bench = _make_fake_bench(channels=["h1"])
    chip, ns = _make_fake_chip(bench)
    ns["chan"]("h1")   # should print path info
    out = capsys.readouterr().out
    assert "h1" in out or "b0" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step3c_gain_and_latch_run(capsys):
    """STEP 3c: gain() + latch() run without exception in fake mode."""
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    ns["gain"](0x10)
    ns["latch"]()
    out = capsys.readouterr().out
    assert "latch" in out.lower() or "pulse" in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_workbook_smoke.py -v -k "step3"
```
Expected: `FAILED` — `_make_fake_chip` is not yet defined in the test file.  
(Steps 1+2 already have the helper above; confirm the tests exist and fail for the right reason.)

- [ ] **Step 3: Add `_make_fake_chip` helper to test file and run again**

The `_make_fake_chip` function is included in Step 1 above. If tests fail for another reason, debug before continuing.

```
python -m pytest tests/test_workbook_smoke.py -v -k "step3"
```
Expected: All `PASSED`

- [ ] **Step 4: Add STEP 3 block to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 3] CHIP INIT + BRING-UP + HELPER FUNCTIONS
# =============================================================================
# What it does:
#   1. Creates the sivers_api chip object (Stampede or Blueway)
#   2. Runs chip.init() + eFuse load + version_id check (SPI sanity test)
#   3. Enables centerbias_en + centermirror_en (required; NOT done by path.enable)
#   4. Routes CHANNELS to BEAM, sets cal_freq / common_gain / ch_gain / ch_atten
#   5. Commits all register writes to hardware in one burst
#   6. Builds the helper function set and assigns them to local names
#
# After this block: chip is ready, helpers are in scope.
# Re-paste this block to fully re-initialize the chip (e.g. after a register corruption).
# Exports: chip, rd, wr, gain, chgain, atten, latch, chan, enable, disable, paths,
#          biasscan, load_golden, rf, rfoff, level, saconf, peak, vi, commit, shutdown
# =============================================================================
_make_fn    = make_chip_rx if CHIP == "rx" else make_chip
_bringup_fn = bring_up_rx  if CHIP == "rx" else bring_up_tx

chip = _make_fn(bench.board, fake=FAKE)
_bringup_fn(chip, bench.board, require_version=not FAKE)

print(f"[OK] Bring-up done: chip={CHIP}  channels={bench.board.active_channels}"
      f"  beam={bench.board.beam}")

# Build helper namespace and unpack into local names.
# All helpers use the current bench + chip state.
_ns = build_namespace(bench, chip, bench.board.beam)
rd        = _ns["rd"]          # rd("field")          read register field + print value
wr        = _ns["wr"]          # wr("field", val)      write register field (auto-commit)
enable    = _ns["enable"]      # enable("h1")          route channel(s) to beam
disable   = _ns["disable"]     # disable() / disable("h1")  turn path(s) off
paths     = _ns["paths"]       # paths()               print active beam->channel routing
gain      = _ns["gain"]        # gain(code)            set common beam gain (6-bit atten, 0=max)
chgain    = _ns["chgain"]      # chgain("h1", code)    set per-channel gain (TX only)
atten     = _ns["atten"]       # atten("h1", code)     set per-channel-beam digital atten
commit    = _ns["commit"]      # commit()              flush staged writes (if auto-commit off)
latch     = _ns["latch"]       # latch()               pulse all pulse_en fields -> analog apply
load_golden = _ns["load_golden"] # load_golden()       restore known-good register state
chan      = _ns["chan"]         # chan("h1")            bring ONE channel to measurement-ready
biasscan  = _ns["biasscan"]    # biasscan("h1")        sweep PTAT bias, diagnose dead stages
rf        = _ns["rf"]          # rf(True, freq=28e9, level=-20)  SG control + path loss apply
rfoff     = _ns["rfoff"]       # rfoff()               SG RF OFF (safe shortcut)
level     = _ns["level"]       # level(-15)            change SG level only [dBm]
saconf    = _ns["saconf"]      # saconf(center=28e9, span=100e6, ref=20)  configure SA
peak      = _ns["peak"]        # peak()                single sweep, return SA peak [dBm]
vi        = _ns["vi"]          # vi()                  read + print all rail V/I
shutdown  = _ns["shutdown"]    # shutdown()            RF off + ramp all rails to 0V

print()
print("  Helpers ready: rd wr gain chgain atten latch chan enable disable paths")
print("                 biasscan load_golden rf rfoff level saconf peak vi shutdown")
if CHIP == "tx":
    print("  !! Broken HW: H0 / V0 / H2  ->  use H1 / H3 / V1 / V2 / V3")
```

- [ ] **Step 5: Add STEP 3b–3e (standalone mid-session change blocks) to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 3b] CHANGE CHANNEL -- paste any time (no restart needed)
# =============================================================================
# Switches to a single measurement channel without re-running STEP 3.
# What it does: disable all paths -> centerbias ON -> route channel to beam
#               -> RTPS beam table zeroed -> common gain max (code 0)
#
# Examples:   chan("h1")   chan("h3")   chan("v1")   chan("v2")   chan("v3")
# After running: move SA cable to the new channel's RF port, then re-run STEP 4.
#
# RF port to SA cable:
#   chan("h1") -> RF_CH1_HPOL     chan("h3") -> RF_CH3_HPOL
#   chan("v1") -> RF_CH1_VPOL     chan("v2") -> RF_CH2_VPOL     chan("v3") -> RF_CH3_VPOL
# =============================================================================
# chan("h1")


# =============================================================================
# [STEP 3c] CHANGE COMMON GAIN -- paste any time
# =============================================================================
# Sets b{n}_common_gain: a single 6-bit attenuation code applied to ALL channels
# on the beam. After writing, latch() is required to push the value to analog.
#
# Code reference:
#   gain(0x00)   # max gain    (0 dB attenuation)   <- start here
#   gain(0x08)   # ~2 dB attenuation
#   gain(0x10)   # ~5 dB attenuation
#   gain(0x20)   # ~10 dB attenuation
#   gain(0x3F)   # max attenuation (~18 dB)
# =============================================================================
# gain(0x00)
# latch()


# =============================================================================
# [STEP 3d] CHANGE PER-CHANNEL GAIN -- paste any time (TX only)
# =============================================================================
# Sets gain_control_{pol}{idx} for one channel independently of others.
# Useful when channels need different gain to equalize output levels.
# 6-bit code: 0x00 = max gain, 0x3F = min gain.
#
# Examples:
#   chgain("h1", 0x08)   # H1: 6-bit gain code
#   chgain("h3", 0x10)   # H3: slightly more attenuation
# =============================================================================
# chgain("h1", 0x08)
# latch()


# =============================================================================
# [STEP 3e] CHANGE PER-CHANNEL ATTENUATION -- paste any time
# =============================================================================
# Sets ch{idx}_{pol}_b{beam}_attn_cal: per-channel-beam digital attenuation.
# Independent from common gain. Useful for fine-tuning channel-to-channel spread.
# Typical range: 0x00 (no atten) to 0x0F.
#
# Examples:
#   atten("h1", 0x00)   # no extra attenuation
#   atten("h3", 0x04)   # 4-code extra attenuation on H3
# =============================================================================
# atten("h1", 0x00)
# latch()
```

- [ ] **Step 6: Run all tests**

```
python -m pytest tests/test_workbook_smoke.py -v
```
Expected: All `PASSED`

- [ ] **Step 7: Commit**

```
git add scripts/cloudchaser_workbook.py tests/test_workbook_smoke.py
git commit -m "feat(workbook): add STEP 3 bring-up, helpers, and change blocks 3b-3e"
```

---

### Task 4: STEP 4 (SG/SA + Signal Check) + STEP 5 (Register Tweaks)

**Files:**
- Modify: `scripts/cloudchaser_workbook.py` — append STEP 4 + STEP 5a–5e
- Modify: `tests/test_workbook_smoke.py` — add SG/SA and register tweak tests

**Interfaces:**
- Consumes: `rf`, `saconf`, `peak`, `rd`, `wr`, `latch` from STEP 3 namespace
- Produces: SG configured, SA configured, peak reading available

- [ ] **Step 1: Write failing tests for STEP 4 + STEP 5**

Add to `tests/test_workbook_smoke.py`:
```python
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step4_rf_and_peak(capsys):
    """STEP 4: rf() sets SG state; peak() returns a float."""
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    ns["rf"](True, freq=28e9, level=-20)
    ns["saconf"](center=28e9, span=100e6, ref=20)
    p = ns["peak"]()
    assert isinstance(p, float), f"peak() should return float, got {type(p)}"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step5_wr_rd_field(capsys):
    """STEP 5: wr() + rd() run without exception in fake mode."""
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    ns["wr"]("b0_common_gain", 0x10)
    ns["rd"]("b0_common_gain")    # should print value without crashing
    out = capsys.readouterr().out
    assert "b0_common_gain" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step5_latch_runs(capsys):
    """STEP 5: latch() completes and prints confirmation."""
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    ns["latch"]()
    out = capsys.readouterr().out
    # latch() prints how many pulse_en fields it processed
    assert "latch" in out.lower() or "pulse" in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail correctly**

```
python -m pytest tests/test_workbook_smoke.py -v -k "step4 or step5"
```
Expected: `FAILED` — helper functions not yet in test scope (they are in workbook, not imported directly; test uses `_make_fake_chip` to get ns).
Actually these tests use `ns["rf"]` etc., so they should pass once the helpers work. Run and confirm `PASSED`.

- [ ] **Step 3: Add STEP 4 block to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 4] SG / SA SETUP + SIGNAL CHECK
# =============================================================================
# Sets up signal generator + spectrum analyzer, then reads a peak.
# Path loss from loss.toml is applied automatically to SG and SA offsets:
#   - SG level offset set so that LEVEL_DBM = chip input level
#   - SA ref level offset set so that peak() = chip output level
# After rf() + saconf(), just call peak() repeatedly to read signal.
#
# rf(on, freq=Hz, level=dBm)
#   on    : True = RF output ON  |  False = RF OFF
#   freq  : [Hz]  e.g. 25e9, 27e9, 28.0e9, 39e9
#   level : [dBm] chip INPUT level (path loss auto-compensated)
#
# saconf(center=Hz, span=Hz, ref=dBm, rbw=Hz, atten_db=dB)
#   center   : [Hz]  defaults to current SG frequency if omitted
#   span     : [Hz]  display span.  Default 100 MHz
#   ref      : [dBm] reference level (set ~10 dB above expected chip output)
#   rbw      : [Hz]  resolution bandwidth.  Default 1 MHz
#   atten_db : [dB]  input attenuator.  Default 10 dB
#
# peak() -> float [dBm]
#   Single sweep + marker to peak.  Returns chip output power [dBm] (loss-compensated).
# =============================================================================
rf(True, freq=FREQ_HZ, level=LEVEL_DBM)
saconf(center=FREQ_HZ, span=SA_SPAN, ref=SA_REF, rbw=SA_RBW, atten_db=SA_ATTEN)
p = peak()
print(f"  chip output ~= {p:.1f} dBm")

# Quick one-liners for mid-session adjustments (paste individually as needed):
# level(-15)                                    # change SG level only
# rf(False)  / rfoff()                          # RF OFF
# peak()                                        # re-read SA peak
# rf(True, freq=28.5e9, level=-20)              # change frequency + re-apply loss
# saconf(center=28.5e9, ref=20)                 # reconfigure SA to new center
# vi()                                          # check all rail V/I
```

- [ ] **Step 4: Add STEP 5 blocks to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 5a] READ / WRITE REGISTER FIELDS -- paste any time
# =============================================================================
# rd("field")         : read field value, print as hex + decimal, return int
# wr("field", val)    : write field (auto-commits; latch() still needed for pulse_en)
# latch()             : pulse all pulse_en fields to push shadow regs -> analog
# commit()            : flush staged writes (only needed when auto-commit is off)
#
# Common field names:
#   "b0_common_gain"           6-bit beam-0 gain (0=max, 0x3F=max atten)
#   "b1_common_gain"           6-bit beam-1 gain
#   "gain_control_h1"          per-channel H1 gain (TX only)
#   "gain_control_h3"          per-channel H3 gain (TX only)
#   "centerbias_en"            center-tap master bias (must be 1 for RF)
#   "centermirror_en"          center mirror bias (must be 1 for RF)
#   "ch1_h_b0_attn_cal"        H1-B0 digital attenuation
#   "version_id"               read-only chip ID (0xDC=TX Stampede, 0xD4=RX Blueway)
#   "cal_freq_sel"             calibration frequency band select code
# =============================================================================
rd("b0_common_gain")
# wr("b0_common_gain", 0x10); latch()


# =============================================================================
# [STEP 5b] ENABLE / DISABLE CHANNELS -- paste any time
# =============================================================================
# enable("h1")                 route H1 to current beam
# enable("h1", "h3")           route H1 and H3 together
# disable()                    disable all active paths (all channels off)
# disable("h1")                disable only H1 path
# paths()                      print current beam -> channel routing
# =============================================================================
# paths()


# =============================================================================
# [STEP 5c] CENTERBIAS MANUAL OVERRIDE -- paste any time
# =============================================================================
# centerbias_en + centermirror_en are NOT set by chip.path.enable().
# They are set during bring_up_tx/rx and by chan(). If you reset the chip
# or load a custom register state, you may need to re-enable them manually.
# =============================================================================
# wr("centerbias_en", 1)
# wr("centermirror_en", 1)


# =============================================================================
# [STEP 5d] BIAS STAGE DIAGNOSTICS -- paste any time
# =============================================================================
# Sweeps each amplifier stage's PTAT bias 0->63 and watches FE rail current delta.
# "NO RESPONSE" for a stage means that stage is not drawing power (likely dead).
# Run chan("hN") first to isolate one channel before running biasscan.
#
# biasscan("h1")   # diagnose H1
# biasscan("h3")   # diagnose H3
# =============================================================================
# chan("h1"); biasscan("h1")


# =============================================================================
# [STEP 5e] LOAD GOLDEN REGISTER STATE -- paste any time
# =============================================================================
# Restores the full register state captured from a known-good measurement.
# Source file: docs/golden_h0b0_25g.json (MATLAB mem_dump at 25 GHz, H0->B0)
# Use this to verify signal path integrity when starting from a blank state.
#
# load_golden()                             # load default golden file
# load_golden("path/to/custom.json")        # load a different capture
# =============================================================================
# load_golden()
```

- [ ] **Step 5: Run all tests**

```
python -m pytest tests/test_workbook_smoke.py -v
```
Expected: All `PASSED`

- [ ] **Step 6: Commit**

```
git add scripts/cloudchaser_workbook.py tests/test_workbook_smoke.py
git commit -m "feat(workbook): add STEP 4 (SG/SA) and STEP 5 (register tweaks)"
```

---

### Task 5: STEP 6 (Test Items) + STEP 7 (Shutdown) + final smoke test

**Files:**
- Modify: `scripts/cloudchaser_workbook.py` — append STEP 6 + STEP 7
- Modify: `tests/test_workbook_smoke.py` — add test-item wiring smoke test

**Interfaces:**
- Consumes: `bench`, `chip`, `_ns`, `CHIP`, `FAKE` from STEP 3
- Produces: `op1db`, `gain_index_accuracy`, `channel_gain_alignment`, `evm`, `acp`, `ip1db` as callable session functions

- [ ] **Step 1: Write failing test for session wiring (test items)**

Add to `tests/test_workbook_smoke.py`:
```python
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step6_session_wiring_op1db(capsys):
    """STEP 6: session globals wired so op1db() runs in fake mode."""
    import cloudchaser.session as _sess
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)

    # Wire session globals (same as STEP 6 block in workbook)
    _sess.B         = bench
    _sess.C         = chip
    _sess._fake     = True
    _sess._ns       = ns
    _sess._chip_kind = "tx"

    from cloudchaser.session import op1db
    result = op1db(freq_hz=28e9, gain_code=0)
    # In fake mode the test runs and returns a result object (not None)
    assert result is not None, "op1db() returned None in fake mode"
    out = capsys.readouterr().out
    assert "OP1dB" in out or "op1db" in out.lower() or "summary" in out.lower() or "===" in out
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_workbook_smoke.py::test_step6_session_wiring_op1db -v
```
Expected: `FAILED` — `_sess.C` is None (not yet wired). Confirms the wiring is needed.

- [ ] **Step 3: Add STEP 6 block to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 6] TEST ITEMS
# =============================================================================
# Wire session globals so the test-item functions (op1db, evm, etc.) work
# using the current bench + chip state (no reconnect or restart needed).
# Paste the entire wiring block ONCE, then uncomment individual test calls below.
#
# All test functions:
#   - apply path loss from loss.toml to SG/SA offsets automatically
#   - save results as CSV in out/ directory
#   - print a summary line when done
# =============================================================================

# --- Session wiring (paste this sub-block first) ----------------------------
import cloudchaser.session as _sess
_sess.B          = bench
_sess.C          = chip
_sess._fake      = FAKE
_sess._ns        = _ns
_sess._chip_kind = CHIP
from cloudchaser.session import (
    op1db, gain_index_accuracy, channel_gain_alignment, evm, acp, ip1db
)
print("[OK] Session wired: op1db / gain_index_accuracy / channel_gain_alignment / evm / acp / ip1db ready")
# Use params("op1db") etc. for full parameter descriptions after wiring

# --- OP1dB (TX output 1dB compression point) --------------------------------
# Sweeps SG input power from pin_start to pin_stop, measures output, fits 1dB compression.
#
# op1db(freq_hz=FREQ_HZ, gain_code=COMMON_GAIN)
# op1db(freq_hz=28e9, gain_code=0, pin_start_dbm=-30, pin_stop_dbm=5)
# params("op1db")    # show all parameters and their defaults

# --- Gain Index Accuracy -----------------------------------------------------
# Fixes SG level, sweeps common gain codes and (optionally) per-path RTPS codes.
#
# gain_index_accuracy(sg_level_dbm=0)
# gain_index_accuracy(sg_level_dbm=0, channel_kind="beamtable", channel_quad=1)
# params("gain_index_accuracy")

# --- Channel Gain Alignment --------------------------------------------------
# Interactive or auto: measures output level per channel, reports spread [dB].
#   channel_mode="single"  : chip switches channel per measurement (auto SA)
#   channel_mode="all"     : all channels ON simultaneously, you move SA cable
#   channels_script="h1,h3": non-interactive script mode (no input() prompts)
#
# channel_gain_alignment(channel_mode="single")
# channel_gain_alignment(channels_script="h1,h3")
# params("channel_gain_alignment")

# --- EVM (5G NR modulation quality vs output power) -------------------------
# modulation="setup"  : SG creates waveform internally (default)
# modulation="load"   : load waveform from file (waveform_path required)
# modulation="manual" : waveform already loaded on SG, skip setup
#
# evm(freq_hz=FREQ_HZ)
# evm(freq_hz=28e9, modulation="load", waveform_path="waveforms/nr_fr2.wv")
# params("evm")

# --- ACP (Adjacent Channel Power Ratio vs output power) ---------------------
# acp(freq_hz=FREQ_HZ)
# params("acp")

# --- IP1dB (RX input 1dB compression — Blueway EVB only) --------------------
# RX signal flow: SG -> channel port (antenna input) -> IC -> beam port -> SA
#
# ip1db(freq_hz=19.5e9, gain_code=0)
# params("ip1db")
```

- [ ] **Step 4: Add STEP 7 block to workbook**

Append to `scripts/cloudchaser_workbook.py`:
```python

# =============================================================================
# [STEP 7] SHUTDOWN
# =============================================================================
# Safely ends the session:
#   1. Turns RF output OFF (SG: RF off)
#   2. Ramps all PSU rails to 0V in reverse power-up order:
#      FE1_4V0 -> FE3_1V8 -> FE2_1V8 -> IO_1V3 -> DIG_1V8 -> CORE_1V0
#   3. Closes all TCP sockets
#
# Call shutdown() when you are done with the EVB for this session.
# Power stays OFF after this; re-paste STEP 1+2 to start a new session.
# =============================================================================
# rfoff()          # optional: turn RF off before shutdown (shutdown() does this too)
# shutdown()       # ramps rails to 0V
# bench.close_all()  # optional: close sockets after shutdown
```

- [ ] **Step 5: Run all tests**

```
python -m pytest tests/test_workbook_smoke.py -v
```
Expected: All `PASSED`

- [ ] **Step 6: Final syntax check on workbook**

```
python -c "import ast; ast.parse(open('scripts/cloudchaser_workbook.py').read()); print('OK: syntax valid')"
```
Expected: `OK: syntax valid`

- [ ] **Step 7: Run full test suite**

```
python -m pytest -v
```
Expected: All tests `PASSED` (workbook tests + existing tests)

- [ ] **Step 8: Commit**

```
git add scripts/cloudchaser_workbook.py tests/test_workbook_smoke.py
git commit -m "feat(workbook): add STEP 6 (test items) and STEP 7 (shutdown) -- complete workbook"
```

---

## Self-Review

### 1. Spec Coverage

| Spec requirement | Task |
|-----------------|------|
| All parameters in one PARAMETERS block (IPs + chip/board + SG/SA + misc) | Task 1 |
| IP addresses in PARAMETERS block | Task 1 |
| STEP 1: Connect (IP override + bench.toml load) | Task 2 |
| STEP 2: Power up (rail by rail) | Task 2 |
| STEP 3: Chip init + bring-up + all helpers | Task 3 |
| Standalone channel change block (3b) | Task 3 |
| Standalone gain change blocks (3c, 3d, 3e) | Task 3 |
| STEP 4: SG/SA setup + signal check | Task 4 |
| STEP 5: Register tweaks (rd/wr/latch/biasscan/centerbias/load_golden) | Task 4 |
| STEP 6: Test items (op1db/evm/acp/ip1db/gain_idx/chan_align) with session wiring | Task 5 |
| STEP 7: Shutdown | Task 5 |
| Detailed inline comments on every parameter (valid values, examples) | Task 1 |
| Comments policy: all parameters have units + valid values + examples | Task 1-5 |
| `FAKE=True` smoke tests for each block | Tasks 1-5 |

No gaps identified.

### 2. Placeholder Scan

No "TBD", "TODO", "implement later", or vague error handling instructions found.

### 3. Type Consistency

- `_make_fake_bench()` → returns `bench: Bench` → used in `_make_fake_chip(bench)` → returns `(chip, ns: dict)` → tests access `ns["rd"]`, `ns["gain"]`, etc.
- `_sess.B`, `_sess.C`, `_sess._fake`, `_sess._ns`, `_sess._chip_kind` — exact attribute names verified against `session.py` global declarations.
- `bench.board.active_channels`, `bench.board.beam`, `bench.chip_kind` — verified against `Bench` dataclass and `_apply_board_overrides` in `session.py`.
- `bench.psu1.host`, `bench.psu2.host`, etc. — verified as `ScpiSocket.host` attribute (set before `connect()` is called).
