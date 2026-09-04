"""Test Item: OP1dB Test (output 1-dB compression point).

목적: 고정된 동작 게인에서 CW 입력 전력(SG 레벨)을 sweep 하며, 이득이 소신호(선형)
이득보다 1 dB 낮아지는 지점의 '출력 전력'(OP1dB)을 구한다.

측정 구성(TX): SG(CW, 전력 sweep) → [입력 케이블 손실] → 보드 입력 → 보드 →
보드 출력(beam 포트) → [출력 케이블+외부 감쇠기 손실] → SA(피크 전력 측정).

알고리즘은 MATLAB 측정코드 'Meas_260518_STMPD01_Psweep_NChNPolNBm_OP1dB.m' 을 이식했다:
  - Pin(칩 입력) = SG 레벨 - 입력경로 손실(in_loss_db)
  - Pout(칩 출력) = SA 측정값 + 출력경로 손실(out_loss_db)   # 손실만큼 되더해 칩 출력 복원
  - Gain = Pout - Pin
  - 기준(소신호) 이득 g_ref = sweep 앞쪽 일부 점의 평균. 단 MATLAB 과 동일하게
    맨 앞 ref_skip_pts 점은 버린다(bias 미최적화 시 첫 점이 튀는 것을 피하려고).
  - OP1dB = 이득 최대 지점(idx_max) '이후'(하강 구간)에서 Gain 이 (g_ref-1dB) 가
    되는 지점의 Pout. (peak 가 마지막 점이면 아직 압축 전 -> OP1dB 없음.)

채널 선택: 어느 채널/빔을 켜는지는 이 테스트가 아니라 보드 bring-up 이 결정한다
(config/bench.toml 의 [board].active_channels). SA 는 beam 출력 포트 1개를 보므로,
H0 만 켜면 H0 기여만, 여러 채널을 켜면 합쳐진 출력을 측정한다. 따라서 "한 채널만"
또는 "여러 채널"은 bench.toml 만 바꾸면 된다(코드 수정 불필요).

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import time

from ..board.gain_map import resolve_gain_params, set_gain
from .base import (
    Param,
    TestContext,
    TestItem,
    TestResult,
    psu_rail_names,
    rail_idd_ma,
    rail_vi_columns,
    read_rail_vi,
)


def _interp_frac(prev: float, cur: float, target: float) -> float:
    """prev->cur 구간에서 값이 target 이 되는 위치 비율(0~1). 평탄하면 0."""
    return 0.0 if prev == cur else (prev - target) / (prev - cur)


def compute_op1db(sg_levels: list[float], pins: list[float], pouts: list[float],
                  gains: list[float], ref_skip: int, ref_avg: int) -> dict:
    """OP1dB 계산(MATLAB 이식). 측정 배열만 받아 순수 계산하므로 단위테스트가 쉽다.

    반환 dict: g_ref(소신호 이득), op1db_pout / ip1db_pin / sg_at_op1db
               (압축점에서의 Pout/Pin/SG 레벨; 압축점이 없으면 None).
    """
    n = len(gains)
    # 1) 기준(소신호) 이득: 앞쪽 ref_skip 점을 건너뛰고 이어지는 ref_avg 점 평균.
    start = min(ref_skip, max(0, n - 1))
    sel = gains[start:start + ref_avg] or gains[:1]
    g_ref = sum(sel) / len(sel)
    target = g_ref - 1.0

    # 2) 이득이 최대인 지점(피크). 압축은 이 지점 '이후' 하강 구간에서만 의미가 있다.
    idx_max = max(range(n), key=lambda i: gains[i])
    if idx_max >= n - 1:
        # 피크가 마지막 점 -> 이득이 끝까지 안 꺾임 = 아직 압축 전. (sweep 범위 확장 필요)
        return {"g_ref": g_ref, "op1db_pout": None, "ip1db_pin": None,
                "sg_at_op1db": None}

    # 3) 하강 구간에서 Gain 이 (g_ref-1dB) 로 처음 내려가는 곳을 선형 보간.
    for k in range(idx_max + 1, n):
        if gains[k] <= target:
            frac = _interp_frac(gains[k - 1], gains[k], target)
            return {
                "g_ref": g_ref,
                "op1db_pout": pouts[k - 1] + frac * (pouts[k] - pouts[k - 1]),
                "ip1db_pin": pins[k - 1] + frac * (pins[k] - pins[k - 1]),
                "sg_at_op1db": sg_levels[k - 1] + frac * (sg_levels[k] - sg_levels[k - 1]),
            }
    # 하강은 했지만 1 dB 까지는 안 떨어짐.
    return {"g_ref": g_ref, "op1db_pout": None, "ip1db_pin": None,
            "sg_at_op1db": None}


def run_power_sweep(bench, sg_levels, *, settle, rail_names, log=print,
                    prefix=None, tag=""):
    """SG 전력 sweep 1회(측정점마다 Pout/Gain + 전 레일 V/I 기록).

    op1db 와 vdd_sensitivity 가 공유한다 -- 압축점 sweep 루프가 두 벌로 갈라지지
    않게 하려는 것. SG/SA 오프셋에는 이미 경로손실이 적용돼 있으므로 SG 레벨이
    곧 칩 입력, SA 로 읽은 값이 곧 칩 출력이다.

    prefix : 각 행 앞에 붙일 고정 컬럼 값 리스트(예: [FE1 전압]). None 이면 없음.
    tag    : 로그 줄 앞에 붙일 짧은 식별자(예: "4.00V ").
    반환: (rows, pins, pouts, gains, idds)
    """
    head = list(prefix) if prefix else []
    rows: list[list] = []
    pins: list[float] = []
    pouts: list[float] = []
    gains: list[float] = []
    idds: list[float] = []
    for lvl in sg_levels:
        bench.sg.set_level(lvl)        # SG 오프셋 적용됨 -> lvl = 칩 입력 전력
        time.sleep(settle)
        pin = lvl
        pout = bench.sa.measure_peak_dbm()   # SA 오프셋 적용됨 -> 곧 칩 출력 전력
        gain = pout - pin
        rail = read_rail_vi(bench, rail_names, log)   # 전 레일 V/mA + 합산 Idd
        idds.append(rail_idd_ma(rail))
        rows.append(head + [round(lvl, 2), round(pin, 2), round(pout, 2),
                            round(gain, 2)] + rail)
        pins.append(pin)
        pouts.append(pout)
        gains.append(gain)
        log(f"  {tag}SG={lvl:+.1f} dBm  Pin={pin:+.2f}  Pout={pout:+.2f}  "
            f"Gain={gain:.2f} dB  Idd={rail_idd_ma(rail):.0f} mA")
    return rows, pins, pouts, gains, idds


class OP1dBTest(TestItem):
    id = "op1db"
    title = "OP1dB Test"
    description = ("TX: at a fixed gain, sweep CW input power and find the output "
                   "1-dB compression point (OP1dB). (RX uses ip1db instead.)")
    chips = ("tx",)   # 출력 압축 = TX(PA) 측정. RX 는 ip1db 사용.

    params = [
        Param("freq_hz", "CW Frequency", "float", 28.0e9, unit="Hz",
              help="SG CW frequency (= SA center)"),
        Param("gain_target", "Gain Target", "choice", "",
              choices=["", "common", "fe", "beamtable"],
              help="which gain knob to hold fixed: common (beam-wide), "
                   "fe (per-channel FE), beamtable (RTPS attenuator). "
                   "BLANK = common (also lets a legacy gain_field override "
                   "resolve its own target instead of being masked by this default)."),
        Param("beam", "Beam", "str", "",
              help="beam override (b0/b1/b2). BLANK = use the board beam."),
        Param("channel", "Channel", "str", "",
              help="channel override for fe/beamtable targets (e.g. h1). "
                   "BLANK = first active channel."),
        Param("gain_code", "Gain Code", "int", 0x20,
              help="gain code to hold fixed (operating point). 0=max gain"),
        # --- power sweep (SG output level) ---
        Param("pin_start_dbm", "SG Power Start", "float", -22.0, unit="dBm",
              help="SG sweep start (MATLAB default -22)"),
        Param("pin_stop_dbm", "SG Power Stop", "float", 10.0, unit="dBm",
              help="SG sweep stop (MATLAB default 10)"),
        Param("pin_step_db", "Power Step", "float", 1.0, unit="dB",
              help="sweep step size"),
        # path loss(cable + board trace)는 자동으로 SG/SA 오프셋에 적용된다
        # (bench.apply_path_loss). SG level = 칩 입력, SA read = 칩 출력.
        # --- small-signal gain reference ---
        Param("ref_skip_pts", "Ref Skip Points", "int", 1,
              help="points to skip at sweep start for reference gain calc (MATLAB default 1)"),
        Param("ref_avg_pts", "Ref Avg Points", "int", 2,
              help="points to average for reference gain (MATLAB default 2 -- 2nd & 3rd)"),
        # --- SA settings ---
        Param("sa_span_hz", "SA Span", "float", 100.0e6, unit="Hz",
              help="SA span (wide enough to contain the CW tone)"),
        Param("sa_ref_level_dbm", "SA Ref Level", "float", 25.0, unit="dBm",
              help="SA reference level. Must cover the COMPRESSED output, not the "
                   "small-signal one: Stampede Psat is ~24 dBm, so 25 dBm is the "
                   "default (instrument max is 25). Too low clips the top of the "
                   "sweep and OP1dB comes out wrong."),
        Param("settle_s", "Settle Time", "float", 0.2, unit="s",
              help="settle time after setting SG level before SA read"),
        # 전 PSU 레일 전류(+ 총 Idd)는 모든 측정점에서 자동 기록된다.
    ]

    def run(self, ctx: TestContext, params: dict, log=print) -> TestResult:
        bench = ctx.bench
        sg = bench.sg
        sa = bench.sa
        chip = ctx.chip
        params, fh, beam, channel = resolve_gain_params(params, bench, chip, log=log)
        freq = float(params["freq_hz"])
        target = params.get("gain_target") or "common"
        code = int(params["gain_code"])
        p0 = float(params["pin_start_dbm"])
        p1 = float(params["pin_stop_dbm"])
        step = float(params["pin_step_db"])
        ref_skip = int(params["ref_skip_pts"])
        ref_avg = int(params["ref_avg_pts"])
        settle = float(params["settle_s"])
        rail_names = psu_rail_names(bench)

        # SG 출력 sweep 지점(부동소수 누적오차 피하려 정수 카운트로 생성).
        n = int(round((p1 - p0) / step)) + 1
        sg_levels = [round(p0 + k * step, 3) for k in range(max(1, n))]

        # 1) 게인 고정(동작점) + SG 주파수 설정 + 경로손실 -> SG/SA 오프셋 적용.
        set_gain(fh, target, code, beam=beam, channel=channel)
        sg.modulation_off(log=log)   # CW 보장(직전 EVM 등의 ARB 파형 잔류 방지)
        sg.set_frequency(freq)
        in_loss, out_loss = bench.apply_path_loss(freq, log=log)

        # 2) SA 를 측정 주파수에 맞춰 설정(★ 이걸 안 하면 SA 가 톤이 아니라 노이즈
        #    플로어 피크를 읽는다 — 이전 평탄 측정의 원인). rbw/atten/모드는 bench.toml,
        #    center 는 측정 주파수, span/ref 는 파라미터로.
        sa_cfg = getattr(bench, "sa_cfg", {})
        sa.configure(
            center_hz=freq,
            span_hz=float(params["sa_span_hz"]),
            rbw_hz=float(sa_cfg.get("rbw_hz", 1.0e6)),
            ref_level_dbm=float(params["sa_ref_level_dbm"]),
            input_atten_db=float(sa_cfg.get("input_atten_db", 10.0)),
            spectrum_mode=bool(sa_cfg.get("spectrum_mode", True)),
            log=log,
        )

        sg.rf_output(True)
        log(f"[op1db  ] beam={beam} ch={channel}  gain_target={target}={hex(code)}, "
            f"CW {freq/1e9:.3f} GHz, SG {p0}..{p1} dBm "
            f"(in_loss={in_loss} out_loss={out_loss} dB)")

        columns = ["SG_dBm", "Pin_dBm", "Pout_dBm", "Gain_dB"] + \
            rail_vi_columns(rail_names)
        try:
            # 3) 전력 sweep(공용 헬퍼 -- vdd_sensitivity 와 같은 루프)
            rows, pins, pouts, gains, idds = run_power_sweep(
                bench, sg_levels, settle=settle, rail_names=rail_names, log=log)
        finally:
            sg.rf_output(False)  # 측정 끝나면 RF OFF(안전)

        # 4) OP1dB 계산(MATLAB 이식)
        r = compute_op1db(sg_levels, pins, pouts, gains, ref_skip, ref_avg)
        g_ref = r["g_ref"]
        op1db = r["op1db_pout"]
        ip1db = r["ip1db_pin"]
        sg_at = r["sg_at_op1db"]

        # 5) 결과 요약
        passed = None  # 단순 측정(합격 기준은 추후 추가 가능)
        if op1db is not None:
            summary = (f"OP1dB = {op1db:.2f} dBm @ Pin {ip1db:.2f} dBm "
                       f"(SG {sg_at:.2f} dBm), small-signal gain = {g_ref:.2f} dB")
        else:
            summary = (f"no 1-dB compression within SG {p0}..{p1} dBm "
                       f"(small-signal gain = {g_ref:.2f} dB) - extend sweep range")
        log(f"[op1db  ] {summary}")
        return TestResult(self.id, self.title, passed, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "op1db_dbm": op1db, "ip1db_dbm": ip1db,
                                "sg_at_op1db_dbm": sg_at,
                                "small_signal_gain_db": round(g_ref, 3),
                                "gain_code": code, "freq_hz": freq,
                                "in_loss_db": in_loss, "out_loss_db": out_loss,
                                "idd_max_ma": round(max(idds), 1) if idds else None})
