"""Test Item: IP1dB Test (input 1-dB compression point, RX).

목적: RX 고정 게인에서 CW 입력 전력(SG 레벨)을 sweep 하며, 이득이 소신호(선형)
이득보다 1 dB 낮아지는 지점의 '입력 전력'(IP1dB)을 구한다.

측정 구성(RX): SG(CW, 전력 sweep) -> [입력 케이블 손실] -> 채널 포트(안테나 입력)
-> Blueway IC -> 빔 포트 -> [출력 케이블 손실] -> SA(피크 전력 측정).

TX op1db 와 알고리즘은 동일하지만 신호 방향이 반대다:
  - TX: SG -> 빔 포트 -> IC -> 채널 포트 -> SA
  - RX: SG -> 채널 포트 -> IC -> 빔 포트 -> SA
따라서 손실 모델도 반전된 방향으로 적용된다(bench.apply_path_loss 가 Loss_data CSV 로 처리, TX/RX 동일):
  - in_loss  = sg_cable + trace/2            (SG 가 채널 쪽으로 들어감)
  - out_loss = sa_cable + trace/2            (SA 가 빔 쪽에 연결)

결과는 IP1dB(입력 기준) 와 OP1dB(출력 기준) 를 모두 보고한다.
op1db 모듈의 compute_op1db() 함수를 재사용한다.

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
from .op1db import compute_op1db  # 알고리즘 재사용


class IP1dBTest(TestItem):
    id = "ip1db"
    title = "IP1dB Test (RX)"
    description = ("RX: at a fixed gain, sweep CW input power and find the input "
                   "1-dB compression point (IP1dB) for the Blueway RX chip. "
                   "Signal flow: SG -> channel port -> IC -> beam port -> SA.")
    chips = ("rx",)   # 입력 압축 = RX(LNA) 측정. TX 는 op1db 사용.

    params = [
        Param("freq_hz", "CW Frequency", "float", 19.5e9, unit="Hz",
              help="SG CW frequency (= SA center). Blueway band: 17.7-21.2 GHz"),
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
        Param("gain_code", "Gain Code", "int", 0,
              help="common gain code to hold fixed (0=max gain, 0x3f=max atten). "
                   "Linearity is measured at max gain -> default 0. The channel "
                   "beam-table attenuator is also reset to max gain (0) at test start."),
        # --- CW power sweep (SG output level) ---
        Param("pin_start_dbm", "SG Power Start", "float", -50.0, unit="dBm",
              help="SG sweep start (RX is more sensitive than TX, start lower)"),
        Param("pin_stop_dbm", "SG Power Stop", "float", -20.0, unit="dBm",
              help="SG sweep stop (IP1dB ~ -36 dBm at max gain -> -50..-20 is enough)"),
        Param("pin_step_db", "Power Step", "float", 1.0, unit="dB",
              help="sweep step size"),
        # path loss(cable + board trace)는 자동으로 SG/SA 오프셋에 적용된다
        # (bench.apply_path_loss; Loss_data CSV, TX/RX 동일). SG level = 칩 입력, SA read = 칩 출력.
        # --- small-signal gain reference ---
        Param("ref_skip_pts", "Ref Skip Points", "int", 1,
              help="points to skip at sweep start for reference gain (same as op1db)"),
        Param("ref_avg_pts", "Ref Avg Points", "int", 2,
              help="points to average for reference gain"),
        # --- SA settings ---
        Param("sa_span_hz", "SA Span", "float", 100.0e6, unit="Hz",
              help="SA span"),
        Param("sa_ref_level_dbm", "SA Ref Level", "float", 0.0, unit="dBm",
              help="SA reference level (RX output is lower than TX PA output)"),
        Param("settle_s", "Settle Time", "float", 0.2, unit="s",
              help="wait after setting SG level before SA read"),
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

        n = int(round((p1 - p0) / step)) + 1
        sg_levels = [round(p0 + k * step, 3) for k in range(max(1, n))]

        # 1) 게인 고정 + SG 주파수 설정
        set_gain(fh, target, code, beam=beam, channel=channel)
        # 최대 게인 측정 보장: 채널 RTPS(beam table)도 0(max gain)으로 리셋한다.
        # 직전 gain sweep 등이 RTPS 를 감쇠 코드로 남겨두면 소신호 게인이 낮게 나오므로,
        # common(gain_code) 과 channel(RTPS) 을 모두 max 로 맞춘 뒤 sweep 한다.
        # raw 기입은 예외를 던지지 않으므로 try/except 로 감쌀 필요가 없다.
        fh.load_beam_table(0, [[0, 0, 0, 0, 0, 0, 0, 0]])
        fh.beam_up()
        sg.modulation_off(log=log)   # CW 보장(직전 EVM 등의 ARB 파형 잔류 방지)
        sg.set_frequency(freq)
        in_loss, out_loss = bench.apply_path_loss(freq, log=log)

        # 2) SA 설정
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
        log(f"[ip1db  ] beam={beam} ch={channel}  gain_target={target}={hex(code)}, "
            f"CW {freq/1e9:.3f} GHz, SG {p0}..{p1} dBm "
            f"(in_loss={in_loss} out_loss={out_loss} dB)")
        log("[ip1db  ] RX path: SG->channel->IC->beam->SA")

        columns = ["SG_dBm", "Pin_dBm", "Pout_dBm", "Gain_dB"] + \
            rail_vi_columns(rail_names)
        rows: list[list] = []
        pins: list[float] = []
        pouts: list[float] = []
        gains: list[float] = []
        idds: list[float] = []
        try:
            # 3) 전력 sweep
            for lvl in sg_levels:
                sg.set_level(lvl)          # SG 오프셋 적용됨 -> lvl = 칩 입력 전력
                time.sleep(settle)
                # SA 오프셋 적용됨 -> 읽은 값이 곧 칩 출력 전력
                pin = lvl
                pout = sa.measure_peak_dbm()
                gain = pout - pin
                rail = read_rail_vi(bench, rail_names, log)  # 전 레일 mA + Idd
                idds.append(rail_idd_ma(rail))
                rows.append([round(lvl, 2), round(pin, 2), round(pout, 2),
                             round(gain, 2)] + rail)
                pins.append(pin)
                pouts.append(pout)
                gains.append(gain)
                log(f"  SG={lvl:+.1f} dBm  Pin={pin:+.2f}  Pout={pout:+.2f}  "
                    f"Gain={gain:.2f} dB  Idd={rail_idd_ma(rail):.0f} mA")
        finally:
            sg.rf_output(False)

        # 4) IP1dB 계산 (op1db 와 동일 알고리즘 재사용)
        r = compute_op1db(sg_levels, pins, pouts, gains, ref_skip, ref_avg)
        g_ref = r["g_ref"]
        op1db = r["op1db_pout"]
        ip1db = r["ip1db_pin"]   # <- RX 의 primary 결과
        sg_at = r["sg_at_op1db"]

        # 5) 결과 요약 (RX 는 IP1dB 를 먼저 보고)
        passed = None
        if ip1db is not None:
            summary = (f"IP1dB = {ip1db:.2f} dBm (OP1dB = {op1db:.2f} dBm) "
                       f"@ SG {sg_at:.2f} dBm, small-signal gain = {g_ref:.2f} dB")
        else:
            summary = (f"no 1-dB compression within SG {p0}..{p1} dBm "
                       f"(small-signal gain = {g_ref:.2f} dB) - extend sweep range")
        log(f"[ip1db  ] {summary}")
        return TestResult(self.id, self.title, passed, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "ip1db_dbm": ip1db, "op1db_dbm": op1db,
                                "sg_at_ip1db_dbm": sg_at,
                                "small_signal_gain_db": round(g_ref, 3),
                                "gain_code": code, "freq_hz": freq,
                                "in_loss_db": in_loss, "out_loss_db": out_loss,
                                "idd_max_ma": round(max(idds), 1) if idds else None})
