# Bias Current Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `python -m cloudchaser.bias_match`, a bench tool that sweeps the six Sivers bias codes until our EVB rail currents match their reference IC, then reproduces their measurement for a direct CSV diff.

**Architecture:** One new module `src/cloudchaser/bias_match.py` with four subcommands (`jacobian`, `solve`, `verify`, `dist-gain`) built on a small knob/rail primitive layer. The search measures a 6x6 coupling matrix first, then exploits the block-diagonal structure with per-rail 1-D bisection; the under-determined DIST block is bisected on a single ratio scale factor. Single-channel setup is shared with `biasscan_compare` via a promoted `gain_map.setup_single_channel()`.

**Tech Stack:** Python 3.13, stdlib only (`tomllib`, `argparse`, `csv`, `dataclasses`), existing `FH` raw-register engine, `Bench` PSU/SG/SA layer, pytest with `--fake` transports.

**Spec:** `docs/superpowers/specs/2026-09-01-bias-current-matching-design.md`

## Global Constraints

- Python 3.13; run tests with the project venv: `python -m pytest`. **Every task ends with the full suite passing before the commit.**
- All user-visible text (`print` / `log` / `raise` messages) and any docstring reachable from the `_ns` session namespace is written in **English**. Code comments and module docstrings may be Korean.
- Configuration values go in `config/bench.toml`, never hard-coded in the module.
- Writes to the chip go through the raw `FH` engine only. Never call vendor high-level write APIs (`chip.fields.wr`, `chip.path.*`, `chip.commit`, `chip.beam_table`). `fh.rd` / `fields.rd` reads are fine.
- Every subcommand must run under `--fake` without hardware.
- Commit messages: PowerShell here-strings put the closing `'@` at column 0; avoid non-ASCII (no em-dash, no `§`) because the console is cp949.
- Work on branch `feat/bias-current-matching` (already created, spec already committed there).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `config/bench.toml` | new `[bias_match]` section (targets, tolerances); corrected `IO_1V3` comment |
| `src/cloudchaser/board/gain_map.py` | gains **plus** the shared `setup_single_channel()` single-channel measurement state |
| `src/cloudchaser/biasscan_compare.py` | delegates its `_setup_single` to `gain_map.setup_single_channel` |
| `src/cloudchaser/bias_match.py` | config loader, knob table, rail reads, jacobian, solve, verify, dist-gain, CLI |
| `tests/test_bias_match.py` | fake-mode tests with a synthetic rail model |
| `README.md`, `docs/SESSION.md` | document the new tool |

---

### Task 1: `[bias_match]` config section and loader

**Files:**
- Modify: `config/bench.toml` (append a new section; fix the `IO_1V3` rail comment around line 44)
- Create: `src/cloudchaser/bias_match.py`
- Test: `tests/test_bias_match.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `BiasMatchCfg` dataclass with fields `targets_ma: dict[str, float]`, `report_only: list[str]`, `tol_ma: float`, `avg_n: int`, `settle_s: float`, `max_iter: int`, `dist_ratio: list[int]`
  - `load_bias_match_cfg(path: Path) -> BiasMatchCfg`
  - `DEFAULT_CONFIG: Path` (re-exported from `setup_tx`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_bias_match.py`:

```python
"""bias_match 의 오프라인(fake) 테스트.

전류계는 fake 에서 정적이라, 탐색 로직은 fh 레지스터 read-back 을 입력으로 쓰는
합성 레일 모델(_synthetic_read_all_vi)을 bench.read_all_vi 에 주입해 검증한다.
"""

from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def test_load_bias_match_cfg():
    from cloudchaser.bias_match import load_bias_match_cfg

    cfg = load_bias_match_cfg(CONFIG)
    assert cfg.targets_ma["FE1_4V0"] == 27.8
    assert cfg.targets_ma["FE2_1V8"] == 18.35
    assert cfg.targets_ma["FE3_1V8"] == 10.37
    assert cfg.targets_ma["IO_1V3"] == 64.4
    assert cfg.report_only == ["DIG_1V8", "CORE_1V0"]
    assert cfg.tol_ma == 0.5
    assert cfg.avg_n == 3
    assert cfg.max_iter == 3
    assert cfg.dist_ratio == [50, 13, 13]


def test_load_bias_match_cfg_defaults(tmp_path):
    """[bias_match] 섹션이 없는 toml 도 기본값으로 로드된다."""
    from cloudchaser.bias_match import load_bias_match_cfg

    p = tmp_path / "empty.toml"
    p.write_text("[ramp]\nstep_v = 0.2\n", encoding="utf-8")
    cfg = load_bias_match_cfg(p)
    assert cfg.targets_ma == {}
    assert cfg.tol_ma == 0.5
    assert cfg.dist_ratio == [50, 13, 13]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cloudchaser.bias_match'`

- [ ] **Step 3: Add the config section**

Append to `config/bench.toml` (after the `[sa]` / before `[vna]`, or at the end — position does not matter for TOML, but put it after the PSU rails so it reads next to the rail names it references):

```toml
# ---------------------------------------------------------------------
# bias_match — Sivers 레퍼런스 IC 전류 매칭 타깃.
# 출처: reference/Stampede_T582616915_25_Aug_26_09_30_19.csv
#       (VDD_FE1 = 4 V, beam0/pol0/ch0 단일 채널)
# 설계: docs/superpowers/specs/2026-09-01-bias-current-matching-design.md
# ---------------------------------------------------------------------
[bias_match]
targets_ma  = { FE1_4V0 = 27.8, FE2_1V8 = 18.35, FE3_1V8 = 10.37, IO_1V3 = 64.4 }
report_only = ["DIG_1V8", "CORE_1V0"]   # 타깃이 아니라 기록만 하는 레일
tol_ma      = 0.5        # 레일별 수렴 허용오차 [mA]
avg_n       = 3          # 측정점마다 평균낼 전류 읽기 횟수
settle_s    = 0.3        # 레지스터 기입 후 전류 읽기 전 대기 [s]
max_iter    = 3          # 커플링 수렴용 바깥 루프 반복 횟수
dist_ratio  = [50, 13, 13]   # DIST St1 : St2_0 : St2_1 (v4 Casper). 배율 k 로 스케일.
```

Then fix the misleading comment on the `IO_1V3` rail (psu1 ch3). Replace its
`detect = true` comment line with:

```toml
detect = true     # SPI/detect rail (1.3V on both TX & RX) -> powered first for chip auto-detect
# NOTE: 실크/이름과 달리 이 레일은 DIST(스플리터) 전원이다. Sivers 레퍼런스 CSV 의
# IDC_Dist 에 대응한다: reset 0 mA -> 동작 64.4 mA (단일 채널). 순수 IO 레일이 아니다.
```

- [ ] **Step 4: Write the module skeleton and loader**

Create `src/cloudchaser/bias_match.py`:

```python
"""Sivers 레퍼런스 IC 와 레일 전류를 맞추는 bias 코드 매칭 도구.

Sivers 는 bias 코드가 IC 마다 다르지만 '전류 소비 매트릭스'는 공통이라고 했다
(2026-08-25 메일). 그래서 우리 EVB 의 6개 bias 코드를 그들의 레퍼런스 전류에
맞춘 뒤에야 게인/EVM 비교가 apples-to-apples 가 된다.

설계: docs/superpowers/specs/2026-09-01-bias-current-matching-design.md

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .setup_tx import DEFAULT_CONFIG

_DEFAULT_DIST_RATIO = [50, 13, 13]


@dataclass
class BiasMatchCfg:
    """[bias_match] 섹션 -- 매칭 타깃과 탐색 파라미터."""

    targets_ma: dict[str, float] = field(default_factory=dict)
    report_only: list[str] = field(default_factory=list)
    tol_ma: float = 0.5
    avg_n: int = 3
    settle_s: float = 0.3
    max_iter: int = 3
    dist_ratio: list[int] = field(default_factory=lambda: list(_DEFAULT_DIST_RATIO))


def load_bias_match_cfg(path: str | Path = DEFAULT_CONFIG) -> BiasMatchCfg:
    """Load the [bias_match] section of a bench TOML file.

    A missing section yields defaults with no targets, so the tool still
    imports and the CLI can report the miswiring instead of crashing.
    """
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    sec = doc.get("bias_match", {})
    return BiasMatchCfg(
        targets_ma={str(k): float(v) for k, v in sec.get("targets_ma", {}).items()},
        report_only=[str(x) for x in sec.get("report_only", [])],
        tol_ma=float(sec.get("tol_ma", 0.5)),
        avg_n=int(sec.get("avg_n", 3)),
        settle_s=float(sec.get("settle_s", 0.3)),
        max_iter=int(sec.get("max_iter", 3)),
        dist_ratio=[int(x) for x in sec.get("dist_ratio", _DEFAULT_DIST_RATIO)],
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: all tests PASS (the `bench.toml` edit must not break existing config tests)

- [ ] **Step 7: Commit**

```bash
git add config/bench.toml src/cloudchaser/bias_match.py tests/test_bias_match.py
git commit -m "feat(bias_match): add [bias_match] config section and loader"
```

---

### Task 2: Promote `setup_single_channel` into `gain_map`

**Files:**
- Modify: `src/cloudchaser/board/gain_map.py` (add function at end)
- Modify: `src/cloudchaser/biasscan_compare.py:52-67` (`_setup_single` becomes a thin delegate)
- Test: `tests/test_biasscan_compare.py` (add one test)

**Interfaces:**
- Consumes: `BiasMatchCfg` from Task 1 (not used here, but the module now exists).
- Produces: `cloudchaser.board.gain_map.setup_single_channel(fh, beam: str, ch: str) -> None`

**Why:** `bias_match` needs the exact measurement state `biasscan_compare._setup_single()` already builds. Duplicating it would let the two drift apart.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_biasscan_compare.py`:

```python
def test_setup_single_channel_is_shared():
    """gain_map.setup_single_channel 이 biasscan_compare._setup_single 과 같은
    레지스터 상태를 만든다(중복 셋업 방지)."""
    from cloudchaser.board.firehawk import FH
    from cloudchaser.board.gain_map import setup_single_channel

    bench_a, chip_a = _bench_chip_brought_up()
    fh_a = getattr(chip_a, "_fh", None) or FH(chip_a, 0)
    setup_single_channel(fh_a, "b0", "h1")
    regs_a = {a: fh_a.rd(a) for a in (0x1008, 0x100C, 0x1010)}

    bench_b, chip_b = _bench_chip_brought_up()
    from cloudchaser.biasscan_compare import _setup_single
    fh_b = getattr(chip_b, "_fh", None) or FH(chip_b, 0)
    _setup_single(fh_b, "b0", "h1")
    regs_b = {a: fh_b.rd(a) for a in (0x1008, 0x100C, 0x1010)}

    assert regs_a == regs_b
    bench_a.close_all()
    bench_b.close_all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_biasscan_compare.py::test_setup_single_channel_is_shared -v`
Expected: FAIL with `ImportError: cannot import name 'setup_single_channel'`

- [ ] **Step 3: Add the function to `gain_map.py`**

Append to `src/cloudchaser/board/gain_map.py`:

```python
def setup_single_channel(fh, beam, ch):
    """Bring exactly one channel into the measurable state; disable the rest.

    Vendor high-level write APIs (path / fields writes / beam-table objects) are
    NOT used: they are read-modify-write against a Python shadow cache and can
    revert the raw 0x1008/0x100C/0x1010 writes made by bring-up.
    """
    disable_all(fh)
    # centerbias_en / centermirror_en (0x1008 bits 0/1) ON.
    fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    # TX/RX 라우팅 극성은 칩 identity 레지스터로 런타임 판별한다.
    route_channels(fh, [ch], beam, chip_kind(fh))
    fh.load_beam_table(0, [[0] * 8])
    fh.beam_up()
    set_gain(fh, "common", 0, beam=beam)
```

- [ ] **Step 4: Make `biasscan_compare._setup_single` delegate**

In `src/cloudchaser/biasscan_compare.py`, replace the body of `_setup_single`
with a delegate and update the import line:

```python
from .board.gain_map import chip_kind, disable_all, route_channels, set_gain, setup_single_channel
```

```python
def _setup_single(fh: FH, beam: str, ch: str) -> None:
    """채널 ch 하나만 측정 가능 상태로. gain_map 의 공용 구현으로 위임한다
    (bias_match 와 같은 셋업을 쓰기 위해 Task 2 에서 승격)."""
    setup_single_channel(fh, beam, ch)
```

Note: `disable_all`, `route_channels`, `chip_kind`, `set_gain` may now be unused
in `biasscan_compare`. Remove any name from the import that `ruff`/`pyflakes`
flags as unused; keep only what the file still references.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_biasscan_compare.py -v`
Expected: PASS (all existing tests plus the new one)

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/cloudchaser/board/gain_map.py src/cloudchaser/biasscan_compare.py tests/test_biasscan_compare.py
git commit -m "refactor(board): promote single-channel setup into gain_map"
```

---

### Task 3: Knob table and rail-reading primitives

**Files:**
- Modify: `src/cloudchaser/bias_match.py`
- Test: `tests/test_bias_match.py`

**Interfaces:**
- Consumes: `BiasMatchCfg`, `load_bias_match_cfg` (Task 1); `gain_map.setup_single_channel` (Task 2).
- Produces:
  - `Knob` frozen dataclass: `name: str`, `kind: str` (`"fe"`/`"dist"`), `col: int`, `rail: str`
  - `FE_KNOBS: list[Knob]`, `DIST_KNOBS: list[Knob]`, `ALL_KNOBS: list[Knob]`
  - `DIST_RAIL: str` = `"IO_1V3"`
  - `beam_index(beam: str) -> int`
  - `read_knob(fh, knob, *, row: int, beam_idx: int) -> int`
  - `write_knob(fh, knob, value: int, *, row: int, beam_idx: int) -> None`
  - `rail_limits_ma(bench) -> dict[str, float]`
  - `guard_rails(bench, rails_ma: dict[str, float], *, frac: float = 0.95) -> None` — raises `RuntimeError` naming the rail that is at/over its `i_limit`
  - `read_rails_ma(bench, *, avg_n: int, settle_s: float, guard: bool = True) -> dict[str, float]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bias_match.py`:

```python
def _bench_chip_brought_up(channels=("h0",)):
    """bring_up_tx 까지 마친 fake bench/chip."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    bench.board.active_channels = list(channels)
    bench.board.beam = "b0"
    chip = make_chip(bench.board, fake=True)
    bring_up_tx(chip, bench.board, require_version=False, log=lambda *a, **k: None)
    return bench, chip


def _fh_of(chip):
    from cloudchaser.board.firehawk import FH
    return getattr(chip, "_fh", None) or FH(chip, 0)


def test_knob_roundtrip():
    from cloudchaser.bias_match import ALL_KNOBS, beam_index, read_knob, write_knob

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")     # h0 -> FE bias row 0
    for i, kn in enumerate(ALL_KNOBS):
        write_knob(fh, kn, 7 + i, row=row, beam_idx=bidx)
    for i, kn in enumerate(ALL_KNOBS):
        assert read_knob(fh, kn, row=row, beam_idx=bidx) == 7 + i
    bench.close_all()


def test_write_knob_rejects_out_of_range():
    import pytest

    from cloudchaser.bias_match import ALL_KNOBS, beam_index, write_knob

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    with pytest.raises(ValueError):
        write_knob(fh, ALL_KNOBS[0], 64, row=0, beam_idx=beam_index("b0"))
    bench.close_all()


def test_read_rails_ma_returns_all_rails():
    from cloudchaser.bias_match import read_rails_ma

    bench, _chip = _bench_chip_brought_up()
    rails = read_rails_ma(bench, avg_n=2, settle_s=0.0)
    for name in ("FE1_4V0", "FE2_1V8", "FE3_1V8", "IO_1V3", "DIG_1V8", "CORE_1V0"):
        assert name in rails
        assert isinstance(rails[name], float)
    bench.close_all()


def test_guard_rails_raises_at_current_limit():
    """i_limit 근처 전류는 이름을 밝히며 중단시킨다(보드 보호)."""
    import pytest

    from cloudchaser.bias_match import guard_rails, rail_limits_ma

    bench, _chip = _bench_chip_brought_up()
    limits = rail_limits_ma(bench)
    assert limits["FE1_4V0"] == 300.0        # bench.toml: 0.3 A
    guard_rails(bench, {"FE1_4V0": 27.8})    # 정상 -> 조용히 통과
    with pytest.raises(RuntimeError, match="FE1_4V0"):
        guard_rails(bench, {"FE1_4V0": 299.0})
    bench.close_all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: FAIL with `ImportError: cannot import name 'ALL_KNOBS'`

- [ ] **Step 3: Implement the primitives**

Add to `src/cloudchaser/bias_match.py` (imports first, then the code):

```python
import time
from dataclasses import dataclass, field
```

```python
# ---------------------------------------------------------------------
# 손잡이(knob) 표 -- Sivers 가 지목한 6개 bias 코드.
#   FE   bias 8x5, 열 = [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS]
#   DIST bias 3x6, 열 = [PTAT1 PTAT2_0 PTAT2_1 cbias1 cbias2_0 cbias2_1]
# rail = 그 손잡이가 주로 움직이는 PSU 레일(bench.toml 이름).
# ---------------------------------------------------------------------
DIST_RAIL = "IO_1V3"


@dataclass(frozen=True)
class Knob:
    """하나의 6-bit bias 코드와 그것이 주로 구동하는 레일."""

    name: str
    kind: str        # "fe" | "dist"
    col: int         # FE/DIST bias 행 안의 열 인덱스
    rail: str


FE_KNOBS = [
    Knob("ptat_st1", "fe", 0, "FE1_4V0"),    # PA
    Knob("ptat_st2", "fe", 1, "FE2_1V8"),    # Driver
    Knob("ptat_st3", "fe", 2, "FE3_1V8"),    # Combiner
]
DIST_KNOBS = [
    Knob("dist_st1", "dist", 0, DIST_RAIL),
    Knob("dist_st2_0", "dist", 1, DIST_RAIL),
    Knob("dist_st2_1", "dist", 2, DIST_RAIL),
]
ALL_KNOBS = FE_KNOBS + DIST_KNOBS

CODE_MIN, CODE_MAX = 0, 63


def beam_index(beam: str) -> int:
    """'b0'/'b1'/'b2' -> 0/1/2."""
    b = str(beam).strip().lower()
    if len(b) != 2 or b[0] != "b" or not b[1].isdigit() or not 0 <= int(b[1]) <= 2:
        raise ValueError(f"bad beam {beam!r}: expected b0, b1 or b2")
    return int(b[1])


def read_knob(fh, knob: Knob, *, row: int, beam_idx: int) -> int:
    """Read one bias code back from the chip."""
    if knob.kind == "fe":
        return int(fh.get_fe_bias()[row][knob.col])
    dist, _ctat = fh.get_dist_bias()
    return int(dist[beam_idx][knob.col])


def write_knob(fh, knob: Knob, value: int, *, row: int, beam_idx: int) -> None:
    """Write one bias code, leaving every other field untouched."""
    v = int(value)
    if not CODE_MIN <= v <= CODE_MAX:
        raise ValueError(f"{knob.name} code {v} out of range "
                         f"{CODE_MIN}..{CODE_MAX}")
    if knob.kind == "fe":
        bias = fh.get_fe_bias()
        bias[row][knob.col] = v
        fh.set_fe_bias(bias)
    else:
        dist, ctat = fh.get_dist_bias()
        dist[beam_idx][knob.col] = v
        fh.set_dist_bias(dist, ctat)


def rail_limits_ma(bench) -> dict[str, float]:
    """Rail name -> its configured current limit in mA (bench.toml i_limit)."""
    return {r.name: float(r.i_limit) * 1000.0
            for psu in bench.psus for r in psu.rails.values()}


def guard_rails(bench, rails_ma: dict[str, float], *, frac: float = 0.95) -> None:
    """Abort if any rail sits at its current limit (the PSU has gone into CC).

    A rail in constant-current mode is no longer at its programmed voltage, so
    every reading after that point is meaningless -- and it usually means the
    board is drawing more than it should.
    """
    limits = rail_limits_ma(bench)
    for name, cur in rails_ma.items():
        lim = limits.get(name)
        if lim is not None and cur >= lim * frac:
            raise RuntimeError(
                f"rail {name} at {cur:.1f} mA is within {100 * (1 - frac):.0f}% "
                f"of its {lim:.0f} mA limit (PSU likely in CC) -- aborting")


def read_rails_ma(bench, *, avg_n: int, settle_s: float,
                  guard: bool = True) -> dict[str, float]:
    """Settle, then return every PSU rail current in mA, averaged avg_n times."""
    if settle_s > 0:
        time.sleep(settle_s)
    acc: dict[str, list[float]] = {}
    for _ in range(max(1, int(avg_n))):
        for name, vi in bench.read_all_vi().items():
            acc.setdefault(name, []).append(float(vi["i"]) * 1000.0)
    out = {n: sum(v) / len(v) for n, v in acc.items()}
    if guard:
        guard_rails(bench, out)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/bias_match.py tests/test_bias_match.py
git commit -m "feat(bias_match): knob table and rail-current primitives"
```

---

### Task 4: Synthetic rail model + `measure_jacobian`

**Files:**
- Modify: `src/cloudchaser/bias_match.py`
- Test: `tests/test_bias_match.py`

**Interfaces:**
- Consumes: `Knob`, `ALL_KNOBS`, `read_knob`, `write_knob`, `read_rails_ma`, `beam_index` (Task 3).
- Produces:
  - `measure_jacobian(bench, fh, *, row, beam_idx, cfg, delta=8, log=print) -> tuple[dict[str, float], dict[str, int], list[dict]]`
    returning `(base_rails_ma, base_codes, rows)` where each `rows` entry is
    `{"knob": str, "code0": int, "code1": int, "resp_ma": float, "rising": bool, "d": dict[str, float]}`.
    `d[rail]` is mA per code step; `resp_ma` is the absolute rail change of the
    knob's own rail over the perturbation.
  - `directions_from_jacobian(rows, *, noise_ma=0.2) -> dict[str, bool]` — knob name -> rising, omitting knobs whose `resp_ma` is below the noise floor.
  - `format_jacobian(base_rails, rows) -> str` — console table.

**Note on the test model:** the fake PSU returns a static current, so the tests
install a synthetic model that computes rail currents from the codes read back
out of `fh`. It is deliberately linear, and its coefficients are chosen so the
real targets in `bench.toml` are reachable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bias_match.py`:

```python
def _install_synthetic_rails(bench, fh, row, beam_idx):
    """bench.read_all_vi 를 '레지스터 코드 -> 전류' 합성 모델로 교체한다.

    계수는 bench.toml 타깃이 코드 0..63 안에서 도달 가능하도록 잡았다:
      FE1 27.8 -> code 59 / FE2 18.35 -> 61 / FE3 10.37 -> 51 / Dist 64.4 -> k=1.11
    """
    def read_all_vi():
        fe = fh.get_fe_bias()
        dist, _ctat = fh.get_dist_bias()
        c = [fe[row][0], fe[row][1], fe[row][2],
             dist[beam_idx][0], dist[beam_idx][1], dist[beam_idx][2]]
        return {
            "FE1_4V0":  {"v": 4.0, "i": (4.34 + 0.40 * c[0]) / 1000.0},
            "FE2_1V8":  {"v": 1.8, "i": (0.07 + 0.30 * c[1]) / 1000.0},
            "FE3_1V8":  {"v": 1.8, "i": (0.07 + 0.20 * c[2]) / 1000.0},
            "IO_1V3":   {"v": 1.3, "i": (0.9 * c[3] + 0.5 * c[4] + 0.5 * c[5]) / 1000.0},
            "DIG_1V8":  {"v": 1.8, "i": (0.9 + 0.02 * sum(c)) / 1000.0},
            "CORE_1V0": {"v": 1.0, "i": 3.2 / 1000.0},
        }
    bench.read_all_vi = read_all_vi
    return read_all_vi


def test_jacobian_is_diagonally_dominant():
    from cloudchaser.bias_match import (
        ALL_KNOBS, beam_index, directions_from_jacobian, load_bias_match_cfg,
        measure_jacobian,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    base, codes, rows = measure_jacobian(bench, fh, row=row, beam_idx=bidx,
                                         cfg=cfg, delta=8, log=lambda *a: None)
    assert len(rows) == len(ALL_KNOBS)
    assert set(codes) == {k.name for k in ALL_KNOBS}
    by_name = {r["knob"]: r for r in rows}
    # 각 FE knob 은 자기 레일에서 가장 크게 반응한다.
    for kn in ALL_KNOBS[:3]:
        d = by_name[kn.name]["d"]
        assert abs(d[kn.rail]) == max(abs(x) for x in d.values())
    # 어떤 knob 도 CORE_1V0 을 움직이지 않는다.
    for r in rows:
        assert abs(r["d"]["CORE_1V0"]) < 1e-9
    # 코드는 원래 값으로 복원된다.
    from cloudchaser.bias_match import read_knob
    for kn in ALL_KNOBS:
        assert read_knob(fh, kn, row=row, beam_idx=bidx) == codes[kn.name]

    dirs = directions_from_jacobian(rows)
    assert all(dirs[k.name] is True for k in ALL_KNOBS)
    bench.close_all()


def test_directions_drop_dead_knobs():
    from cloudchaser.bias_match import directions_from_jacobian

    rows = [
        {"knob": "ptat_st1", "resp_ma": 3.2, "rising": True, "d": {}},
        {"knob": "ptat_st2", "resp_ma": 0.05, "rising": False, "d": {}},
    ]
    dirs = directions_from_jacobian(rows, noise_ma=0.2)
    assert dirs == {"ptat_st1": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: FAIL with `ImportError: cannot import name 'measure_jacobian'`

- [ ] **Step 3: Implement**

Add to `src/cloudchaser/bias_match.py`:

```python
NOISE_MA = 0.2      # 이보다 작은 반응은 '무응답'으로 본다.


def measure_jacobian(bench, fh, *, row: int, beam_idx: int, cfg: BiasMatchCfg,
                     delta: int = 8, log=print):
    """Measure dI/dcode for every knob against every rail.

    Perturbs one knob at a time by `delta` codes (flipping the sign when the
    code is near the top of its range), records all rail currents, then puts
    the code back. Costs 1 + len(ALL_KNOBS) measurement points.

    Returns (base_rails_ma, base_codes, rows).
    """
    base_codes = {k.name: read_knob(fh, k, row=row, beam_idx=beam_idx)
                  for k in ALL_KNOBS}
    base = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
    log(f"[bias-match] jacobian baseline: "
        + "  ".join(f"{n}={v:.2f}mA" for n, v in sorted(base.items())))
    rows: list[dict] = []
    for kn in ALL_KNOBS:
        c0 = base_codes[kn.name]
        c1 = c0 + delta if c0 + delta <= CODE_MAX else c0 - delta
        c1 = max(CODE_MIN, min(CODE_MAX, c1))
        step = c1 - c0
        if step == 0:
            log(f"[bias-match] {kn.name}: cannot perturb (code {c0}), skipped")
            rows.append({"knob": kn.name, "code0": c0, "code1": c0,
                         "resp_ma": 0.0, "rising": True,
                         "d": {r: 0.0 for r in base}})
            continue
        write_knob(fh, kn, c1, row=row, beam_idx=beam_idx)
        cur = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
        write_knob(fh, kn, c0, row=row, beam_idx=beam_idx)
        d = {r: (cur[r] - base[r]) / step for r in base}
        resp = abs(cur[kn.rail] - base[kn.rail])
        rows.append({"knob": kn.name, "code0": c0, "code1": c1,
                     "resp_ma": resp, "rising": d[kn.rail] >= 0, "d": d})
        log(f"[bias-match] {kn.name}: {c0}->{c1}  "
            f"{kn.rail} {base[kn.rail]:.2f}->{cur[kn.rail]:.2f} mA  "
            f"({d[kn.rail]:+.3f} mA/code)")
    return base, base_codes, rows


def directions_from_jacobian(rows, *, noise_ma: float = NOISE_MA) -> dict[str, bool]:
    """Knob name -> True if its rail current rises with the code.

    Knobs whose response is below the noise floor are omitted: the caller must
    treat a missing key as NO RESPONSE and skip that knob.
    """
    return {r["knob"]: bool(r["rising"])
            for r in rows if float(r["resp_ma"]) > noise_ma}


def format_jacobian(base_rails: dict[str, float], rows) -> str:
    """Render the dI/dcode matrix as a console table (mA per code step)."""
    rail_names = sorted(base_rails)
    out = ["", "=== Jacobian: dI/dcode [mA per code step] ===",
           f"{'knob':12}" + "".join(f"{r:>11}" for r in rail_names) + "   response"]
    for r in rows:
        line = f"{r['knob']:12}" + "".join(f"{r['d'][n]:>+11.3f}" for n in rail_names)
        line += f"   {r['resp_ma']:6.2f} mA"
        if r["resp_ma"] <= NOISE_MA:
            line += "  ** NO RESPONSE **"
        out.append(line)
    return "\n".join(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/bias_match.py tests/test_bias_match.py
git commit -m "feat(bias_match): measure the 6x6 dI/dcode Jacobian"
```

---

### Task 5: Bisection solvers and the outer solve loop

**Files:**
- Modify: `src/cloudchaser/bias_match.py`
- Test: `tests/test_bias_match.py`

**Interfaces:**
- Consumes: everything from Tasks 1, 3, 4.
- Produces:
  - `bisect_knob(bench, fh, knob, target_ma, *, row, beam_idx, cfg, rising, log=print) -> tuple[int, float, float]` — `(code, current_ma, err_ma)`
  - `bisect_dist_scale(bench, fh, target_ma, *, beam_idx, cfg, rising, iters=8, log=print) -> tuple[tuple[int, int, int], float, float, float]` — `(codes, k, current_ma, err_ma)`
  - `solve_bias(bench, fh, *, row, beam_idx, cfg, directions, log=print) -> dict` with keys `codes: dict[str, int]`, `rails_ma: dict[str, float]`, `errors_ma: dict[str, float]`, `iterations: int`, `converged: bool`, `skipped: list[str]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bias_match.py`:

```python
def test_solve_converges_on_synthetic_model():
    from cloudchaser.bias_match import (
        beam_index, directions_from_jacobian, load_bias_match_cfg,
        measure_jacobian, solve_bias,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    _base, _codes, jrows = measure_jacobian(bench, fh, row=row, beam_idx=bidx,
                                            cfg=cfg, delta=8, log=lambda *a: None)
    dirs = directions_from_jacobian(jrows)
    res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                     directions=dirs, log=lambda *a: None)

    assert res["converged"] is True
    assert res["skipped"] == []
    for rail, target in cfg.targets_ma.items():
        assert abs(res["rails_ma"][rail] - target) <= cfg.tol_ma, rail
        assert abs(res["errors_ma"][rail]) <= cfg.tol_ma
    assert res["codes"]["ptat_st1"] == 59
    assert res["codes"]["ptat_st2"] == 61
    assert res["codes"]["ptat_st3"] in (51, 52)
    bench.close_all()


def test_dist_solve_preserves_ratio():
    from cloudchaser.bias_match import (
        beam_index, bisect_dist_scale, load_bias_match_cfg,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    codes, k, cur, err = bisect_dist_scale(bench, fh, cfg.targets_ma["IO_1V3"],
                                           beam_idx=bidx, cfg=cfg, rising=True,
                                           log=lambda *a: None)
    expected = tuple(max(0, min(63, int(round(k * r)))) for r in cfg.dist_ratio)
    assert codes == expected
    assert abs(err) <= cfg.tol_ma
    assert abs(cur - cfg.targets_ma["IO_1V3"]) <= cfg.tol_ma
    bench.close_all()


def test_unreachable_target_reports_residual():
    """코드 63 으로도 못 미치는 타깃은 예외가 아니라 잔차 보고로 끝난다."""
    from cloudchaser.bias_match import (
        beam_index, bisect_knob, FE_KNOBS, load_bias_match_cfg,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    code, cur, err = bisect_knob(bench, fh, FE_KNOBS[0], 60.0, row=row,
                                 beam_idx=bidx, cfg=cfg, rising=True,
                                 log=lambda *a: None)
    assert code == 63
    assert err < -cfg.tol_ma      # 여전히 부족하다고 보고
    assert abs(cur - (4.34 + 0.40 * 63)) < 1e-6
    bench.close_all()


def test_solve_skips_dead_knobs():
    from cloudchaser.bias_match import (
        beam_index, load_bias_match_cfg, solve_bias,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    # ptat_st2 만 무응답으로 취급 -> 건너뛰고 나머지는 계속 푼다.
    dirs = {"ptat_st1": True, "ptat_st3": True,
            "dist_st1": True, "dist_st2_0": True, "dist_st2_1": True}
    res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                     directions=dirs, log=lambda *a: None)
    assert res["skipped"] == ["ptat_st2"]
    assert res["converged"] is False          # FE2 레일은 타깃에 못 맞음
    assert abs(res["errors_ma"]["FE1_4V0"]) <= cfg.tol_ma
    bench.close_all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: FAIL with `ImportError: cannot import name 'solve_bias'`

- [ ] **Step 3: Implement the solvers**

Add to `src/cloudchaser/bias_match.py`:

```python
def bisect_knob(bench, fh, knob: Knob, target_ma: float, *, row: int,
                beam_idx: int, cfg: BiasMatchCfg, rising: bool, log=print):
    """Binary-search one 6-bit code so its rail hits target_ma.

    `rising` comes from the Jacobian: True when rail current grows with the
    code. Returns (code, current_ma, err_ma) for the best point seen, and
    leaves that code written. An unreachable target is not an error -- the
    residual is returned so the caller can report it.
    """
    lo, hi = CODE_MIN, CODE_MAX
    best: tuple[int, float, float] | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        write_knob(fh, knob, mid, row=row, beam_idx=beam_idx)
        cur = read_rails_ma(bench, avg_n=cfg.avg_n,
                            settle_s=cfg.settle_s)[knob.rail]
        err = cur - target_ma
        if best is None or abs(err) < abs(best[2]):
            best = (mid, cur, err)
        if abs(err) <= cfg.tol_ma:
            break
        if (err < 0) == rising:
            lo = mid + 1
        else:
            hi = mid - 1
    assert best is not None      # 루프는 최소 1회 돈다 (lo <= hi at entry)
    write_knob(fh, knob, best[0], row=row, beam_idx=beam_idx)
    flag = "" if abs(best[2]) <= cfg.tol_ma else "  ** NOT REACHED **"
    log(f"[bias-match] {knob.name} -> code {best[0]}: "
        f"{knob.rail} {best[1]:.2f} mA (target {target_ma:.2f}, "
        f"err {best[2]:+.2f}){flag}")
    return best


def bisect_dist_scale(bench, fh, target_ma: float, *, beam_idx: int,
                      cfg: BiasMatchCfg, rising: bool, iters: int = 8,
                      log=print):
    """Scale the whole DIST ratio by one factor k until DIST_RAIL hits target.

    The DIST block has three knobs but only one observable, so the ratio from
    `cfg.dist_ratio` is held fixed and only its scale is searched. Codes are
    round(k * ratio) clamped to 0..63; repeated code vectors reuse the cached
    reading instead of re-measuring.

    Returns (codes, k, current_ma, err_ma) for the best point, left written.
    """
    ratio = list(cfg.dist_ratio)
    if not ratio or max(ratio) <= 0:
        raise ValueError("bias_match.dist_ratio must contain a positive value")

    def codes_for(k: float) -> tuple[int, ...]:
        return tuple(max(CODE_MIN, min(CODE_MAX, int(round(k * r)))) for r in ratio)

    def apply(codes) -> None:
        for kn, c in zip(DIST_KNOBS, codes):
            write_knob(fh, kn, c, row=0, beam_idx=beam_idx)

    k_lo, k_hi = 0.0, float(CODE_MAX) / max(ratio)
    seen: dict[tuple[int, ...], float] = {}
    best: tuple[tuple[int, ...], float, float, float] | None = None
    for _ in range(iters):
        k = (k_lo + k_hi) / 2.0
        codes = codes_for(k)
        if codes in seen:
            cur = seen[codes]
        else:
            apply(codes)
            cur = read_rails_ma(bench, avg_n=cfg.avg_n,
                                settle_s=cfg.settle_s)[DIST_RAIL]
            seen[codes] = cur
        err = cur - target_ma
        if best is None or abs(err) < abs(best[3]):
            best = (codes, k, cur, err)
        if abs(err) <= cfg.tol_ma:
            break
        if (err < 0) == rising:
            k_lo = k
        else:
            k_hi = k
    assert best is not None
    apply(best[0])
    flag = "" if abs(best[3]) <= cfg.tol_ma else "  ** NOT REACHED **"
    log(f"[bias-match] dist {list(best[0])} (k={best[1]:.3f}): "
        f"{DIST_RAIL} {best[2]:.2f} mA (target {target_ma:.2f}, "
        f"err {best[3]:+.2f}){flag}")
    return best


def solve_bias(bench, fh, *, row: int, beam_idx: int, cfg: BiasMatchCfg,
               directions: dict[str, bool], log=print) -> dict:
    """Outer loop: solve each rail 1-D, repeat until cross-coupling settles.

    `directions` comes from directions_from_jacobian(); a knob missing from it
    did not respond and is skipped (reported in the result, not raised).
    Non-convergence after cfg.max_iter is reported, not raised.
    """
    skipped = [k.name for k in ALL_KNOBS if k.name not in directions]
    dist_live = [k for k in DIST_KNOBS if k.name in directions]
    iterations = 0
    # max_iter 가 0 이어도 rails/errors 가 정의돼 있도록 루프 전에 한 번 읽는다.
    rails = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
    errors = {r: rails[r] - t for r, t in cfg.targets_ma.items()}
    for it in range(1, cfg.max_iter + 1):
        iterations = it
        log(f"[bias-match] --- solve iteration {it}/{cfg.max_iter} ---")
        for kn in FE_KNOBS:
            if kn.name in skipped:
                log(f"[bias-match] {kn.name}: NO RESPONSE, skipped")
                continue
            target = cfg.targets_ma.get(kn.rail)
            if target is None:
                continue
            bisect_knob(bench, fh, kn, target, row=row, beam_idx=beam_idx,
                        cfg=cfg, rising=directions[kn.name], log=log)
        dist_target = cfg.targets_ma.get(DIST_RAIL)
        if dist_target is not None and dist_live:
            bisect_dist_scale(bench, fh, dist_target, beam_idx=beam_idx,
                              cfg=cfg, rising=directions[dist_live[0].name],
                              log=log)
        elif dist_target is not None:
            log(f"[bias-match] all DIST knobs are dead, {DIST_RAIL} left as-is")
        rails = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
        errors = {r: rails[r] - t for r, t in cfg.targets_ma.items()}
        if all(abs(e) <= cfg.tol_ma for e in errors.values()):
            log(f"[bias-match] converged after {it} iteration(s)")
            break
    else:
        log(f"[bias-match] no convergence after {cfg.max_iter} iterations "
            "-- reporting best effort")
    codes = {k.name: read_knob(fh, k, row=row, beam_idx=beam_idx)
             for k in ALL_KNOBS}
    return {"codes": codes, "rails_ma": rails, "errors_ma": errors,
            "iterations": iterations,
            "converged": all(abs(e) <= cfg.tol_ma for e in errors.values()),
            "skipped": skipped}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/bias_match.py tests/test_bias_match.py
git commit -m "feat(bias_match): block-diagonal bisection solver"
```

---

### Task 6: CLI with `jacobian` and `solve`

**Files:**
- Modify: `src/cloudchaser/bias_match.py`
- Test: `tests/test_bias_match.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces:
  - `main(argv: list[str] | None = None) -> int` with subcommands `jacobian` and `solve`
  - `open_bench(args) -> tuple[bench, chip, fh, row, beam_idx, beam, ch]` — shared session setup
  - `write_csv(path: Path, columns: list[str], rows: list[list], meta: dict) -> None`
  - `meta_dict(args, bench, beam, ch) -> dict`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bias_match.py`:

```python
def test_main_jacobian_fake_runs(tmp_path):
    from cloudchaser.bias_match import main

    out = tmp_path / "jac.csv"
    rc = main(["jacobian", "--fake", "--config", str(CONFIG),
               "--csv", str(out), "--ambient-c", "25.0"])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "ptat_st1" in text and "dist_st2_1" in text
    assert "ambient_C" in text


def test_main_solve_fake_runs(tmp_path):
    """fake 는 전류가 정적이라 수렴하지 않는다 -- 예외 없이 max_iter 로 끝나야 한다."""
    from cloudchaser.bias_match import main

    out = tmp_path / "solve.csv"
    rc = main(["solve", "--fake", "--config", str(CONFIG),
               "--csv", str(out), "--ambient-c", "25.0"])
    assert rc == 0
    assert out.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bias_match.py -k main -v`
Expected: FAIL with `ImportError: cannot import name 'main'`

- [ ] **Step 3: Implement the CLI**

Add the remaining imports at the top of `src/cloudchaser/bias_match.py`:

```python
import argparse
import sys
from datetime import datetime

from .bench import Bench
from .board.bringup import apply_split_mode, bring_up_tx, make_chip
from .board.firehawk import FH, fe_row
from .board.gain_map import setup_single_channel
from .manual import _parse_ch
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout
```

Then append:

```python
def _engine(bench, chip) -> FH:
    """raw 레지스터 엔진. bring_up_tx 가 chip._fh 를 남기지만 bare FH 로 폴백한다."""
    return getattr(chip, "_fh", None) or FH(chip, getattr(bench.board, "chip_id", 0))


def open_bench(args):
    """Power up, bring up TX, and put exactly one channel in the measured state.

    Returns (bench, chip, fh, row, beam_idx, beam, ch).
    """
    bench = Bench.from_toml(args.config, fake=args.fake)
    beam = args.beam or bench.board.beam
    ch = args.ch.strip().lower()
    bench.connect_all()
    if not args.no_power:
        bench.power_up()
    else:
        print("[bias-match] skipping power-up (--no-power)")
    chip = make_chip(bench.board, fake=args.fake)
    bench.board.active_channels = [ch]
    bench.board.beam = beam
    bring_up_tx(chip, bench.board, require_version=not args.fake)
    fh = _engine(bench, chip)
    setup_single_channel(fh, beam, ch)
    # route_channels() 는 split 설정을 지우므로 다시 적용한다.
    apply_split_mode(fh, bench.board, kind="tx")
    pol, idx = _parse_ch(ch)
    return bench, chip, fh, fe_row(idx, pol), beam_index(beam), beam, ch


def meta_dict(args, bench, beam, ch) -> dict:
    """CSV 헤더에 남길 측정 맥락. 온도는 사용자가 준 값을 그대로 기록한다.

    레일 전압까지 남기는 이유: Sivers 와의 전류 비교는 같은 공급전압에서만
    성립한다(특히 DIST 레일 1.3V -- 저쪽 전압은 아직 미확인).
    """
    meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "beam": beam,
        "channel": ch,
        "ambient_C": args.ambient_c,
        "split_mode": bool(getattr(bench.board, "split_mode", False)),
        "fake": bool(args.fake),
        "reference_csv": "Stampede_T582616915_25_Aug_26_09_30_19.csv",
    }
    for psu in bench.psus:
        for r in psu.rails.values():
            meta[f"V_{r.name}"] = r.v_target
    return meta


def write_csv(path: Path, columns: list[str], rows: list[list], meta: dict) -> None:
    """Write a CSV with a '# key=value' metadata preamble."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {k}={v}" for k, v in meta.items()]
    lines.append(",".join(columns))
    for r in rows:
        lines.append(",".join("" if c is None else str(c) for c in r))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[bias-match] CSV written: {path}")


def _default_csv(name: str) -> Path:
    return Path("out") / f"bias_{name}_{datetime.now():%y%m%d_%H%M%S}.csv"


def cmd_jacobian(args) -> int:
    cfg = load_bias_match_cfg(args.config)
    bench, _chip, fh, row, bidx, beam, ch = open_bench(args)
    try:
        base, codes, jrows = measure_jacobian(bench, fh, row=row, beam_idx=bidx,
                                              cfg=cfg, delta=args.delta)
        print(format_jacobian(base, jrows))
        rail_names = sorted(base)
        columns = ["knob", "code0", "code1", "resp_mA", "rising"] + \
                  [f"d_{r}_mA_per_code" for r in rail_names]
        rows = [[r["knob"], r["code0"], r["code1"], round(r["resp_ma"], 3),
                 int(r["rising"])] + [round(r["d"][n], 4) for n in rail_names]
                for r in jrows]
        meta = meta_dict(args, bench, beam, ch)
        meta.update({f"base_{n}_mA": round(base[n], 3) for n in rail_names})
        meta.update({f"code_{k}": v for k, v in codes.items()})
        write_csv(args.csv or _default_csv("jacobian"), columns, rows, meta)
    finally:
        bench.close_all()
        print("[bias-match] sockets closed. (power left as-is)")
    return 0


def cmd_solve(args) -> int:
    cfg = load_bias_match_cfg(args.config)
    bench, _chip, fh, row, bidx, beam, ch = open_bench(args)
    try:
        base, _codes, jrows = measure_jacobian(bench, fh, row=row,
                                               beam_idx=bidx, cfg=cfg,
                                               delta=args.delta)
        print(format_jacobian(base, jrows))
        dirs = directions_from_jacobian(jrows, noise_ma=args.noise_ma)
        res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                         directions=dirs)
        print("\n=== Bias match result ===")
        print(f"converged: {res['converged']}  iterations: {res['iterations']}")
        if res["skipped"]:
            print(f"skipped (no response): {', '.join(res['skipped'])}")
        for k in ALL_KNOBS:
            print(f"  {k.name:12} = {res['codes'][k.name]}")
        for rail in sorted(set(cfg.targets_ma) | set(cfg.report_only)):
            cur = res["rails_ma"].get(rail)
            tgt = cfg.targets_ma.get(rail)
            if cur is None:
                continue
            if tgt is None:
                print(f"  {rail:10} {cur:7.2f} mA   (report only)")
            else:
                print(f"  {rail:10} {cur:7.2f} mA   target {tgt:6.2f}   "
                      f"err {cur - tgt:+.2f}")
        print("\n# paste into config/bench.toml or bias_v4.py:")
        print(f"#   FE   ptat_st1/2/3 = "
              f"{res['codes']['ptat_st1']}, {res['codes']['ptat_st2']}, "
              f"{res['codes']['ptat_st3']}")
        print(f"#   DIST st1/st2_0/st2_1 = "
              f"{res['codes']['dist_st1']}, {res['codes']['dist_st2_0']}, "
              f"{res['codes']['dist_st2_1']}")
        columns = ["knob", "code"] + \
                  [f"{r}_mA" for r in sorted(res["rails_ma"])] + \
                  [f"{r}_err_mA" for r in sorted(res["errors_ma"])]
        rail_vals = [round(res["rails_ma"][r], 3) for r in sorted(res["rails_ma"])]
        err_vals = [round(res["errors_ma"][r], 3) for r in sorted(res["errors_ma"])]
        rows = [[k.name, res["codes"][k.name]] + rail_vals + err_vals
                for k in ALL_KNOBS]
        meta = meta_dict(args, bench, beam, ch)
        meta.update({"converged": res["converged"],
                     "iterations": res["iterations"],
                     "skipped": "|".join(res["skipped"])})
        write_csv(args.csv or _default_csv("match"), columns, rows, meta)
    finally:
        bench.close_all()
        print("[bias-match] sockets closed. (power left as-is)")
    return 0


def _add_common(p) -> None:
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--beam", default=None,
                   help="beam to route to (default: bench.toml beam)")
    p.add_argument("--ch", default="h0", help="channel to measure (default h0)")
    p.add_argument("--delta", type=int, default=8,
                   help="code perturbation for the Jacobian (default 8)")
    p.add_argument("--noise-ma", type=float, default=NOISE_MA,
                   help=f"below this rail change a knob counts as dead "
                        f"(default {NOISE_MA})")
    p.add_argument("--ambient-c", type=float, default=None,
                   help="ambient temperature [C], recorded in the CSV. PTAT "
                        "currents are temperature-proportional, so a comparison "
                        "without it is not meaningful.")
    p.add_argument("--csv", type=Path, default=None, help="CSV output path")
    p.add_argument("--no-power", action="store_true",
                   help="skip PSU ramp-up (already powered)")
    p.add_argument("--fake", action="store_true",
                   help="run without hardware (currents are static -- the solve "
                        "will not converge; structure check only)")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Match EVB bias codes to the Sivers reference IC currents")
    sub = p.add_subparsers(dest="cmd", required=True)
    _add_common(sub.add_parser("jacobian", help="measure the dI/dcode matrix"))
    _add_common(sub.add_parser("solve", help="solve the six codes to the targets"))
    args = p.parse_args(argv)
    if args.ambient_c is None:
        print("[bias-match] WARNING: --ambient-c not given. PTAT currents are "
              "temperature-proportional; record the ambient temperature or the "
              "comparison with Sivers is not meaningful.")
    return {"jacobian": cmd_jacobian, "solve": cmd_solve}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Smoke-test the CLI by hand**

Run: `python -m cloudchaser.bias_match jacobian --fake`
Expected: exit 0, a Jacobian table printed (all zeros, since fake currents are static), a CSV written under `out/`.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/cloudchaser/bias_match.py tests/test_bias_match.py
git commit -m "feat(bias_match): CLI for jacobian and solve"
```

---

### Task 7: `verify` — reproduce the Sivers sweep

**Files:**
- Modify: `src/cloudchaser/bias_match.py`
- Test: `tests/test_bias_match.py`

**Interfaces:**
- Consumes: `open_bench`, `read_rails_ma`, `write_csv`, `meta_dict` (Task 6).
- Produces:
  - `SIVERS_COLUMNS: list[str]` — their column names, in their order
  - `cmd_verify(args) -> int`, registered as the `verify` subcommand
  - `--vdd`, `--freqs`, `--sg-level-dbm`, `--sa-ref-dbm`, `--sa-span-hz`, `--serial` CLI options

**Rail-to-column mapping** (their name -> our `bench.toml` rail):
`IDC_1p0 -> CORE_1V0`, `IDC_1p8 -> DIG_1V8`, `IDC_Dist -> IO_1V3`,
`IDC_FE1 -> FE1_4V0`, `IDC_FE2 -> FE2_1V8`, `IDC_FE3 -> FE3_1V8`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bias_match.py`:

```python
def test_main_verify_fake_runs(tmp_path):
    from cloudchaser.bias_match import SIVERS_COLUMNS, main

    out = tmp_path / "verify.csv"
    rc = main(["verify", "--fake", "--config", str(CONFIG), "--csv", str(out),
               "--ambient-c", "25.0", "--vdd", "4.0,3.6",
               "--freqs", "27.5,28.0"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    header = [ln for ln in text.splitlines() if not ln.startswith("#")][0]
    assert header == ",".join(SIVERS_COLUMNS)
    # 2 VDD x 2 freq = 4 data rows
    data = [ln for ln in text.splitlines()
            if not ln.startswith("#") and not ln.startswith("measurement_name")]
    assert len(data) == 4
    assert all("IDC_Dist" not in ln for ln in data)


def test_sivers_columns_match_reference_file():
    """레퍼런스 CSV 에 실제로 있는 컬럼 이름만 쓴다(오탈자 방지)."""
    from cloudchaser.bias_match import SIVERS_COLUMNS

    ref = (Path(__file__).resolve().parents[1] / "reference"
           / "Stampede_T582616915_25_Aug_26_09_30_19.csv")
    if not ref.exists():
        import pytest
        pytest.skip("reference CSV not present")
    head = ref.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    for col in SIVERS_COLUMNS:
        assert col in head, col
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bias_match.py -k verify -v`
Expected: FAIL with `ImportError: cannot import name 'SIVERS_COLUMNS'`

- [ ] **Step 3: Implement `verify`**

Add to `src/cloudchaser/bias_match.py`:

```python
# Sivers 레퍼런스 CSV 와 같은 이름/순서의 컬럼만 쓴다 -> 두 파일을 그대로 diff 할 수 있다.
SIVERS_COLUMNS = [
    "measurement_name", "dut_name", "serial_no", "beam", "pol", "channel",
    "RF_Freq[GHz]", "RF_level_cal[dBm]", "Gain[dB]", "VDD_FE1[V]",
    "IDC_1p0[mA]", "IDC_1p8[mA]", "IDC_Dist[mA]",
    "IDC_FE1[mA]", "IDC_FE2[mA]", "IDC_FE3[mA]",
]
# Sivers 컬럼 -> 우리 bench.toml 레일 이름.
SIVERS_RAILS = [
    ("IDC_1p0[mA]", "CORE_1V0"),
    ("IDC_1p8[mA]", "DIG_1V8"),
    ("IDC_Dist[mA]", DIST_RAIL),
    ("IDC_FE1[mA]", "FE1_4V0"),
    ("IDC_FE2[mA]", "FE2_1V8"),
    ("IDC_FE3[mA]", "FE3_1V8"),
]
DEFAULT_VDD = [4.0, 3.6, 3.3, 3.0, 2.7, 2.4, 2.2]
DEFAULT_FREQS_GHZ = [27.5, 28.0, 28.5, 29.0, 29.5, 30.0, 30.5, 31.0]


def _floats(text: str) -> list[float]:
    return [float(x) for x in str(text).split(",") if x.strip()]


def cmd_verify(args) -> int:
    """Replay the Sivers measurement (VDD_FE1 x RF frequency) at our codes."""
    cfg = load_bias_match_cfg(args.config)
    vdds = _floats(args.vdd)
    freqs = _floats(args.freqs)
    bench, _chip, _fh, _row, _bidx, beam, ch = open_bench(args)
    pol, idx = _parse_ch(ch)
    nominal = bench.rail_nominal_v("FE1_4V0")
    rows: list[list] = []
    try:
        sg, sa = bench.sg, bench.sa
        sg.modulation_off()
        sa_cfg = getattr(bench, "sa_cfg", {})
        sg.rf_output(True)
        for vdd in vdds:
            bench.set_rail_voltage("FE1_4V0", vdd)
            for f_ghz in freqs:
                f_hz = f_ghz * 1e9
                sg.set_frequency(f_hz)
                bench.apply_path_loss(f_hz)
                sg.set_level(args.sg_level_dbm)
                sa.configure(
                    center_hz=f_hz, span_hz=args.sa_span_hz,
                    rbw_hz=float(sa_cfg.get("rbw_hz", 1.0e6)),
                    ref_level_dbm=args.sa_ref_dbm,
                    input_atten_db=float(sa_cfg.get("input_atten_db", 10.0)),
                    spectrum_mode=bool(sa_cfg.get("spectrum_mode", True)),
                )
                pout = sa.measure_peak_dbm()
                rails = read_rails_ma(bench, avg_n=cfg.avg_n,
                                      settle_s=cfg.settle_s)
                rows.append([
                    "RF_Freq_sweep", "Stampede", args.serial,
                    beam[1], pol, idx,
                    f_ghz, round(pout, 2), round(pout - args.sg_level_dbm, 2),
                    vdd,
                ] + [round(rails.get(r, float("nan")), 2)
                     for _col, r in SIVERS_RAILS])
                print(f"[bias-match] VDD={vdd:.1f} V  {f_ghz:.2f} GHz  "
                      f"Pout={pout:+.2f} dBm  "
                      f"gain={pout - args.sg_level_dbm:+.2f} dB")
    finally:
        try:
            bench.sg.rf_output(False)
            bench.set_rail_voltage("FE1_4V0", nominal)
            print(f"[bias-match] FE1_4V0 restored to {nominal:.2f} V")
        finally:
            if rows:
                write_csv(args.csv or _default_csv("verify"),
                          SIVERS_COLUMNS, rows, meta_dict(args, bench, beam, ch))
            bench.close_all()
            print("[bias-match] sockets closed. (power left as-is)")
    return 0
```

Register the subcommand in `main()` — replace the two `_add_common(...)` lines
and the dispatch dict:

```python
    _add_common(sub.add_parser("jacobian", help="measure the dI/dcode matrix"))
    _add_common(sub.add_parser("solve", help="solve the six codes to the targets"))
    pv = sub.add_parser("verify", help="replay the Sivers VDD x frequency sweep")
    _add_common(pv)
    pv.add_argument("--vdd", default=",".join(str(v) for v in DEFAULT_VDD),
                    help="comma list of VDD_FE1 [V] (default: the Sivers set)")
    pv.add_argument("--freqs", default=",".join(str(f) for f in DEFAULT_FREQS_GHZ),
                    help="comma list of RF frequencies [GHz]")
    pv.add_argument("--sg-level-dbm", type=float, default=-28.0,
                    help="chip-input power [dBm], path-loss compensated "
                         "(Sivers used about -28)")
    pv.add_argument("--sa-ref-dbm", type=float, default=20.0,
                    help="SA reference level [dBm]")
    pv.add_argument("--sa-span-hz", type=float, default=100.0e6,
                    help="SA span [Hz]")
    pv.add_argument("--serial", default="", help="DUT serial recorded in the CSV")
    args = p.parse_args(argv)
```

```python
    return {"jacobian": cmd_jacobian, "solve": cmd_solve,
            "verify": cmd_verify}[args.cmd](args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/bias_match.py tests/test_bias_match.py
git commit -m "feat(bias_match): verify command replaying the Sivers sweep"
```

---

### Task 8: `dist-gain` — the constrained gain surface

**Files:**
- Modify: `src/cloudchaser/bias_match.py`
- Test: `tests/test_bias_match.py`

**Interfaces:**
- Consumes: `open_bench`, `write_knob`, `read_rails_ma`, `write_csv`, `meta_dict`, `DIST_KNOBS`, `DIST_RAIL`.
- Produces:
  - `screen_dist_grid(bench, fh, *, beam_idx, cfg, target_ma, window_ma, step, log=print) -> list[tuple[tuple[int, int, int], float]]` — the code vectors whose DIST current lands inside the window, with their current
  - `cmd_dist_gain(args) -> int`, registered as the `dist-gain` subcommand
  - `--grid-step`, `--window-ma`, `--gain-freq-ghz` CLI options

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bias_match.py`:

```python
def test_screen_dist_grid_keeps_only_in_window():
    from cloudchaser.bias_match import (
        beam_index, load_bias_match_cfg, screen_dist_grid,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    # step=16 그리드(0/16/32/48)에서 합성 모델이 낼 수 있는 값은 64.4 에서 최소
    # 2.0 mA 떨어져 있다 -> window 2.0 은 부동소수 경계라 불안정하다. 4.0 으로 잡는다.
    kept = screen_dist_grid(bench, fh, beam_idx=bidx, cfg=cfg,
                            target_ma=64.4, window_ma=4.0, step=16,
                            log=lambda *a: None)
    assert kept, "expected at least one in-window combination"
    for codes, cur in kept:
        assert abs(cur - 64.4) <= 4.0
        assert all(0 <= c <= 63 for c in codes)
    # 합성 모델은 0.9*c0 + 0.5*c1 + 0.5*c2 이므로 직접 재계산과 일치해야 한다.
    for codes, cur in kept:
        assert abs(cur - (0.9 * codes[0] + 0.5 * codes[1] + 0.5 * codes[2])) < 1e-6
    bench.close_all()


def test_main_dist_gain_fake_runs(tmp_path):
    from cloudchaser.bias_match import main

    out = tmp_path / "distgain.csv"
    rc = main(["dist-gain", "--fake", "--config", str(CONFIG),
               "--csv", str(out), "--ambient-c", "25.0", "--grid-step", "32"])
    assert rc == 0
    assert out.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bias_match.py -k dist_gain -v`
Expected: FAIL with `ImportError: cannot import name 'screen_dist_grid'`

- [ ] **Step 3: Implement**

Add to `src/cloudchaser/bias_match.py` (add `import itertools` to the imports):

```python
def screen_dist_grid(bench, fh, *, beam_idx: int, cfg: BiasMatchCfg,
                     target_ma: float, window_ma: float, step: int,
                     log=print):
    """Sweep the three DIST codes coarsely, keeping only the in-window ones.

    The DIST rail current is one constraint on three knobs, so it collapses the
    cube to a surface. RF is not needed here -- only the DC current.

    Returns [(codes, current_ma), ...] sorted by |current - target|.
    """
    grid = list(range(CODE_MIN, CODE_MAX + 1, max(1, int(step))))
    kept: list[tuple[tuple[int, int, int], float]] = []
    total = len(grid) ** 3
    log(f"[bias-match] screening {total} DIST combinations "
        f"(step {step}) for {DIST_RAIL} = {target_ma:.1f} +/- {window_ma:.1f} mA")
    for c0, c1, c2 in itertools.product(grid, repeat=3):
        codes = (c0, c1, c2)
        for kn, c in zip(DIST_KNOBS, codes):
            write_knob(fh, kn, c, row=0, beam_idx=beam_idx)
        cur = read_rails_ma(bench, avg_n=cfg.avg_n,
                            settle_s=cfg.settle_s)[DIST_RAIL]
        if abs(cur - target_ma) <= window_ma:
            kept.append((codes, cur))
            log(f"[bias-match]   keep {list(codes)}: {cur:.2f} mA")
    kept.sort(key=lambda t: abs(t[1] - target_ma))
    log(f"[bias-match] {len(kept)}/{total} combinations inside the window")
    return kept


def cmd_dist_gain(args) -> int:
    """Find the max-gain point on the DIST-current-constrained surface."""
    cfg = load_bias_match_cfg(args.config)
    target = cfg.targets_ma.get(DIST_RAIL)
    if target is None:
        print(f"[bias-match] no {DIST_RAIL} target in [bias_match]; "
              "nothing to constrain")
        return 1
    bench, _chip, fh, _row, bidx, beam, ch = open_bench(args)
    rows: list[list] = []
    # 스크리닝이 아무것도 못 건지면 그리드 마지막 코드가 남는다 -> 원래 값으로 되돌린다.
    orig_dist = [read_knob(fh, kn, row=0, beam_idx=bidx) for kn in DIST_KNOBS]
    restore_dist = True
    try:
        kept = screen_dist_grid(bench, fh, beam_idx=bidx, cfg=cfg,
                                target_ma=target, window_ma=args.window_ma,
                                step=args.grid_step)
        if not kept:
            print("[bias-match] no combination landed inside the window -- "
                  "widen --window-ma or shrink --grid-step")
        else:
            f_hz = args.gain_freq_ghz * 1e9
            sg, sa = bench.sg, bench.sa
            sg.modulation_off()
            sg.set_frequency(f_hz)
            bench.apply_path_loss(f_hz)
            sg.set_level(args.sg_level_dbm)
            sa_cfg = getattr(bench, "sa_cfg", {})
            sa.configure(
                center_hz=f_hz, span_hz=args.sa_span_hz,
                rbw_hz=float(sa_cfg.get("rbw_hz", 1.0e6)),
                ref_level_dbm=args.sa_ref_dbm,
                input_atten_db=float(sa_cfg.get("input_atten_db", 10.0)),
                spectrum_mode=bool(sa_cfg.get("spectrum_mode", True)),
            )
            sg.rf_output(True)
            best = None
            for codes, cur in kept:
                for kn, c in zip(DIST_KNOBS, codes):
                    write_knob(fh, kn, c, row=0, beam_idx=bidx)
                pout = sa.measure_peak_dbm()
                gain = pout - args.sg_level_dbm
                rows.append([codes[0], codes[1], codes[2], round(cur, 2),
                             round(pout, 2), round(gain, 2)])
                if best is None or gain > best[1]:
                    best = (codes, gain, cur)
                print(f"[bias-match] dist {list(codes)}: {cur:.2f} mA  "
                      f"gain={gain:+.2f} dB")
            sg.rf_output(False)
            print(f"\n[bias-match] best gain {best[1]:+.2f} dB at "
                  f"dist {list(best[0])} ({best[2]:.2f} mA)")
            for kn, c in zip(DIST_KNOBS, best[0]):
                write_knob(fh, kn, c, row=0, beam_idx=bidx)
            restore_dist = False
    finally:
        if restore_dist:
            for kn, c in zip(DIST_KNOBS, orig_dist):
                write_knob(fh, kn, c, row=0, beam_idx=bidx)
            print(f"[bias-match] DIST codes restored to {orig_dist}")
        # rows 가 비어도(=in-window 조합 없음) 헤더만 있는 CSV 를 남긴다 --
        # '아무것도 안 걸렸다'는 것 자체가 기록할 결과다.
        write_csv(args.csv or _default_csv("distgain"),
                  ["dist_st1", "dist_st2_0", "dist_st2_1",
                   f"{DIST_RAIL}_mA", "Pout_dBm", "Gain_dB"],
                  rows, meta_dict(args, bench, beam, ch))
        bench.close_all()
        print("[bias-match] sockets closed. (power left as-is)")
    return 0
```

Register the subcommand in `main()`, before `args = p.parse_args(argv)`:

```python
    pd = sub.add_parser("dist-gain",
                        help="max gain on the DIST-current-constrained surface")
    _add_common(pd)
    pd.add_argument("--grid-step", type=int, default=16,
                    help="DIST code grid step (default 16 -> 4^3 = 64 points)")
    pd.add_argument("--window-ma", type=float, default=2.0,
                    help="keep combinations within this much of the target [mA]")
    pd.add_argument("--gain-freq-ghz", type=float, default=28.0,
                    help="frequency at which gain is compared [GHz]")
    pd.add_argument("--sg-level-dbm", type=float, default=-28.0,
                    help="chip-input power [dBm], path-loss compensated")
    pd.add_argument("--sa-ref-dbm", type=float, default=20.0,
                    help="SA reference level [dBm]")
    pd.add_argument("--sa-span-hz", type=float, default=100.0e6,
                    help="SA span [Hz]")
```

and extend the dispatch dict:

```python
    return {"jacobian": cmd_jacobian, "solve": cmd_solve,
            "verify": cmd_verify, "dist-gain": cmd_dist_gain}[args.cmd](args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bias_match.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/bias_match.py tests/test_bias_match.py
git commit -m "feat(bias_match): dist-gain surface search"
```

---

### Task 9: Documentation and branch integration

**Files:**
- Modify: `README.md` (the `## 구조` tree around line 71-95, and the `## 실행` block around line 34-44)
- Modify: `docs/SESSION.md` (add a section after the `split()` section around line 95)

- [ ] **Step 1: Add `bias_match.py` to the README structure tree**

In `README.md`, inside the `src/cloudchaser/` tree block, add a line after
`regdump.py`:

```
  bias_match.py  # Sivers 레퍼런스 IC 전류 매칭 (jacobian/solve/verify/dist-gain)
```

- [ ] **Step 2: Add the commands to the README run block**

In `README.md`, append to the `## 실행` powershell block:

```powershell
# Sivers 레퍼런스 IC 와 레일 전류 맞추기 (RF 없이 DC 만 -> jacobian/solve)
python -m cloudchaser.bias_match jacobian --ambient-c 25
python -m cloudchaser.bias_match solve --ambient-c 25
```

- [ ] **Step 3: Add the SESSION.md section**

In `docs/SESSION.md`, after the `### DIST 스플리터 모드 전환 — split()` section,
insert:

```markdown
### Sivers 레퍼런스 전류 매칭 — `bias_match` (TX)

Sivers 는 bias 코드가 IC 마다 다르고 **전류 소비 매트릭스가 공통**이라고 했다
(2026-08-25 메일). 그래서 게인/EVM 을 비교하기 전에 6개 bias 코드
(FE `ptat_st1/2/3` + DIST `st1/st2_0/st2_1`)를 그들의 레퍼런스 전류에 맞춘다.
타깃은 `config/bench.toml` 의 `[bias_match]` 에 있다.

```powershell
# 1) 6x6 커플링 행렬 실측 (7점, RF 불필요) -- 어떤 코드가 어떤 레일을 움직이나
python -m cloudchaser.bias_match jacobian --ambient-c 25

# 2) 타깃 전류로 6개 코드 풀기 (레일별 1D 이진탐색 + DIST 비율 스케일)
python -m cloudchaser.bias_match solve --ambient-c 25

# 3) Sivers 스크립트 재현 (VDD_FE1 x 주파수) -- 그들 CSV 와 같은 컬럼으로 저장
python -m cloudchaser.bias_match verify --ambient-c 25 --serial <DUT S/N>

# 4) (선택) DIST 전류 제약 곡면 위에서 게인 최대점 확인
python -m cloudchaser.bias_match dist-gain --ambient-c 25
```

- 레일 대응: `IDC_1p0`=CORE_1V0, `IDC_1p8`=DIG_1V8, **`IDC_Dist`=IO_1V3(1.3V)**,
  `IDC_FE1/2/3`=FE1_4V0/FE2_1V8/FE3_1V8.
- `CORE_1V0` 는 reset 전류 = 동작 전류라 조절 손잡이가 없다 -- health check 전용.
  `DIG_1V8` 은 종속변수라 기록만 한다.
- **`--ambient-c` 를 꼭 준다.** PTAT 전류는 온도 비례라 온도 없이는 비교가 무의미하다.
- 열린 항목: Sivers 쪽 Dist 레일 전압이 우리와 같은 1.3V 인지 미확인. 다르면
  64.4 mA 타깃 자체가 이전되지 않는다.
```

- [ ] **Step 4: Run the full suite one more time**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 5: Commit the docs**

```bash
git add README.md docs/SESSION.md
git commit -m "docs: document the bias_match tool in README and SESSION"
```

- [ ] **Step 6: Merge the branch**

```bash
git push -u origin feat/bias-current-matching
git checkout main
git merge --no-ff feat/bias-current-matching -m "Merge feat/bias-current-matching: Sivers reference current matching"
git push
git branch -d feat/bias-current-matching
git push origin --delete feat/bias-current-matching
```

---

## Hardware bring-up checklist (after the branch merges)

The plan above is verifiable offline. On the bench, run in this order and stop
if a step surprises you:

1. `bias_match jacobian --ambient-c <T>` — confirm the matrix is block-diagonal
   and no knob reads NO RESPONSE. If `dist_st2_1` is dead, that answers the
   open 13-vs-28 question by itself.
2. Compare the baseline row against the Sivers reset row
   (CORE 3.2 / DIG 0.9 / Dist 0.0 / FE1 4.34 / FE2 0.07 / FE3 0.07 mA).
3. `bias_match solve --ambient-c <T>` — expect convergence within `max_iter`.
4. `bias_match verify --ambient-c <T> --serial <S/N>` — diff against
   `reference/Stampede_T582616915_25_Aug_26_09_30_19.csv`.
5. Only if gain still looks low: `bias_match dist-gain`, once with
   `dist_ratio = [50, 13, 13]` and once with `[50, 13, 28]`.

Mail Sivers the four open items from the spec before step 4, since the Dist
rail voltage decides whether the 64.4 mA target is transferable at all.
