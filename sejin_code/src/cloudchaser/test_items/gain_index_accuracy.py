"""Test Item: Gain Index Accuracy.

목적: SG 파워를 고정한 채로 IC 내부의 게인 인덱스(공통 게인 + 채널 게인)를 모두
sweep 하면서 출력 전력을 측정한다. 인덱스별 게인 변화(정확도/단조성)와 '가장 높은
게인'을 주는 인덱스를 확인한다.

게인 손잡이 출처(1차 문서 기준):
  - Common-beam gain : b0/b1_common_gain (6-bit, Blueway 레지스터맵 0x1005/0x1006,
                       "Common gain ... applied after combining"). 0 = 최대 게인,
                       클수록 감쇠↑. (dB 범위/step 수치는 레지스터맵·벤더 API에 미정의.)
  - Per-path gain    : beam-table 'attenuator_setting' 필드 = 진폭 감쇠기.
                       (vendor sivers_api chips/cloudchaser/blocks/beam.py 의 beam_field:
                        attenuator_setting=(0,6) -> bits[5:0], 6-bit. 0=최대 게인.)
                       ※ 이건 진폭이다. RTPS(위상)는 같은 워드의 phase_shifter_setting=
                       (7,7) bits[13:7]로 '별개'. 'gain_control_<ch>' quad 필드는 이 칩에서
                       무반응(channel_kind 참고). dB/step·총 range 는 어느 1차 문서에도
                       없어 미검증(과거 "0.5dB/32dB"는 firehawk/타칩 유래 추정).

동작: SG(CW, 고정 레벨) → 보드 → SA. common × channel 2D sweep 으로 각 조합의
Pout 를 측정한다. 한쪽 codes 를 단일값으로 주면 1D sweep 이 된다.
  예) gain_index_accuracy(channel_codes=[0])  -> common 만 sweep
      gain_index_accuracy(common_codes=[0])   -> channel(per-path) 만 sweep

측정 전력은 경로 손실로 보정한다: Pin = SG - in_loss, Pout = SA측정 + out_loss.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import time

from ..board.gain_map import check_gain_codes, resolve_gain_params, set_gain
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


class GainIndexAccuracyTest(TestItem):
    id = "gain_index_accuracy"
    title = "Gain Index Accuracy"
    description = ("Fix SG power and sweep common / per-path (beam-table "
                   "attenuator_setting) gain indices, measuring output to check "
                   "gain-vs-index and the max-gain index.")

    # ----------------------------------------------------------------------
    # 파라미터 개요 (params('gain_index_accuracy') 로도 볼 수 있음):
    #   이 테스트 = SG 입력을 '고정'하고 게인 코드를 sweep -> 코드별 출력(Pout) 측정.
    #   게인 손잡이 2축: (A) 빔 공통게인 common_codes, (B) 채널 per-path beam-table
    #   attenuator_setting channel_codes.
    #   한 축을 단일값(예: [0])으로 주면 다른 축만 1D sweep. Gain_dB = Pout - Pin.
    #
    #   [!] RX(Blueway) 직접 호출 주의: gain_index_accuracy() 를 '함수로' 부르면
    #       rx_default(19.5GHz/-50dBm/ref10)가 적용되지 않고 TX 기본값(28GHz/0dBm/ref20)이
    #       쓰인다(rx_default 는 대화형 wizard 에서만 적용; session.resolve 가 p.default 사용).
    #       -> RX 에서는 freq_hz / sg_level_dbm / sa_ref_level_dbm 를 반드시 명시할 것.
    # ----------------------------------------------------------------------
    params = [
        # 측정 주파수: CW 톤 주파수이자 SA 중심주파수. (RX 직접호출 시 명시 필수)
        Param("freq_hz", "CW Frequency", "float", 28.0e9, unit="Hz",
              rx_default=19.5e9,
              help="CW tone freq (= SA center). TX ~28GHz, RX(Blueway) ~19.5GHz. "
                   "NOTE: direct call ignores rx_default -> pass this on RX."),
        # 고정 SG 입력전력(칩 입력, 경로손실 보정됨). 게인만 보므로 입력은 고정.
        Param("sg_level_dbm", "SG Power", "float", 0.0, unit="dBm",
              rx_default=-50.0,
              help="FIXED chip-input power (path-loss compensated). Held constant while "
                   "gain codes sweep. RX LNA is sensitive -> use low (~-50). Pass on RX."),
        Param("beam", "Beam", "str", "",
              help="beam override (b0/b1/b2). BLANK = use the board beam."),
        # --- (A) 빔 공통 게인 축 -------------------------------------------
        # common (0x1005 + beam index): 6-bit, combining 이후 빔 전체에 적용. code 0 = 최대 게인.
        Param("common_target", "Common Gain Target", "choice", "",
              choices=["", "common"],
              help="beam-wide gain knob (0x1005 + beam index). BLANK = common "
                   "(also lets a legacy common_field/gain_field override resolve "
                   "its own target instead of being masked by this default)."),
        Param("common_codes", "Common Codes", "int_list",
              list(range(0, 64)),
              help="common-gain codes to sweep (the MAIN knob). full 0..63, or a subset "
                   "like [0,16,32,48,63]. Single value e.g. [0] = hold common fixed."),
        # --- (B) 채널 per-path 게인 축 -------------------------------------
        # 채널 게인 손잡이는 2종류이며 동작하는 건 beam-table attenuator 쪽이다:
        #   'beamtable' = beam table 워드의 attenuator_setting(bits[5:0], 6-bit 실기입은
        #                 7-bit 폭 필드). code 0 = 최대 게인(최소 감쇠). <- 이걸 사용.
        #                 (진폭 감쇠기; RTPS=phase_shifter_setting bits[13:7]는 별개의 위상 필드.)
        #   'fe'        = per-channel FE 게인(0x1018 + 채널 인덱스, 4-bit). 이 칩에서 무반응(DEAD).
        Param("channel_target", "Channel Gain Target", "choice", "",
              choices=["", "beamtable", "fe"],
              help="per-path gain knob. BLANK = beamtable (beam-table attenuator, "
                   "works on this chip). fe = per-channel FE gain (DEAD on this "
                   "silicon). Only matters when the channel axis is swept."),
        Param("channel", "Channel", "str", "",
              help="channel override for the fe target (e.g. h1). "
                   "BLANK = first active channel."),
        # MUST match the routed channel's quad. beam table = 1024 beam x 4 quad;
        # set_channel writes beam0/quad=channel_quad. If it does NOT match the active
        # channel, you sweep a quad that is not the measured path -> the output does
        # not respond (and you write a different quad's beam-table entry). Default None
        # = auto-derive from the active channel (h0/v0->0, h1/v1->1, h2/v2->2, h3/v3->3).
        Param("channel_quad", "Beamtable Quad Index", "int", None,
              help="quad (0..3) whose beam-table attenuator_setting to address. MUST match the routed "
                   "channel. None = auto from active channel (h0->0, h1->1, ...). "
                   "Override only to deliberately sweep a different quad."),
        # 기본 [0] = 채널 고정(1D: common 만 sweep). 안 그러면 64x64=4096점 2D 가 되어
        # wizard 기본 실행이 매우 느리고(첫 진행 로그가 안쪽 64점 후에야 나옴) 멈춘 듯 보인다.
        # per-path(beam-table attenuator) 정확도를 보려면 range(0,64,4) 처럼 명시해 채널축 sweep.
        Param("channel_codes", "Channel Codes", "int_list",
              [0],
              help="per-path(beam-table attenuator_setting) codes to sweep. DEFAULT [0] = "
                   "hold channel fixed and "
                   "sweep common only (1D, fast). Give a range e.g. [0,4,..] to sweep the "
                   "channel axis (2D). [0] = max gain (min atten)."),
        # path loss는 자동으로 SG/SA 오프셋에 적용된다(bench.apply_path_loss).
        # --- SA 설정 -------------------------------------------------------
        Param("sa_span_hz", "SA Span", "float", 100.0e6, unit="Hz",
              help="SA display span [Hz]. 100 MHz is fine for a CW tone."),
        Param("sa_ref_level_dbm", "SA Ref Level", "float", 20.0, unit="dBm",
              rx_default=10.0,
              help="SA reference level, set ~10 dB above expected peak. RX output is "
                   "lower (~10). NOTE: direct call ignores rx_default -> pass on RX."),
        Param("settle_s", "Settle Time", "float", 0.1, unit="s",
              help="wait [s] after setting a gain code before reading SA peak."),
        # --- PSU 전류 로깅 -------------------------------------------------
        # True: 모든 측정점에서 전 PSU 레일 V/I + 총 Idd 를 CSV 에 기록(코드별 바이어스 확인).
        # False: PSU 읽기를 통째로 건너뜀 -> sweep 이 빨라지고 PSU timeout 을 회피.
        #   (대형 sweep 에서 PSU timeout 이 잦으면 False 로 두거나 sweep 점수를 줄일 것.)
        Param("log_psu", "Log PSU Rails", "bool", True,
              help="record every PSU rail's V/I + total Idd at each point. "
                   "set False to skip all PSU reads (faster, avoids PSU timeouts)."),
    ]

    def run(self, ctx: TestContext, params: dict, log=print) -> TestResult:
        bench = ctx.bench
        sg = bench.sg
        sa = bench.sa
        chip = ctx.chip
        params, fh, beam, channel = resolve_gain_params(params, bench, chip, log=log)
        freq = float(params["freq_hz"])
        sg_level = float(params["sg_level_dbm"])
        ctarget = params.get("common_target") or "common"
        ccodes = list(params["common_codes"])
        chtarget = params.get("channel_target") or "beamtable"
        chcodes = list(params["channel_codes"])
        log_psu = bool(params.get("log_psu", True))

        # Ruling 20: validate the FULL sweep code lists against the target's field
        # width BEFORE any instrument setup or measurement -- set_gain() itself
        # raises on a bad code, but only when that code is actually written, which
        # (without this check) could be mid-sweep after earlier points already ran.
        check_gain_codes(ctarget, ccodes)
        check_gain_codes(chtarget, chcodes)

        # channel_quad 는 routed 채널의 quad 와 반드시 일치해야 한다. None 이면 active
        # 채널에서 자동 유도(h0->0, h1->1, ...). 불일치 시 측정 경로가 아닌 quad 를
        # sweep 하게 되어 출력이 반응하지 않는다.
        chquad = params.get("channel_quad")
        if chquad is None:
            # 채널 문자열에서 quad 인덱스 파싱: "h0"->0, "v3"->3.
            chquad = (int(channel[1]) if len(channel) >= 2 and channel[1].isdigit()
                      else 0)
            log(f"[gain-sw] channel_quad auto = {chquad} (from channel {channel})")
        chquad = int(chquad)

        def set_channel(code: int) -> None:
            """채널 게인 한 코드 적용."""
            if chtarget == "beamtable":
                # per-path gain = beam table attenuator_setting (0=max gain).
                # raw 코드 0..63 의 gain 은 2단(fine bits0:3 / coarse bits5:4) 구조라
                # 본질적으로 비단조(톱니) -- 칩 특성이며 write 방식 문제 아님.
                set_gain(fh, "beamtable", int(code), channel=f"h{chquad}")
            else:
                set_gain(fh, "fe", int(code), channel=channel)
        settle = float(params["settle_s"])
        pin = sg_level   # IC 입력 전력(고정; SG 오프셋이 경로손실을 보상)
        rail_names = psu_rail_names(bench) if log_psu else []

        # 1) SG 고정 설정(+경로손실 오프셋) + SA 설정.
        sg.modulation_off(log=log)   # CW 보장(직전 EVM 등의 ARB 파형 잔류 방지)
        sg.set_frequency(freq)
        in_loss, out_loss = bench.apply_path_loss(freq, log=log)
        sg.set_level(sg_level)
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
        n_total = len(ccodes) * len(chcodes)
        chlabel = (f"beamtable_atten[quad{chquad}]" if chtarget == "beamtable"
                   else f"fe[{channel}]")
        log(f"[gain-sw] beam={beam} ch={channel}  CW {freq/1e9:.3f} GHz @ "
            f"SG {sg_level:.1f} dBm, sweep common[{ctarget}]({len(ccodes)}) x "
            f"{chlabel}({len(chcodes)}) = {n_total} points")

        # log_psu=False 면 PSU 컬럼/읽기를 통째로 생략(빠르고 PSU timeout 회피).
        columns = ["common_code", "channel_code", "SG_dBm", "Pin_dBm",
                   "Pout_dBm", "Gain_dB"] + (rail_vi_columns(rail_names) if log_psu else [])
        rows: list[list] = []
        best = None  # (gain, common, channel, pout)
        try:
            for c in ccodes:
                set_gain(fh, ctarget, c, beam=beam)
                c_best = None  # (gain, ch, pout, idd) — 이 common 코드 안에서의 최고
                for ch in chcodes:
                    set_channel(ch)
                    time.sleep(settle)
                    pout = sa.measure_peak_dbm()   # SA 오프셋 적용됨 = 칩 출력
                    gain = pout - pin
                    rail = read_rail_vi(bench, rail_names, log) if log_psu else []
                    idd = rail_idd_ma(rail)   # 마지막 원소 = 총 Idd[mA] (없으면 None)
                    rows.append([hex(c), hex(ch), round(sg_level, 2),
                                 round(pin, 2), round(pout, 2), round(gain, 2)] + rail)
                    if c_best is None or gain > c_best[0]:
                        c_best = (gain, ch, pout, idd)
                    if best is None or gain > best[0]:
                        best = (gain, c, ch, pout)
                    # 채널축을 sweep 할 때는 안쪽 루프가 길어 끝까지 멈춘 듯 보이므로,
                    # common sweep 처럼 포인트마다 실시간 로그를 찍는다.
                    if len(chcodes) > 1:
                        idd_s = f"  Idd={idd:.0f} mA" if idd is not None else ""
                        log(f"  common={hex(c)} channel={hex(ch)}: "
                            f"gain={gain:+.2f} dB  Pout={pout:+.2f} dBm{idd_s}")
                # common 코드별로 '실제 값'을 찍는다(채널 여러개면 그 중 최고).
                idd_str = f"  Idd={c_best[3]:.0f} mA" if c_best[3] is not None else ""
                if len(chcodes) == 1:
                    log(f"  common={hex(c)}: gain={c_best[0]:+.2f} dB  "
                        f"Pout={c_best[2]:+.2f} dBm{idd_str}")
                else:
                    log(f"  common={hex(c)}: best gain={c_best[0]:+.2f} dB "
                        f"@ channel={hex(c_best[1])}  Pout={c_best[2]:+.2f} dBm{idd_str}")
        finally:
            sg.rf_output(False)

        if best is not None:
            g, bc, bch, bpout = best
            passed = None
            summary = (f"max gain {g:.2f} dB @ common={hex(bc)} channel={hex(bch)} "
                       f"(Pout {bpout:.2f} dBm)")
        else:
            passed = None
            summary = "no points measured"
        # sweep 한 축 식별(파일명 태그용). 한 축만 다수면 그 축, 둘 다면 2d, 둘 다 단일이면 None.
        n_c, n_ch = len(ccodes), len(chcodes)
        axis = ("common" if n_c > 1 and n_ch == 1 else
                "chan" if n_ch > 1 and n_c == 1 else
                "2d" if n_c > 1 and n_ch > 1 else None)
        log(f"[gain-sw] {summary}")
        return TestResult(self.id, self.title, passed, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "axis": axis,
                                "channel_quad": chquad,
                                "best_gain_db": round(best[0], 3) if best else None,
                                "best_common": hex(best[1]) if best else None,
                                "best_channel": hex(best[2]) if best else None,
                                "freq_hz": freq, "sg_level_dbm": sg_level,
                                "in_loss_db": in_loss, "out_loss_db": out_loss})
