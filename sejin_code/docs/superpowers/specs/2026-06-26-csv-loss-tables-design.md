# CSV-based Path Loss Tables — Design

Date: 2026-06-26
Status: Approved (brainstorming)

## Background

Path loss (cable + board trace) is compensated at measure time by applying
SG/SA level offsets so that, inside the chip, `SG level = chip input` and
`SA read = chip output`. The current model reads two TOML files
(`config/loss.toml` for TX, `config/loss_rx.toml` for RX), each carrying
per-frequency cable loss (`sg_to_evb` / `evb_to_sa`) plus per-port board
trace loss (`b0,b1,h0..h3,v0..v3`), with `bench.apply_path_loss` swapping
beam/channel for RX.

These TOML tables held placeholder values. The user has now measured the real
losses with a VNA (MS4644B) and exported three CSV files into `Loss_data/`:

- `SG_Cable_Loss_<YYMMDD>.csv` — SG → EVB cable
- `SA_Cable_Loss_<YYMMDD>.csv` — EVB → SA cable
- `Board_Trace_Loss_<YYMMDD>.csv` — board trace

Each CSV is a 4-trace S-parameter sweep (S11/S12/S21/S22), 16–32 GHz, 321
points at 50 MHz spacing. The header block is lines starting with non-digits;
the data section begins after a `PNT,FREQ1.GHZ,LOGMAG1,...` row. Columns
(0-based): `1=FREQ(GHz)`, `5=LOGMAG2=S12 (dB)`, `8=LOGMAG3=S21 (dB)`.

## Decisions (locked during brainstorming)

1. **S21 vs S12** — use the conservative `loss(f) = max(|S12(f)|, |S21(f)|)`
   per frequency. They are nearly identical (reciprocal passive network); the
   max applies slightly more compensation.
2. **Board trace** — a single trace value per frequency, split evenly:
   half added to the SG side, half to the SA side. No per-port (beam/channel)
   differentiation anymore.
3. **CSV selection** — auto-pick the newest file of each kind from `Loss_data/`
   (by `YYMMDD` token in the filename, falling back to mtime). The chosen
   filenames are logged and recorded in CSV meta.
4. **Manual override** — add a direct offset setter `set_loss(in_db, out_db)`;
   `set_loss()` with no args clears it and returns to CSV-auto.
5. **TX/RX unification** — one CSV set (16–32 GHz) covers both bands
   (RX 17.7–21.2, TX 27.5–31). Cables are physically fixed to the SG/SA side
   and the trace is beam/channel-independent, so the loss is identical for TX
   and RX. The `chip_kind` swap is removed.
6. **Folder** — `Loss_data/` at repo root, a code constant (overridable by
   argument for tests).

## Loss model

```
in_loss(f)  = SG_cable(f) + trace(f)/2     # SG level offset = -(in_loss)
out_loss(f) = SA_cable(f) + trace(f)/2     # SA ref level offset = +out_loss
```

`cable(f)` / `trace(f)` are obtained by linear interpolation on the 50 MHz
grid; out-of-range frequencies clamp to the nearest endpoint (existing
`_interp` behavior).

## Components

### `src/cloudchaser/loss.py` (rewritten)

Public surface:

- `LOSS_DIR` — constant `Path(repo_root)/"Loss_data"`.
- `load_loss_csv(path) -> list[tuple[freq_hz, loss_db]]` — parse one VNA CSV;
  skip header until the `PNT,...` row, then for each data row take
  `max(abs(S12), abs(S21))` as the loss and `FREQ1*1e9` as the frequency;
  return sorted.
- `latest_files(loss_dir=LOSS_DIR) -> {"sg":Path, "sa":Path, "trace":Path}` —
  newest per kind by date token / mtime; raises a clear English error if any
  kind is missing.
- `get_loss(freq_hz, loss_dir=LOSS_DIR) -> (in_loss, out_loss)` — applies the
  model above.
- `loss_table(loss_dir=LOSS_DIR) -> str` — human-readable table (which files,
  a few sample frequencies with in/out loss).
- `_interp` — kept as-is.

Removed: TOML loading, `DEFAULT_LOSS`/`DEFAULT_LOSS_RX`, per-port `TRACE_PORTS`,
`load_cable`/`load_trace`/`get_cable`/`get_trace`, beam/channel/path params,
legacy `[[loss]]` fallback.

### `src/cloudchaser/bench.py`

- Add `self._loss_override: tuple[float, float] | None = None` to `Bench`.
- `apply_path_loss(freq_hz, *, channel=None, log=print)` — drop `chip_kind`/
  beam-channel logic. **Keep `channel=` accepted but ignored** for back-compat
  (callers in `channel_gain_alignment.py` and `test_loss_offset.py` still pass
  it; trace is now channel-independent so it has no effect on the value). If
  `_loss_override` is set, use it; else `get_loss(freq_hz)`. Set SG offset
  `-(in_loss)`, SA offset `+out_loss`, log, return `(in_loss, out_loss)`.
- Add `set_loss_override(in_db, out_db)` / `clear_loss_override()` helpers.
- Remove `DEFAULT_LOSS_RX` import.

### `src/cloudchaser/session.py`

- `loss(freq_ghz=None)` — rewrite to use CSV `loss_table()` / `get_loss()`.
  Drop `DEFAULT_LOSS_RX` and the RX beam/channel swap. Show override state when
  active.
- New `set_loss(in_db=None, out_db=None)` exposed in `_ns`:
  - both given → `B.set_loss_override(in_db, out_db)`, print confirmation;
  - no args → `B.clear_loss_override()`, print "back to CSV-auto".
- Register `set_loss` in `_ns` and in the help listing.
- Remove `DEFAULT_LOSS_RX` constant/import.

### Callers of `apply_path_loss(channel=...)`

`manual.py`, `acp/evm/gain_index_accuracy/ip1db/op1db` call
`apply_path_loss(freq, log=...)` — unaffected. `channel_gain_alignment.py`
(lines 121, 161) and `test_loss_offset.py` pass `channel=`; since `channel=`
is kept as an accepted-but-ignored kwarg, these callers need no edits and the
per-channel `out_loss` is now simply the same value for every channel. No call
site rewrites required.

## Config / files removed

- Delete `config/loss.toml`, `config/loss_rx.toml`.
- `Loss_data/*.csv` stays **git-ignored** (matches the existing `*.csv` rule;
  cal data is local to this measurement rig). Code raises a clear English
  error if the folder/files are missing, rather than silently using 0 dB.

## Testing

- `tests/test_loss.py` — rewrite: parse a small fixture CSV (a few rows),
  assert `max(|S12|,|S21|)` selection, interpolation between points, endpoint
  clamp, and `in/out = cable + trace/2`.
- `tests/test_loss_offset.py` — update to the new `apply_path_loss` (no
  beam/channel), assert SG offset `= -(SG_cable+trace/2)` and SA offset
  `= +(SA_cable+trace/2)`; add a manual-override test (`set_loss` wins over
  CSV, `set_loss()` reverts).
- Fixtures live under `tests/` (small hand-written CSVs), not the real
  `Loss_data/` files, so tests are hermetic.
- `python -m pytest` green before commit.

## Docs to sync

- `CLAUDE.md` — replace the loss.toml schema rule with the CSV model
  (`Loss_data/`, max(S12,S21), trace/2 split, no TX/RX/per-port).
- `docs/SESSION.md` — loss section + `set_loss` usage.
- `README.md` — config/loss description.

## Out of scope

- Re-running rx_suite measurements (separate task, done by user after this
  lands).
- Phase data from the CSVs (only magnitude/loss is used).
- Per-port trace differentiation (intentionally dropped).
