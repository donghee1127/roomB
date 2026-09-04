"""정상 채널 vs 불량 채널 bias-scan 비교 (RF 불필요, DC 전류만).

목적: 한 정상 채널과 하나 이상의 불량 채널에 대해 각 증폭단(PA/Driver/Combiner)의
PTAT 바이어스를 0->63 으로 흔들며 해당 FE 레일 전류 변화(delta)를 측정하고, 정상/불량을
나란히 비교한다. 어떤 단이 죽었는지(전류가 안 변하는 단)를 채널별로 한눈에 본다.

- FE1_4V0 = PA 4V, FE2_1V8 = Driver 1.8V, FE3_1V8 = Comb 1.8V (manual.biasscan 과 동일).
- 보드에 SG/SA 를 연결할 필요 없음 — 순수 정지전류(quiescent bias)만 본다.
- FE 레일은 4채널 공유라, 한 번에 한 채널만 ON 하고(chan() 과 동일 셋업) 측정한다.

실행:
  python -m cloudchaser.biasscan_compare                       # good=h1, bad=h0,v0,h2
  python -m cloudchaser.biasscan_compare --good h1 --bad h0,h2
  python -m cloudchaser.biasscan_compare --no-power            # 이미 전원 켜둔 경우
  python -m cloudchaser.biasscan_compare --csv out/biasscan.csv
  python -m cloudchaser.biasscan_compare --fake                # 구조 점검(전류는 안 변함)

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .bench import Bench
from .board.bringup import bring_up_tx, make_chip
from .board.firehawk import FH, fe_row
from .board.gain_map import setup_single_channel
from .manual import _parse_ch
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout

# 증폭단 (stage 번호, FE 레일, 표시 이름). manual.biasscan 과 동일.
STAGES = [(1, "FE1_4V0", "PA"),
          (2, "FE2_1V8", "Driver"),
          (3, "FE3_1V8", "Comb")]
# 이 값보다 전류 변화(delta)가 크면 그 단이 '살아있다'고 본다(biasscan 과 동일 기준).
RESP_THRESH_MA = 2.0


def _engine(bench: Bench, chip) -> FH:
    """raw 레지스터 엔진을 얻는다. bring_up_tx 가 chip._fh 를 남기지만, bring-up 을
    건너뛴 호출자(테스트 등)를 위해 bare FH 로 폴백한다(Ruling 1 과 동일 패턴)."""
    return getattr(chip, "_fh", None) or FH(chip, getattr(bench.board, "chip_id", 0))


def _setup_single(fh: FH, beam: str, ch: str) -> None:
    """채널 ch 하나만 측정 가능 상태로. gain_map 의 공용 구현으로 위임한다
    (bias_match 와 같은 셋업을 쓰기 위해 Task 2 에서 승격)."""
    setup_single_channel(fh, beam, ch)


def scan_channel(bench: Bench, chip, beam: str, ch: str,
                 *, settle: float, restore: int) -> list[dict]:
    """채널 ch 의 각 단 PTAT 를 0->63 흔들며 FE 레일 전류 delta 측정.

    반환: [{stage, rail, desc, i0, i63, delta}, ...] (단별 1개).
    """
    fh = _engine(bench, chip)
    _setup_single(fh, beam, ch)
    time.sleep(settle)
    pol, idx = _parse_ch(ch)
    row = fe_row(idx, pol)     # FE bias 8x5 행 인덱스 (H=2i, V=2i+1)
    out: list[dict] = []
    for st, rail, desc in STAGES:
        col = st - 1           # 열 = [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS]
        name = f"ch{idx}_{pol}_ptat_st{st}"
        try:
            bias = fh.get_fe_bias()
            bias[row][col] = 0
            fh.set_fe_bias(bias)
            time.sleep(settle)
            i0 = bench.read_all_vi()[rail]["i"] * 1000
            bias[row][col] = 63
            fh.set_fe_bias(bias)
            time.sleep(settle)
            i63 = bench.read_all_vi()[rail]["i"] * 1000
            bias[row][col] = int(restore)   # 중간값으로 복귀
            fh.set_fe_bias(bias)
            out.append({"stage": st, "rail": rail, "desc": desc,
                        "i0": i0, "i63": i63, "delta": i63 - i0})
        except Exception as e:  # noqa: BLE001
            print(f"    St{st} {name}: {type(e).__name__}: {e}")
            out.append({"stage": st, "rail": rail, "desc": desc,
                        "i0": float("nan"), "i63": float("nan"),
                        "delta": float("nan")})
    return out


def _responds(delta: float) -> bool:
    return delta == delta and abs(delta) > RESP_THRESH_MA  # NaN-safe


def _print_channel(ch: str, label: str, rows: list[dict]) -> None:
    print(f"\nChannel {ch.upper()} ({label}):")
    for r in rows:
        flag = "OK" if _responds(r["delta"]) else "** NO RESPONSE **"
        print(f"  St{r['stage']} {r['desc']:7} {r['rail']}: "
              f"{r['i0']:6.1f} -> {r['i63']:6.1f} mA   d={r['delta']:+6.1f}   {flag}")


def _print_comparison(good_ch: str, good: list[dict],
                      bads: list[tuple[str, list[dict]]]) -> None:
    """단별로 good delta vs 각 bad delta 를 나란히 + verdict."""
    print("\n=== Comparison: PTAT 0->63 rail-current delta (mA) ===")
    header = f"{'Stage':10} {'Rail':9} {good_ch.upper()+'(good)':>11}"
    for bch, _ in bads:
        header += f" {bch.upper()+'(bad)':>11}"
    header += "   verdict"
    print(header)
    for i, (st, rail, desc) in enumerate(STAGES):
        g = good[i]["delta"]
        line = f"St{st} {desc:7} {rail:9} {g:>+11.1f}"
        dead_on = []
        for bch, brows in bads:
            d = brows[i]["delta"]
            mark = ""
            if _responds(g) and not _responds(d):
                mark = " DEAD"
                dead_on.append(bch.upper())
            line += f" {d:>+10.1f}{mark}"
        if dead_on:
            verdict = f"  <-- {desc} dead on {', '.join(dead_on)}"
        elif not _responds(g):
            verdict = "  (good ch also flat — check setup)"
        else:
            verdict = "  ok everywhere"
        print(line + verdict)


def _write_csv(path: Path, good_ch: str, good: list[dict],
               bads: list[tuple[str, list[dict]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["channel,role,stage,desc,rail,i0_mA,i63_mA,delta_mA,responds"]
    for ch, role, rows in [(good_ch, "good", good)] + \
            [(b, "bad", r) for b, r in bads]:
        for r in rows:
            lines.append(f"{ch.upper()},{role},{r['stage']},{r['desc']},{r['rail']},"
                         f"{r['i0']:.1f},{r['i63']:.1f},{r['delta']:.1f},"
                         f"{int(_responds(r['delta']))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[biasscan-compare] CSV written: {path}")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Compare per-stage bias-scan current (good vs bad channels), RF not needed")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--good", default="h1", help="known-good channel (default h1)")
    p.add_argument("--bad", default="h0,v0,h2",
                   help="comma list of suspect channels (default h0,v0,h2)")
    p.add_argument("--beam", default=None, help="beam to route to (default bench.toml beam)")
    p.add_argument("--settle", type=float, default=0.15, help="settle [s] per bias write")
    p.add_argument("--restore", type=int, default=32, help="PTAT value to restore after scan")
    p.add_argument("--csv", type=Path, default=None, help="optional CSV output path")
    p.add_argument("--no-power", action="store_true", help="skip PSU ramp-up (already powered)")
    p.add_argument("--fake", action="store_true",
                   help="run without hardware (currents won't move — structure check only)")
    args = p.parse_args(argv)

    good_ch = args.good.strip().lower()
    bad_chs = [c.strip().lower() for c in args.bad.split(",") if c.strip()]
    all_chs = [good_ch] + bad_chs

    bench = Bench.from_toml(args.config, fake=args.fake)
    beam = args.beam or bench.board.beam
    bench.connect_all()
    if not args.no_power:
        bench.power_up()
    else:
        print("[biasscan-compare] skipping power-up (--no-power)")

    chip = make_chip(bench.board, fake=args.fake)
    # 관여하는 채널들로 표준 bring-up(efuse/기본 바이어스 적용) — 그 뒤 채널별 단독 셋업.
    bench.board.active_channels = all_chs
    bench.board.beam = beam
    bring_up_tx(chip, bench.board, require_version=not args.fake)

    print(f"\n=== Bias scan compare ===  beam={beam}  settle={args.settle}s  "
          f"restore={args.restore}")
    print(f"good={good_ch.upper()}  bad={','.join(c.upper() for c in bad_chs)}")
    if args.fake:
        print("[biasscan-compare] FAKE mode: rail current is static, deltas ~0 "
              "(structure check only)")

    try:
        good_rows = scan_channel(bench, chip, beam, good_ch,
                                 settle=args.settle, restore=args.restore)
        _print_channel(good_ch, "GOOD", good_rows)
        bads: list[tuple[str, list[dict]]] = []
        for bch in bad_chs:
            rows = scan_channel(bench, chip, beam, bch,
                                settle=args.settle, restore=args.restore)
            _print_channel(bch, "BAD?", rows)
            bads.append((bch, rows))
        _print_comparison(good_ch, good_rows, bads)
        if args.csv:
            _write_csv(args.csv, good_ch, good_rows, bads)
    finally:
        bench.close_all()
        print("\n[biasscan-compare] sockets closed. (power left as-is)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
