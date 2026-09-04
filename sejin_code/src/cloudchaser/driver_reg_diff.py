"""정상 채널 vs 불량 채널 driver(및 per-channel) 레지스터 덤프·diff.

목적: biasscan 으로 driver 단(St2)이 죽은 게 확인된 뒤, 그게 '레지스터/efuse 설정 차이'
때문인지 '실리콘/패키지 하드웨어 결함'인지 가른다. 같은 편파의 정상 채널을 기준(ref)으로
불량 채널의 per-channel 레지스터를 전부 떠서 값이 다른 필드를 찾는다.

  - 차이 필드가 driver 바이어스(ptat_st2/ctat/enables/pwrdn/bias_en/efuse)에 있으면
    -> 설정 문제 가능성(코드/efuse 가 다르게 프로그래밍됨).
  - 전 필드가 동일하면 -> 설정은 같은데 동작만 죽은 것 -> 실리콘/HW 결함 확정.

비교 방식: 필드명의 채널 토큰만 치환(ch{bad}->ch{good})해 같은 의미의 필드끼리 1:1 비교.
편파(h/v)는 같은 편파 ref 끼리만 비교한다(편파 고유차를 결함으로 오인하지 않게).

RF 불필요. 단, efuse 가 반영된 '동작 상태'를 보려면 전원 ON + bring-up 후 떠야 하므로
기본으로 전원 인가 후 읽는다(이미 켜져 있으면 --no-power).

실행:
  python -m cloudchaser.driver_reg_diff                          # good=h1,v1  bad=h0,v0,h2
  python -m cloudchaser.driver_reg_diff --good h1,v1 --bad h0,h2
  python -m cloudchaser.driver_reg_diff --no-power --csv out/regdiff.csv
  python -m cloudchaser.driver_reg_diff --fake                   # 구조 점검(값은 무의미)

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .bench import Bench
from .board.bringup import bring_up_tx, make_chip
from .manual import _parse_ch
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout

# 포커스해서 항상 보여줄 driver/bias 핵심 필드(label, template, kind).
#   kind="gate" : 단을 켜고 끄는 게이팅/인에이블 필드(다르면 진짜 config 문제 가능).
#   kind="trim" : 채널별 아날로그 트림 코드(efuse). 단을 on/off 하지 못하므로,
#                 몇 LSB 차이는 정상 efuse 스프레드 — 죽은 원인이 될 수 없다.
# '*' 가 붙은 것이 driver 단(St2) 직접 관련.
KEY_FIELDS = [
    ("st1 PA",        "d2a_ch{i}_{pol}_ptat_st1",   "trim"),
    ("st2 DRV *",     "d2a_ch{i}_{pol}_ptat_st2",   "trim"),
    ("st3 Comb",      "d2a_ch{i}_{pol}_ptat_st3",   "trim"),
    ("ctat",          "d2a_ch{i}_{pol}_ctat",       "trim"),
    ("enables",       "ch{i}_{pol}_enables",        "gate"),
    ("pwrdn",         "ch{i}_{pol}_pwrdn",          "gate"),
    ("pd_en",         "ch{i}_{pol}_pd_en",          "gate"),
    ("bias_en",       "ch{i}_bias_en",              "gate"),
    ("efuse_pd_dis",  "ch{i}_efuse_pwrdn_dis",      "gate"),
    ("pwrdn_overr",   "ch{i}_pwrdn_override",       "gate"),
]

# 아날로그 트림(켜고 끄지 못하는 캘리브레이션) 으로 분류할 필드명 패턴.
_TRIM_PAT = re.compile(r"ptat|ctat|cbias|captune|attn_cal|cal_freq")


def _is_gate(field: str) -> bool:
    """게이팅/인에이블 필드(=다르면 단을 죽일 수 있는)면 True, 트림이면 False."""
    return not _TRIM_PAT.search(field)


def _all_field_names(chip) -> list[str]:
    """레지스터맵의 전체 필드 이름 목록(벤더 FieldBlock 은 dir() 로 필드명을 노출)."""
    return [n for n in dir(chip.fields.fields) if not n.startswith("_")]


def _belongs(name: str, idx: int, pol: str) -> bool:
    """필드 name 이 채널 (idx, pol) 소유인지. 다른 편파의 pol-specific 은 제외."""
    if re.match(rf"^(?:d2a_)?ch{idx}_{pol}_", name):
        return True            # 이 편파 전용 필드
    if re.match(rf"^ch{idx}_(?!h_|v_)", name):
        return True            # 채널 공용(편파 무관) 필드
    if re.match(rf"^pulse_en_ch{idx}_", name):
        return True
    return False


def _to_ref(name: str, bad_idx: int, good_idx: int) -> str:
    """불량 채널 필드명 -> 같은 의미의 정상 채널 필드명(채널 토큰만 치환)."""
    return name.replace(f"ch{bad_idx}", f"ch{good_idx}")


def _rd(chip, name: str):
    try:
        return int(chip.fields.rd(name))
    except Exception:  # noqa: BLE001
        return None


def _fmt(v) -> str:
    return "ERR" if v is None else (f"{v:#x}" if v > 9 else str(v))


def snapshot_fields(chip, names: list[str] | None = None) -> dict[str, int | None]:
    """현재 레지스터 값을 {필드명: 값} 으로 떠둔다(나중에 diff_channel 에 주입용).

    바이어스 스윕처럼 레지스터를 바꾸는 작업 '전에' 호출해 두면, 원본 상태(efuse
    트림 포함)로 비교할 수 있다.
    """
    if names is None:
        names = _all_field_names(chip)
    return {n: _rd(chip, n) for n in names}


def diff_channel(chip, good_ch: str, bad_ch: str, *, read=None) -> dict:
    """bad_ch 의 per-channel 필드를 good_ch(같은 편파) 와 1:1 비교.

    read: name->value 콜러블. None 이면 chip 에서 라이브로 읽는다. 스냅샷 dict 의
          .get 을 넘기면 그 시점(예: 스윕 전) 값으로 비교한다.
    반환: {key_rows, diffs, n_compared, n_diff}.
    """
    if read is None:
        read = lambda name: _rd(chip, name)  # noqa: E731
    gpol, gidx = _parse_ch(good_ch)
    bpol, bidx = _parse_ch(bad_ch)
    names = _all_field_names(chip)

    # 1) 핵심 driver/bias 필드(항상 표시).
    key_rows = []
    for label, tmpl, kind in KEY_FIELDS:
        bf = tmpl.format(i=bidx, pol=bpol)
        gf = tmpl.format(i=gidx, pol=gpol)
        if bf not in names:
            continue
        gv, bv = read(gf), read(bf)
        key_rows.append({"label": label, "kind": kind,
                         "field": tmpl.format(i="", pol=bpol).replace("ch_", "ch*_"),
                         "good": gv, "bad": bv, "same": gv == bv})

    # 2) 전체 per-channel 필드 diff(핵심 외 차이까지 빠짐없이).
    diffs = []
    n_compared = 0
    for bf in sorted(names):
        if not _belongs(bf, bidx, bpol):
            continue
        gf = _to_ref(bf, bidx, gidx)
        if gf not in names:
            continue
        gv, bv = read(gf), read(bf)
        n_compared += 1
        if gv != bv:
            diffs.append({"field": bf, "good": gv, "bad": bv,
                          "kind": "gate" if _is_gate(bf) else "trim"})
    return {"key_rows": key_rows, "diffs": diffs,
            "n_compared": n_compared, "n_diff": len(diffs),
            "good_ch": good_ch, "bad_ch": bad_ch}


def _print_result(res: dict) -> None:
    g, b = res["good_ch"].upper(), res["bad_ch"].upper()
    print(f"\n--- {b}(bad) vs {g}(good) ---")
    print("  key driver/bias fields:")
    for r in res["key_rows"]:
        if r["same"]:
            note = "same"
        else:
            note = "DIFF (gating!)" if r["kind"] == "gate" else "diff (efuse trim)"
        print(f"    {r['label']:13} {r['field']:26} "
              f"{g}={_fmt(r['good']):>6}  {b}={_fmt(r['bad']):>6}   {note}")
    if res["diffs"]:
        print(f"  all differing per-channel fields ({res['n_diff']}):")
        for d in res["diffs"]:
            kind = "GATING" if d["kind"] == "gate" else "trim"
            print(f"    {d['field']:32} {g}={_fmt(d['good']):>6}  "
                  f"{b}={_fmt(d['bad']):>6}   [{kind}]")
    # 판정: 게이팅 필드 차이만이 '설정으로 단을 죽였을' 후보. 트림 차이는 정상 efuse 스프레드.
    n_gate = sum(1 for d in res["diffs"] if d["kind"] == "gate")
    n_trim = res["n_diff"] - n_gate
    if n_gate:
        print(f"  => {n_gate} GATING/enable field(s) differ "
              f"-> suspect config/efuse (could disable the stage). investigate these.")
    elif n_trim:
        print(f"  => only {n_trim} analog-trim field(s) differ (normal per-channel efuse "
              f"spread; cannot gate a stage on/off).")
        print(f"     gating/enable fields identical -> config is NOT the cause. "
              f"With biasscan St2 no-response, defect is silicon/HW.")
    else:
        print(f"  => all {res['n_compared']} per-channel fields IDENTICAL "
              f"-> config same, defect is silicon/HW (not registers)")


def _write_csv(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["bad_ch,good_ch,field,good_val,bad_val,same"]
    for res in results:
        g, b = res["good_ch"].upper(), res["bad_ch"].upper()
        for r in res["key_rows"]:
            lines.append(f"{b},{g},{r['field']},{_fmt(r['good'])},"
                         f"{_fmt(r['bad'])},{int(r['same'])}")
        for d in res["diffs"]:
            lines.append(f"{b},{g},{d['field']},{_fmt(d['good'])},"
                         f"{_fmt(d['bad'])},0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[driver-reg-diff] CSV written: {path}")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Dump & diff per-channel (driver) registers, good vs bad channels")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--good", default="h1,v1",
                   help="known-good reference channel(s), one per pol (default h1,v1)")
    p.add_argument("--bad", default="h0,v0,h2",
                   help="comma list of suspect channels (default h0,v0,h2)")
    p.add_argument("--beam", default=None, help="beam for bring-up (default bench.toml beam)")
    p.add_argument("--csv", type=Path, default=None, help="optional CSV output path")
    p.add_argument("--no-power", action="store_true", help="skip PSU ramp-up (already powered)")
    p.add_argument("--fake", action="store_true",
                   help="run without hardware (register values not meaningful)")
    args = p.parse_args(argv)

    goods = [c.strip().lower() for c in args.good.split(",") if c.strip()]
    bad_chs = [c.strip().lower() for c in args.bad.split(",") if c.strip()]
    good_by_pol: dict[str, str] = {}
    for g in goods:
        good_by_pol.setdefault(_parse_ch(g)[0], g)

    bench = Bench.from_toml(args.config, fake=args.fake)
    beam = args.beam or bench.board.beam
    bench.connect_all()
    if not args.no_power:
        bench.power_up()
    else:
        print("[driver-reg-diff] skipping power-up (--no-power)")

    chip = make_chip(bench.board, fake=args.fake)
    bench.board.active_channels = list(dict.fromkeys(goods + bad_chs))
    bench.board.beam = beam
    bring_up_tx(chip, bench.board, require_version=not args.fake)

    print(f"\n=== Driver register diff ===  beam={beam}")
    print(f"ref(good)={','.join(c.upper() for c in goods)}  "
          f"targets(bad)={','.join(c.upper() for c in bad_chs)}")
    if args.fake:
        print("[driver-reg-diff] FAKE mode: values are shadow defaults, not meaningful")

    try:
        results = []
        for bch in bad_chs:
            pol = _parse_ch(bch)[0]
            gch = good_by_pol.get(pol)
            if gch is None:
                print(f"\n--- {bch.upper()}: no same-pol good ref (pol '{pol}'). "
                      f"add one via --good (e.g. --good h1,v1). skipped.")
                continue
            if _parse_ch(gch)[1] == _parse_ch(bch)[1]:
                print(f"\n--- {bch.upper()}: good ref {gch.upper()} is the same channel. skipped.")
                continue
            res = diff_channel(chip, gch, bch)
            _print_result(res)
            results.append(res)
        if args.csv and results:
            _write_csv(args.csv, results)
    finally:
        bench.close_all()
        print("\n[driver-reg-diff] sockets closed. (power left as-is)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
