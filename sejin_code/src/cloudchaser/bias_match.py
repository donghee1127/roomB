"""Sivers 레퍼런스 IC 와 레일 전류를 맞추는 bias 코드 매칭 도구.

Sivers 는 bias 코드가 IC 마다 다르지만 '전류 소비 매트릭스'는 공통이라고 했다
(2026-08-25 메일). 그래서 우리 EVB 의 6개 bias 코드를 그들의 레퍼런스 전류에
맞춘 뒤에야 게인/EVM 비교가 apples-to-apples 가 된다.

설계: docs/superpowers/specs/2026-09-01-bias-current-matching-design.md

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .bench import Bench
from .board.bringup import apply_split_mode, bring_up_tx, make_chip
from .board.firehawk import FH, fe_row
from .board.gain_map import setup_single_channel
from .manual import _parse_ch
from .test_items.base import psu_rail_names, rail_vi_columns
from .test_items.op1db import compute_op1db, run_power_sweep
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout

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


# ---------------------------------------------------------------------
# 손잡이(knob) 표 -- Sivers 가 지목한 6개 bias 코드.
#   FE   bias 8x5, 열 = [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS]
#   DIST bias 3x6, 열 = [PTAT1 PTAT2_0 PTAT2_1 cbias1 cbias2_0 cbias2_1]
# rail = 그 손잡이가 주로 움직이는 PSU 레일(bench.toml 이름).
# ---------------------------------------------------------------------
# DIST bias 전류가 실제로 흐르는 레일. 2026-09-02 자코비안 실측으로 확정했다
# (DIST 코드가 이 레일을 0.26~0.41 mA/code 로 움직이는 반면 IO 쪽은 0.002 = 노이즈).
# 2026-09-03 재배선 후 이 레일은 VDD_1p8V_DIST 2핀 전용이라 Sivers IDC_Dist 와 1:1 이다.
DIST_RAIL = "DIST_1V8"


# 6비트 bias 코드의 기본 범위. 일부 열(DIST cbias)은 더 좁다 -> Knob.code_max.
CODE_MIN, CODE_MAX = 0, 63


@dataclass(frozen=True)
class Knob:
    """하나의 6-bit bias 코드와 그것이 주로 구동하는 레일."""

    name: str
    kind: str        # "fe" | "dist"
    col: int         # FE/DIST bias 행 안의 열 인덱스
    rail: str
    # 이 코드의 상한. FE 는 전 열이 6비트지만 DIST 의 cbias 3열은 3비트(0..7)다
    # (firehawk.get_dist_bias: (w2>>6)&0x7, (w2>>9)&0x7, (w2>>12)&0x7).
    code_max: int = CODE_MAX


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
# 아직 탐색에 쓰지 않는 나머지 bias 열. bring-up 이 넣은 값(FE 는 die eFuse,
# DIST cbias 는 v4 Casper cbias1=6)을 그대로 두고 있었다 -- jacobian --all-knobs 로
# 효과를 재 보고 쓸지 정한다. rail 은 잠정값이라(어느 레일을 움직이는지 미확인)
# 자코비안 표의 'response' 열만 그걸 기준으로 계산된다. 전 레일 기울기는 다 나온다.
EXTRA_KNOBS = [
    Knob("fe_ctat", "fe", 3, "FE1_4V0"),       # FE bias 열3 CTAT (6비트)
    Knob("fe_cbias", "fe", 4, "FE1_4V0"),      # FE bias 열4 FE_CBIAS (6비트)
    Knob("dist_cbias1", "dist", 3, DIST_RAIL, code_max=7),
    Knob("dist_cbias2_0", "dist", 4, DIST_RAIL, code_max=7),
    Knob("dist_cbias2_1", "dist", 5, DIST_RAIL, code_max=7),
]
ALL_KNOBS = FE_KNOBS + DIST_KNOBS



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
    if not CODE_MIN <= v <= knob.code_max:
        raise ValueError(f"{knob.name} code {v} out of range "
                         f"{CODE_MIN}..{knob.code_max}")
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


NOISE_MA = 0.2      # 이보다 작은 반응은 '무응답'으로 본다.


def _probe_rail(bench, fh, knob: Knob, code: int, *, row: int, beam_idx: int,
                cfg: BiasMatchCfg) -> float:
    """Write one code and return only that knob's own rail current [mA]."""
    write_knob(fh, knob, code, row=row, beam_idx=beam_idx)
    return read_rails_ma(bench, avg_n=cfg.avg_n,
                         settle_s=cfg.settle_s)[knob.rail]


def measure_jacobian(bench, fh, *, row: int, beam_idx: int, cfg: BiasMatchCfg,
                     delta: int = 8, knobs: list[Knob] | None = None, log=print):
    """Measure dI/dcode for every knob against every rail.

    Perturbs one knob at a time by `delta` codes (flipping the sign when the
    code is near the top of its range), records all rail currents, then puts
    the code back. Each knob is additionally probed at both ends of its code
    range, so the caller can tell whether its response keeps one direction --
    the bisection in solve_bias is only valid when it does. Costs
    1 + 3 * len(ALL_KNOBS) measurement points.

    Returns (base_rails_ma, base_codes, rows).
    """
    knobs = ALL_KNOBS if knobs is None else knobs
    base_codes = {k.name: read_knob(fh, k, row=row, beam_idx=beam_idx)
                  for k in knobs}
    base = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
    log(f"[bias-match] jacobian baseline: "
        + "  ".join(f"{n}={v:.2f}mA" for n, v in sorted(base.items())))
    rows: list[dict] = []
    for kn in knobs:
        c0 = base_codes[kn.name]
        # 3비트 knob 은 delta 8 이 통째로 범위 밖이라 상한에 맞춰 줄인다.
        d_k = max(1, min(delta, kn.code_max))
        c1 = c0 + d_k if c0 + d_k <= kn.code_max else c0 - d_k
        c1 = max(CODE_MIN, min(kn.code_max, c1))
        step = c1 - c0
        if step == 0:
            log(f"[bias-match] {kn.name}: cannot perturb (code {c0}), skipped")
            rows.append({"knob": kn.name, "code0": c0, "code1": c0,
                         "resp_ma": 0.0, "rising": True,
                         "span_resp_ma": 0.0, "span_rising": True,
                         "d": {r: 0.0 for r in base}})
            continue
        write_knob(fh, kn, c1, row=row, beam_idx=beam_idx)
        cur = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
        # 양 끝점 프로브: 국소 기울기의 부호가 코드 전 구간에서 유지되는지 본다.
        lo_ma = _probe_rail(bench, fh, kn, CODE_MIN, row=row,
                            beam_idx=beam_idx, cfg=cfg)
        hi_ma = _probe_rail(bench, fh, kn, kn.code_max, row=row,
                            beam_idx=beam_idx, cfg=cfg)
        write_knob(fh, kn, c0, row=row, beam_idx=beam_idx)
        d = {r: (cur[r] - base[r]) / step for r in base}
        resp = abs(cur[kn.rail] - base[kn.rail])
        span = hi_ma - lo_ma
        rows.append({"knob": kn.name, "code0": c0, "code1": c1,
                     "resp_ma": resp, "rising": d[kn.rail] >= 0,
                     "span_resp_ma": abs(span), "span_rising": span >= 0,
                     "d": d})
        log(f"[bias-match] {kn.name}: {c0}->{c1}  "
            f"{kn.rail} {base[kn.rail]:.2f}->{cur[kn.rail]:.2f} mA  "
            f"({d[kn.rail]:+.3f} mA/code)  "
            f"span {CODE_MIN}->{kn.code_max}: {lo_ma:.2f}->{hi_ma:.2f} mA")
    return base, base_codes, rows


def directions_from_jacobian(rows, *, noise_ma: float = NOISE_MA) -> dict[str, bool]:
    """Knob name -> True if its rail current rises with the code.

    Knobs whose response is below the noise floor are omitted: the caller must
    treat a missing key as NO RESPONSE and skip that knob.
    """
    return {r["knob"]: bool(r["rising"])
            for r in rows if float(r["resp_ma"]) > noise_ma}


def nonmonotonic_knobs(rows, *, noise_ma: float = NOISE_MA) -> list[str]:
    """Knob names whose full-range response contradicts the local perturbation.

    The bisection assumes the rail current keeps one direction over the whole
    code range. A knob listed here breaks that assumption, so the solve must
    fall back to a linear scan. Knobs that did not respond at all are not
    listed: they are handled as NO RESPONSE and skipped.
    """
    out: list[str] = []
    for r in rows:
        if float(r.get("resp_ma", 0.0)) <= noise_ma:
            continue
        span = float(r.get("span_resp_ma", 0.0))
        if span <= noise_ma or bool(r.get("span_rising", True)) != bool(r["rising"]):
            out.append(str(r["knob"]))
    return out


def format_jacobian(base_rails: dict[str, float], rows, *, noise_ma: float = NOISE_MA) -> str:
    """Render the dI/dcode matrix as a console table (mA per code step)."""
    rail_names = sorted(base_rails)
    nonmono = set(nonmonotonic_knobs(rows, noise_ma=noise_ma))
    out = ["", "=== Jacobian: dI/dcode [mA per code step] ===",
           f"{'knob':14}" + "".join(f"{r:>11}" for r in rail_names) + "   response"]
    for r in rows:
        line = f"{r['knob']:14}" + "".join(f"{r['d'][n]:>+11.3f}" for n in rail_names)
        line += f"   {r['resp_ma']:6.2f} mA"
        if r["resp_ma"] <= noise_ma:
            line += "  ** NO RESPONSE **"
        elif r["knob"] in nonmono:
            line += "  ** NON-MONOTONIC **"
        out.append(line)
    return "\n".join(out)


def bisect_knob(bench, fh, knob: Knob, target_ma: float, *, row: int,
                beam_idx: int, cfg: BiasMatchCfg, rising: bool, log=print):
    """Binary-search one 6-bit code so its rail hits target_ma.

    `rising` comes from the Jacobian: True when rail current grows with the
    code. Returns (code, current_ma, err_ma) for the best point seen, and
    leaves that code written. An unreachable target is not an error -- the
    residual is returned so the caller can report it.
    """
    lo, hi = CODE_MIN, knob.code_max
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


# 이분탐색 뒤 이웃 코드를 다시 훑는 기본 칸 수.
REFINE_STEPS = 4


def refine_knob(bench, fh, knob: Knob, target_ma: float, *, row: int,
                beam_idx: int, cfg: BiasMatchCfg, start: int,
                max_steps: int = REFINE_STEPS, log=print):
    """Re-measure around `start` back to back and move to the local best.

    The bisection compares readings taken minutes apart, at different points in
    the sweep and at whatever die temperature the earlier probes left behind.
    On this chip that is enough to pick the wrong code: on v1 the PA rail steps
    3.3 mA between codes 13 and 14 while neighbouring steps are 0.4-0.7, so the
    target sat on a cliff edge and a 0.5 mA drift flipped the ranking. A rail
    read that times out and retries can flip it too.

    This measures `start` and its neighbours one after another, so the
    comparison is made under the same conditions, and walks in the improving
    direction for at most `max_steps` codes. Returns (code, current_ma, err_ma)
    and leaves that code written. max_steps=0 disables it.
    """
    seen: dict[int, tuple[int, float, float]] = {}

    def at(code: int):
        if code not in seen:
            write_knob(fh, knob, code, row=row, beam_idx=beam_idx)
            cur = read_rails_ma(bench, avg_n=cfg.avg_n,
                                settle_s=cfg.settle_s)[knob.rail]
            seen[code] = (code, cur, cur - target_ma)
        return seen[code]

    start = int(start)
    if max_steps <= 0:
        write_knob(fh, knob, start, row=row, beam_idx=beam_idx)
        cur = read_rails_ma(bench, avg_n=cfg.avg_n,
                            settle_s=cfg.settle_s)[knob.rail]
        return (start, cur, cur - target_ma)
    best = at(start)
    for c in (start - 1, start + 1):
        if CODE_MIN <= c <= knob.code_max and abs(at(c)[2]) < abs(best[2]):
            best = seen[c]
    step = best[0] - start
    if step:
        # 이웃이 이겼다 -> 그 방향으로 개선이 멈출 때까지 간다(칸 수 상한).
        code = best[0]
        for _ in range(max_steps - 1):
            code += step
            if not CODE_MIN <= code <= knob.code_max:
                break
            nxt = at(code)
            if abs(nxt[2]) >= abs(best[2]):
                break
            best = nxt
    write_knob(fh, knob, best[0], row=row, beam_idx=beam_idx)
    if best[0] != start:
        log(f"[bias-match] {knob.name} refined {start} -> {best[0]}: "
            f"{knob.rail} {best[1]:.2f} mA (target {target_ma:.2f}, "
            f"err {best[2]:+.2f})")
    return best


def scan_knob(bench, fh, knob: Knob, target_ma: float, *, row: int,
              beam_idx: int, cfg: BiasMatchCfg, log=print):
    """Linear scan of one knob's whole code range, keeping the best point.

    The fallback for a knob the Jacobian flagged non-monotonic: bisection is
    not valid there, so every code is measured. Returns (code, current_ma,
    err_ma) for the best point seen, and leaves that code written. Costs
    CODE_MAX - CODE_MIN + 1 measurement points.
    """
    best: tuple[int, float, float] | None = None
    for code in range(CODE_MIN, knob.code_max + 1):
        write_knob(fh, knob, code, row=row, beam_idx=beam_idx)
        cur = read_rails_ma(bench, avg_n=cfg.avg_n,
                            settle_s=cfg.settle_s)[knob.rail]
        err = cur - target_ma
        if best is None or abs(err) < abs(best[2]):
            best = (code, cur, err)
    assert best is not None      # 코드 범위는 비어 있지 않다
    write_knob(fh, knob, best[0], row=row, beam_idx=beam_idx)
    flag = "" if abs(best[2]) <= cfg.tol_ma else "  ** NOT REACHED **"
    log(f"[bias-match] {knob.name} -> code {best[0]} (linear scan): "
        f"{knob.rail} {best[1]:.2f} mA (target {target_ma:.2f}, "
        f"err {best[2]:+.2f}){flag}")
    return best


def _dist_ratio(cfg: BiasMatchCfg) -> list[int]:
    """Validate and return bias_match.dist_ratio.

    The length matters: zip(DIST_KNOBS, codes) would silently drop the tail
    knobs of a short ratio, and they would then still be reported as solved.
    """
    ratio = list(cfg.dist_ratio)
    if len(ratio) != len(DIST_KNOBS):
        raise ValueError(
            f"bias_match.dist_ratio must have exactly {len(DIST_KNOBS)} "
            f"entries ({', '.join(k.name for k in DIST_KNOBS)}), got "
            f"{len(ratio)}: {ratio}")
    if max(ratio) <= 0:
        raise ValueError("bias_match.dist_ratio must contain a positive value")
    return ratio


def _apply_dist_codes(fh, codes, *, beam_idx: int) -> None:
    """Write the three DIST codes for one beam."""
    for kn, c in zip(DIST_KNOBS, codes):
        write_knob(fh, kn, c, row=0, beam_idx=beam_idx)


def _smallest_positive(ratio: list[int]) -> int:
    """ratio 에서 0 보다 큰 가장 작은 항. DIST 스케일 k 의 상한을 정하는 데 쓴다.

    k*ratio 는 63 에서 clamp 되므로, '가장 작은 항이 63 이 되는 k' 가 모든 항이
    포화하는 지점이다. 전부 0 이면 스케일을 아무리 키워도 코드가 안 움직이므로
    1 을 돌려 k 범위가 무의미하게 발산하지 않게 한다.
    """
    positive = [r for r in ratio if r > 0]
    return min(positive) if positive else 1


def bisect_dist_scale(bench, fh, target_ma: float, *, beam_idx: int,
                      cfg: BiasMatchCfg, rising: bool, iters: int = 12,
                      log=print):
    """Scale the whole DIST ratio by one factor k until DIST_RAIL hits target.

    The DIST block has three knobs but only one observable, so the ratio from
    `cfg.dist_ratio` is held fixed and only its scale is searched. Codes are
    round(k * ratio) clamped to 0..63; repeated code vectors reuse the cached
    reading instead of re-measuring.

    Returns (codes, k, current_ma, err_ma) for the best point, left written.

    iters is 12, not the 8 that covered the old narrow k range: the search now
    runs to k = 63/min(ratio) (4.85 for [50,13,13] instead of 1.26), so it needs
    four more halvings to still resolve a single code step. Extra probes are
    nearly free -- repeated code vectors come from the cache.
    """
    ratio = _dist_ratio(cfg)

    def codes_for(k: float) -> tuple[int, ...]:
        return tuple(max(CODE_MIN, min(CODE_MAX, int(round(k * r)))) for r in ratio)

    def apply(codes) -> None:
        _apply_dist_codes(fh, codes, beam_idx=beam_idx)

    # k 상한은 '모든' ratio 항이 63 에 닿는 지점까지 열어 둔다. max(ratio) 로 잡으면
    # 가장 큰 항(v4 Casper 는 st1=50)이 63 에 닿는 k=1.26 에서 탐색이 끝나고, 그때
    # st2 는 16 까지밖에 못 올라간다 -- DIST 를 28~33 mA 범위만 훑게 되어 레퍼런스
    # 64.4 mA 에는 영원히 못 닿는다(2026-09-03 실측: 64.4 는 (63,63,63) 부근).
    # 큰 항이 clamp 되는 구간에서는 ratio 가 그대로 유지되지 않지만, 그 구간 없이는
    # 타깃에 도달할 수 없다.
    k_lo, k_hi = 0.0, float(CODE_MAX) / _smallest_positive(ratio)
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


def scan_dist_scale(bench, fh, target_ma: float, *, beam_idx: int,
                    cfg: BiasMatchCfg, log=print):
    """Linear scan of the DIST scale factor k, keeping the best point.

    The fallback used when the Jacobian flagged a DIST knob non-monotonic.
    k is stepped so the *smallest* ratio entry walks every code 0..63. Stepping
    the largest entry instead would stop at the k where it first clamps, which
    leaves most of the reachable current range unexplored (see bisect_dist_scale).

    Returns (codes, k, current_ma, err_ma) for the best point, left written.
    """
    ratio = _dist_ratio(cfg)
    top = _smallest_positive(ratio)   # bisect 와 같은 이유로 '가장 작은' 항 기준
    seen: dict[tuple[int, ...], float] = {}
    best: tuple[tuple[int, ...], float, float, float] | None = None
    for c in range(CODE_MIN, CODE_MAX + 1):
        k = float(c) / top
        codes = tuple(max(CODE_MIN, min(CODE_MAX, int(round(k * r))))
                      for r in ratio)
        if codes in seen:
            continue
        _apply_dist_codes(fh, codes, beam_idx=beam_idx)
        cur = read_rails_ma(bench, avg_n=cfg.avg_n,
                            settle_s=cfg.settle_s)[DIST_RAIL]
        seen[codes] = cur
        err = cur - target_ma
        if best is None or abs(err) < abs(best[3]):
            best = (codes, k, cur, err)
    assert best is not None      # 코드 범위는 비어 있지 않다
    _apply_dist_codes(fh, best[0], beam_idx=beam_idx)
    flag = "" if abs(best[3]) <= cfg.tol_ma else "  ** NOT REACHED **"
    log(f"[bias-match] dist {list(best[0])} (k={best[1]:.3f}, linear scan): "
        f"{DIST_RAIL} {best[2]:.2f} mA (target {target_ma:.2f}, "
        f"err {best[3]:+.2f}){flag}")
    return best


def solve_bias(bench, fh, *, row: int, beam_idx: int, cfg: BiasMatchCfg,
               directions: dict[str, bool], nonmonotonic=(), log=print) -> dict:
    """Outer loop: solve each rail 1-D, repeat until cross-coupling settles.

    `directions` comes from directions_from_jacobian(); a knob missing from it
    did not respond and is skipped (reported in the result, not raised).
    `nonmonotonic` comes from nonmonotonic_knobs(): those knobs cannot be
    bisected, so they fall back to a full linear scan with a warning.
    Non-convergence after cfg.max_iter is reported, not raised.
    """
    skipped = [k.name for k in ALL_KNOBS if k.name not in directions]
    nonmono = {n for n in nonmonotonic if n not in skipped}
    dist_live = [k for k in DIST_KNOBS if k.name in directions]
    dist_nonmono = any(k.name in nonmono for k in dist_live)
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
            if kn.name in nonmono:
                log(f"[bias-match] WARNING: {kn.name} is non-monotonic -- "
                    f"falling back to a full {CODE_MAX - CODE_MIN + 1}-point "
                    "linear scan")
                scan_knob(bench, fh, kn, target, row=row, beam_idx=beam_idx,
                          cfg=cfg, log=log)
            else:
                got = bisect_knob(bench, fh, kn, target, row=row,
                                  beam_idx=beam_idx, cfg=cfg,
                                  rising=directions[kn.name], log=log)
                # 이분탐색은 서로 다른 시점의 읽기를 비교한다 -- 마지막에 이웃을
                # 연달아 재서 국소 최적을 확인한다(2026-09-04 v1 에서 한 칸 어긋났다).
                refine_knob(bench, fh, kn, target, row=row, beam_idx=beam_idx,
                            cfg=cfg, start=got[0], log=log)
        dist_target = cfg.targets_ma.get(DIST_RAIL)
        if dist_target is not None and dist_live and dist_nonmono:
            log("[bias-match] WARNING: a DIST knob is non-monotonic -- "
                f"falling back to a full {CODE_MAX - CODE_MIN + 1}-point "
                "linear scan of the DIST scale")
            scan_dist_scale(bench, fh, dist_target, beam_idx=beam_idx,
                            cfg=cfg, log=log)
        elif dist_target is not None and dist_live:
            bisect_dist_scale(bench, fh, dist_target, beam_idx=beam_idx,
                              cfg=cfg, rising=directions[dist_live[0].name],
                              log=log)
        elif dist_target is not None:
            log(f"[bias-match] all DIST knobs are dead, {DIST_RAIL} left as-is")
        rails = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
        errors = {r: rails[r] - t for r, t in cfg.targets_ma.items()}
        # errors 가 비면(타깃 없음) all() 은 True 다 -- 아무것도 안 했으므로 수렴이 아니다.
        if errors and all(abs(e) <= cfg.tol_ma for e in errors.values()):
            log(f"[bias-match] converged after {it} iteration(s)")
            break
    else:
        log(f"[bias-match] no convergence after {cfg.max_iter} iterations "
            "-- reporting best effort")
    codes = {k.name: read_knob(fh, k, row=row, beam_idx=beam_idx)
             for k in ALL_KNOBS}
    return {"codes": codes, "rails_ma": rails, "errors_ma": errors,
            "iterations": iterations,
            "converged": bool(errors) and all(abs(e) <= cfg.tol_ma
                                              for e in errors.values()),
            "skipped": skipped,
            "nonmonotonic": sorted(nonmono)}


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

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
    # split 모드는 bench.toml 을 따르는 게 기본이다(= split). Sivers 가 공유한 결과가
    # 전부 split 이라 그게 비교 기준이다. --split/--no-split 는 명시적 override 일 때만.
    if args.split is not None:
        bench.board.split_mode = bool(args.split)
    print(f"[bias-match] splitter mode: "
          f"{'split' if bench.board.split_mode else 'thru'}")
    bring_up_tx(chip, bench.board, require_version=not args.fake)
    fh = _engine(bench, chip)
    setup_single_channel(fh, beam, ch)
    # route_channels() 는 split 설정을 지우므로 다시 적용한다(순서가 중요, d7b76c5).
    apply_split_mode(fh, bench.board, kind="tx")
    pol, idx = _parse_ch(ch)
    row, bidx = fe_row(idx, pol), beam_index(beam)
    # solve 가 찾은 코드로 측정하려면 여기서 덮어써야 한다. bring_up_tx 는 v4 시트
    # Casper 를 기입하므로, 이게 없으면 verify 가 매칭 전 코드로 측정한다.
    _apply_code_overrides(fh, args, row=row, beam_idx=bidx)
    return bench, chip, fh, row, bidx, beam, ch


def _codes_arg(text, knobs, label):
    """'18,55,61' -> [18, 55, 61]. 개수/범위를 검사한다."""
    vals = [v.strip() for v in str(text).split(",") if v.strip()]
    if len(vals) != len(knobs):
        raise ValueError(f"--{label} needs {len(knobs)} comma-separated codes "
                         f"({', '.join(k.name for k in knobs)}), got {len(vals)}")
    out = []
    for v in vals:
        c = int(v)
        if not CODE_MIN <= c <= CODE_MAX:
            raise ValueError(f"--{label} code {c} out of range "
                             f"{CODE_MIN}..{CODE_MAX}")
        out.append(c)
    return out


def _apply_code_overrides(fh, args, *, row: int, beam_idx: int) -> None:
    """--ptat / --dist / --fe-extra / --dist-cbias 로 준 bias 코드를 기입한다.

    주지 않은 그룹은 bring-up 이 넣은 값을 그대로 둔다.
    """
    for label, knobs in (("ptat", FE_KNOBS), ("dist", DIST_KNOBS),
                        ("fe_extra", EXTRA_KNOBS[:2]),
                        ("dist_cbias", EXTRA_KNOBS[2:])):
        text = getattr(args, label, None)
        if not text:
            continue
        codes = _codes_arg(text, knobs, label)
        for kn, c in zip(knobs, codes):
            write_knob(fh, kn, c, row=row, beam_idx=beam_idx)
        print(f"[bias-match] {label} codes applied: "
              + ", ".join(f"{k.name}={c}" for k, c in zip(knobs, codes)))


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
        "ptat_override": getattr(args, "ptat", None) or "",
        "dist_override": getattr(args, "dist", None) or "",
        "fe_extra_override": getattr(args, "fe_extra", None) or "",
        "dist_cbias_override": getattr(args, "dist_cbias", None) or "",
    }
    # Gain[dB] 는 이 값 기준으로 계산되므로 CSV 만 보고도 재현 가능해야 한다.
    level = getattr(args, "sg_level_dbm", None)
    if level is not None:
        meta["sg_level_dbm"] = level
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


def _read_all_codes(fh, *, row: int, beam_idx: int) -> dict[str, int]:
    """Every knob's current code, so an aborted run can put them back.

    EXTRA_KNOBS 도 포함한다 -- --all-knobs 자코비안이 중간에 죽으면 그 열들도
    임의 값에 남기 때문이다.
    """
    return {k.name: read_knob(fh, k, row=row, beam_idx=beam_idx)
            for k in ALL_KNOBS + EXTRA_KNOBS}


def _restore_all_codes(fh, codes: dict[str, int], *, row: int,
                       beam_idx: int) -> None:
    """Write the codes captured by _read_all_codes back to the chip.

    codes 에 없는 knob 은 건너뛴다 -- 옛 CSV/부분 dict 로도 안전하게 돌아간다.
    """
    for k in ALL_KNOBS + EXTRA_KNOBS:
        if k.name in codes:
            write_knob(fh, k, codes[k.name], row=row, beam_idx=beam_idx)


def cmd_jacobian(args) -> int:
    cfg = load_bias_match_cfg(args.config)
    bench, _chip, fh, row, bidx, beam, ch = open_bench(args)
    # 예외(대부분 guard_rails)로 중단되면 코드가 임의 값에 남는다 -> 원래대로 되돌린다.
    orig_codes = _read_all_codes(fh, row=row, beam_idx=bidx)
    restore_codes = True
    try:
        knobs = (ALL_KNOBS + EXTRA_KNOBS) if getattr(args, "all_knobs", False)             else ALL_KNOBS
        base, codes, jrows = measure_jacobian(bench, fh, row=row, beam_idx=bidx,
                                              cfg=cfg, delta=args.delta,
                                              knobs=knobs)
        print(format_jacobian(base, jrows, noise_ma=args.noise_ma))
        rail_names = sorted(base)
        columns = ["knob", "code0", "code1", "resp_mA", "rising",
                   "span_resp_mA", "span_rising"] + \
                  [f"d_{r}_mA_per_code" for r in rail_names]
        rows = [[r["knob"], r["code0"], r["code1"], round(r["resp_ma"], 3),
                 int(r["rising"]), round(float(r.get("span_resp_ma", 0.0)), 3),
                 int(bool(r.get("span_rising", True)))]
                + [round(r["d"][n], 4) for n in rail_names]
                for r in jrows]
        meta = meta_dict(args, bench, beam, ch)
        meta.update({f"base_{n}_mA": round(base[n], 3) for n in rail_names})
        meta.update({f"code_{k}": v for k, v in codes.items()})
        meta["nonmonotonic"] = "|".join(
            nonmonotonic_knobs(jrows, noise_ma=args.noise_ma))
        write_csv(args.csv or _default_csv("jacobian"), columns, rows, meta)
        # measure_jacobian 은 각 knob 을 스스로 복원한다 -> 정상 종료면 할 일 없다.
        restore_codes = False
    finally:
        # cmd_dist_gain 과 같은 패턴: 정리 단계마다 자기 try/except 를 둬서
        # 앞 단계가 실패해도 뒤 단계(소켓 close)가 스킵되지 않게 한다.
        try:
            if restore_codes:
                _restore_all_codes(fh, orig_codes, row=row, beam_idx=bidx)
                print(f"[bias-match] bias codes restored to {orig_codes}")
        except Exception as e:  # noqa: BLE001
            print(f"[bias-match] RESTORE FAILED: bias codes could not be "
                  f"restored to {orig_codes}: {e} -- check the chip before "
                  f"further measurements")
        finally:
            bench.close_all()
            print("[bias-match] sockets closed. (power left as-is)")
    return 0


def _check_targets(args, cfg: BiasMatchCfg) -> list[str]:
    """Return English complaints about [bias_match].targets_ma, empty if sane.

    Checked before any bring-up or measurement: a typo'd rail name would
    otherwise raise a bare KeyError mid-run with the codes left arbitrary,
    and an empty target set would 'converge' having done nothing.
    """
    if not cfg.targets_ma:
        return [f"[bias_match].targets_ma is empty in {args.config} -- "
                "nothing to solve for"]
    known = rail_limits_ma(Bench.from_toml(args.config, fake=args.fake))
    unknown = sorted(r for r in cfg.targets_ma if r not in known)
    if unknown:
        return [f"[bias_match].targets_ma names rail(s) that do not exist in "
                f"{args.config}: {', '.join(unknown)}",
                f"known rails: {', '.join(sorted(known))}"]
    return []


def cmd_solve(args) -> int:
    cfg = load_bias_match_cfg(args.config)
    problems = _check_targets(args, cfg)
    if problems:
        for line in problems:
            print(f"[bias-match] {line}")
        return 1
    bench, _chip, fh, row, bidx, beam, ch = open_bench(args)
    # 예외(대부분 guard_rails)로 중단되면 코드가 임의 값에 남는다 -> 원래대로 되돌린다.
    orig_codes = _read_all_codes(fh, row=row, beam_idx=bidx)
    restore_codes = True
    rf_on = False
    try:
        # 레퍼런스 전류는 RF 를 건 상태에서 잰 값이다(저쪽 CSV 는 Pin 이 인가된
        # RF_Freq_sweep). 정지전류로 맞추면 구동전류가 어긋난다 -- 실측으로
        # dist (63,16,0) 에서 FE1 이 RF OFF 26.8 mA vs RF ON 29.1 mA 였다.
        if args.rf:
            f_hz = args.rf_freq_ghz * 1e9
            _setup_rf_point(bench, args, f_hz)
            bench.sg.rf_output(True)
            rf_on = True
            print(f"[bias-match] solving with RF ON at "
                  f"{args.rf_freq_ghz:.3f} GHz, {args.sg_level_dbm:.1f} dBm "
                  "-- currents are matched under drive")
        base, _codes, jrows = measure_jacobian(bench, fh, row=row,
                                               beam_idx=bidx, cfg=cfg,
                                               delta=args.delta)
        print(format_jacobian(base, jrows, noise_ma=args.noise_ma))
        dirs = directions_from_jacobian(jrows, noise_ma=args.noise_ma)
        nonmono = nonmonotonic_knobs(jrows, noise_ma=args.noise_ma)
        if nonmono:
            print(f"[bias-match] WARNING: non-monotonic knob(s): "
                  f"{', '.join(nonmono)} -- each falls back to a full "
                  f"{CODE_MAX - CODE_MIN + 1}-point linear scan")
        res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                         directions=dirs, nonmonotonic=nonmono)
        print("\n=== Bias match result ===")
        print(f"converged: {res['converged']}  iterations: {res['iterations']}")
        if res["skipped"]:
            print(f"skipped (no response): {', '.join(res['skipped'])}")
        if res["nonmonotonic"]:
            print(f"linear-scanned (non-monotonic): "
                  f"{', '.join(res['nonmonotonic'])}")
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
        if rf_on:
            pout = bench.sa.measure_peak_dbm()
            print(f"  gain at {args.rf_freq_ghz:.3f} GHz: "
                  f"{pout - args.sg_level_dbm:+.2f} dB  (Pout {pout:+.2f} dBm)")
        c = res["codes"]
        print("")
        print("# measure with these codes -- no file edit needed:")
        print(f"  python -m cloudchaser.bias_match verify "
              f"--ptat {c['ptat_st1']},{c['ptat_st2']},{c['ptat_st3']} "
              f"--dist {c['dist_st1']},{c['dist_st2_0']},{c['dist_st2_1']} "
              f"--serial <DUT S/N>")
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
                     "skipped": "|".join(res["skipped"]),
                     "nonmonotonic": "|".join(res["nonmonotonic"])})
        write_csv(args.csv or _default_csv("match"), columns, rows, meta)
        # 정상 종료면 푼 코드를 그대로 남긴다(그게 이 명령의 결과물이다).
        restore_codes = False
    finally:
        try:
            if rf_on:
                bench.sg.rf_output(False)
        except Exception as e:  # noqa: BLE001
            print(f"[bias-match] RF output off FAILED: {e}")
        try:
            if restore_codes:
                _restore_all_codes(fh, orig_codes, row=row, beam_idx=bidx)
                print(f"[bias-match] bias codes restored to {orig_codes}")
        except Exception as e:  # noqa: BLE001
            print(f"[bias-match] RESTORE FAILED: bias codes could not be "
                  f"restored to {orig_codes}: {e} -- check the chip before "
                  f"further measurements")
        finally:
            bench.close_all()
            print("[bias-match] sockets closed. (power left as-is)")
    return 0


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
    # 2026-09-03 재배선으로 확정: 저쪽 IDC_1p8 = ANA + IO_SOUTH + IO_NORTH,
    # IDC_Dist = VDD_1p8V_DIST 2핀. 우리 두 채널을 같은 묶음으로 다시 물렸다.
    ("IDC_1p8[mA]", "IO_ANA_1V8"),
    ("IDC_Dist[mA]", "DIST_1V8"),
    ("IDC_FE1[mA]", "FE1_4V0"),
    ("IDC_FE2[mA]", "FE2_1V8"),
    ("IDC_FE3[mA]", "FE3_1V8"),
]
DEFAULT_VDD = [4.0, 3.6, 3.3, 3.0, 2.7, 2.4, 2.2]
DEFAULT_FREQS_GHZ = [27.5, 28.0, 28.5, 29.0, 29.5, 30.0, 30.5, 31.0]


def _floats(text: str) -> list[float]:
    return [float(x) for x in str(text).split(",") if x.strip()]


def _setup_rf_point(bench, args, f_hz: float) -> None:
    """Set SG (CW, frequency, path loss, level) and SA up for one point.

    RF output is deliberately NOT switched on here: the caller turns it on
    only once every setting for the point about to be measured is in place,
    which is the ordering every other test item in this repo uses.
    """
    sg, sa = bench.sg, bench.sa
    sg.modulation_off()          # CW 보장(직전 EVM 등의 ARB 파형 잔류 방지)
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


def _drop_freqs_above_sa_limit(freqs_ghz, *, bench_cfg_path) -> list[float]:
    """Drop sweep points the spectrum analyser cannot actually measure.

    Above the SA's top frequency the reading is its noise floor, which shows up
    as a plausible-looking but meaningless -40 dB gain. Silently keeping those
    rows would put junk in the CSV we hand to the vendor.
    """
    with open(bench_cfg_path, "rb") as f:
        limit = tomllib.load(f).get("sa", {}).get("max_freq_hz")
    if not limit:
        return list(freqs_ghz)
    lim_ghz = float(limit) / 1e9
    keep = [f for f in freqs_ghz if f <= lim_ghz + 1e-9]
    dropped = [f for f in freqs_ghz if f > lim_ghz + 1e-9]
    if dropped:
        print(f"[bias-match] skipping {len(dropped)} point(s) above the SA limit "
              f"({lim_ghz:.1f} GHz): "
              + ", ".join(f"{f:.2f}" for f in dropped)
              + " GHz -- the SA would only report its noise floor there")
    return keep


def cmd_verify(args) -> int:
    """Replay the Sivers measurement (VDD_FE1 x RF frequency).

    Measures at whatever bias the bring-up left, unless --ptat / --dist give
    the codes to use -- pass the ones a solve run reported, or this sweeps the
    pre-match bias and the comparison means nothing.
    """
    cfg = load_bias_match_cfg(args.config)
    vdds = _floats(args.vdd)
    freqs = _floats(args.freqs)
    freqs = _drop_freqs_above_sa_limit(freqs, bench_cfg_path=args.config)
    if not freqs:
        print("[bias-match] every requested frequency is above the SA limit; "
              "nothing to measure")
        return 1
    bench, _chip, _fh, _row, _bidx, beam, ch = open_bench(args)
    pol, idx = _parse_ch(ch)
    nominal = bench.rail_nominal_v("FE1_4V0")
    rows: list[list] = []
    try:
        sg, sa = bench.sg, bench.sa
        for vdd in vdds:
            # FE1_4V0 은 PA 드레인이다 -- 전압을 램프하는 동안 RF 를 끈다
            # (vdd_sensitivity 와 같은 패턴).
            sg.rf_output(False)
            bench.set_rail_voltage("FE1_4V0", vdd)
            for f_ghz in freqs:
                f_hz = f_ghz * 1e9
                _setup_rf_point(bench, args, f_hz)
                sg.rf_output(True)
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
        # cmd_dist_gain 과 같은 패턴: 정리 단계마다 자기 try/except 를 둬서
        # 앞 단계가 실패해도 뒤 단계(CSV 기록과 소켓 close)가 스킵되지 않게 한다.
        try:
            bench.sg.rf_output(False)
        except Exception as e:  # noqa: BLE001
            print(f"[bias-match] RF output off FAILED: {e}")
        try:
            bench.set_rail_voltage("FE1_4V0", nominal)
            print(f"[bias-match] FE1_4V0 restored to {nominal:.2f} V")
        except Exception as e:  # noqa: BLE001
            print(f"[bias-match] RESTORE FAILED: rail FE1_4V0 could not be "
                  f"set back to {nominal:.2f} V: {e} -- check the PSU before "
                  f"further measurements")
        try:
            # rows 가 비어도(=첫 점에서 중단) 헤더만 있는 CSV 를 남긴다 --
            # dist-gain 과 같은 규칙이다.
            write_csv(args.csv or _default_csv("verify"),
                      SIVERS_COLUMNS, rows, meta_dict(args, bench, beam, ch))
        finally:
            bench.close_all()
            print("[bias-match] sockets closed. (power left as-is)")
    return 0


def dist_axis_codes(args) -> list[list[int]]:
    """Per-axis DIST code lists: --st1/--st2-0/--st2-1 if given, else the grid."""
    grid = list(range(CODE_MIN, CODE_MAX + 1, max(1, int(args.grid_step))))
    out = []
    for attr in ("st1", "st2_0", "st2_1"):
        flag = "--" + attr.replace("_", "-")
        text = getattr(args, attr, None)
        if not text:
            out.append(grid)
            continue
        codes = []
        for v in str(text).split(","):
            v = v.strip()
            if not v:
                continue
            c = int(v)
            if not CODE_MIN <= c <= CODE_MAX:
                raise ValueError(f"{flag} code {c} out of range "
                                 f"{CODE_MIN}..{CODE_MAX}")
            codes.append(c)
        if not codes:
            raise ValueError(f"{flag} is empty")
        out.append(codes)
    return out


def gain_sensitivity(points) -> dict:
    """Local |dGain/dcode| per measured point, from its measured neighbours.

    `points` is [(codes, gain), ...]. For each axis the nearest measured codes
    on either side (the other two axes equal) give a difference quotient; the
    result is the largest slope across the three axes.

    Why it matters: two DIST settings can produce the same gain while sitting
    on very different slopes. A point on a steep slope turns small bias or
    temperature drift into a visible gain and PA-current wobble, so among
    equally accurate settings the flattest one is the one to run.
    Points with no neighbour on any axis get None.
    """
    gains = {tuple(c): g for c, g in points}
    out = {}
    for codes in gains:
        slopes = []
        for axis in range(3):
            same = [c for c in gains
                    if all(c[i] == codes[i] for i in range(3) if i != axis)]
            lo = max((c for c in same if c[axis] < codes[axis]),
                     key=lambda c: c[axis], default=None)
            hi = min((c for c in same if c[axis] > codes[axis]),
                     key=lambda c: c[axis], default=None)
            pair = [c for c in (lo, codes, hi) if c is not None]
            if len(pair) < 2:
                continue
            a, b = pair[0], pair[-1]
            dc = b[axis] - a[axis]
            if dc:
                slopes.append(abs((gains[b] - gains[a]) / dc))
        out[codes] = max(slopes) if slopes else None
    return out


def screen_dist_grid(bench, fh, *, beam_idx: int, cfg: BiasMatchCfg,
                     target_ma: float, window_ma: float, axes,
                     log=print):
    """Sweep the DIST codes over `axes`, keeping the in-window combinations.

    `axes` is one code list per DIST knob, so this covers a coarse cube, a
    corner scan, or a 1-D sweep of one knob with the others pinned. RF is not
    needed here -- only the DC current.

    Returns [(codes, rails_ma), ...] sorted by |DIST rail current - target|.
    Every rail is kept, not just the DIST one: picking a DIST setting means
    weighing its gain against the FE currents it drags along with it.
    """
    kept = []
    combos = list(itertools.product(*axes))
    log(f"[bias-match] screening {len(combos)} DIST combination(s) for "
        f"{DIST_RAIL} = {target_ma:.1f} +/- {window_ma:.1f} mA")
    for codes in combos:
        _apply_dist_codes(fh, codes, beam_idx=beam_idx)
        rails = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
        if abs(rails[DIST_RAIL] - target_ma) <= window_ma:
            kept.append((tuple(codes), rails))
            log(f"[bias-match]   keep {list(codes)}: "
                f"{DIST_RAIL}={rails[DIST_RAIL]:.2f} mA")
    kept.sort(key=lambda t: abs(t[1][DIST_RAIL] - target_ma))
    log(f"[bias-match] {len(kept)}/{len(combos)} combination(s) in the window")
    return kept


def _sweep_op1db(bench, args, *, prefix, rail_names, log=print):
    """Run a power sweep at the current bias and return (result, rows).

    소신호 게인 하나만 재는 것과 달리 압축점까지 본다. 계산은 op1db 테스트 항목과
    똑같은 함수를 쓴다(`run_power_sweep` + `compute_op1db`) -- 압축점 정의가 두 벌로
    갈라지면 같은 칩에서 서로 다른 OP1dB 가 나온다.

    result: compute_op1db() dict (g_ref, op1db_pout, ip1db_pin, sg_at_op1db)
    rows  : sweep 원본 행(측정점마다 Pout/Gain + 전 레일 V/I). 압축이 어디서
            시작하는지 -- PA 가 한계인지 앞단이 한계인지 -- 는 이 행들로만 보인다.
    """
    levels = []
    lvl = float(args.pin_start_dbm)
    while lvl <= float(args.pin_stop_dbm) + 1e-9:
        levels.append(round(lvl, 3))
        lvl += float(args.pin_step_db)
    rows, pins, pouts, gains, _idds = run_power_sweep(
        bench, levels, settle=args.settle_s, rail_names=rail_names, log=log,
        prefix=prefix, tag="")
    res = compute_op1db(levels, pins, pouts, gains,
                        int(args.ref_skip_pts), int(args.ref_avg_pts))
    return res, rows


def cmd_dist_gain(args) -> int:
    """Find the max-gain point on the DIST-current-constrained surface."""
    cfg = load_bias_match_cfg(args.config)
    target = args.target_ma if args.target_ma is not None         else cfg.targets_ma.get(DIST_RAIL)
    if target is None:
        print(f"[bias-match] no {DIST_RAIL} target in [bias_match] and no "
              "--target-ma given; nothing to constrain")
        return 1
    bench, _chip, fh, _row, bidx, beam, ch = open_bench(args)
    rows: list[list] = []
    rail_names = sorted(rail_limits_ma(bench))
    # 스크리닝이 아무것도 못 건지면 그리드 마지막 코드가 남는다 -> 원래 값으로 되돌린다.
    orig_dist = [read_knob(fh, kn, row=0, beam_idx=bidx) for kn in DIST_KNOBS]
    restore_dist = True
    try:
        kept = screen_dist_grid(bench, fh, beam_idx=bidx, cfg=cfg,
                                target_ma=target, window_ma=args.window_ma,
                                axes=dist_axis_codes(args))
        if not kept:
            print("[bias-match] no combination landed inside the window -- "
                  "widen --window-ma or shrink --grid-step")
        else:
            f_hz = args.gain_freq_ghz * 1e9
            sg, sa = bench.sg, bench.sa
            if args.op1db:
                # 압축까지 밀면 Pout 이 20 dBm 근처까지 간다 -- 소신호용 ref level
                # 그대로 두면 SA 가 클리핑한다(op1db 테스트 항목 기본값도 25).
                args.sa_ref_dbm = float(args.sa_ref_op1db_dbm)
                print(f"[bias-match] op1db mode: SA ref level -> "
                      f"{args.sa_ref_dbm:.1f} dBm, Pin sweep "
                      f"{args.pin_start_dbm:+.1f}..{args.pin_stop_dbm:+.1f} dBm")
            _setup_rf_point(bench, args, f_hz)
            sg.rf_output(True)
            best = None
            scored = []
            sweep_rows: list[list] = []
            rail_names = psu_rail_names(bench) if args.op1db else []
            for codes, _screen_rails in kept:
                _apply_dist_codes(fh, codes, beam_idx=bidx)
                if args.op1db:
                    res, srows = _sweep_op1db(
                        bench, args, prefix=list(codes),
                        rail_names=rail_names, log=lambda *a: None)
                    sweep_rows.extend(srows)
                    gain = res["g_ref"]
                    op1 = res["op1db_pout"]
                    ip1 = res["ip1db_pin"]
                    # 요약행의 전류는 소신호 지점 값이어야 레퍼런스와 비교된다.
                    sg.set_level(float(args.pin_start_dbm))
                    time.sleep(args.settle_s)
                    pout = float("nan")
                else:
                    pout = sa.measure_peak_dbm()
                    gain = pout - args.sg_level_dbm
                    op1 = ip1 = None
                # 전류는 RF 를 건 상태에서 다시 읽는다. screen_dist_grid 가 잰 값은
                # RF OFF 정지전류라, DIST 를 올릴 때 따라 오르는 PA 전류가 안 보인다
                # (실측: (63,63,0) 에서 FE1 이 RF OFF 26.8 mA vs RF ON 31.3 mA).
                # Sivers 레퍼런스도 구동 상태에서 잰 값이므로 그쪽과 맞춰야 한다.
                rails = read_rails_ma(bench, avg_n=cfg.avg_n,
                                      settle_s=cfg.settle_s)
                rail_cols = sorted(rails)
                row = [codes[0], codes[1], codes[2], round(gain, 2)]
                if args.op1db:
                    row += ["" if op1 is None else round(op1, 2),
                            "" if ip1 is None else round(ip1, 2)]
                else:
                    row += [round(pout, 2)]
                row += [round(rails[r], 2) for r in rail_cols]
                rows.append(row)
                scored.append((codes, gain, rails, op1))
                if best is None or gain > best[1]:
                    best = (codes, gain, rails, op1)
                extra = ("" if not args.op1db else
                         ("  OP1dB=" + ("n/a" if op1 is None else f"{op1:+.2f} dBm")))
                print(f"[bias-match] dist {list(codes)}: gain={gain:+.2f} dB{extra}  "
                      + "  ".join(f"{r}={rails[r]:.2f}" for r in rail_cols))
            sens = gain_sensitivity([(c, g) for c, g, *_ in scored])
            for row, (codes, _g, _r, *_rest) in zip(rows, scored):
                sv = sens.get(codes)
                row.append("" if sv is None else round(sv, 3))
            print(f"\n[bias-match] highest gain {best[1]:+.2f} dB at "
                  f"dist {list(best[0])}")
            pick = best
            if args.op1db and args.gain_target_db is not None:
                # 우선순위: (1) 전류는 --ptat 로 이미 고정, (2) 게인이 창 안,
                # (3) 그 안에서 OP1dB 최대. 사용자가 제시한 판정 순서 그대로다.
                inwin = [t for t in scored
                         if abs(t[1] - args.gain_target_db) <= args.gain_tol_db
                         and t[3] is not None]
                pool = inwin or [t for t in scored if t[3] is not None]
                if not inwin and pool:
                    print(f"[bias-match] no combination landed within "
                          f"{args.gain_tol_db:.2f} dB of the gain target -- "
                          "ranking every point that produced an OP1dB instead")
                if pool:
                    pool.sort(key=lambda t: -t[3])
                    pick = pool[0]
                    print(f"\n[bias-match] best OP1dB inside the gain window: "
                          f"dist {list(pick[0])}  OP1dB={pick[3]:+.2f} dBm  "
                          f"gain={pick[1]:+.2f} dB")
                    print("[bias-match] ranked by OP1dB (gain window "
                          f"{args.gain_target_db:+.2f} +/- {args.gain_tol_db:.2f} dB):")
                    for codes, gain, rails, o in pool[:10]:
                        fe1 = rails.get("FE1_4V0", float("nan"))
                        mark = "" if abs(gain - args.gain_target_db) <= args.gain_tol_db \
                            else "  (gain out of window)"
                        print(f"    dist {str(list(codes)):14} "
                              f"OP1dB={o:+7.2f} dBm  gain={gain:+7.2f} dB  "
                              f"FE1={fe1:6.2f} mA{mark}")
                else:
                    print("[bias-match] no combination produced an OP1dB -- "
                          "widen --pin-stop-dbm; the sweep never compressed")
            elif args.gain_target_db is not None:
                scored.sort(key=lambda t: abs(t[1] - args.gain_target_db))
                pick = scored[0]
                print(f"[bias-match] closest to the "
                      f"{args.gain_target_db:+.2f} dB gain target: "
                      f"dist {list(pick[0])} at {pick[1]:+.2f} dB")
                print("[bias-match] ranked by |gain - target|  "
                      "(sens = local |dGain/dcode|; lower is a steadier point):")
                for codes, gain, rails, *_ in scored[:10]:
                    fe1 = rails.get("FE1_4V0", float("nan"))
                    sv = sens.get(codes)
                    sv_s = "   n/a" if sv is None else f"{sv:6.3f}"
                    print(f"    dist {str(list(codes)):14} "
                          f"gain={gain:+7.2f} dB "
                          f"(d={gain - args.gain_target_db:+6.2f})  "
                          f"sens={sv_s} dB/code  "
                          f"FE1={fe1:6.2f} mA  "
                          f"{DIST_RAIL}={rails[DIST_RAIL]:6.2f} mA")
                # 목표 오차가 tol 안인 점들 중 가장 둔감한 점을 따로 알려준다.
                near = [(c, g, r) for c, g, r, *_ in scored
                        if abs(g - args.gain_target_db) <= args.gain_tol_db
                        and sens.get(c) is not None]
                if near:
                    flat = min(near, key=lambda t: sens[t[0]])
                    print(f"[bias-match] steadiest point within "
                          f"{args.gain_tol_db:.2f} dB of target: "
                          f"dist {list(flat[0])} at {flat[1]:+.2f} dB, "
                          f"sens={sens[flat[0]]:.3f} dB/code")
            _apply_dist_codes(fh, pick[0], beam_idx=bidx)
            print(f"[bias-match] left the chip at dist {list(pick[0])}")
            restore_dist = False
    finally:
        # cmd_verify 와 같은 패턴: 정리 단계마다 자기 try/except 를 둬서
        # 앞 단계가 실패해도 뒤 단계(특히 CSV 기록과 소켓 close)가 스킵되지 않게 한다.
        try:
            bench.sg.rf_output(False)
        except Exception as e:  # noqa: BLE001
            print(f"[bias-match] RF output off FAILED: {e}")
        try:
            if restore_dist:
                _apply_dist_codes(fh, orig_dist, beam_idx=bidx)
                print(f"[bias-match] DIST codes restored to {orig_dist}")
        except Exception as e:  # noqa: BLE001
            print(f"[bias-match] RESTORE FAILED: DIST codes could not be "
                  f"restored to {orig_dist}: {e} -- check the chip before "
                  f"further measurements")
        finally:
            try:
                # rows 가 비어도(=in-window 조합 없음) 헤더만 있는 CSV 를 남긴다 --
                # '아무것도 안 걸렸다'는 것 자체가 기록할 결과다.
                summary_path = args.csv or _default_csv("distgain")
                rail_cols = sorted(rail_limits_ma(bench))
                cols = ["dist_st1", "dist_st2_0", "dist_st2_1", "Gain_dB"]
                cols += (["OP1dB_dBm", "IP1dB_dBm"] if args.op1db
                         else ["Pout_dBm"])
                cols += [f"{r}_mA" for r in rail_cols]
                if rows and len(rows[0]) > len(cols):
                    cols += ["dGain_dcode"]
                write_csv(summary_path, cols, rows,
                          meta_dict(args, bench, beam, ch))
                if sweep_rows:
                    # 스윕 원본을 따로 남긴다 -- 압축이 어디서 시작하는지(PA 한계인지
                    # 앞단 한계인지)는 Pin 마다의 FE1 전류로만 판별된다.
                    sweep_path = summary_path.with_name(
                        summary_path.stem + "_sweep" + summary_path.suffix)
                    write_csv(sweep_path,
                              ["dist_st1", "dist_st2_0", "dist_st2_1",
                               "SG_dBm", "Pin_dBm", "Pout_dBm", "Gain_dB"]
                              + rail_vi_columns(rail_names),
                              sweep_rows, meta_dict(args, bench, beam, ch))
            finally:
                bench.close_all()
                print("[bias-match] sockets closed. (power left as-is)")
    return 0


def _add_common(p) -> None:
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--beam", default=None,
                   help="beam to route to (default: bench.toml beam)")
    p.add_argument("--ch", default="h0", help="channel to measure (default h0)")
    p.add_argument("--split", action=argparse.BooleanOptionalAction,
                   default=None,
                   help="DIST splitter mode. Omit to follow split_mode in "
                        "bench.toml (currently split), which is what the Sivers "
                        "reference results were taken in. Pass --no-split only "
                        "to measure thru deliberately; the two modes differ by "
                        "about 8 dB of gain, so a mode mismatch invalidates any "
                        "comparison against their file.")
    p.add_argument("--ptat", default=None, metavar="C1,C2,C3",
                   help="FE bias codes ptat_st1,ptat_st2,ptat_st3 to write after "
                        "bring-up (e.g. 18,55,61 from a solve run). Omit to keep "
                        "the bring-up values.")
    p.add_argument("--dist", default=None, metavar="C1,C2,C3",
                   help="DIST bias codes st1,st2_0,st2_1 to write after bring-up. "
                        "Omit to keep the bring-up values.")
    p.add_argument("--fe-extra", dest="fe_extra", default=None, metavar="CTAT,CBIAS",
                   help="FE bias columns 3,4 (CTAT, FE_CBIAS), 0..63 each. These "
                        "normally keep the die eFuse trim; pass them only to "
                        "explore. Omit to keep the bring-up values.")
    p.add_argument("--dist-cbias", dest="dist_cbias", default=None,
                   metavar="C1,C2_0,C2_1",
                   help="DIST bias columns 3,4,5 (cbias1, cbias2_0, cbias2_1). "
                        "These are 3-bit, 0..7 -- not 0..63 like the PTAT codes. "
                        "bring-up leaves them at the v4 Casper value (cbias1=6).")
    p.add_argument("--ambient-c", type=float, default=None,
                   help="ambient temperature [C], recorded in the CSV. Optional. "
                        "The PTAT field name implies the bias current tracks "
                        "absolute temperature, so logging it helps explain a "
                        "later deviation; Sivers did not ask for it and their "
                        "reference CSV has no temperature column.")
    p.add_argument("--csv", type=Path, default=None, help="CSV output path")
    p.add_argument("--no-power", action="store_true",
                   help="skip PSU ramp-up (already powered)")
    p.add_argument("--fake", action="store_true",
                   help="run without hardware (currents are static -- the solve "
                        "will not converge; structure check only)")


def _add_jacobian_opts(p) -> None:
    """Options that only the Jacobian-running subcommands (jacobian, solve) use."""
    p.add_argument("--delta", type=int, default=8,
                   help="code perturbation for the Jacobian (default 8)")
    p.add_argument("--noise-ma", type=float, default=NOISE_MA,
                   help=f"below this rail change a knob counts as dead "
                        f"(default {NOISE_MA})")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Match EVB bias codes to the Sivers reference IC currents")
    sub = p.add_subparsers(dest="cmd", required=True)
    pj = sub.add_parser("jacobian", help="measure the dI/dcode matrix")
    pj.add_argument("--all-knobs", dest="all_knobs", action="store_true",
                    help="also probe the five columns solve never touches "
                         "(fe_ctat, fe_cbias, dist_cbias1/2_0/2_1). Costs 3 more "
                         "measurement points per knob.")
    _add_common(pj)
    _add_jacobian_opts(pj)
    ps = sub.add_parser("solve", help="solve the six codes to the targets")
    _add_common(ps)
    _add_jacobian_opts(ps)
    ps.add_argument("--rf", action="store_true",
                    help="solve with RF applied, so the currents matched are "
                         "the ones under drive -- which is how the reference "
                         "file was measured. Without it the quiescent current "
                         "is matched instead, and the PA rail then reads high "
                         "once drive is applied.")
    ps.add_argument("--rf-freq-ghz", type=float, default=27.5,
                    help="CW frequency for --rf [GHz] (default 27.5, the "
                         "frequency the reference gain is quoted at)")
    ps.add_argument("--sg-level-dbm", type=float, default=-28.0,
                    help="chip-input power for --rf [dBm], path-loss compensated")
    ps.add_argument("--sa-ref-dbm", type=float, default=10.0,
                    help="SA reference level for --rf [dBm]")
    ps.add_argument("--sa-span-hz", type=float, default=100.0e6,
                    help="SA span for --rf [Hz]")
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
    pd = sub.add_parser("dist-gain",
                        help="max gain on the DIST-current-constrained surface")
    _add_common(pd)
    pd.add_argument("--target-ma", type=float, default=None,
                    help=f"{DIST_RAIL} current to hold [mA]. Default: the "
                         "[bias_match] target for that rail, if one is set.")
    pd.add_argument("--st1", default=None, metavar="LIST",
                    help="dist_st1 codes to sweep, e.g. 63 or 0,32,63. "
                         "Default: the --grid-step grid.")
    pd.add_argument("--st2-0", default=None, metavar="LIST",
                    help="dist_st2_0 codes to sweep. Default: the grid.")
    pd.add_argument("--st2-1", default=None, metavar="LIST",
                    help="dist_st2_1 codes to sweep. Default: the grid.")
    pd.add_argument("--op1db", action="store_true",
                    help="sweep input power at each combination and report the "
                         "1-dB compression point as well as the small-signal "
                         "gain, then rank by OP1dB inside the gain window. Uses "
                         "the same sweep and compression maths as the op1db "
                         "test item.")
    pd.add_argument("--pin-start-dbm", type=float, default=-16.0,
                    help="--op1db sweep start [dBm] (default -16)")
    pd.add_argument("--pin-stop-dbm", type=float, default=2.0,
                    help="--op1db sweep stop [dBm] (default +2)")
    pd.add_argument("--pin-step-db", type=float, default=1.0,
                    help="--op1db sweep step [dB] (default 1)")
    pd.add_argument("--sa-ref-op1db-dbm", type=float, default=25.0,
                    help="SA reference level used in --op1db mode [dBm]. The "
                         "small-signal level would clip near compression.")
    pd.add_argument("--ref-skip-pts", type=int, default=1,
                    help="--op1db: sweep points to skip before the reference gain")
    pd.add_argument("--ref-avg-pts", type=int, default=2,
                    help="--op1db: points averaged for the reference gain")
    pd.add_argument("--settle-s", type=float, default=0.2,
                    help="--op1db: settle [s] after each SG level change")
    pd.add_argument("--gain-tol-db", type=float, default=0.5,
                    help="with --gain-target-db, how close counts as on target "
                         "when picking the steadiest point (default 0.5 dB)")
    pd.add_argument("--gain-target-db", type=float, default=None,
                    help="rank results by closeness to this gain instead of "
                         "reporting only the maximum, and leave the chip on "
                         "the closest point (e.g. 23.1 to match the reference)")
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
    args = p.parse_args(argv)
    if args.ambient_c is None:
        print("[bias-match] note: --ambient-c not given, so no temperature is "
              "recorded in the CSV. Not required -- it only helps explain a "
              "later deviation, since PTAT bias tracks absolute temperature.")
    return {"jacobian": cmd_jacobian, "solve": cmd_solve,
            "verify": cmd_verify, "dist-gain": cmd_dist_gain}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
