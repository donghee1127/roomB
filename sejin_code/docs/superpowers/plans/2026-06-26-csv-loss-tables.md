# CSV-based Path Loss Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the TOML-based (per-port, TX/RX-split) path-loss model with a single CSV-based model read from VNA measurements in `Loss_data/`, plus a manual `set_loss` override.

**Architecture:** `loss.py` is rewritten to parse three VNA CSVs (SG cable, SA cable, board trace), take the conservative `max(|S12|,|S21|)` per frequency, and compute `in_loss = sg_cable + trace/2`, `out_loss = sa_cable + trace/2` with linear interpolation on the 50 MHz grid. `bench.apply_path_loss` drops the TX/RX/beam/channel logic and supports a manual override held on the `Bench` instance. `session` exposes `set_loss()`.

**Tech Stack:** Python 3.13, stdlib only (`pathlib`, `re`), pytest. No new dependencies.

## Global Constraints

- All user-visible text (print/log/raise messages, `_ns` function docstrings) MUST be English (cp949 console). Code comments / module docstrings may be Korean.
- Run tests with the project venv: `python -m pytest` (this PC uses `.venv`). pytest MUST be green before any commit.
- Commit message bodies: PowerShell here-string closing `'@` at column 0; avoid non-ASCII (em-dash, §). End commit messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- CSV column layout (0-based): `1 = FREQ1 [GHz]`, `5 = LOGMAG2 = S12 [dB]`, `8 = LOGMAG3 = S21 [dB]`. Data section starts after a line whose first cell is `PNT`.
- Loss folder is `Loss_data/` at repo root (code constant `LOSS_DIR`, overridable by argument).
- Work branch: `feat/csv-loss-tables` (already created; spec already committed there).

---

## File Structure

- `src/cloudchaser/loss.py` — **rewritten**: CSV loader + interpolation + `get_loss`/`loss_table`/`latest_files`/`load_loss_csv`.
- `src/cloudchaser/bench.py` — `apply_path_loss` simplified; `_loss_override` field + `set_loss_override`/`clear_loss_override`; drop `DEFAULT_LOSS_RX` import.
- `src/cloudchaser/session.py` — `loss()` rewritten; new `set_loss()`; `_ns` + help updated; drop `DEFAULT_LOSS_RX`.
- `tests/test_loss.py` — **rewritten** for CSV model.
- `tests/test_loss_offset.py` — **rewritten** (monkeypatch `get_loss`; add override test).
- `config/loss.toml`, `config/loss_rx.toml` — **deleted**.
- Docs: `CLAUDE.md`, `docs/SESSION.md`, `README.md`, `scripts/cloudchaser_workbook*.py` comments — string sync.

---

## Task 1: Rewrite loss.py as a CSV loader

**Files:**
- Modify (full rewrite): `src/cloudchaser/loss.py`
- Test (full rewrite): `tests/test_loss.py`

**Interfaces:**
- Produces:
  - `LOSS_DIR: Path` — repo-root `Loss_data/`.
  - `load_loss_csv(path) -> list[tuple[float, float]]` — `(freq_hz, loss_db)` sorted; `loss_db = max(|S12|, |S21|)`.
  - `latest_files(loss_dir=LOSS_DIR) -> dict[str, Path]` — keys `"sg"`, `"sa"`, `"trace"`; newest per kind; raises `FileNotFoundError` if folder or a kind is missing.
  - `get_loss(freq_hz, loss_dir=LOSS_DIR) -> tuple[float, float]` — `(in_loss, out_loss)`.
  - `loss_table(loss_dir=LOSS_DIR) -> str`.
  - `_interp(rows, freq_hz) -> float` — unchanged behavior.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_loss.py` with:

```python
"""경로 손실(VNA CSV) 조회 로직 테스트 -- max(S12,S21) + cable + trace/2."""

from __future__ import annotations

import pytest

from cloudchaser.loss import (
    get_loss,
    latest_files,
    load_loss_csv,
)

# 최소 VNA CSV: 헤더 몇 줄 + PNT 헤더 + 데이터 2행.
# 컬럼: PNT,FREQ1,LOGMAG1(S11),PHASE1,FREQ2,LOGMAG2(S12),PHASE2,
#       FREQ3,LOGMAG3(S21),PHASE3,FREQ4,LOGMAG4(S22),PHASE4
def _csv(rows: list[tuple[float, float, float]]) -> str:
    """rows = [(freq_ghz, s12_db, s21_db), ...] -> VNA CSV 문자열."""
    head = (
        "MS4644B\n!comment\n!IF.BANDWIDTH: 1KHZ\n"
        "PNT,FREQ1.GHZ,LOGMAG1,PHASE1.DEG,FREQ2.GHZ,LOGMAG2,PHASE2.DEG,"
        "FREQ3.GHZ,LOGMAG3,PHASE3.DEG,FREQ4.GHZ,LOGMAG4,PHASE4.DEG\n"
    )
    body = ""
    for i, (f, s12, s21) in enumerate(rows, start=1):
        body += (f"{i},{f},-40,0,{f},{s12},0,{f},{s21},0,{f},-40,0\n")
    return head + body


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(_csv(rows), encoding="utf-8")
    return p


def test_load_loss_csv_takes_max_abs(tmp_path):
    # S12=-3.0, S21=-3.2 -> loss = max(3.0, 3.2) = 3.2
    p = _write(tmp_path, "SG_Cable_Loss_260626.csv",
               [(28.0, -3.0, -3.2), (30.0, -4.0, -3.9)])
    rows = load_loss_csv(p)
    assert rows == [(28.0e9, 3.2), (30.0e9, 4.0)]


def _write_set(tmp_path, date="260626", sg=None, sa=None, tr=None):
    sg = sg or [(28.0, -3.0, -2.8), (30.0, -3.0, -2.8)]   # loss 3.0
    sa = sa or [(28.0, -1.0, -0.9), (30.0, -1.0, -0.9)]   # loss 1.0
    tr = tr or [(28.0, -2.0, -1.9), (30.0, -2.0, -1.9)]   # loss 2.0
    _write(tmp_path, f"SG_Cable_Loss_{date}.csv", sg)
    _write(tmp_path, f"SA_Cable_Loss_{date}.csv", sa)
    _write(tmp_path, f"Board_Trace_Loss_{date}.csv", tr)


def test_get_loss_cable_plus_half_trace(tmp_path):
    _write_set(tmp_path)
    il, ol = get_loss(28.0e9, tmp_path)
    assert il == pytest.approx(3.0 + 2.0 / 2)   # sg + trace/2 = 4.0
    assert ol == pytest.approx(1.0 + 2.0 / 2)   # sa + trace/2 = 2.0


def test_get_loss_interpolates(tmp_path):
    _write_set(tmp_path)
    # 29 GHz = 28/30 중간. 값이 일정하므로 동일.
    il, ol = get_loss(29.0e9, tmp_path)
    assert il == pytest.approx(4.0)
    assert ol == pytest.approx(2.0)


def test_get_loss_clamps_out_of_range(tmp_path):
    _write_set(tmp_path)
    assert get_loss(10.0e9, tmp_path) == get_loss(28.0e9, tmp_path)
    assert get_loss(40.0e9, tmp_path) == get_loss(30.0e9, tmp_path)


def test_latest_files_picks_newest_date(tmp_path):
    _write_set(tmp_path, date="260101")
    _write_set(tmp_path, date="260626")
    files = latest_files(tmp_path)
    assert files["sg"].name == "SG_Cable_Loss_260626.csv"
    assert files["sa"].name == "SA_Cable_Loss_260626.csv"
    assert files["trace"].name == "Board_Trace_Loss_260626.csv"


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_loss(28.0e9, tmp_path / "nope")


def test_missing_kind_raises(tmp_path):
    _write(tmp_path, "SG_Cable_Loss_260626.csv", [(28.0, -3.0, -3.0)])
    with pytest.raises(FileNotFoundError):
        latest_files(tmp_path)   # SA / trace 없음
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_loss.py -v`
Expected: FAIL (ImportError: cannot import name `latest_files` / `load_loss_csv`, since loss.py still has the old API).

- [ ] **Step 3: Rewrite `src/cloudchaser/loss.py`**

Replace the entire file with:

```python
"""경로 손실(케이블 + board trace) 보정 -- VNA CSV 테이블 로딩/조회.

측정마다, 그리고 주파수가 바뀔 때마다 입력/출력 경로 손실을 보상해야 IC 기준의
정확한 전력이 나온다. 손실은 VNA(MS4644B)로 측정한 3개의 CSV(Loss_data/)에서 읽는다:

  SG_Cable_Loss_<YYMMDD>.csv     SG -> EVB 케이블
  SA_Cable_Loss_<YYMMDD>.csv     EVB -> SA 케이블
  Board_Trace_Loss_<YYMMDD>.csv  보드 trace

각 CSV 는 4-trace S-파라미터 sweep(S11/S12/S21/S22), 16~32 GHz, 50 MHz 간격.
주파수별 loss = max(|S12|, |S21|)(보수적). board trace 는 절반씩 SG/SA 에 더한다:

  in_loss(f)  = sg_cable(f) + trace(f)/2     (SG level offset = -(in_loss))
  out_loss(f) = sa_cable(f) + trace(f)/2     (SA ref level offset = +out_loss)

빔/채널·TX/RX 구분 없음(케이블은 항상 SG/SA 측 고정, trace 는 단일값 half/half).
표에 없는 주파수는 선형보간(범위 밖은 끝점 clamp). 폴더에서 종류별 최신 날짜
파일을 자동 선택한다. 수동 조정은 bench.set_loss_override()(session.set_loss).

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import re
from pathlib import Path

# 기본 loss CSV 폴더: 이 파일 기준 repo 루트의 Loss_data/.
LOSS_DIR = Path(__file__).resolve().parents[2] / "Loss_data"

# CSV 컬럼(0-based): 1=FREQ1[GHz], 5=LOGMAG2=S12[dB], 8=LOGMAG3=S21[dB].
_COL_FREQ = 1
_COL_S12 = 5
_COL_S21 = 8

# 파일명 끝의 YYMMDD 날짜 토큰.
_DATE_RE = re.compile(r"_(\d{6})\.csv$", re.IGNORECASE)

# 종류별 파일명 접두사(대소문자 무시).
_KINDS = {"sg": "sg_cable", "sa": "sa_cable", "trace": "board_trace"}


def _interp(rows: list[tuple[float, float]], freq_hz: float) -> float:
    """(freq, value) 정렬 리스트에서 freq_hz 의 값을 선형보간(범위 밖은 끝점 clamp)."""
    if not rows:
        return 0.0
    if freq_hz <= rows[0][0]:
        return rows[0][1]
    if freq_hz >= rows[-1][0]:
        return rows[-1][1]
    for i in range(1, len(rows)):
        f0, v0 = rows[i - 1]
        f1, v1 = rows[i]
        if f0 <= freq_hz <= f1:
            t = (freq_hz - f0) / (f1 - f0)
            return v0 + t * (v1 - v0)
    return rows[-1][1]  # 도달 불가(안전망)


def load_loss_csv(path: str | Path) -> list[tuple[float, float]]:
    """VNA CSV 1개를 (freq_hz, loss_db) 정렬 리스트로 파싱한다.

    loss_db = max(|S12|, |S21|)(보수적). 'PNT,...' 헤더 줄을 만나기 전까지는
    모두 건너뛰고, 그 다음 데이터 행만 읽는다.
    """
    rows: list[tuple[float, float]] = []
    seen_header = False
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        cells = line.split(",")
        if not seen_header:
            if cells and cells[0].strip().upper() == "PNT":
                seen_header = True
            continue
        if len(cells) <= _COL_S21:
            continue
        try:
            f = float(cells[_COL_FREQ]) * 1e9
            s12 = abs(float(cells[_COL_S12]))
            s21 = abs(float(cells[_COL_S21]))
        except ValueError:
            continue
        rows.append((f, max(s12, s21)))
    rows.sort()
    return rows


def _date_key(p: Path) -> int:
    """파일명의 YYMMDD 를 int 로(없으면 -1)."""
    m = _DATE_RE.search(p.name)
    return int(m.group(1)) if m else -1


def latest_files(loss_dir: str | Path = LOSS_DIR) -> dict[str, Path]:
    """Loss_data 에서 종류별(sg/sa/trace) 최신 CSV 경로를 dict 로 반환한다.

    파일명의 YYMMDD 가 큰 것 우선, 없거나 동률이면 mtime 으로 고른다.
    폴더가 없거나 종류가 하나라도 없으면 명확한 에러(0 dB 로 조용히 측정하는 걸 막음).
    """
    d = Path(loss_dir)
    if not d.is_dir():
        raise FileNotFoundError(
            f"Loss data folder not found: {d}. "
            f"Put SG/SA/Board VNA CSVs there (see README).")
    csvs = list(d.glob("*.csv"))
    out: dict[str, Path] = {}
    for key, prefix in _KINDS.items():
        cands = [p for p in csvs if p.name.lower().startswith(prefix)]
        if not cands:
            raise FileNotFoundError(
                f"No '{prefix}*.csv' in {d} (needed for {key} loss).")
        out[key] = max(cands, key=lambda p: (_date_key(p), p.stat().st_mtime))
    return out


def get_loss(freq_hz: float, loss_dir: str | Path = LOSS_DIR) -> tuple[float, float]:
    """주파수[Hz] 의 (in_loss_db, out_loss_db) 경로 손실을 반환한다.

      in_loss  = sg_cable + trace/2
      out_loss = sa_cable + trace/2
    각 항은 50 MHz 격자에서 선형보간(범위 밖은 끝점 clamp).
    """
    files = latest_files(loss_dir)
    sg = _interp(load_loss_csv(files["sg"]), freq_hz)
    sa = _interp(load_loss_csv(files["sa"]), freq_hz)
    tr = _interp(load_loss_csv(files["trace"]), freq_hz)
    return sg + tr / 2.0, sa + tr / 2.0


def loss_table(loss_dir: str | Path = LOSS_DIR) -> str:
    """현재 loss(선택된 파일 + 대표 주파수의 in/out)를 사람이 보기 좋은 문자열로."""
    try:
        files = latest_files(loss_dir)
    except FileNotFoundError as e:
        return f"(loss CSVs missing: {e})"
    lines = [
        f"  files: sg={files['sg'].name}",
        f"         sa={files['sa'].name}",
        f"         trace={files['trace'].name}",
        "  freq[GHz]  in_loss  out_loss",
    ]
    for fghz in (18.0, 19.5, 21.0, 27.5, 28.0, 29.0, 30.0, 31.0):
        il, ol = get_loss(fghz * 1e9, loss_dir)
        lines.append(f"  {fghz:8.2f}  {il:7.2f}  {ol:8.2f}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_loss.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/cloudchaser/loss.py tests/test_loss.py
git commit -m "feat(loss): CSV-based path loss tables (max S12/S21, cable+trace/2)"
```

---

## Task 2: Simplify apply_path_loss + add manual override

**Files:**
- Modify: `src/cloudchaser/bench.py` (import line 22; `Bench` field ~line 40; `apply_path_loss` lines 176-205; add two methods)
- Test (full rewrite): `tests/test_loss_offset.py`

**Interfaces:**
- Consumes: `loss.get_loss(freq_hz) -> (in_loss, out_loss)` (Task 1).
- Produces:
  - `Bench._loss_override: tuple[float, float] | None`
  - `Bench.set_loss_override(in_db, out_db) -> None`
  - `Bench.clear_loss_override() -> None`
  - `Bench.apply_path_loss(freq_hz, *, channel=None, log=print) -> (in_loss, out_loss)` — `channel` accepted but ignored.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_loss_offset.py` with:

```python
"""경로 손실 -> 계측기 오프셋 적용(Bench.apply_path_loss) 오프라인 테스트.

손실은 per-point 계산이 아니라 SG/SA 오프셋으로 '계측기에' 적용된다:
  - SG level offset = -(in_loss)  -> set_level(P) 가 칩 입력 P 를 의미(출력은 P+in_loss)
  - SA ref level offset = +out_loss -> 읽기 = 칩 출력
이 부호/매핑과 수동 override(set_loss) 우선순위를 고정한다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "bench.toml"


def _bench(monkeypatch, in_loss, out_loss):
    import cloudchaser.bench as bench_mod
    from cloudchaser.bench import Bench
    monkeypatch.setattr(bench_mod, "get_loss", lambda f: (in_loss, out_loss))
    B = Bench.from_toml(CONFIG, fake=True)
    B.connect_all(log=lambda *_a: None)
    sg_cmds: list[str] = []
    sa_cmds: list[str] = []
    B.sg.write = lambda c: sg_cmds.append(c)   # type: ignore[assignment]
    B.sa.write = lambda c: sa_cmds.append(c)   # type: ignore[assignment]
    return B, sg_cmds, sa_cmds


def test_offsets_sign(monkeypatch):
    B, sg_cmds, sa_cmds = _bench(monkeypatch, 5.0, 3.0)
    in_loss, out_loss = B.apply_path_loss(28e9, log=lambda *_a: None)
    assert (in_loss, out_loss) == (5.0, 3.0)
    # SG offset = -(in_loss)
    assert f"SOUR:POW:OFFS {-in_loss:.2f}" in sg_cmds
    # SA offset = +out_loss
    assert f"DISP:WIND:TRAC:Y:SCAL:RLEV:OFFS {out_loss:.2f}" in sa_cmds


def test_channel_kwarg_ignored(monkeypatch):
    # channel= 은 하위호환용으로 받기만 하고 값에 영향 없음.
    B, _sg, _sa = _bench(monkeypatch, 5.0, 3.0)
    a = B.apply_path_loss(28e9, channel="h0", log=lambda *_a: None)
    b = B.apply_path_loss(28e9, channel="v3", log=lambda *_a: None)
    assert a == b == (5.0, 3.0)


def test_manual_override_wins_and_clears(monkeypatch):
    B, _sg, _sa = _bench(monkeypatch, 5.0, 3.0)
    B.set_loss_override(9.0, 1.0)
    assert B.apply_path_loss(28e9, log=lambda *_a: None) == (9.0, 1.0)
    B.clear_loss_override()
    assert B.apply_path_loss(28e9, log=lambda *_a: None) == (5.0, 3.0)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_pin_equals_command_no_perpoint_math(monkeypatch):
    """오프셋 적용 후 op1db 의 Pin = 명령 레벨(per-point in_loss 빼기 없음)."""
    import cloudchaser.bench as bench_mod
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.test_items import TestContext, get_test

    monkeypatch.setattr(bench_mod, "get_loss", lambda f: (2.0, 1.0))
    B = Bench.from_toml(CONFIG, fake=True)
    B.chip_kind = "tx"
    B.connect_all(log=lambda *_a: None)
    C = make_chip(B.board, fake=True)
    bring_up_tx(C, B.board, require_version=False, log=lambda *_a: None)
    test = get_test("op1db")()
    res = test.run(TestContext(bench=B, chip=C, fake=True),
                   test.resolve({"pin_start_dbm": -5.0, "pin_stop_dbm": -3.0,
                                 "freq_hz": 28e9}), log=lambda *_a: None)
    assert res.columns[:2] == ["SG_dBm", "Pin_dBm"]
    for row in res.rows:
        assert row[0] == row[1]   # SG 명령 == Pin
    assert "in_loss_db" not in test.defaults()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_loss_offset.py -v`
Expected: FAIL (`Bench` has no `set_loss_override`; and import of `bench.get_loss` monkeypatch target may still work, but the override methods are missing).

- [ ] **Step 3: Edit `src/cloudchaser/bench.py` — import**

Change line 22 from:

```python
from .loss import DEFAULT_LOSS_RX, get_loss
```

to:

```python
from .loss import get_loss
```

- [ ] **Step 4: Edit `src/cloudchaser/bench.py` — add override field**

In the `Bench` dataclass, after the `chip_kind` field (currently line 40):

```python
    chip_kind: str = "tx"   # 'tx'(Stampede) or 'rx'(Blueway) — bring-up/chip 식별용
    _loss_override: tuple[float, float] | None = None  # 수동 loss override(set_loss)
```

- [ ] **Step 5: Edit `src/cloudchaser/bench.py` — rewrite apply_path_loss + add methods**

Replace the whole `apply_path_loss` method (currently lines 176-205) with:

```python
    def apply_path_loss(self, freq_hz: float, *, channel: str | None = None,
                        log=print) -> tuple[float, float]:
        """주파수의 경로 손실을 SG·SA 오프셋으로 '계측기에' 적용한다.

        - in_loss = sg_cable + trace/2, out_loss = sa_cable + trace/2 (Loss_data CSV).
        - SG: level offset = -(in_loss) -> set_level(P) 가 'DUT 입력 P' 를 의미(출력은
          P+in_loss 로 부스트). SA: ref level offset = +out_loss -> 읽기 = DUT 출력.
        - 수동 override(set_loss_override)가 있으면 CSV 대신 그 값을 쓴다.
        - channel 인자는 하위호환용으로 받기만 하고 무시한다(trace 는 채널 무관).
        - fake 모드에서 CSV 가 없으면 0 dB 로 경고만(실제 측정은 에러로 막는다).
        반환: (in_loss, out_loss) [dB] (CSV meta 기록용).
        """
        if self._loss_override is not None:
            in_loss, out_loss = self._loss_override
            src = "manual"
        else:
            try:
                in_loss, out_loss = get_loss(freq_hz)
                src = "csv"
            except FileNotFoundError as e:
                if not self.fake:
                    raise
                in_loss, out_loss = 0.0, 0.0
                src = "no-cal(fake)"
                log(f"[loss  ] WARNING: {e} -> using 0 dB (fake mode)")
        self.sg.set_level_offset(-in_loss)     # SG 출력 부스트 -> 칩 입력 = 명령값
        self.sa.set_ref_level_offset(out_loss)  # SA 읽기 = 칩 출력
        log(f"[loss  ] {freq_hz/1e9:.3f} GHz ({src}) -> "
            f"SG offset {-in_loss:+.2f} dB (in_loss {in_loss:.2f}), "
            f"SA offset {out_loss:+.2f} dB (out_loss {out_loss:.2f})")
        return in_loss, out_loss

    def set_loss_override(self, in_db: float, out_db: float) -> None:
        """SG/SA 오프셋을 직접 고정한다(CSV 자동값 무시). 간이 측정용."""
        self._loss_override = (float(in_db), float(out_db))

    def clear_loss_override(self) -> None:
        """수동 override 해제 -> 다시 CSV 자동 손실을 사용한다."""
        self._loss_override = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_loss_offset.py -v`
Expected: PASS (the op1db test is skipped if `sivers_api` is absent; otherwise PASS).

- [ ] **Step 7: Commit**

```bash
git add src/cloudchaser/bench.py tests/test_loss_offset.py
git commit -m "feat(loss): apply_path_loss uses CSV loss + manual override; drop TX/RX swap"
```

---

## Task 3: session loss() rewrite + set_loss

**Files:**
- Modify: `src/cloudchaser/session.py` (remove `DEFAULT_LOSS_RX` line 47; rewrite `loss()` lines 539-557; add `set_loss()`; register in `_ns` ~line 300; help section ~line 754)
- Test: append to `tests/test_session_ux.py`

**Interfaces:**
- Consumes: `Bench.set_loss_override` / `clear_loss_override` / `_loss_override` (Task 2); `loss.get_loss` / `loss_table` (Task 1).
- Produces: session `set_loss(in_db=None, out_db=None)` registered in `_ns`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_session_ux.py`:

```python
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_set_loss_override_roundtrip(capsys):
    """set_loss(in,out) sets the bench override; set_loss() clears it."""
    sess = _start_fake()
    sess.set_loss(7.0, 2.0)
    assert sess.B._loss_override == (7.0, 2.0)
    out = capsys.readouterr().out
    assert "override set" in out.lower()
    sess.set_loss()
    assert sess.B._loss_override is None
    out = capsys.readouterr().out
    assert "cleared" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_session_ux.py::test_set_loss_override_roundtrip -v`
Expected: FAIL (`module 'cloudchaser.session' has no attribute 'set_loss'`).

- [ ] **Step 3: Remove the stale `DEFAULT_LOSS_RX` constant**

In `src/cloudchaser/session.py`, delete lines 46-47:

```python
# loss_rx.toml 기본 경로
DEFAULT_LOSS_RX = Path(__file__).resolve().parents[2] / "config" / "loss_rx.toml"
```

(Leave the `from .loss import get_loss, loss_table` import at line 39 as-is.)

- [ ] **Step 4: Rewrite `loss()` and add `set_loss()`**

Replace the `loss()` function (currently lines 539-557) with:

```python
def loss(freq_ghz=None):
    """Path loss lookup (from Loss_data CSVs). loss() shows the table,
    loss(28) shows in/out loss at 28 GHz. Shows manual override when active."""
    ov = getattr(B, "_loss_override", None) if B is not None else None
    if freq_ghz is None:
        print(loss_table())
        if ov is not None:
            print(f"  [manual override active] in_loss={ov[0]:.2f} "
                  f"out_loss={ov[1]:.2f} dB (set_loss() to clear)")
        return None
    f = float(freq_ghz) * 1e9
    if ov is not None:
        il, ol = ov
        tag = " [manual override]"
    else:
        il, ol = get_loss(f)
        tag = ""
    print(f"  {float(freq_ghz):.3f} GHz: in_loss={il:.2f} dB, "
          f"out_loss={ol:.2f} dB{tag}")
    return il, ol


def set_loss(in_db=None, out_db=None):
    """Manually fix SG/SA loss offsets (overrides CSV auto-loss) for quick tests.
    set_loss(in_db, out_db) -> fix; set_loss() -> clear (back to CSV-auto)."""
    if B is None:
        print("not started.")
        return None
    if in_db is None and out_db is None:
        B.clear_loss_override()
        print("  loss override cleared -> CSV-auto")
        return None
    if in_db is None or out_db is None:
        print("  set_loss needs both in_db and out_db (or none to clear).")
        return None
    B.set_loss_override(in_db, out_db)
    print(f"  loss override set: in_loss={float(in_db):.2f} dB, "
          f"out_loss={float(out_db):.2f} dB")
    return None
```

- [ ] **Step 5: Register `set_loss` in the namespace**

In `_finalize`, change the `_ns.update({...})` entry (currently line 300) from:

```python
        "loss": loss, "peakc": peakc,
```

to:

```python
        "loss": loss, "set_loss": set_loss, "peakc": peakc,
```

- [ ] **Step 6: Update the help listing**

Replace the `"loss (path comp)"` help section (currently lines 754-756) with:

```python
    "loss (path comp)": [
        ("loss() / loss(28)", "show loss table / loss at a freq (from Loss_data CSVs)"),
        ("set_loss(in, out) / set_loss()", "manual loss override / clear (back to CSV-auto)"),
    ],
```

- [ ] **Step 7: Update the wizard banner string**

Change line ~655 from:

```python
        print("  Loss   : auto (applied to SG/SA offsets from loss.toml)")
```

to:

```python
        print("  Loss   : auto (applied to SG/SA offsets from Loss_data CSVs)")
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_session_ux.py -v`
Expected: PASS (new test passes; others unchanged). If `sivers_api` is absent these are skipped — then run `.venv\Scripts\python -c "import cloudchaser.session"` and expect no error.

- [ ] **Step 9: Commit**

```bash
git add src/cloudchaser/session.py tests/test_session_ux.py
git commit -m "feat(loss): session loss() reads CSVs; add set_loss manual override"
```

---

## Task 4: Remove TOML configs, sync docstrings/comments, run full suite

**Files:**
- Delete: `config/loss.toml`, `config/loss_rx.toml`
- Modify (string-only): `src/cloudchaser/session.py` (docstrings 380, 474, 541-area, 578), `src/cloudchaser/test_items/ip1db.py` (12, 64), `src/cloudchaser/test_items/op1db.py` (104), `src/cloudchaser/test_items/channel_gain_alignment.py` (19), `scripts/cloudchaser_workbook.py` (80, 304, 422), `scripts/cloudchaser_workbook_ko.py` (98, 336, 460)
- Docs: `CLAUDE.md`, `docs/SESSION.md`, `README.md`

- [ ] **Step 1: Delete the TOML loss configs**

```bash
git rm config/loss.toml config/loss_rx.toml
```

- [ ] **Step 2: Fix remaining `loss.toml` / `loss_rx.toml` string references in src**

Find them:

```bash
grep -rn "loss\.toml\|loss_rx\|_apply_loss_rx" src/ scripts/ | grep -v __pycache__
```

Apply these literal replacements (comments/docstrings only — no logic):
- `src/cloudchaser/session.py` line ~380: `(config/loss.toml) inside the run` -> `(from Loss_data CSVs) inside the run`.
- `src/cloudchaser/session.py` line ~474 (ip1db docstring): `Path loss auto-applied (loss_rx.toml) to SG/SA offsets.` -> `Path loss auto-applied (Loss_data CSVs) to SG/SA offsets.`
- `src/cloudchaser/session.py` line ~578: `loss.toml (same as calling the function directly).` -> `Loss_data CSVs (same as calling the function directly).`
- `src/cloudchaser/test_items/ip1db.py` line ~12: replace the `session.py 의 _apply_loss_rx() 가 처리` clause with `bench.apply_path_loss 가 Loss_data CSV 로 처리(TX/RX 동일)`.
- `src/cloudchaser/test_items/ip1db.py` line ~64: `# (bench.apply_path_loss; RX 는 loss_rx.toml).` -> `# (bench.apply_path_loss; Loss_data CSV, TX/RX 동일).`
- `src/cloudchaser/test_items/op1db.py` line ~104: any `loss.toml` mention -> `Loss_data CSV`.
- `src/cloudchaser/test_items/channel_gain_alignment.py` line ~19: `config/loss.toml 에서` -> `Loss_data CSV 에서`.
- `scripts/cloudchaser_workbook.py` lines ~80, 304, 422 and `scripts/cloudchaser_workbook_ko.py` lines ~98, 336, 460: replace `loss.toml` with `Loss_data CSVs` (English file) / `Loss_data CSV` (Korean file) in those comment lines.

- [ ] **Step 3: Update CLAUDE.md loss rule**

In `CLAUDE.md`, replace the bullet that begins `경로 손실 모델: loss.toml은 ...` (the `[[cable]]` + `[[trace]]` schema description) with:

```markdown
- 경로 손실 모델: `Loss_data/`의 VNA CSV 3개(SG_Cable / SA_Cable / Board_Trace, 16-32GHz/50MHz)에서 읽는다. 주파수별 `loss = max(|S12|,|S21|)`(보수적), 종류별 최신 날짜 파일 자동 선택. `in_loss = sg_cable + trace/2`, `out_loss = sa_cable + trace/2`(빔/채널·TX/RX 구분 없음). 표에 없는 주파수는 선형보간(범위 밖 끝점 clamp). 간이 측정 시 `set_loss(in,out)`로 수동 override, `set_loss()`로 해제. `Loss_data/*.csv`는 git-ignore(로컬 cal 데이터).
```

- [ ] **Step 4: Update docs/SESSION.md and README.md**

```bash
grep -n "loss\.toml\|loss_rx\|loss(28)\|path loss\|경로 손실\|경로손실" docs/SESSION.md README.md
```

For each hit describing the old TOML/per-port model, update the prose to the CSV model: three VNA CSVs in `Loss_data/`, `max(S12,S21)`, `cable + trace/2`, auto-newest selection, no TX/RX/per-port split, and document `loss()` / `set_loss(in,out)` / `set_loss()`. Ensure no remaining reference tells the user to "edit config/loss.toml".

- [ ] **Step 5: Run the full test suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green (the same skip count as before for `sivers_api`-gated tests). If any test fails because it depended on the deleted TOMLs or old loss API, fix it in line with Tasks 1-3 (no TOML, CSV-based) and re-run.

- [ ] **Step 6: Verify no stale references remain**

Run: `grep -rn "loss\.toml\|loss_rx\|DEFAULT_LOSS\|get_cable\|get_trace\|_apply_loss_rx" src/ tests/ docs/ scripts/ CLAUDE.md README.md | grep -v __pycache__`
Expected: no matches (empty output).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(loss): remove loss.toml/loss_rx.toml; sync docs to CSV model"
```

---

## Final integration (after all tasks)

Per CLAUDE.md auto-merge workflow, once `python -m pytest` is green on `feat/csv-loss-tables`:

```bash
git push -u origin feat/csv-loss-tables
git checkout main && git merge --no-ff feat/csv-loss-tables
git push origin main
git branch -d feat/csv-loss-tables && git push origin --delete feat/csv-loss-tables
```

(Destructive remote-branch delete: confirm with the user first if there is any doubt.)

---

## Self-Review

**Spec coverage:**
- max(|S12|,|S21|) -> Task 1 (`load_loss_csv`, `test_load_loss_csv_takes_max_abs`). ✓
- cable + trace/2 -> Task 1 (`get_loss`, `test_get_loss_cable_plus_half_trace`). ✓
- newest-file auto-select -> Task 1 (`latest_files`, `test_latest_files_picks_newest_date`). ✓
- interpolation + clamp -> Task 1 (`_interp`, two tests). ✓
- TX/RX + beam/channel removed -> Task 2 (`apply_path_loss`, `test_channel_kwarg_ignored`). ✓
- manual override (`set_loss`) -> Task 2 (bench methods) + Task 3 (session fn). ✓
- missing-CSV hard error (real) / fake fallback -> Task 1 (`test_missing_*`) + Task 2 (apply_path_loss fake branch). ✓
- delete TOMLs + Loss_data git-ignored -> Task 4. ✓
- docs sync (CLAUDE/SESSION/README) -> Task 4. ✓

**Placeholder scan:** No TBD/TODO; all code blocks complete. ✓

**Type consistency:** `get_loss(freq_hz, loss_dir=LOSS_DIR) -> (float,float)`, `latest_files -> dict[str,Path]`, `set_loss_override(in_db,out_db)` / `clear_loss_override()` used consistently across Tasks 1-3. ✓
