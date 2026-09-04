# Bias Current Matching against the Sivers Reference IC — Design

Date: 2026-09-01
Status: Approved (brainstorming)

## Background

Sivers' feedback on our bias questions (mail, 2026-08-25) says the bias *code*
differs from IC to IC, but the *current consumption matrix* is common. To
compare apples to apples we must sweep our bias codes until our EVB draws the
same rail currents as their reference IC.

They named **six** bias targets, not three:

| Sivers name    | Register field (our code)        | Location               |
|----------------|----------------------------------|------------------------|
| PTAT_St1 (PA)  | `ptat_st1`   = FE bias col 0     | `FH.set_fe_bias` 8x5   |
| PTAT_St2 (DRV) | `ptat_st2`   = FE bias col 1     | `FH.set_fe_bias` 8x5   |
| PTAT_St3 (Comb)| `ptat_st3`   = FE bias col 2     | `FH.set_fe_bias` 8x5   |
| Dist St1       | `st1_ptat`   = DIST bias col 0   | `FH.set_dist_bias` 3x6 |
| Dist St2_0     | `st2_0_ptat` = DIST bias col 1   | `FH.set_dist_bias` 3x6 |
| Dist St2_1     | `st2_1_ptat` = DIST bias col 2   | `FH.set_dist_bias` 3x6 |

All six fields are 6-bit (0..63). Our previous work swept only the three FE
PTAT codes and tried 63/63/63, which was recorded as an un-adopted trial
value rather than a setting we shipped; the three DIST codes were left at the v4
sheet values (`CASPER_DIST_B0` = 50 / 13 / `bench.toml:dist_st2_1_ptat`).

## Reference data

`reference/Stampede_T582616915_25_Aug_26_09_30_19.csv` — their reference IC,
beam 0 / pol 0 / channel 0, a **VDD_FE1 sweep** (4.0, 3.6, 3.3, 3.0, 2.7,
2.4, 2.2 V) crossed with RF 27.5..31.0 GHz in 0.5 GHz steps, Pin about
-28 dBm at the chip.

Row 1 is a `Reset state` row. Subtracting it isolates what each rail is:

| Rail (theirs) | our `bench.toml` rail | reset | @4V   | delta | meaning                          |
|---------------|-----------------------|-------|-------|-------|----------------------------------|
| IDC_1p0       | `CORE_1V0`            | 3.2   | 3.2   | 0.0   | digital / LDO — bias-independent |
| IDC_1p8       | `DIG_1V8`             | 0.9   | 13.9  | +13.0 | master bias generator            |
| IDC_Dist      | `IO_1V3`              | 0.0   | 64.4  | +64.4 | splitter chain St1/St2_0/St2_1   |
| IDC_FE1       | `FE1_4V0`             | 4.34  | 27.8  | +23.5 | PA drain                         |
| IDC_FE2       | `FE2_1V8`             | 0.07  | 18.35 | +18.3 | Driver drain                     |
| IDC_FE3       | `FE3_1V8`             | 0.07  | 10.37 | +10.3 | Combiner drain                   |

Across the whole VDD_FE1 sweep only `IDC_FE1` moves (27.8 -> 6.5 mA); the
other five rails stay flat to within the meter's 0.1 mA resolution. Their own
data therefore demonstrates that the rails are near-independent.

## Decisions (locked during brainstorming)

1. **`CORE_1V0` is not a tuning target.** Reset current equals operating
   current, so no bias code moves it. Reported as a health check only.
2. **`DIG_1V8` is not a tuning target either.** It is a dependent variable
   (the reference legs of the current mirrors sit on it). Reported, not
   solved for.
3. **Four real targets**: `FE1_4V0` 27.8, `FE2_1V8` 18.35, `FE3_1V8` 10.37,
   `IO_1V3` 64.4 mA.
4. **Search = measured Jacobian, then block-diagonal 1-D bisection.** The
   coupling matrix is measured first (19 points) rather than assumed; the
   solve then exploits the block structure. A full 6-D grid (64^6) is
   rejected.
5. **The DIST block is under-determined** (3 knobs, 1 observable). Resolved
   in two stages: (a) lock the v4 Casper ratio and bisect a single scale
   factor; (b) later, optionally search the `IDC_Dist`-constrained surface
   for maximum gain to check that (a) is not leaving performance behind.
6. **Targets live in `config/bench.toml`**, not in code.
7. **Verification reproduces their script** (VDD_FE1 x RF frequency) and
   emits their exact column names, so the two CSVs can be diffed directly.

## Open items (to be asked of Sivers by mail)

1. **Dist rail voltage on their board.** Ours is 1.3 V. If theirs differs,
   the 64.4 mA target is not transferable. This is the single largest risk to
   the whole exercise.
2. Supply voltages for FE2 / FE3 / 1p0 / 1p8 (we assume 1.8 / 1.8 / 1.0 /
   1.8 V from the naming, but it is not stated).
3. Ambient temperature at measurement time — PTAT currents are by definition
   temperature-proportional.
4. Per-stage current split of the Dist rail (St1 vs St2_0 vs St2_1). If they
   provide it, stage D below becomes unnecessary.
(Splitter mode was briefly an open question and is now settled — see
"Splitter mode" below. It is recorded there rather than here.)

## Splitter mode (settled)

Every result Sivers has shared was taken in **split** mode, per the project
owner. `bias_match` therefore follows `bench.toml:split_mode` (currently
`true` = split) by default; `--split` / `--no-split` exist only to override
that deliberately, and the effective mode is recorded in every CSV's meta.

This was briefly ruled the other way during implementation, on the reasoning
that their 23.1 dB single-channel gain matched our thru measurement (~24 dB,
commit d7b76c5) far better than our split one (~16 dB). That reasoning was
wrong: it compared across mode AND bias at once. Their 23.1 dB is split at
*their* bias codes; our 16 dB is split at *ours*. The gap between those two
numbers is not a mode difference — it is precisely the gap this whole
exercise exists to close.

## Configuration

New section in `config/bench.toml`:

```toml
[bias_match]
# Sivers reference IC currents, VDD_FE1 = 4 V, B0/H0/ch0 single channel.
# Source: reference/Stampede_T582616915_25_Aug_26_09_30_19.csv
targets_ma  = { FE1_4V0 = 27.8, FE2_1V8 = 18.35, FE3_1V8 = 10.37, IO_1V3 = 64.4 }
report_only = ["DIG_1V8", "CORE_1V0"]
tol_ma      = 0.5             # per-rail convergence tolerance
avg_n       = 3               # rail-current readings averaged per point
settle_s    = 0.3             # wait after a register write before reading
max_iter    = 3               # outer coupling-convergence iterations
dist_ratio  = [50, 13, 13]    # v4 Casper St1 : St2_0 : St2_1, scaled by k
```

`dist_ratio` mirrors today's operating point: `CASPER_DIST_B0` gives
St1 = 50 and St2_0 = 13, and St2_1 comes from `bench.toml:dist_st2_1_ptat`,
which is currently 13 (the v4 sheet value; the older MATLAB dump used 28).
The 13-vs-28 question is still open, so `dist-gain` (stage D) should be run
with both ratios if stage B leaves gain on the table.

Also correct the misleading comment on the `IO_1V3` rail: it is described as
an "SPI-only rail", but reset 0 mA -> operating 64.4 mA shows it powers the
distribution/splitter chain. The `detect = true` behaviour is unchanged.

## Components

### `src/cloudchaser/bias_match.py`

One module, four subcommands, run as `python -m cloudchaser.bias_match <cmd>`.

Common measurement state, identical for every subcommand: single channel
(default `--beam b0 --ch h0`), `common_gain = 0`, zero beam table — i.e. the
setup `biasscan_compare` already performs. Each rail reading is the mean of
`avg_n` samples of `Bench.read_all_vi()` taken after `settle_s`.

**A. `jacobian`** — baseline plus, per knob, one perturbation and a low/high
probe pair that checks the response sign is consistent (default `--delta 8`,
clamped into 0..63); 19 measurement points, each recording all six rails. Emits a 6x6 `dI/dcode` table (mA per code step) to the console and
to `out/bias_jacobian_<date>.csv`.

Purpose beyond the solve: it verifies the block-diagonal assumption instead
of assuming it, detects dead knobs (`|delta| ~ 0`), records the sign of every
response so the bisection knows its direction, and produces the evidence for
the "does PTAT move the 1p8 rail?" answer back to Sivers.

**B. `solve`** — outer loop over `max_iter`, inner 1-D bisection per knob:

```
for it in 1..max_iter:
    ptat_st1 <- bisect(rail FE1_4V0 -> 27.8)     # <= 6 steps
    ptat_st2 <- bisect(rail FE2_1V8 -> 18.35)    # <= 6 steps
    ptat_st3 <- bisect(rail FE3_1V8 -> 10.37)    # <= 6 steps
    k        <- bisect(rail IO_1V3  -> 64.4)     # dist = clamp(round(k*ratio))
    if all rails within tol_ma: break
```

Bisection assumes monotonicity; the direction comes from stage A. If stage A
reported a non-monotonic or non-responding knob, that knob falls back to a
full linear scan (64 points) and a warning is printed. Because `k` maps to
three integer codes, the effective `k` grid is coarse near the top of the
range — the bisection terminates on code-vector equality, not on `k`
precision.

Output: the six final codes, the six measured rail currents, per-rail error,
and a ready-to-paste TOML snippet; plus `out/bias_match_<date>.csv`.

**C. `verify`** — replays their measurement: RF 27.5..31.0 GHz in 0.5 GHz
steps for each VDD_FE1 in {4.0, 3.6, 3.3, 3.0, 2.7, 2.4, 2.2}, writing
`out/bias_verify_<date>.csv` with Sivers' column names (`RF_Freq[GHz]`,
`Gain[dB]`, `IDC_1p0[mA]`, ...) so their file and ours can be diffed
column by column. Uses the existing loss model for level calibration.

**D. `dist-gain`** (second phase, optional) — coarse grid over the three DIST
codes, keeping only combinations whose `IO_1V3` current lands within
`64.4 +/- 2` mA. That constraint collapses the 3-D space to a 2-D surface;
gain at 28 GHz is then measured on the surviving points and the maximum is
reported. Confirms or refutes the ratio-locked solution from B.

### Refactor: shared single-channel setup

`biasscan_compare._setup_single()` is exactly the state `bias_match` needs.
Promote it to `board/gain_map.py` as `setup_single_channel(fh, beam, ch)` and
have `biasscan_compare` call it, so the setup is not duplicated. No behaviour
change.

### Untouched

`FH.get/set_fe_bias` (8x5), `FH.get/set_dist_bias` (3x6 + ctat) and
`Bench.read_all_vi()` are used as they are. No new low-level register code,
and no vendor high-level write API (the raw-register bring-up rule stands).

## Measurement cost

| Stage | Points |
|-------|--------|
| A jacobian | 19 |
| B solve    | <= 4 knobs x 6 steps x 3 iterations = 72; a knob that falls back to the linear scan costs 64 instead of 6 |
| C verify   | 7 VDD x 8 freq = 56 |
| D dist-gain (optional) | ~125 screened, ~30 with gain |

Roughly 150 measurement points for A-C, one to two hours on the bench, versus
6.9e10 for an exhaustive 6-D grid.

## Error handling

- A rail current beyond `i_limit`, or a PSU that has fallen into CC, aborts
  the run with the offending rail named.
- A knob whose stage-A response is below a noise floor (default 0.2 mA over
  the perturbation) is reported as NO RESPONSE and skipped; the solve
  continues on the remaining knobs.
- Non-convergence after `max_iter` is not an error: the best-so-far codes and
  the residual errors are reported, so a partial result is still usable.
- `--fake` runs the whole flow against the fake transport. Currents do not
  move there, so the solve terminates on `max_iter` and only the control flow
  is exercised.

## Metadata

The chip temperature sensor is a vendor stub (it returns 0), so temperature
cannot be read from the die. `--ambient-c <float>` takes it from the operator
and records it in every CSV. This is optional and our own addition: Sivers
never raised temperature and their reference CSV has no temperature column.
The rationale is only that the PTAT field name implies the bias current
tracks absolute temperature, so a lab-to-lab difference of ~10 C would be a
few percent -- comparable to `tol_ma` -- and worth being able to rule out
afterwards. No temperature coefficient is given in any primary document, so
that figure is an inference from the name, not a datasheet number.
Chip serial, active channel, rail voltages and the source CSV filename are
recorded as well.

## Testing

`tests/test_bias_match.py`, all `--fake`, with a synthetic linear rail model
injected in place of `Bench.read_all_vi`:

1. `jacobian` produces a 6x6 table with the expected diagonal dominance.
2. `solve` converges to the codes implied by the synthetic model.
3. The DIST solve preserves the configured ratio (codes stay proportional to
   `dist_ratio` within integer rounding).
4. An unreachable target (beyond code 63) ends with a warning and a reported
   residual rather than an exception.

## Conventions

- All user-visible text (print / log / raise) and any docstring reachable
  from the `_ns` session namespace is written in English.
- Config values go in `config/bench.toml`, not in code.
- `docs/SESSION.md` and `README.md` get the new command documented; the
  module is a bench tool, not a `TestItem`, so `test_items/_ALL` is untouched.
