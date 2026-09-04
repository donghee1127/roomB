"""RX 측정 CSV -> 정리된 xlsx 후처리 (tidy/long 포맷, 피벗 가능).

out/ 의 측정 CSV(ip1db / gain_index_accuracy common·chan / evm)를 채널별로 모아
한 워크북으로 정리한다. 데이터는 Beam/Channel 컬럼을 붙인 long 포맷으로 쭉 쌓아
엑셀에서 필터·피벗으로 채널을 골라볼 수 있게 한다.

사용:
  python scripts/postprocess_rx.py [입력폴더] [출력.xlsx]
  기본 입력 = "out/Blueway EVB Test Results", 출력 = 그 폴더의 Blueway_RX_Test_Results.xlsx

시트:
  Summary           채널별 핵심 지표 1행
  Linearity         IP1dB sweep (레일 I[mA] + Psum[W]); IP1dB 마커
  GainAccuracy      common/channel 게인 raw (Code/Gain/Ideal/Err)
  GainAcc_ChanCorr  channel(RTPS) 게인을 내림차순 정렬한 보정 곡선 + Ideal
  EVM               EVM bathtub + PAE/efficiency
  TotalPDC          IP1dB 동작점 레일 I[mA] + Psum
  Charts            게인 vs Ideal 직선 비교 그래프

처리:
- 레일 전력 P=V*I, Psum 계산(V 는 거의 고정).
- PSU timeout 으로 전 레일이 0 인 행은 전/후 값으로 선형 보간.
- Ideal 직선: common 0.25 dB/step, channel 0.5 dB/step(datasheet) 기준.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import openpyxl
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.series import SeriesLabel
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

DEFAULT_DIR = Path("out/Blueway EVB Test Results")
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=12)


# ---------------------------------------------------------------- parsing
def parse_csv(path: Path) -> dict:
    meta: dict[str, str] = {}
    summary = ""
    header: list[str] | None = None
    rows: list[list[str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            c0 = row[0]
            if c0.startswith("# meta."):
                k, _, v = c0[len("# meta."):].partition(": ")
                meta[k] = v
            elif c0.startswith("# summary:"):
                summary = c0[len("# summary: "):]
            elif c0.startswith("#"):
                continue
            elif header is None:
                header = row
            else:
                rows.append(row)
    return {"path": path, "meta": meta, "summary": summary,
            "header": header or [], "rows": rows}


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        try:
            return float(int(s, 0))   # hex code (0x..)
        except (TypeError, ValueError):
            return None


def column(d: dict, name: str) -> list:
    h = d["header"]
    if name not in h:
        return []
    i = h.index(name)
    return [fnum(r[i]) if i < len(r) else None for r in d["rows"]]


def rail_names(header: list[str]) -> list[str]:
    return [h[:-2] for h in header if h.endswith("_V")]


def classify(path: Path, meta: dict) -> str:
    n = path.name
    if n.startswith("ip1db"):
        return "linearity"
    if n.startswith("gain_index_accuracy"):
        return "gain_" + (meta.get("axis") or "common")
    if n.startswith("evm"):
        return "evm"
    return "other"


# ---------------------------------------------------------------- numeric helpers
def interp_at(vals: list, idxs: set) -> list:
    """idxs(보간 대상 인덱스)를 그 외 유효값들로 선형보간해 채운다."""
    out = list(vals)
    good = [i for i in range(len(vals))
            if i not in idxs and vals[i] is not None]
    if not good:
        return out
    for i in idxs:
        left = max((g for g in good if g < i), default=None)
        right = min((g for g in good if g > i), default=None)
        if left is None:
            out[i] = out[right]
        elif right is None:
            out[i] = out[left]
        else:
            t = (i - left) / (right - left)
            out[i] = out[left] + (out[right] - out[left]) * t
    return out


def rails_filled(d: dict):
    """레일별 V/mA 시리즈 + timeout(전 레일 0) 행 보간. 반환: rails, mA dict, V dict, timeout set."""
    rails = rail_names(d["header"])
    ma = {r: column(d, f"{r}_mA") for r in rails}
    v = {r: column(d, f"{r}_V") for r in rails}
    n = len(d["rows"])
    timeout = {i for i in range(n)
               if all((ma[r][i] in (0.0, None)) for r in rails)}
    for r in rails:
        ma[r] = interp_at(ma[r], timeout)
        v[r] = interp_at(v[r], timeout)
    return rails, ma, v, timeout


def psum_w(rails, ma, v, i) -> float:
    s = 0.0
    for r in rails:
        if ma[r][i] is not None and v[r][i] is not None:
            s += v[r][i] * ma[r][i] / 1000.0
    return s


def _linfit(xs, ys):
    """단순 최소자승 1차 직선 fit -> (slope, intercept). 점이 부족하면 (0, 평균)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def _range(vals):
    v = [x for x in vals if x is not None]
    return (max(v) - min(v)) if v else None


# ---------------------------------------------------------------- writers
def hrow(ws, names):
    ws.append(names)
    for c in ws[ws.max_row]:
        c.font = BOLD


def write_summary(ws, channels):
    ws.append(["Blueway RX Test Summary"])
    ws["A1"].font = TITLE
    ws.append([])
    hrow(ws, ["Beam", "Channel", "Freq(MHz)", "IP1dB(dBm)", "OP1dB(dBm)",
              "SmallSigGain(dB)", "CommonRange(dB)", "ChanRange(dB)",
              "BestEVM(%)", "BestEVM@SG(dBm)", "PDC@IP1dB(W)"])
    for key in sorted(channels):
        ch = channels[key]
        beam, chan = key.split("_")
        lin, gc, gh, ev = (ch.get("linearity"), ch.get("gain_common"),
                           ch.get("gain_chan"), ch.get("evm"))
        freq = ip1 = op1 = ssg = pdc = None
        if lin:
            f = fnum(lin["meta"].get("freq_hz", "")) or 0
            freq = f / 1e6 if f else None
            ip1 = fnum(lin["meta"].get("ip1db_dbm", ""))
            op1 = fnum(lin["meta"].get("op1db_dbm", ""))
            ssg = fnum(lin["meta"].get("small_signal_gain_db", ""))
            pdc = _pdc_at_ip1db(lin)
        ws.append([beam, chan, _r(freq, 0), _r(ip1), _r(op1), _r(ssg),
                   _r(_range(column(gc, "Gain_dB")) if gc else None),
                   _r(_range(column(gh, "Gain_dB")) if gh else None),
                   _r(fnum(ev["meta"].get("best_evm_pct", "")) if ev else None),
                   _r(fnum(ev["meta"].get("best_sg_dbm", "")) if ev else None),
                   _r(pdc, 4)])


def write_linearity(ws, channels):
    rails = _any_rails(channels, "linearity")
    hrow(ws, ["Beam", "Channel", "Index", "Freq(MHz)", "Pin(dBm)", "Pout(dBm)",
              "Gain(dB)", "Data"] + [f"{r}(mA)" for r in rails] + ["Psum(W)"])
    for key in sorted(channels):
        lin = channels[key].get("linearity")
        if not lin:
            continue
        beam, chan = key.split("_")
        rs, ma, v, timeout = rails_filled(lin)
        pin, pout, gain = (column(lin, "Pin_dBm"), column(lin, "Pout_dBm"),
                           column(lin, "Gain_dB"))
        freq = round((fnum(lin["meta"].get("freq_hz", "")) or 0) / 1e6)
        ip1 = fnum(lin["meta"].get("ip1db_dbm", ""))
        mark = (min(range(len(pin)), key=lambda i: abs((pin[i] or 1e9) - ip1))
                if ip1 is not None and pin else None)
        for i in range(len(lin["rows"])):
            tag = "IP1dB" if i == mark else ("interp" if i in timeout else "")
            row = [beam, chan, i, freq, pin[i], pout[i], gain[i], tag]
            row += [_r(ma[r][i], 1) for r in rails]
            row += [_r(psum_w(rs, ma, v, i), 5)]
            ws.append(row)


def write_gain(ws, channels):
    """common/channel 게인 raw (long). 반환: chart 용 행범위 dict."""
    hrow(ws, ["Beam", "Channel", "Axis", "Code", "Pout(dBm)", "Gain(dB)",
              "Ideal(dB)", "Err(dB)"])
    ranges = {}
    for key in sorted(channels):
        beam, chan = key.split("_")
        for axis, kind, step in (("common", "gain_common", 0.25),
                                 ("channel", "gain_chan", 0.5)):
            d = channels[key].get(kind)
            if not d:
                continue
            tbl = _gain_table(d, step)
            start = ws.max_row + 1
            for code, pout, g, ideal, err in tbl:
                ws.append([beam, chan, axis, code, pout, g, ideal, err])
            ranges[(key, axis)] = (start, ws.max_row)
    return ranges


def write_gain_corr(ws, channels):
    """channel(RTPS) 게인을 내림차순 정렬한 보정 곡선 + Ideal. 반환: 행범위 dict."""
    hrow(ws, ["Beam", "Channel", "Rank", "OrigCode", "GainSorted(dB)",
              "Ideal(dB)", "Err(dB)"])
    ranges = {}
    for key in sorted(channels):
        d = channels[key].get("gain_chan")
        if not d:
            continue
        beam, chan = key.split("_")
        codes = [int(c) if c is not None else None for c in column(d, "channel_code")]
        gain = column(d, "Gain_dB")
        pairs = sorted([(g, c) for g, c in zip(gain, codes) if g is not None],
                       key=lambda x: x[0], reverse=True)
        # Ideal = sorted gain 에 대한 best-fit(최소자승) 직선. Err = 측정 - fit.
        ys = [g for g, _ in pairs]
        slope, intercept = _linfit(list(range(len(ys))), ys)
        start = ws.max_row + 1
        for rank, (g, c) in enumerate(pairs):
            ideal = intercept + slope * rank
            ws.append([beam, chan, rank, c, _r(g), _r(ideal), _r(g - ideal)])
        ranges[key] = (start, ws.max_row)
    return ranges


def write_evm(ws, channels):
    rails = _any_rails(channels, "evm")
    hrow(ws, ["Beam", "Channel", "Index", "Pin(dBm)", "NR_Pout(dBm)", "Gain(dB)",
              "EVM(dB)", "EVM(%)"] + [f"{r}(mA)" for r in rails] + ["Psum(W)"])
    for key in sorted(channels):
        ev = channels[key].get("evm")
        if not ev:
            continue
        beam, chan = key.split("_")
        rs, ma, v, _to = rails_filled(ev)
        pin, pout = column(ev, "Pin_dBm"), column(ev, "NR_Pout_dBm")
        evmd, evmp = column(ev, "EVM_dB"), column(ev, "EVM_pct")
        for i in range(len(ev["rows"])):
            g = (pout[i] - pin[i]) if (pout[i] is not None and pin[i] is not None) else None
            row = [beam, chan, i, pin[i], pout[i], _r(g), evmd[i], evmp[i]]
            row += [_r(ma[r][i], 1) for r in rails]
            row += [_r(psum_w(rs, ma, v, i), 5)]
            ws.append(row)


def write_evm_pivot(ws, channels):
    """EVM bathtub 피벗 + 드롭다운 선택 차트.

    와이드 표(Pin x 채널 EVM%) + 드롭다운(16채널) -> INDEX/MATCH 헬퍼 -> 라인차트.
    드롭다운을 바꾸면 그 beam/channel 의 bathtub 가 그려진다. (openpyxl 은 네이티브
    PivotChart 를 못 만들어 동등 기능을 동적 차트로 구현; 이 와이드 표로 Excel
    네이티브 PivotChart 도 직접 만들 수 있다.)
    """
    keys = sorted(channels)
    data, pins = {}, set()
    for key in keys:
        ev = channels[key].get("evm")
        if not ev:
            continue
        pin, evp = column(ev, "Pin_dBm"), column(ev, "EVM_pct")
        m = {p: e for p, e in zip(pin, evp) if p is not None and e is not None}
        if m:
            data[key] = m
            pins |= set(m)
    keys = [k for k in keys if k in data]
    if not keys:
        return
    pin_axis = sorted(pins)
    n = len(pin_axis)
    # --- 와이드 피벗 표: A=Pin, B.. = 채널별 EVM% ---
    ws.cell(1, 1, "Pin(dBm)").font = BOLD
    for j, key in enumerate(keys, start=2):
        ws.cell(1, j, key).font = BOLD
    for i, p in enumerate(pin_axis, start=2):
        ws.cell(i, 1, p)
        for j, key in enumerate(keys, start=2):
            val = data[key].get(p)
            if val is not None:
                ws.cell(i, j, val)
    last = 1 + len(keys)                       # 마지막 채널 열
    first_l, last_l = get_column_letter(2), get_column_letter(last)
    # --- 드롭다운(채널 선택) ---
    sel_col = last + 2
    ws.cell(1, sel_col, "Channel:").font = BOLD
    sel = ws.cell(1, sel_col + 1, keys[0])     # 선택 셀
    dv = DataValidation(type="list", formula1='"' + ",".join(keys) + '"',
                        allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(sel)
    sel_addr = f"${get_column_letter(sel_col + 1)}$1"
    # --- 헬퍼 열: 선택 채널의 EVM% (INDEX/MATCH) ---
    hcol = sel_col + 3
    hL = get_column_letter(hcol)
    ws.cell(1, hcol, "Selected EVM(%)").font = BOLD
    for i in range(2, n + 2):
        ws.cell(i, hcol,
                f"=IFERROR(INDEX({first_l}{i}:{last_l}{i},"
                f"MATCH({sel_addr},${first_l}$1:${last_l}$1,0)),\"\")")
    # --- 차트: x=Pin, y=선택 EVM% ---
    ch = LineChart()
    ch.title = "EVM bathtub (pick channel in the dropdown)"
    ch.height, ch.width = 9, 16
    ch.x_axis.title, ch.y_axis.title = "Pin (dBm)", "EVM (%)"
    ch.x_axis.delete = ch.y_axis.delete = False
    yref = Reference(ws, min_col=hcol, min_row=2, max_row=n + 1)
    ch.add_data(yref, titles_from_data=False)
    ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n + 1))
    ch.series[0].tx = SeriesLabel(v="EVM %")
    ws.add_chart(ch, f"{get_column_letter(sel_col)}3")


def write_total_pdc(ws, channels):
    rails = _any_rails(channels, "linearity")
    hrow(ws, ["Beam", "Channel", "Pin@IP1dB(dBm)"]
             + [f"{r}(mA)" for r in rails] + ["Psum(W)"])
    for key in sorted(channels):
        lin = channels[key].get("linearity")
        if not lin:
            continue
        beam, chan = key.split("_")
        rs, ma, v, _to = rails_filled(lin)
        pin = column(lin, "Pin_dBm")
        ip1 = fnum(lin["meta"].get("ip1db_dbm", ""))
        mark = (min(range(len(pin)), key=lambda i: abs((pin[i] or 1e9) - ip1))
                if ip1 is not None and pin else 0)
        row = [beam, chan, _r(pin[mark])]
        row += [_r(ma[r][mark], 1) for r in rails]
        row += [_r(psum_w(rs, ma, v, mark), 5)]
        ws.append(row)


def write_charts(ws, gain_ws, gain_ranges, corr_ws, corr_ranges):
    """게인 vs Ideal 직선 비교 그래프(채널별). common(raw) + channel(보정)."""
    ws["A1"] = "Gain vs ideal-line comparison (per channel)"
    ws["A1"].font = TITLE
    # 왼쪽 열(A): common(raw) 게인 vs ideal. 오른쪽 열(J): channel 보정(sorted) vs ideal.
    row = 3
    for (key, axis), (s, e) in sorted(gain_ranges.items()):
        if axis != "common":
            continue
        _line_chart(ws, gain_ws, f"{key} common gain vs ideal",
                    code_col=4, ycols=[(6, "Gain"), (7, "Ideal")],
                    s=s, e=e, anchor=f"A{row}")
        row += 16
    row = 3
    for key, (s, e) in sorted(corr_ranges.items()):
        _line_chart(ws, corr_ws, f"{key} channel gain (sorted) vs ideal",
                    code_col=3, ycols=[(5, "GainSorted"), (6, "Ideal")],
                    s=s, e=e, anchor=f"J{row}")
        row += 16


def _line_chart(charts_ws, data_ws, title, code_col, ycols, s, e, anchor):
    ch = LineChart()
    ch.title = title
    ch.height, ch.width = 7.5, 14
    ch.x_axis.title, ch.y_axis.title = "code", "gain (dB)"
    ch.x_axis.delete = ch.y_axis.delete = False
    cols = [c for c, _ in ycols]
    data = Reference(data_ws, min_col=min(cols), max_col=max(cols),
                     min_row=s, max_row=e)
    ch.add_data(data, titles_from_data=False)   # 인접 열 -> 열마다 1 series
    ch.set_categories(Reference(data_ws, min_col=code_col, min_row=s, max_row=e))
    for i, (_c, name) in enumerate(ycols):
        if i < len(ch.series):
            ch.series[i].tx = SeriesLabel(v=name)
    charts_ws.add_chart(ch, anchor)


# ---------------------------------------------------------------- small helpers
def _gain_table(d, step):
    cc, hc = column(d, "common_code"), column(d, "channel_code")
    use = "channel_code" if len({x for x in hc if x is not None}) > 1 else "common_code"
    codes = column(d, use)
    pout, gain = column(d, "Pout_dBm"), column(d, "Gain_dB")
    g0 = gain[0] if gain else None
    out = []
    for i in range(len(d["rows"])):
        ideal = (g0 - step * i) if g0 is not None else None
        err = (gain[i] - ideal) if (gain[i] is not None and ideal is not None) else None
        out.append([int(codes[i]) if codes[i] is not None else i,
                    pout[i], gain[i], _r(ideal), _r(err)])
    return out


def _pdc_at_ip1db(lin):
    rs, ma, v, _to = rails_filled(lin)
    pin = column(lin, "Pin_dBm")
    ip1 = fnum(lin["meta"].get("ip1db_dbm", ""))
    if not pin or ip1 is None:
        return None
    mark = min(range(len(pin)), key=lambda i: abs((pin[i] or 1e9) - ip1))
    return psum_w(rs, ma, v, mark)


def _any_rails(channels, kind):
    for ch in channels.values():
        if ch.get(kind):
            return rail_names(ch[kind]["header"])
    return []


# ---------------------------------------------------------------- main
def main(argv):
    in_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT_DIR
    out_path = (Path(argv[2]) if len(argv) > 2
                else in_dir / "Blueway_RX_Test_Results.xlsx")
    files = sorted(in_dir.glob("*.csv"))
    if not files:
        print(f"no CSV found in {in_dir}")
        return 1

    channels: dict[str, dict] = {}
    for path in files:
        d = parse_csv(path)
        kind = classify(path, d["meta"])
        key = f"{(d['meta'].get('beam') or 'Bx').upper()}_" \
              f"{(d['meta'].get('channel') or 'CHx').upper()}"
        channels.setdefault(key, {})[kind] = d
        print(f"  {path.name}  ->  {key} / {kind}")

    wb = openpyxl.Workbook()
    write_summary(wb.active, channels)
    wb.active.title = "Summary"
    write_linearity(wb.create_sheet("Linearity"), channels)
    gain_ws = wb.create_sheet("GainAccuracy")
    gain_ranges = write_gain(gain_ws, channels)
    corr_ws = wb.create_sheet("GainAcc_ChanCorr")
    corr_ranges = write_gain_corr(corr_ws, channels)
    write_evm(wb.create_sheet("EVM"), channels)
    write_evm_pivot(wb.create_sheet("EVM_Bathtub"), channels)
    write_total_pdc(wb.create_sheet("TotalPDC"), channels)
    write_charts(wb.create_sheet("Charts"), gain_ws, gain_ranges,
                 corr_ws, corr_ranges)
    try:
        wb.save(out_path)
    except PermissionError:
        print(f"\nERROR: cannot write {out_path}\n"
              "  -> the file is open in Excel. Close it and re-run.")
        return 2
    print(f"\nwrote {out_path}  ({len(channels)} channels: {', '.join(sorted(channels))})")
    print(f"  charts on the 'Charts' sheet ({2 * len(channels)}: common + "
          "channel-corrected per channel)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
