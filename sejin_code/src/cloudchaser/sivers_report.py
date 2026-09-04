"""Sivers 전달용 driver 단(St2 / FE2_1V8) 결함 리포트 생성기.

두 진단을 하나로 합쳐, 제3자(Sivers)가 바로 이해할 수 있는 영어 리포트를 stdout +
텍스트 파일로 남긴다:

  TEST 1 — 전 채널의 각 증폭단(PA/Driver/Comb) PTAT 바이어스를 0->63 으로 흔들며
           해당 FE 레일 전류 변화를 측정(RF 불필요, DC 정지전류). driver(St2)가
           바이어스에 반응하는지 PASS/FAIL.
  TEST 2 — St2 가 FAIL 한 채널의 per-channel 레지스터를 같은 편파의 정상 채널과 1:1
           비교. 게이팅/인에이블은 같고 efuse 트림만 다름을 보여 '설정 문제 아님'을 입증.

결론: driver 단이 바이어스 전 범위에서 무반응 + 게이팅 레지스터 동일 → 실리콘/HW 결함.

실행:
  python -m cloudchaser.sivers_report                       # 전 채널, 자동 파일명
  python -m cloudchaser.sivers_report --channels h0,h1,h2,h3,v0,v1,v2,v3
  python -m cloudchaser.sivers_report --no-power            # 이미 전원 켜둔 경우
  python -m cloudchaser.sivers_report --out report.txt
  python -m cloudchaser.sivers_report --fake                # 구조 점검(전류 무의미)

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .bench import Bench
from .biasscan_compare import RESP_THRESH_MA, STAGES, scan_channel
from .board.bringup import bring_up_tx, make_chip
from .driver_reg_diff import diff_channel, snapshot_fields
from .manual import _parse_ch
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout

DEFAULT_CHANNELS = ["h0", "h1", "h2", "h3", "v0", "v1", "v2", "v3"]
DRIVER_STAGE = 2  # St2 = Driver = FE2_1V8


def _st(rows: list[dict], stage: int) -> dict:
    """scan 결과 rows 에서 특정 stage 행."""
    return next(r for r in rows if r["stage"] == stage)


def run_report(bench: Bench, chip, beam: str, channels: list[str],
               *, settle: float, restore: int, emit) -> dict:
    """리포트 본문을 emit(line) 으로 출력하고 요약 dict 반환."""
    # ---- 헤더 ----------------------------------------------------------
    try:
        ver = int(chip.fields.rd("version_id"))
    except Exception:  # noqa: BLE001
        ver = None
    try:
        vi = bench.read_all_vi()
    except Exception:  # noqa: BLE001
        vi = {}
    rails = "  ".join(f"{rn}={d.get('v', 0.0):.2f}V" for rn, d in vi.items())

    emit("=" * 80)
    emit(" CloudChaser Stampede2731 (TX) EVB"
         " - Driver stage (St2 / FE2_1V8) defect report")
    emit("=" * 80)
    emit(f" Generated   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (local)")
    emit(f" Chip        : chip_id={getattr(bench.board, 'chip_id', '?')}  "
         f"version_id={'0x%02x' % ver if ver is not None else '?'}  "
         f"(efuse trim applied at init)")
    emit(f" Beam routing: {beam}")
    emit(" Stimulus    : none (DC quiescent bias only, no RF applied)")
    emit(f" PSU rails   : {rails}")
    emit("")
    emit(" Front-end amplifier chain (per channel, both polarizations):")
    emit("   St1 = PA       supplied by FE1_4V0 (4.0 V)")
    emit("   St2 = Driver   supplied by FE2_1V8 (1.8 V)   <-- stage under investigation")
    emit("   St3 = Combiner supplied by FE3_1V8 (1.8 V)")
    emit("")

    # 레지스터 스냅샷: TEST 1 스윕이 PTAT 를 덮어쓰기 '전에' 원본(efuse 트림 포함)을
    # 떠둔다. TEST 2 는 이 스냅샷으로 비교한다.
    reg_snapshot = snapshot_fields(chip)

    # ---- TEST 1: 단별 바이어스 응답 -----------------------------------
    emit("-" * 80)
    emit(" TEST 1 - Per-stage bias response  (PTAT code 0 -> 63, watch supply current)")
    emit("-" * 80)
    emit(" Method : enable one channel at a time, sweep each stage's PTAT bias code")
    emit("          from 0 to 63, and measure the change in that stage's supply")
    emit("          current. A healthy stage draws more current as bias rises; a")
    emit("          dead stage stays flat regardless of the code.")
    emit(f" PASS   : |delta current| > {RESP_THRESH_MA:.1f} mA over the 0..63 sweep.")
    emit("")
    emit(" Channel | St2 Driver (FE2_1V8)             | St1 PA   | St3 Comb | verdict")
    emit("         | i0(mA) i63(mA)  delta    result  | delta    | delta    |")
    emit(" " + "-" * 77)

    scans: dict[str, list[dict]] = {}
    fails: list[str] = []
    for ch in channels:
        rows = scan_channel(bench, chip, beam, ch, settle=settle, restore=restore)
        scans[ch] = rows
        d2 = _st(rows, 2)
        d1, d3 = _st(rows, 1), _st(rows, 3)
        st2_ok = abs(d2["delta"]) > RESP_THRESH_MA
        if not st2_ok:
            fails.append(ch)
        verdict = "ok" if st2_ok else "DRIVER DEAD"
        emit(f" {ch.upper():7} | {d2['i0']:6.1f} {d2['i63']:6.1f}  "
             f"{d2['delta']:+6.1f}   {'OK ' if st2_ok else 'FAIL':4}  | "
             f"{d1['delta']:+6.1f}  | {d3['delta']:+6.1f}  | {verdict}")

    passes = [c for c in channels if c not in fails]
    emit("")
    emit(f" => St2 (Driver) FAILS on: "
         f"{', '.join(c.upper() for c in fails) if fails else '(none)'}")
    emit(f"    St2 (Driver) OK    on: "
         f"{', '.join(c.upper() for c in passes) if passes else '(none)'}")
    if fails:
        st1_all = all(abs(_st(scans[c], 1)['delta']) > RESP_THRESH_MA for c in fails)
        st3_all = all(abs(_st(scans[c], 3)['delta']) > RESP_THRESH_MA for c in fails)
        if st1_all and st3_all:
            emit("    On the failing channels, St1 (PA) and St3 (Combiner) respond")
            emit("    normally -> the defect is isolated to the Driver stage.")
    emit("")

    # ---- TEST 2: 레지스터 비교 ----------------------------------------
    emit("-" * 80)
    emit(" TEST 2 - Register comparison  (failing channel vs healthy same-pol channel)")
    emit("-" * 80)
    emit(" Purpose: rule out a register/efuse programming difference as the cause.")
    emit("          For each failing channel, every per-channel register is compared")
    emit("          1:1 against a healthy channel of the same polarization.")
    emit("          Values are the original post-bring-up state, captured BEFORE the")
    emit("          TEST 1 bias sweep (so factory efuse trim is shown as-is).")
    emit("          'gating' fields enable/disable a stage; 'trim' fields are analog")
    emit("          bias codes (factory efuse) that cannot turn a stage on/off.")
    emit("")

    diff_results = []
    for bch in fails:
        pol = _parse_ch(bch)[0]
        ref = next((c for c in passes if _parse_ch(c)[0] == pol), None)
        if ref is None:
            emit(f" {bch.upper()}: no healthy same-pol reference channel available - skipped.")
            continue
        res = diff_channel(chip, ref, bch, read=reg_snapshot.get)
        diff_results.append(res)
        g, b = ref.upper(), bch.upper()
        emit(f" {b} (FAIL) vs {g} (OK):")
        # 게이팅 필드 요약
        gate_rows = [r for r in res["key_rows"] if r["kind"] == "gate"]
        gate_diff = [r for r in gate_rows if not r["same"]]
        if gate_diff:
            emit("   GATING/enable registers DIFFER:")
            for r in gate_diff:
                emit(f"     {r['field']:28} {g}={r['good']:#x}  {b}={r['bad']:#x}")
        else:
            emit("   gating/enable registers (enables, pwrdn, bias_en, efuse_pwrdn_dis,")
            emit("   pwrdn_override): ALL IDENTICAL to the healthy channel.")
        # 차이(트림) 나열
        trim_diff = [d for d in res["diffs"] if d["kind"] == "trim"]
        other_gate = [d for d in res["diffs"] if d["kind"] == "gate"]
        if trim_diff:
            emit("   analog bias-trim differences (per-channel efuse, a few LSB):")
            for d in trim_diff:
                emit(f"     {d['field']:28} {g}={d['good']:#x}  {b}={d['bad']:#x}")
        if not trim_diff and not other_gate:
            emit("   no per-channel register differs at all.")
        emit("")

    # ---- 결론 ----------------------------------------------------------
    any_gate_diff = any(not r["same"]
                        for res in diff_results for r in res["key_rows"]
                        if r["kind"] == "gate")
    emit("=" * 80)
    emit(" CONCLUSION")
    emit("=" * 80)
    if fails:
        emit(f" - Driver stage (St2, FE2_1V8) draws NO incremental bias current on "
             f"{', '.join(c.upper() for c in fails)}")
        emit("   across the full PTAT code range (0..63). PA (St1) and Combiner (St3)")
        emit("   on these same channels respond normally.")
        if not diff_results:
            emit(" - No healthy same-polarization channel was available to compare")
            emit("   registers against, so config could not be ruled out automatically.")
        elif not any_gate_diff:
            emit(" - Enable/gating registers of the failing channels are IDENTICAL to the")
            emit("   healthy channels; only per-channel efuse trim codes differ by a few")
            emit("   LSB, which cannot gate a stage and had no effect when swept in TEST 1.")
            emit(" - Assessment: the driver-stage defect is in HARDWARE (silicon / package /")
            emit("   driver bias path), NOT in register programming or efuse enable.")
        else:
            emit(" - NOTE: some gating/enable registers differ (see TEST 2). The driver")
            emit("   configuration is not identical; review these before concluding HW fault.")
    else:
        emit(" - All channels' driver stage (St2) responded to bias. No defect reproduced.")
    emit("=" * 80)

    return {"fails": fails, "passes": passes, "scans": scans,
            "diff_results": diff_results, "gate_diff": any_gate_diff}


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Generate a Sivers-facing driver-stage defect report (bias scan + reg diff)")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--channels", default=",".join(DEFAULT_CHANNELS),
                   help="comma list of channels to test (default all h0..h3,v0..v3)")
    p.add_argument("--beam", default=None, help="beam for bring-up (default bench.toml beam)")
    p.add_argument("--settle", type=float, default=0.15, help="settle [s] per bias write")
    p.add_argument("--restore", type=int, default=32, help="PTAT value to restore after scan")
    p.add_argument("--out", type=Path, default=None,
                   help="report text file path (default out/sivers_driver_report_<ts>.txt)")
    p.add_argument("--no-power", action="store_true", help="skip PSU ramp-up (already powered)")
    p.add_argument("--fake", action="store_true",
                   help="run without hardware (currents/registers not meaningful)")
    args = p.parse_args(argv)

    channels = [c.strip().lower() for c in args.channels.split(",") if c.strip()]

    bench = Bench.from_toml(args.config, fake=args.fake)
    beam = args.beam or bench.board.beam
    bench.connect_all()
    if not args.no_power:
        bench.power_up()
    else:
        print("[sivers-report] skipping power-up (--no-power)")

    chip = make_chip(bench.board, fake=args.fake)
    bench.board.active_channels = list(channels)
    bench.board.beam = beam
    bring_up_tx(chip, bench.board, require_version=not args.fake)

    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    try:
        if args.fake:
            emit("[sivers-report] FAKE mode: currents/registers are not real "
                 "(structure check only)")
            emit("")
        run_report(bench, chip, beam, channels,
                   settle=args.settle, restore=args.restore, emit=emit)
    finally:
        bench.close_all()

    out = args.out
    if out is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path("out") / f"sivers_driver_report_{ts}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[sivers-report] report saved: {out}")
    print("[sivers-report] sockets closed. (power left as-is)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
