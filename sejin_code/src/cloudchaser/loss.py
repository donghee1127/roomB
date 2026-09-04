"""경로 손실(케이블 + board trace) 보정 -- VNA CSV 테이블 로딩/조회.

측정마다, 그리고 주파수가 바뀔 때마다 입력/출력 경로 손실을 보상해야 IC 기준의
정확한 전력이 나온다. 손실은 VNA(MS4644B)로 측정한 3개의 CSV(Loss_data/)에서 읽는다:

  SG_Cable_Loss_<YYMMDD>.csv     SG -> EVB 케이블
  SA_Cable_Loss_<YYMMDD>.csv     EVB -> SA 케이블
  Board_Trace_Loss_<YYMMDD>.csv  보드 trace

각 CSV 는 4-trace S-파라미터 sweep(S11/S12/S21/S22). 주파수 범위·간격은 측정마다
다르므로 고정 가정하지 않는다(파일에서 읽은 격자를 그대로 쓴다).
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

# 컬럼 위치는 헤더('PNT,...')에서 찾는다. 하드코딩하면 안 된다 — MS4644B 는
# 저장 설정에 따라 PHASE 열을 포함하기도, 빼기도 한다:
#   260626: PNT,FREQ1,LOGMAG1,PHASE1,FREQ2,LOGMAG2,PHASE2,FREQ3,LOGMAG3,...
#   260820: PNT,FREQ1,LOGMAG1,FREQ2,LOGMAG2,FREQ3,LOGMAG3,...
# 열 번호를 고정해두면 후자에서 FREQ3 를 S12 로, LOGMAG4(S22) 를 S21 로 읽어
# 조용히 엉뚱한 값(주파수 숫자)이 loss 로 들어간다.
_TRACE_FREQ_RE = re.compile(r"^FREQ(\d+)", re.IGNORECASE)
_TRACE_MAG_RE = re.compile(r"^LOGMAG(\d+)", re.IGNORECASE)

# 쓰는 트레이스: freq 는 trace1, S12=trace2, S21=trace3 (4-trace S-param sweep).
_FREQ_TRACE = 1
_S12_TRACE = 2
_S21_TRACE = 3

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


def _header_columns(header_cells: list[str], fname: str) -> dict[str, int]:
    """'PNT,...' 헤더에서 freq/S12/S21 열 위치를 찾는다.

    MS4644B 저장 설정에 따라 PHASE 열이 있기도 없기도 해서 열 번호가 밀린다.
    이름으로 찾아야 두 형식 모두 안전하다.
    """
    freq_cols: dict[int, int] = {}
    mag_cols: dict[int, int] = {}
    for idx, cell in enumerate(header_cells):
        name = cell.strip()
        m = _TRACE_FREQ_RE.match(name)
        if m:
            freq_cols[int(m.group(1))] = idx
            continue
        m = _TRACE_MAG_RE.match(name)
        if m:
            mag_cols[int(m.group(1))] = idx
    missing = []
    if _FREQ_TRACE not in freq_cols:
        missing.append(f"FREQ{_FREQ_TRACE}")
    if _S12_TRACE not in mag_cols:
        missing.append(f"LOGMAG{_S12_TRACE}")
    if _S21_TRACE not in mag_cols:
        missing.append(f"LOGMAG{_S21_TRACE}")
    if missing:
        raise ValueError(
            f"{fname}: header is missing {', '.join(missing)} "
            f"(need a 4-trace S-parameter sweep: FREQ1/LOGMAG2=S12/LOGMAG3=S21). "
            f"Header was: {','.join(c.strip() for c in header_cells)}")
    return {"freq": freq_cols[_FREQ_TRACE],
            "s12": mag_cols[_S12_TRACE],
            "s21": mag_cols[_S21_TRACE]}


def load_loss_csv(path: str | Path) -> list[tuple[float, float]]:
    """VNA CSV 1개를 (freq_hz, loss_db) 정렬 리스트로 파싱한다.

    loss_db = max(|S12|, |S21|)(보수적). 'PNT,...' 헤더 줄을 만나기 전까지는
    모두 건너뛰고, 그 다음 데이터 행만 읽는다.
    """
    rows: list[tuple[float, float]] = []
    cols: dict[str, int] | None = None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        cells = line.split(",")
        if cols is None:
            if cells and cells[0].strip().upper() == "PNT":
                cols = _header_columns(cells, Path(path).name)
            continue
        if len(cells) <= max(cols.values()):
            continue
        try:
            f = float(cells[cols["freq"]]) * 1e9
            s12 = abs(float(cells[cols["s12"]]))
            s21 = abs(float(cells[cols["s21"]]))
        except ValueError:
            continue
        rows.append((f, max(s12, s21)))
    rows.sort()
    if not rows:
        raise ValueError(
            f"No parseable data rows in {Path(path).name} "
            f"(expected a 'PNT,...' header followed by numeric rows).")
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


def get_loss(freq_hz: float, loss_dir: str | Path = LOSS_DIR,
             log=None) -> tuple[float, float]:
    """주파수[Hz] 의 (in_loss_db, out_loss_db) 경로 손실을 반환한다.

      in_loss  = sg_cable + trace/2
      out_loss = sa_cable + trace/2
    각 항은 측정 격자에서 선형보간(범위 밖은 끝점 clamp).
    log 를 주면 요청 주파수가 테이블 범위를 벗어날 때 경고를 남긴다.
    """
    files = latest_files(loss_dir)
    tables = {k: load_loss_csv(p) for k, p in files.items()}
    if log is not None:
        # 측정 주파수가 테이블 밖이면 _interp 가 끝점으로 clamp 한다 -- 조용히
        # 엉뚱한 loss 를 쓰는 대신 어느 파일이 얼마나 모자라는지 말한다.
        # (예: 27~32 GHz 케이블 테이블로 19.5 GHz RX 를 재면 27 GHz 값이 쓰인다.)
        outside = [
            f"{k}={files[k].name} covers "
            f"{rows[0][0] / 1e9:.2f}-{rows[-1][0] / 1e9:.2f} GHz"
            for k, rows in tables.items()
            if not (rows[0][0] <= freq_hz <= rows[-1][0])
        ]
        if outside:
            log(f"[loss   ] WARNING: {freq_hz / 1e9:.3f} GHz is outside "
                f"{len(outside)} loss table(s); the nearest endpoint value is "
                f"used instead (clamped): {'; '.join(outside)}")
    sg = _interp(tables["sg"], freq_hz)
    sa = _interp(tables["sa"], freq_hz)
    tr = _interp(tables["trace"], freq_hz)
    return sg + tr / 2.0, sa + tr / 2.0


def loss_table(loss_dir: str | Path = LOSS_DIR) -> str:
    """현재 loss(선택된 파일 + 대표 주파수의 in/out)를 사람이 보기 좋은 문자열로."""
    try:
        files = latest_files(loss_dir)
        tables = {k: load_loss_csv(p) for k, p in files.items()}
        # 파일 이름만으로는 "이 표가 내 측정 주파수를 덮는가" 를 알 수 없다.
        # 커버리지를 같이 찍어야 260820(27-32GHz) 같은 좁은 표를 바로 알아본다.
        lines = ["  files (kind = name  [coverage]):"]
        for kind in ("sg", "sa", "trace"):
            rows = tables[kind]
            lines.append(
                f"    {kind:5s} {files[kind].name}  "
                f"[{rows[0][0] / 1e9:.2f}-{rows[-1][0] / 1e9:.2f} GHz, "
                f"{len(rows)} pts]")
        lines.append("  freq[GHz]  in_loss  out_loss")
        for fghz in (18.0, 19.5, 21.0, 27.5, 28.0, 29.0, 30.0, 31.0):
            f_hz = fghz * 1e9
            il, ol = get_loss(f_hz, loss_dir)
            # 표 밖이면 끝점으로 clamp 된 값이다 -- 실제 손실이 아니라고 표시한다.
            clamped = [k for k, rows in tables.items()
                       if not (rows[0][0] <= f_hz <= rows[-1][0])]
            mark = f"  <- CLAMPED ({', '.join(clamped)} out of range)" if clamped else ""
            lines.append(f"  {fghz:8.2f}  {il:7.2f}  {ol:8.2f}{mark}")
    except (FileNotFoundError, ValueError) as e:
        return f"(loss CSVs unavailable: {e})"
    return "\n".join(lines)
