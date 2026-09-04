"""한 채널의 bias 코드를 찾아 `bench.toml` 에 되돌려 적는 최소 절차.

`bias_match` 의 CLI 서브커맨드들(jacobian/solve/dist-gain)을 사람이 네 번 나눠
돌리던 흐름을, 살아 있는 세션 안에서 한 번에 도는 함수로 묶은 것이다. 전원 사이클도
bring-up 도 하지 않는다 -- 채널을 바꾸려면 케이블을 손으로 옮겨야 하므로, 자동으로
채널을 순회하는 건 이 장비에선 의미가 없다.

4단계 (2026-09-03 h0 에서 확립한 절차 그대로):
  A.  PTAT 3열을 Sivers 레퍼런스 전류에 매칭 (FE1/FE2/FE3, 자코비안 -> 이분탐색)
  B/C. DIST 3열 그리드를 한 번 순회 -- 조합마다 레일 1회 + 게인 1점을 재서
       전류 창(폭주 방지)과 게인 창(19..25 dB, split 행)으로 거른다
  D.  남은 후보를 파워 스윕해 OP1dB 최대점 선택
  A'. 확정된 DIST 위에서 PTAT 재매칭 + 확인 측정 -> bench.toml 기입

A' 가 필요한 이유: FE1 은 자기 PTAT 뿐 아니라 DIST 코드에도 끌려간다(2026-09-04 h0
실측에서 같은 PTAT 로 27.1~30.3 mA). A 는 탐색 시작 시점의 DIST 위에서 맞춘 값이라
D 가 DIST 를 바꾸고 나면 타깃에서 벗어나 있다.

선택 규칙: OP1dB 최대. 단 OP1dB 가 `op1db_tol_db` 안에서 동률이면 DIST 전류가 큰
쪽을 고른다 -- h0 에서 `dist_st2_1 = 63` 을 고른 근거와 같다(성능은 그대로 두고
레퍼런스 IDC_Dist 에 더 붙는 축).

전류 창은 '선택'이 아니라 '폭주 방지' 장치다. 레퍼런스 IDC_Dist(64.4 mA)는 게인
max 25 dB 를 깨지 않고는 도달할 수 없음이 h0 에서 증명됐다(스펙 인 상한 48.7 mA).

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from .bias_match import (
    CODE_MAX, CODE_MIN, DIST_KNOBS, DIST_RAIL, FE_KNOBS, _default_csv,
    _read_all_codes, _restore_all_codes, _setup_rf_point, _sweep_op1db,
    _apply_dist_codes, beam_index, bisect_knob, directions_from_jacobian,
    load_bias_match_cfg, measure_jacobian, nonmonotonic_knobs, read_knob,
    read_rails_ma, refine_knob, scan_knob, write_csv, REFINE_STEPS,
)
from .board.bias_measured import write_measured_bias
from .board.firehawk import fe_row, parse_ch
from .setup_tx import DEFAULT_CONFIG
from .test_items.base import psu_rail_names


@dataclass
class FindBiasOpts:
    """탐색 파라미터. 기본값은 h0 를 확정할 때 쓴 조건과 같다."""

    # A 단계 -- 전류 매칭. Sivers 레퍼런스가 측정된 조건(27.5 GHz, Pin -28.27 dBm).
    match_freq_ghz: float = 27.5
    delta: int = 8                    # 자코비안 섭동 코드 수
    # B/C/D 단계 -- 성능 평가. 28 GHz 가 우리 기준 주파수다.
    freq_ghz: float = 28.0
    sg_level_dbm: float = -28.0       # 경로손실 보정된 칩 입력 전력
    sa_span_hz: float = 100.0e6
    sa_ref_dbm: float = 20.0
    sa_ref_op1db_dbm: float = 25.0    # 압축까지 밀면 소신호용 ref 는 클리핑한다
    grid_step: int = 16               # DIST 코드 그리드 간격(63 은 항상 포함)
    # 전류 창은 폭주 방지용이다 -- 기본값은 0..2*target 이라 사실상 전부 통과한다.
    window_ma: float = 64.0
    gain_min_db: float = 19.0         # 데이터시트 p14 All channels 2beam(split) 행
    gain_max_db: float = 25.0
    max_op1db: int = 12               # OP1dB 를 스윕할 후보 수 상한(시간 상한)
    op1db_tol_db: float = 0.3         # 이 안이면 동률로 보고 전류가 큰 쪽을 고른다
    # OP1dB 스윕(op1db 테스트 항목과 같은 수식을 쓴다)
    pin_start_dbm: float = -22.0
    pin_stop_dbm: float = 10.0
    pin_step_db: float = 1.0
    settle_s: float = 0.2
    ref_skip_pts: int = 1
    ref_avg_pts: int = 2
    # A' -- DIST 확정 뒤 PTAT 재매칭. FE1 이 DIST 에도 끌려가므로 A 한 번으로는
    # 최종 동작점에서 타깃을 벗어난다. 끄면 +2~3분을 아끼는 대신 그 오차가 남는다.
    rematch_ptat: bool = True
    rematch_warn_db: float = 0.5      # 재매칭이 성능을 이보다 흔들면 경고한다
    # 이분탐색 뒤 이웃 코드를 다시 훑을 칸 수. 0 이면 끈다.
    refine_steps: int = REFINE_STEPS


@dataclass
class FindBiasResult:
    """탐색 결과. `dist is None` 이면 게인 창을 통과한 조합이 없었다는 뜻이다."""

    channel: str
    beam: str
    ptat: list[int]
    dist: list[int] | None = None
    gain_db: float | None = None
    op1db_dbm: float | None = None
    rails_ma: dict = field(default_factory=dict)
    targets_ma: dict = field(default_factory=dict)
    candidates: list = field(default_factory=list)
    csv_path: Path | None = None
    written: bool = False
    rematched: bool = False       # A' 를 돌았는가(= 성능 수치가 재측정값인가)
    # B~D 를 도는 동안 걸려 있던 PTAT. A' 가 이걸 바꾸므로 후보 표(CSV)의 게인/OP1dB
    # 는 이 값에서 잰 것이고, 최종 `ptat` 와 다를 수 있다.
    ptat_scan: list[int] = field(default_factory=list)

    def __str__(self) -> str:
        if self.dist is None:
            return (f"find_bias {self.channel}/{self.beam}: no combination "
                    "passed the gain window")
        return (f"find_bias {self.channel}/{self.beam}: ptat={self.ptat} "
                f"dist={self.dist}  gain={self.gain_db:+.2f} dB  "
                f"OP1dB={self.op1db_dbm:+.2f} dBm")


def _rf_args(opts: FindBiasOpts, *, sa_ref_dbm: float | None = None):
    """`bias_match` 의 RF 헬퍼들이 기대하는 argparse 네임스페이스를 흉내낸다.

    같은 SG/SA 설정 코드와 같은 OP1dB 수식을 쓰기 위해서다 -- 여기서 따로 구현하면
    op1db 테스트 항목과 압축점 정의가 갈라진다.
    """
    return SimpleNamespace(
        sg_level_dbm=opts.sg_level_dbm,
        sa_span_hz=opts.sa_span_hz,
        sa_ref_dbm=opts.sa_ref_dbm if sa_ref_dbm is None else sa_ref_dbm,
        pin_start_dbm=opts.pin_start_dbm, pin_stop_dbm=opts.pin_stop_dbm,
        pin_step_db=opts.pin_step_db, settle_s=opts.settle_s,
        ref_skip_pts=opts.ref_skip_pts, ref_avg_pts=opts.ref_avg_pts,
    )


def dist_grid(step: int) -> list[list[int]]:
    """축마다 같은 코드 그리드. 상한 63 은 반드시 포함한다.

    range(0, 64, 16) 은 48 에서 끝나 63 을 건너뛴다 -- h0 의 확정값이 [63, 16, 63]
    이었으므로 끝점을 빠뜨리면 정답이 후보에 없다.
    """
    codes = sorted(set(range(CODE_MIN, CODE_MAX + 1, max(1, int(step)))) | {CODE_MAX})
    return [list(codes) for _ in DIST_KNOBS]


def match_ptat(bench, fh, *, row: int, beam_idx: int, cfg, delta: int = 8,
               refine_steps: int = REFINE_STEPS, log=print) -> list[int]:
    """A 단계: FE 3열을 각자의 레일 타깃 전류로 몬다.

    자코비안으로 방향(코드가 오르면 전류가 오르는가)과 단조성을 먼저 보고, 단조면
    이분탐색, 아니면 전 범위 선형 스캔으로 간다 -- `solve_bias` 와 같은 판단이지만
    DIST 는 건드리지 않는다(DIST 는 B~D 단계가 성능 기준으로 따로 정한다).
    """
    _base, _codes, rows = measure_jacobian(bench, fh, row=row, beam_idx=beam_idx,
                                           cfg=cfg, delta=delta, knobs=FE_KNOBS,
                                           log=log)
    dirs = directions_from_jacobian(rows)
    nonmono = set(nonmonotonic_knobs(rows))
    for kn in FE_KNOBS:
        target = cfg.targets_ma.get(kn.rail)
        if target is None:
            log(f"[find-bias] {kn.name}: no target for {kn.rail}, left as-is")
            continue
        if kn.name not in dirs:
            log(f"[find-bias] {kn.name}: NO RESPONSE, left as-is")
            continue
        if kn.name in nonmono:
            log(f"[find-bias] WARNING: {kn.name} is non-monotonic -- "
                "falling back to a full linear scan")
            code, cur, err = scan_knob(bench, fh, kn, target, row=row,
                                       beam_idx=beam_idx, cfg=cfg, log=log)
        else:
            code, cur, err = bisect_knob(bench, fh, kn, target, row=row,
                                         beam_idx=beam_idx, cfg=cfg,
                                         rising=dirs[kn.name], log=log)
            # 이분탐색은 몇 분 간격으로, 다른 다이 온도에서 잰 값들을 비교한다.
            # 마지막에 이웃 코드를 연달아 재서 국소 최적인지 확인한다.
            if refine_steps > 0:
                code, cur, err = refine_knob(bench, fh, kn, target, row=row,
                                             beam_idx=beam_idx, cfg=cfg,
                                             start=code, max_steps=refine_steps,
                                             log=log)
        log(f"[find-bias] {kn.name} = {code}  {kn.rail}={cur:.2f} mA "
            f"(target {target:.2f}, err {err:+.2f})")
    return [read_knob(fh, kn, row=row, beam_idx=beam_idx) for kn in FE_KNOBS]


def find_bias(bench, fh, *, channel: str, beam: str, cfg=None,
              opts: FindBiasOpts | None = None, config_path=DEFAULT_CONFIG,
              measure_gain=None, measure_op1db=None, write_config: bool = True,
              log=print) -> FindBiasResult:
    """Find one channel's bias codes and record them in the bench TOML.

    Runs four stages on the channel that is already routed and cabled: match
    the PTAT codes to the reference rail currents, screen the DIST grid on
    current, keep only the combinations inside the datasheet gain window, then
    pick the highest OP1dB among those. Ties in OP1dB go to the higher DIST
    current, which is the choice that sits closest to the reference.

    The PTAT codes are then matched a second time on the chosen DIST codes,
    because the PA rail follows the DIST setting as well as its own code, and
    the performance is measured again at that final bias. Pass
    rematch_ptat=False to skip both and save a few minutes.

    No power cycle and no bring-up: the caller moves the cable and selects the
    channel first. The chip is left on the chosen codes so a measurement can
    follow immediately; on failure every code is put back.
    """
    opts = opts or FindBiasOpts()
    cfg = cfg or load_bias_match_cfg(config_path)
    name = str(channel).strip().lower()
    pol, idx = parse_ch(name)
    row, bidx = fe_row(idx, pol), beam_index(beam)
    target_ma = cfg.targets_ma.get(DIST_RAIL, 0.0)
    orig = _read_all_codes(fh, row=row, beam_idx=bidx)
    res = FindBiasResult(channel=name, beam=str(beam).strip().lower(),
                         ptat=[], targets_ma=dict(cfg.targets_ma))
    keep_codes = False
    try:
        # --- A: PTAT 전류 매칭 (레퍼런스와 같은 주파수/구동에서) --------------
        log(f"[find-bias] {name}/{beam} stage A: matching PTAT to the "
            f"reference currents at {opts.match_freq_ghz:.2f} GHz")
        _setup_rf_point(bench, _rf_args(opts), opts.match_freq_ghz * 1e9)
        bench.sg.rf_output(True)
        res.ptat = match_ptat(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                              delta=opts.delta,
                              refine_steps=opts.refine_steps, log=log)
        log(f"[find-bias] ptat = {res.ptat}")

        # --- B/C: DIST 그리드 한 번 순회 (전류 창 -> 게인 창) ----------------
        # 전류로 먼저 거르고(B) 통과분의 게인을 따로 재던(C) 구조는 조합마다 레일을
        # 두 번 읽었다. 레일 읽기는 약 8초(avg_n=3 x read_all_vi 2.55초, 2026-09-04
        # 실측)인데 SA 피크는 1초 미만이라, '싼 기준으로 먼저 거른다'는 전제가 거꾸로
        # 였다 -- 거르는 쪽이 더 비쌌다. 조합마다 한 번만 읽는다.
        log(f"[find-bias] stage B/C: sweeping the DIST grid "
            f"(step {opts.grid_step}) at {opts.freq_ghz:.2f} GHz, keeping "
            f"{opts.gain_min_db:.1f}..{opts.gain_max_db:.1f} dB")
        _setup_rf_point(bench, _rf_args(opts), opts.freq_ghz * 1e9)
        gain_of = measure_gain or (lambda _c: bench.sa.measure_peak_dbm()
                                   - opts.sg_level_dbm)
        combos = list(itertools.product(*dist_grid(opts.grid_step)))
        log(f"[find-bias] {len(combos)} combination(s), {DIST_RAIL} window "
            f"{target_ma:.1f} +/- {opts.window_ma:.1f} mA")
        cands = []
        in_current = 0
        for codes in combos:
            _apply_dist_codes(fh, codes, beam_idx=bidx)
            rails = read_rails_ma(bench, avg_n=cfg.avg_n, settle_s=cfg.settle_s)
            dist_ma = rails[DIST_RAIL]
            if abs(dist_ma - target_ma) > opts.window_ma:
                log(f"[find-bias]   dist {list(codes)}: "
                    f"{DIST_RAIL}={dist_ma:.2f} mA  (outside the current window)")
                continue
            in_current += 1
            gain = float(gain_of(list(codes)))
            inside = opts.gain_min_db <= gain <= opts.gain_max_db
            log(f"[find-bias]   dist {list(codes)}: gain={gain:+.2f} dB  "
                f"{DIST_RAIL}={dist_ma:.2f} mA"
                + ("" if inside else "  (outside the gain window)"))
            if inside:
                cands.append({"codes": tuple(codes), "gain_db": gain,
                              "rails_ma": rails, "op1db_dbm": None,
                              "ip1db_dbm": None})
        log(f"[find-bias] {in_current}/{len(combos)} inside the current window, "
            f"{len(cands)} of those inside the gain window")
        res.candidates = cands
        if not cands:
            log("[find-bias] no combination landed inside the gain window -- "
                "nothing to confirm; widen the grid or check the setup")
            return res

        # --- D: OP1dB -------------------------------------------------------
        # 전류가 큰 쪽부터 본다: 성능이 같다면 레퍼런스에 더 붙는 점이 정답이고,
        # 스윕은 점당 20~30초라 상한을 둬야 한다.
        cands.sort(key=lambda c: -c["rails_ma"][DIST_RAIL])
        pool = cands[:max(1, int(opts.max_op1db))]
        log(f"[find-bias] stage D: OP1dB sweep on {len(pool)} of "
            f"{len(cands)} candidate(s), highest {DIST_RAIL} first")
        op_args = _rf_args(opts, sa_ref_dbm=opts.sa_ref_op1db_dbm)
        rail_names = psu_rail_names(bench)
        if measure_op1db is None:
            _setup_rf_point(bench, op_args, opts.freq_ghz * 1e9)

        def _real_sweep(codes):
            out = _sweep_op1db(bench, op_args, prefix=list(codes),
                               rail_names=rail_names, log=lambda *a: None)
            # 스윕은 압축까지 밀고 끝난다 -- 그대로 두면 이어지는 전류 읽기가 구동
            # 상태 값이 된다. 레퍼런스와 비교되는 건 소신호 지점 전류다.
            bench.sg.set_level(float(opts.pin_start_dbm))
            time.sleep(opts.settle_s)
            return out

        sweep_of = measure_op1db or _real_sweep
        sweep_rows: list[list] = []
        for cand in pool:
            _apply_dist_codes(fh, cand["codes"], beam_idx=bidx)
            out, rows = sweep_of(list(cand["codes"]))
            sweep_rows.extend(rows or [])
            cand["op1db_dbm"] = (None if out.get("op1db_pout") is None
                                 else float(out["op1db_pout"]))
            cand["ip1db_dbm"] = (None if out.get("ip1db_pin") is None
                                 else float(out["ip1db_pin"]))
            log(f"[find-bias]   dist {list(cand['codes'])}: "
                f"OP1dB={_fmt(cand['op1db_dbm'])} dBm  "
                f"gain={cand['gain_db']:+.2f} dB")
        scored = [c for c in pool if c["op1db_dbm"] is not None]
        if not scored:
            log("[find-bias] no candidate compressed -- raise --pin-stop-dbm; "
                "nothing confirmed")
            return res
        best = max(c["op1db_dbm"] for c in scored)
        tied = [c for c in scored if best - c["op1db_dbm"] <= opts.op1db_tol_db]
        pick = max(tied, key=lambda c: c["rails_ma"][DIST_RAIL])
        if len(tied) > 1:
            log(f"[find-bias] {len(tied)} candidate(s) within "
                f"{opts.op1db_tol_db:.2f} dB of the best OP1dB -- taking the "
                f"one with the highest {DIST_RAIL}")
        res.dist = list(pick["codes"])
        res.gain_db = pick["gain_db"]
        res.op1db_dbm = pick["op1db_dbm"]
        _apply_dist_codes(fh, pick["codes"], beam_idx=bidx)
        keep_codes = True

        # --- A': 확정 DIST 위에서 PTAT 재매칭 --------------------------------
        # FE1 은 자기 PTAT 뿐 아니라 DIST 코드에도 끌려간다(2026-09-04 h0 실측:
        # 같은 PTAT 에서 DIST 조합에 따라 27.1~30.3 mA). A 단계는 탐색 시작 시점의
        # DIST 위에서 맞춘 것이라, D 가 DIST 를 바꾸고 나면 타깃에서 벗어나 있다.
        if opts.rematch_ptat:
            was = (res.gain_db, res.op1db_dbm)
            res.ptat_scan = list(res.ptat)
            log("[find-bias] stage A': re-matching PTAT on the chosen DIST codes")
            _setup_rf_point(bench, _rf_args(opts), opts.match_freq_ghz * 1e9)
            res.ptat = match_ptat(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                                  delta=opts.delta,
                                  refine_steps=opts.refine_steps, log=log)
            # A' 가 FE bias 를 바꿨으므로 D 단계에서 잰 성능은 더 이상 이 동작점의
            # 값이 아니다. 그 숫자가 bench.toml 주석과 보고서로 나가므로 다시 잰다.
            _setup_rf_point(bench, _rf_args(opts), opts.freq_ghz * 1e9)
            res.gain_db = float(gain_of(list(pick["codes"])))
            if measure_op1db is None:
                _setup_rf_point(bench, op_args, opts.freq_ghz * 1e9)
            out, _rows = sweep_of(list(pick["codes"]))
            if out.get("op1db_pout") is not None:
                res.op1db_dbm = float(out["op1db_pout"])
            res.rematched = True
            log(f"[find-bias] after re-match: ptat={res.ptat}  "
                f"gain={res.gain_db:+.2f} dB ({res.gain_db - was[0]:+.2f})  "
                f"OP1dB={_fmt(res.op1db_dbm)} dBm"
                + ("" if was[1] is None or res.op1db_dbm is None
                   else f" ({res.op1db_dbm - was[1]:+.2f})"))
            moved = [abs(res.gain_db - was[0])]
            if was[1] is not None and res.op1db_dbm is not None:
                moved.append(abs(res.op1db_dbm - was[1]))
            if max(moved) > opts.rematch_warn_db:
                log(f"[find-bias] WARNING: re-matching moved the performance by "
                    f"more than {opts.rematch_warn_db:.2f} dB. The DIST ranking "
                    "was made at the old PTAT, so another run may now pick a "
                    "different DIST combination.")
        res.rails_ma = read_rails_ma(bench, avg_n=cfg.avg_n,
                                     settle_s=cfg.settle_s)
        log(f"[find-bias] {name}/{beam}: ptat={res.ptat}  dist={res.dist}  "
            f"gain={res.gain_db:+.2f} dB  OP1dB={res.op1db_dbm:+.2f} dBm")

        if write_config:
            note = (f"{name}/{beam} {opts.freq_ghz:.1f} GHz: "
                    f"gain {res.gain_db:.2f} dB, OP1dB {res.op1db_dbm:.2f} dBm, "
                    f"{DIST_RAIL} {res.rails_ma[DIST_RAIL]:.1f} mA")
            write_measured_bias(config_path, name, ptat=res.ptat,
                                dist=res.dist, note=note)
            res.written = True
            log(f"[find-bias] written to {config_path} [board.bias.{name}] -- "
                "the next bring-up applies it automatically")
        res.csv_path = _write_csv(res, cands, sweep_rows, bench, opts, rail_names)
        return res
    finally:
        try:
            bench.sg.rf_output(False)
        except Exception as e:                                  # noqa: BLE001
            log(f"[find-bias] RF output off FAILED: {e}")
        if not keep_codes:
            try:
                _restore_all_codes(fh, orig, row=row, beam_idx=bidx)
                log("[find-bias] bias codes restored to the pre-run values")
            except Exception as e:                              # noqa: BLE001
                log(f"[find-bias] RESTORE FAILED: bias codes could not be put "
                    f"back to {orig}: {e} -- check the chip before measuring")


def _fmt(v) -> str:
    return "  n/a" if v is None else f"{v:+.2f}"


def _write_csv(res: FindBiasResult, cands, sweep_rows, bench, opts,
               rail_names) -> Path | None:
    """후보 표와 (있으면) 스윕 원본을 CSV 로 남긴다. 실패해도 결과는 유효하다."""
    try:
        rails = sorted(next(iter(cands))["rails_ma"]) if cands else []
        cols = (["dist_st1", "dist_st2_0", "dist_st2_1", "Gain_dB",
                 "OP1dB_dBm", "IP1dB_dBm"] + [f"{r}_mA" for r in rails]
                + ["chosen"])
        rows = []
        for c in sorted(cands, key=lambda c: -c["rails_ma"][DIST_RAIL]):
            rows.append(list(c["codes"])
                        + [round(c["gain_db"], 2),
                           "" if c["op1db_dbm"] is None else round(c["op1db_dbm"], 2),
                           "" if c["ip1db_dbm"] is None else round(c["ip1db_dbm"], 2)]
                        + [round(c["rails_ma"][r], 2) for r in rails]
                        + ["yes" if res.dist and list(c["codes"]) == res.dist else ""])
        # 표의 게인/OP1dB 는 ptat_scan 에서 잰 값이다. A' 가 PTAT 을 바꿨다면
        # 최종 ptat 와 다르므로 둘 다 남긴다 -- 안 그러면 나중에 이 CSV 를 최종
        # 동작점의 스윕으로 오해한다.
        scan_ptat = res.ptat_scan or res.ptat
        meta = {"tool": "find_bias", "channel": res.channel, "beam": res.beam,
                "ptat": "|".join(str(v) for v in res.ptat),
                "ptat_during_scan": "|".join(str(v) for v in scan_ptat),
                "rematched": res.rematched,
                "dist": "" if res.dist is None else "|".join(str(v) for v in res.dist),
                "gain_db": "" if res.gain_db is None else round(res.gain_db, 2),
                "op1db_dbm": ("" if res.op1db_dbm is None
                              else round(res.op1db_dbm, 2)),
                "freq_ghz": opts.freq_ghz, "sg_level_dbm": opts.sg_level_dbm,
                "gain_window_db": f"{opts.gain_min_db}..{opts.gain_max_db}"}
        path = _default_csv(f"find_{res.channel}")
        write_csv(path, cols, rows, meta)
        return path
    except Exception as e:                                      # noqa: BLE001
        print(f"[find-bias] CSV write FAILED: {e} (result is still valid)")
        return None
