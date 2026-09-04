"""bias 조건별 VDD sensitivity / EVM / VNA gain CSV -> 조건마다 xlsx 한 권.

`scripts/postprocess_tx.py` 의 자매 스크립트다. 그쪽은 채널 스윕 묶음(op1db +
gain accuracy + evm)을 한 권으로 만들고, 이쪽은 **bias 조건 비교**용이다:
입력 폴더 아래의 조건 폴더(예: `15_45_55`, `63_63_63`) 하나가 워크북 하나가 된다.

입력(조건 폴더 안):
  vdd_sensitivity_*.csv   FE1 전압 계단마다 반복한 OP1dB 스윕
  evm_*.csv               EVM bathtub
  vna_gain_result_*.csv   MS4644B 4-trace 스윕(S12 = 통과 경로)

시트:
  Summary          조건 한눈에: 주파수/VDD 별 OP1dB·게인·Pdc, best EVM, VNA 게인
  VddSensitivity   스윕 raw (reference Linearity 형식 + VDD 열)
  EVM              EVM bathtub raw (+ Freq 열)
  VNA_Gain         S12 보정: Gain = S12 + 감쇠기 + board trace loss

VNA 보정: 측정에 30 dB 외부 감쇠기가 물려 있고 보드 trace 손실이 de-embed 되지
않았다. 입력·출력 trace 가 둘 다 경로에 있으므로 **trace 전체**(절반이 아니라)를
더한다. Loss_data 의 최신 Board_Trace CSV 에서 주파수별로 보간해 쓰며, 27~32 GHz
에서 30 + trace = 34.8~35.7 dB 로 현장에서 쓰던 "약 35 dB" 와 맞는다.

사용:
  python scripts/postprocess_bias_vdd.py [입력폴더] [--atten 30]
  기본 입력 = "out/Stampede bias optimize test_260821/260821_Optimized bias code"
  출력      = 각 조건 폴더 옆에 260821_Stampede_TX_Results_<조건>.xlsx
"""

from __future__ import annotations

import ast
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.chart import LineChart, Reference, Series
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cloudchaser.loss import _interp, latest_files, load_loss_csv  # noqa: E402
from postprocess_tx import (column, fnum, parse_csv, psum_w,  # noqa: E402
                            rails_filled)

DEFAULT_DIR = Path("out/Stampede bias optimize test_260821/260821_Optimized bias code")
DEFAULT_ATTEN_DB = 30.0

BOLD = Font(bold=True)
TITLE = Font(bold=True, size=13)

RAIL_ORDER = ["FE1_4V0", "CORE_1V0", "IO_ANA_1V8", "DIST_1V8", "FE2_1V8", "FE3_1V8"]


# ---------------------------------------------------------------- loading
def _freq_mhz(d: dict) -> float:
    f = fnum(d["meta"].get("freq_hz"))
    return round(f / 1e6, 1) if f else 0.0


def _per_vdd(d: dict) -> list[dict]:
    """meta.per_vdd (우리가 쓴 파이썬 리터럴) -> list[dict]. 못 읽으면 빈 리스트."""
    raw = d["meta"].get("per_vdd")
    if not raw:
        return []
    try:
        return list(ast.literal_eval(raw))
    except (ValueError, SyntaxError):
        return []


def load_vna(path: Path) -> list[tuple[float, float]]:
    """MS4644B CSV -> [(freq_hz, S12_dB), ...].

    열 위치는 'PNT,...' 헤더에서 이름으로 찾는다 -- 저장 설정에 따라 PHASE 열이
    빠지기도 해서 번호를 고정하면 주파수를 손실로 읽는다(cloudchaser.loss 와 같은 이유).
    S12 = LOGMAG2 (TRACE.2). S21 은 이 칩에서 역방향이라 -100 dB 근처다.
    """
    freq_re = re.compile(r"^FREQ(\d+)", re.IGNORECASE)
    mag_re = re.compile(r"^LOGMAG(\d+)", re.IGNORECASE)
    cols: dict[str, int] | None = None
    out: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = line.split(",")
        if cols is None:
            if cells and cells[0].strip().upper() == "PNT":
                f_at, m_at = {}, {}
                for i, c in enumerate(cells):
                    m = freq_re.match(c.strip())
                    if m:
                        f_at[int(m.group(1))] = i
                        continue
                    m = mag_re.match(c.strip())
                    if m:
                        m_at[int(m.group(1))] = i
                if 1 not in f_at or 2 not in m_at:
                    raise ValueError(
                        f"{path.name}: need FREQ1 and LOGMAG2 (S12) in the "
                        f"'PNT,...' header, got: {','.join(cells)}")
                cols = {"freq": f_at[1], "s12": m_at[2]}
            continue
        if len(cells) <= max(cols.values()):
            continue
        try:
            out.append((float(cells[cols["freq"]]) * 1e9,
                        float(cells[cols["s12"]])))
        except ValueError:
            continue
    if not out:
        raise ValueError(f"{path.name}: no parseable VNA data rows")
    out.sort()
    return out


def load_condition(d: Path) -> dict:
    """조건 폴더 하나를 읽어 {vdd:[...], evm:[...], vna:path} 로."""
    vdd = [parse_csv(p) for p in sorted(d.glob("vdd_sensitivity_*.csv"))]
    evm = [parse_csv(p) for p in sorted(d.glob("evm_*.csv"))]
    vna = sorted(d.glob("vna_gain_result_*.csv"))
    vdd.sort(key=_freq_mhz)
    evm.sort(key=_freq_mhz)
    return {"name": d.name, "vdd": vdd, "evm": evm,
            "vna": vna[0] if vna else None}


# ---------------------------------------------------------------- writers
def _hrow(ws, names):
    ws.append(names)
    for c in ws[ws.max_row]:
        c.font = BOLD


def _r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def write_vdd(ws, cond) -> dict:
    """VDD sweep raw. 반환: {(freq_mhz, vdd_v): (첫행, 끝행)} 차트용 행 범위."""
    _hrow(ws, ["Beam", "Channel", "Index", "Freq(MHz)", "VDD(V)", "Pin(dBm)",
               "Pout(dBm)", "Gain(dB)"]
          + [f"{r}(mA)" for r in RAIL_ORDER] + ["Psum(W)"])
    ranges: dict[tuple[float, float], tuple[int, int]] = {}
    for d in cond["vdd"]:
        beam = (d["meta"].get("beam") or "").upper()
        chan = (d["meta"].get("channel") or "").upper()
        fm = _freq_mhz(d)
        rails, ma, v, _timeout = rails_filled(d)
        vset = column(d, "VDD_set_V")
        pin = column(d, "Pin_dBm")
        pout = column(d, "Pout_dBm")
        gain = column(d, "Gain_dB")
        idx_in_group = 0
        prev_v = None
        for i in range(len(d["rows"])):
            if vset[i] != prev_v:
                idx_in_group, prev_v = 0, vset[i]
            row = [beam, chan, idx_in_group, fm, vset[i],
                   _r(pin[i]), _r(pout[i]), _r(gain[i])]
            row += [_r(ma[r][i], 1) if r in ma else None for r in RAIL_ORDER]
            row.append(_r(psum_w(rails, ma, v, i), 5))
            ws.append(row)
            key = (fm, vset[i])
            r_now = ws.max_row
            s, _e = ranges.get(key, (r_now, r_now))
            ranges[key] = (s, r_now)
            idx_in_group += 1
    return ranges


def write_evm(ws, cond) -> dict:
    _hrow(ws, ["Beam", "Channel", "Index", "Freq(MHz)", "Pin(dBm)",
               "NR_Pout(dBm)", "Gain(dB)", "EVM(dB)", "EVM(%)"]
          + [f"{r}(mA)" for r in RAIL_ORDER] + ["Psum(W)"])
    ranges: dict[float, tuple[int, int]] = {}
    for d in cond["evm"]:
        beam = (d["meta"].get("beam") or "").upper()
        chan = (d["meta"].get("channel") or "").upper()
        fm = _freq_mhz(d)
        rails, ma, v, _timeout = rails_filled(d)
        pin = column(d, "Pin_dBm")
        pout = column(d, "NR_Pout_dBm")
        edb = column(d, "EVM_dB")
        ep = column(d, "EVM_pct")
        start = ws.max_row + 1
        for i in range(len(d["rows"])):
            gain = (pout[i] - pin[i]) if (pout[i] is not None
                                          and pin[i] is not None) else None
            row = [beam, chan, i, fm, _r(pin[i]), _r(pout[i]), _r(gain),
                   _r(edb[i]), _r(ep[i], 3)]
            row += [_r(ma[r][i], 1) if r in ma else None for r in RAIL_ORDER]
            row.append(_r(psum_w(rails, ma, v, i), 5))
            ws.append(row)
        ranges[fm] = (start, ws.max_row)
    return ranges


def write_vna(ws, cond, atten_db: float):
    """S12 보정 표. 반환: (행범위, [(freq_hz, gain_db), ...])."""
    _hrow(ws, ["Freq(MHz)", "S12_raw(dB)", "Atten(dB)", "BoardTrace(dB)",
               "Gain(dB)"])
    corrected: list[tuple[float, float]] = []
    if cond["vna"] is None:
        ws.append(["(no vna_gain_result_*.csv in this folder)"])
        return (0, 0), corrected
    trace_path = latest_files()["trace"]
    trace = load_loss_csv(trace_path)
    start = ws.max_row + 1
    for f_hz, s12 in load_vna(cond["vna"]):
        tr = _interp(trace, f_hz)
        gain = s12 + atten_db + tr
        corrected.append((f_hz, gain))
        ws.append([round(f_hz / 1e6, 1), _r(s12), atten_db, _r(tr), _r(gain)])
    end = ws.max_row
    ws.append([])
    ws.append([f"S12 = TRACE.2 of {cond['vna'].name}; "
               f"board trace from {trace_path.name} (full trace: the input and "
               f"output traces are both in the VNA path)"])
    return (start, end), corrected


# 조건 폴더 이름에 섞여 들어오는, bias 코드가 아닌 숫자들.
#   앞의 측정일(YYMMDD)  뒤의 채널/빔(H0B0, v2 ...)
_NAME_DATE_RE = re.compile(r"^\d{6}[_\- ]+")
_NAME_CHAN_RE = re.compile(r"[_\- ]*[hv]\d(?:b\d)?$", re.IGNORECASE)


def bias_codes(name: str) -> list[int]:
    """조건 폴더 이름에서 bias 코드를 뽑는다.

    '15_45_55' -> [15,45,55] (FE PTAT 3개)
    'new bias_17_55_61_63_16_0' -> [17,55,61,63,16,0] (FE 3 + DIST 3)
    '260904_new bias_17_55_61_63_16_63_H0B0' -> [17,55,61,63,16,63]

    숫자 그룹만 보되 **앞의 날짜와 뒤의 채널/빔은 먼저 떼어낸다** -- 그냥 다 긁으면
    요약 시트에 `St1=260904` 처럼 날짜가 bias 코드로 찍히고 파일 이름도 어긋난다.
    """
    s = _NAME_CHAN_RE.sub("", _NAME_DATE_RE.sub("", name.strip()))
    return [int(x) for x in re.findall(r"\d+", s)]


def write_summary(ws, cond, vna, atten_db: float) -> None:
    ws.append([f"Stampede TX bias sweep -- condition {cond['name']}"])
    ws["A1"].font = TITLE
    bits = bias_codes(cond["name"])
    if len(bits) >= 3:
        ws.append([f"FE PTAT bias: St1={bits[0]}  St2={bits[1]}  St3={bits[2]}"])
    if len(bits) >= 6:
        ws.append([f"DIST bias: St1={bits[3]}  St2_0={bits[4]}  St2_1={bits[5]}"])
    d0 = (cond["vdd"] or cond["evm"] or [None])[0]
    if d0:
        ws.append([f"Beam {(d0['meta'].get('beam') or '').upper()}  /  "
                   f"Channel {(d0['meta'].get('channel') or '').upper()}"])
    ws.append([])

    # --- VDD sensitivity ---------------------------------------------
    ws.append(["VDD sensitivity (OP1dB sweep repeated per FE1 supply voltage)"])
    ws[f"A{ws.max_row}"].font = BOLD
    _hrow(ws, ["Freq(MHz)", "VDD(V)", "OP1dB(dBm)", "IP1dB(dBm)",
               "SmallSigGain(dB)", "Idd_max(mA)", "Psum@OP1dB(W)",
               "dOP1dB vs nominal(dB)"])
    for d in cond["vdd"]:
        fm = _freq_mhz(d)
        entries = _per_vdd(d)
        ref = entries[0]["op1db_dbm"] if entries else None
        rails, ma, v, _t = rails_filled(d)
        vset, pout = column(d, "VDD_set_V"), column(d, "Pout_dBm")
        for e in entries:
            psum = _psum_at_op1db(rails, ma, v, vset, pout,
                                  e["vdd_v"], e["op1db_dbm"])
            delta = (None if (ref is None or e["op1db_dbm"] is None)
                     else round(e["op1db_dbm"] - ref, 2))
            ws.append([fm, e["vdd_v"], e["op1db_dbm"], e["ip1db_dbm"],
                       e["small_signal_gain_db"], e["idd_max_ma"],
                       _r(psum, 5), delta])
    ws.append([])

    # --- EVM ----------------------------------------------------------
    ws.append(["EVM (best point of the bathtub)"])
    ws[f"A{ws.max_row}"].font = BOLD
    _hrow(ws, ["Freq(MHz)", "BestEVM(%)", "BestEVM(dB)", "@SG(dBm)",
               "NR_Pout@best(dBm)"])
    for d in cond["evm"]:
        m = d["meta"]
        sg = fnum(m.get("best_sg_dbm"))
        pout = column(d, "NR_Pout_dBm")
        pin = column(d, "Pin_dBm")
        at = next((i for i, p in enumerate(pin) if p == sg), None)
        ws.append([_freq_mhz(d), fnum(m.get("best_evm_pct")),
                   fnum(m.get("best_evm_db")), sg,
                   _r(pout[at]) if at is not None else None])
    ws.append([])

    # --- VNA ----------------------------------------------------------
    ws.append([f"VNA gain (S12 + {atten_db:.0f} dB atten + board trace loss)"])
    ws[f"A{ws.max_row}"].font = BOLD
    if not vna:
        ws.append(["(no VNA data)"])
        return
    # 전 51 점을 여기 늘어놓으면 요약이 아니게 된다 -- 1 GHz 격자만 옮기고
    # 전체 곡선은 VNA_Gain 시트에 둔다.
    _hrow(ws, ["Freq(MHz)", "Gain(dB)"])
    for f_hz, g in vna:
        if round(f_hz / 1e9, 6) == round(f_hz / 1e9):
            ws.append([round(f_hz / 1e6, 1), _r(g)])
    ws.append([])
    band = [g for f_hz, g in vna if 27e9 <= f_hz <= 31e9]
    if band:
        _hrow(ws, ["27-31 GHz", "min(dB)", "max(dB)", "peak-to-peak(dB)",
                   "mean(dB)"])
        ws.append(["", _r(min(band)), _r(max(band)),
                   _r(max(band) - min(band)), _r(sum(band) / len(band))])


def _psum_at_op1db(rails, ma, v, vset, pout, vdd, op1db):
    """그 VDD 구간에서 Pout 이 OP1dB 에 가장 가까운 행의 Psum[W]."""
    if op1db is None:
        return None
    best_i, best_d = None, None
    for i, (vv, po) in enumerate(zip(vset, pout)):
        if vv != vdd or po is None:
            continue
        dd = abs(po - op1db)
        if best_d is None or dd < best_d:
            best_i, best_d = i, dd
    return psum_w(rails, ma, v, best_i) if best_i is not None else None


# ---------------------------------------------------------------- charts
def add_vdd_charts(ws, ranges) -> None:
    """주파수마다 1장: Gain vs Pin, VDD 계단이 각 시리즈."""
    freqs = sorted({f for f, _v in ranges})
    for n, f in enumerate(freqs):
        ch = LineChart()
        ch.title = f"Gain vs Pin @ {f/1000:.2f} GHz (per FE1 supply)"
        ch.height, ch.width = 8, 16
        ch.x_axis.title, ch.y_axis.title = "Pin (dBm)", "Gain (dB)"
        ch.x_axis.delete = ch.y_axis.delete = False
        first = None
        for (ff, vv), (s, e) in sorted(ranges.items()):
            if ff != f:
                continue
            ch.append(Series(Reference(ws, min_col=8, min_row=s, max_row=e),
                             title=f"{vv:.1f} V"))
            first = first or (s, e)
        if first:
            ch.set_categories(Reference(ws, min_col=6, min_row=first[0],
                                        max_row=first[1]))
            ws.add_chart(ch, f"{get_column_letter(17)}{2 + n * 17}")


def add_evm_chart(ws, ranges) -> None:
    ch = LineChart()
    ch.title = "EVM bathtub"
    ch.height, ch.width = 8, 16
    ch.x_axis.title, ch.y_axis.title = "Pin (dBm)", "EVM (%)"
    ch.x_axis.delete = ch.y_axis.delete = False
    first = None
    for f, (s, e) in sorted(ranges.items()):
        ch.append(Series(Reference(ws, min_col=9, min_row=s, max_row=e),
                         title=f"{f/1000:.2f} GHz"))
        first = first or (s, e)
    if first:
        ch.set_categories(Reference(ws, min_col=5, min_row=first[0],
                                    max_row=first[1]))
        ws.add_chart(ch, "Q2")


def add_vna_chart(ws, rows) -> None:
    if not rows or not rows[1]:
        return
    s, e = rows
    ch = LineChart()
    ch.title = "VNA gain vs frequency (S12 corrected)"
    ch.height, ch.width = 8, 16
    ch.x_axis.title, ch.y_axis.title = "Frequency (MHz)", "Gain (dB)"
    ch.x_axis.delete = ch.y_axis.delete = False
    ch.append(Series(Reference(ws, min_col=5, min_row=s, max_row=e),
                     title="Gain"))
    ch.set_categories(Reference(ws, min_col=1, min_row=s, max_row=e))
    ws.add_chart(ch, "H2")


# ---------------------------------------------------------------- workbook
def _autosize(ws, limit: int = 60) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is None:
                continue
            widths[c.column] = max(widths.get(c.column, 0),
                                   min(len(str(c.value)), limit))
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w + 2


def build_workbook(cond: dict, out: Path, atten_db: float) -> Path:
    wb = openpyxl.Workbook()
    ws_sum = wb.active
    ws_sum.title = "Summary"
    ws_vdd = wb.create_sheet("VddSensitivity")
    ws_evm = wb.create_sheet("EVM")
    ws_vna = wb.create_sheet("VNA_Gain")

    vdd_ranges = write_vdd(ws_vdd, cond)
    evm_ranges = write_evm(ws_evm, cond)
    vna_rows, vna_corrected = write_vna(ws_vna, cond, atten_db)
    write_summary(ws_sum, cond, vna_corrected, atten_db)

    add_vdd_charts(ws_vdd, vdd_ranges)
    add_evm_chart(ws_evm, evm_ranges)
    add_vna_chart(ws_vna, vna_rows)

    for ws in (ws_vdd, ws_evm, ws_vna):
        ws.freeze_panes = "A2"
    for ws in wb.worksheets:
        _autosize(ws)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def measurement_date(cond) -> str:
    """측정 CSV 파일명에서 YYMMDD 를 뽑는다(예: evm_260902_... -> 260902).

    예전에는 출력 파일 이름에 260821 이 하드코딩돼 있어서, 다른 날 측정한 결과에도
    8월 21일 날짜가 붙었다.
    """
    for group in ("vdd", "evm"):
        for d in cond.get(group) or []:
            m = re.search(r"_(\d{6})_", Path(d["path"]).name)
            if m:
                return m.group(1)
    src = cond.get("vna")
    if src:
        m = re.search(r"_(\d{6})_", Path(src).name)
        if m:
            return m.group(1)
    return datetime.now().strftime("%y%m%d")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    atten = DEFAULT_ATTEN_DB
    conds: list[Path] = []
    out_dir: Path | None = None
    for a in argv:
        if a.startswith("--atten"):
            atten = float(a.split("=", 1)[1]) if "=" in a else atten
        elif a.startswith("--cond="):
            conds.append(Path(a.split("=", 1)[1]))
        elif a.startswith("--out-dir="):
            out_dir = Path(a.split("=", 1)[1])
    if conds:
        # 조건 폴더를 직접 지정 -- 부모 폴더에 다른 자료가 섞여 있어도 되고,
        # 사용자의 폴더 배치를 옮기지 않아도 된다.
        dirs = conds
        base = out_dir or conds[0].parent
    else:
        base = Path(args[0]) if args else DEFAULT_DIR
        if not base.is_dir():
            print(f"input folder not found: {base}")
            return 1
        dirs = sorted(d for d in base.iterdir() if d.is_dir())
        if out_dir:
            base = out_dir
    if not dirs:
        print(f"no condition sub-folders under {base}")
        return 1
    base.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        if not d.is_dir():
            print(f"  skip {d}: not a folder")
            continue
        cond = load_condition(d)
        if not (cond["vdd"] or cond["evm"] or cond["vna"]):
            print(f"  skip {d.name}: no measurement CSVs")
            continue
        codes = bias_codes(d.name)
        label = "_".join(str(c) for c in codes) if codes else d.name.replace(" ", "_")
        out = base / (f"{measurement_date(cond)}_Stampede_TX_Results_"
                      f"{label}.xlsx")
        build_workbook(cond, out, atten)
        print(f"  {d.name}: vdd={len(cond['vdd'])} evm={len(cond['evm'])} "
              f"vna={'yes' if cond['vna'] else 'no'} -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
