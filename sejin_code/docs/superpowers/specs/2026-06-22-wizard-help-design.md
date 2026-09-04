# Design: wizard() + enhanced help() + start() banner

**Date:** 2026-06-22
**Scope:** `src/cloudchaser/session.py` only
**Goal:** Reduce friction when returning to the tool after a gap — guided measurement wizard, richer help, better start banner.

---

## Problem

Coming back after a few days:
- Inside the IPython session, hard to remember which test to run and with what parameters.
- `help()` shows signatures but not purpose or key parameters at a glance.
- After `start()`, no hint about what to do next.

## Solution (Approach B)

Three targeted additions to `session.py`, no other files changed:

1. `wizard()` — step-by-step guided measurement
2. Enhanced `help()` — purpose + key params + example per test
3. Improved `start()` banner — typical flows shown on session start

---

## 1. `wizard()` behavior

Called after `start()`. Guides the user through test selection → parameter input → run.

### Step 1 — Test selection

```
=== Measurement Wizard ===
Active: channels=['h1']  beam=b0
!! Broken HW: H0 / V0 / H2 -- use H1 / H3 / V1 / V2 / V3

Select test:
  1. op1db                  OP1dB -- CW power sweep, find compression point
  2. gain_index_accuracy    Gain Index Accuracy -- sweep gain code vs output
  3. channel_gain_alignment Channel Gain Alignment -- per-channel output (interactive)
  4. evm                    EVM -- 5G NR modulation quality vs power
  5. acp                    ACP -- adjacent channel power ratio vs power
  q. quit

>
```

### Step 2 — Parameter input

- Show each **user-facing parameter** with default value and help text.
- Press Enter → keep default. Type a value → override.
- **Hidden by default** (use defaults silently): internal params (`ref_skip_pts`, `ref_avg_pts`, `sa_span_hz`, `sa_ref_level_dbm`, `settle_s`, `gain_field`). These rarely need changing.
- `in_loss_db` / `out_loss_db`: auto-applied from `loss.toml`. Wizard shows this and offers override.

```
--- op1db parameters (Enter = keep default) ---
  freq_hz       [28000000000.0 Hz]   CW frequency          :
  gain_code     [32]                 Gain code (0=max)     : 0
  pin_start_dbm [-22.0 dBm]         SG sweep start        :
  pin_stop_dbm  [10.0 dBm]          SG sweep stop         : 5
  log_idd       [False]             Log supply current     :

  in_loss / out_loss: auto from loss.toml (override? [n]: )
```

### Step 3 — Confirm and run

```
=== Ready to run ===
  Test      : OP1dB Test
  Key params: freq_hz=28e9  gain_code=0  sg=-22..5 dBm
  Loss      : auto (loss.toml)

Run now? [Y/n]:
```

On confirmation, calls the existing session function (`op1db()`, `evm()`, etc.) with collected kwargs.

### Parameter visibility rules

| Parameter | Shown in wizard |
|-----------|----------------|
| `freq_hz` | yes |
| `gain_code`, `sg_level_dbm` | yes |
| `pin_start_dbm`, `pin_stop_dbm` | yes |
| `channel_mode`, `channels_script` | yes |
| `modulation`, `waveform_path` | yes |
| `log_idd` | yes |
| `in_loss_db`, `out_loss_db` | offered as optional override |
| `ref_skip_pts`, `ref_avg_pts` | hidden (use default) |
| `sa_span_hz`, `sa_ref_level_dbm` | hidden (use default) |
| `settle_s`, `gain_field` | hidden (use default) |

### `channel_gain_alignment` special case

This test is already interactive (prompts per channel). Wizard collects `channel_mode` only, then calls `channel_gain_alignment(channel_mode=...)` which handles its own prompts.

---

## 2. Enhanced `help()`

### `help()` — full list

**Measure section** expanded: each test gets 3 lines (signature, purpose, key params hint).

```
[measure]
  !! Healthy channels only: H1 / H3 / V1 / V2 / V3

  op1db(freq_hz=28e9, gain_code=0)
    CW power sweep -> output 1-dB compression point. CSV -> out/.
    Key: gain_code(0=max), pin_start/stop_dbm, log_idd | params('op1db')

  gain_index_accuracy(sg_level_dbm=0)
    Sweep common & per-path(RTPS) gain codes, record gain vs index.
    Key: channel_kind, channel_quad, channel_codes | params('gain_index_accuracy')

  channel_gain_alignment(channel_mode='all')
    Move SA cable channel by channel, record output level spread.
    channel_mode: 'all'(all ON) / 'single'(switch per ch) | params('channel_gain_alignment')

  evm(freq_hz=28e9)
    5G NR modulation quality (EVM[dB]) vs output power.
    Key: modulation(setup/load/manual), waveform_path | params('evm')

  acp(freq_hz=28e9)
    Adjacent channel power ratio[dBc] vs output power.
    Key: modulation | params('acp')

  wizard()   <- guided: select test + enter params interactively
```

### `help('op1db')` — detail

Existing docstring output + **parameter table appended automatically** (same data as `params('op1db')`, no need to call separately):

```
op1db(**kw)

OP1dB measurement. Path loss auto-applied from loss.toml.
...

Parameters:
  freq_hz        float   28e9 Hz     CW frequency
  gain_code      int     0x20        gain atten code (0=max gain)
  pin_start_dbm  float  -22.0 dBm   SG sweep start
  pin_stop_dbm   float   10.0 dBm   SG sweep stop
  log_idd        bool    False       log supply current per point
  ...
```

---

## 3. `start()` banner

**Before:**
```
[session] ready: channels=['h1'] beam=b0 fake=False power=True
type help() for commands.  (objects: B=bench, C=chip)
```

**After:**
```
[session] ready: channels=['h1']  beam=b0  fake=False  power=True

  wizard()   <- step-by-step guided measurement  (start here)
  help()     <- full command reference
  status()   <- current channel / gain / SG state

  Typical flows:
    Signal check : rf(True, freq=28e9, level=-10) -> peak()
    OP1dB        : op1db(freq_hz=28e9)
    Chan align   : channel_gain_alignment(channel_mode='all')

  !! Broken HW: H0 / V0 / H2  ->  use H1 / H3 / V1..V3
```

---

## 4. Implementation scope

| File | Change |
|------|--------|
| `src/cloudchaser/session.py` | Add `wizard()`, expand `_HELP`, improve `start()` banner, add `wizard` to `_ns` |
| `tests/test_wizard_fake.py` | New: fake-mode test covering wizard flow (non-interactive path via monkeypatch) |

No other files touched. All existing behavior preserved.

---

## 5. Out of scope

- No GUI, no TUI (curses/Rich)
- No changes to test_items, runner, or config
- No "advanced parameters" mode in wizard (kept simple — hidden params use defaults)
- Wizard does not handle `start()` itself (channel/power selection stays manual)
