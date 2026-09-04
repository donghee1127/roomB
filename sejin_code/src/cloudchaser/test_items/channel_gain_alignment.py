"""Test Item: Channel Gain Alignment.

목적: 보드를 bring-up 한 뒤 게인 인덱스를 '최대 게인'(common gain 0 + RTPS 0)으로
고정하고, 각 안테나 채널(H0~H3 / V0~V3)의 출력 전력을 측정해 채널 간 게인 정렬
(편차)을 본다. 사용자가 SA 케이블을 채널 포트로 옮겨가며 한 채널씩 측정한다.

진행 방식(인터랙티브):
  - 콘솔에서 측정할 채널(예: H0)을 입력하고, 케이블을 그 포트로 옮긴 뒤 'y' 를
    입력하면 그 채널의 SA 피크를 1회 측정해 출력 전력으로 저장한다.
  - 다른 채널로 케이블을 옮기고 같은 방식으로 반복.
  - 'n'(또는 stop/quit)을 입력하면 종료하고, 그때까지 측정한 채널들의 결과를
    CSV 로 저장한다.

두 가지 채널 ON 모드(channel_mode):
  - "all"    : 측정 후보 채널을 모두 ON 해두고(케이블만 이동) 측정한다(실제 어레이
               동작에 가까움).
  - "single" : 측정하는 채널 1개만 ON 하고 나머지는 OFF(인접 채널 간섭 배제).

경로 손실(apply_loss=True): Loss_data CSV 에서
  in_loss  = sg_cable + trace/2,
  out_loss = sa_cable + trace/2 를 주파수에 맞춰 자동 보상한다(TX/RX·빔/채널 구분 없음).
손실은 주파수 기준으로 선형보간하고, 범위 밖은 끝점으로 clamp 한다.

PSU 전 레일 V/I 는 매 측정마다 함께 기록한다(게인/전류 상관 진단).

비대화(자동화/테스트): channels_script 에 콤마구분 채널을 주면 그 순서대로 입력
프롬프트 없이 측정한다. fake 모드에서는 channels 후보를 그대로 1회씩 측정한다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import time

from ..board.gain_map import chip_kind, disable_all, resolve_gain_params, route_channels, set_gain
from .base import Param, TestContext, TestItem, TestResult

# 유효한 측정 채널(편파 h/v × 인덱스 0~3).
VALID_CHANNELS = frozenset(f"{p}{i}" for p in ("h", "v") for i in range(4))
# 종료로 해석할 입력.
STOP_WORDS = frozenset({"n", "no", "q", "quit", "stop", "exit"})


class ChannelGainAlignmentTest(TestItem):
    id = "channel_gain_alignment"
    title = "Channel Gain Alignment"
    description = ("Fix gain index to max, then measure each channel's output power "
                   "(move SA cable per channel) to check channel-to-channel gain "
                   "alignment. Interactive: enter a channel, 'y' to measure, 'n' to stop.")

    params = [
        Param("freq_hz", "CW Frequency", "float", 28.0e9, unit="Hz",
              rx_default=19.5e9,
              help="SG CW frequency (= SA center). TX~28GHz, RX(Blueway)~19.5GHz"),
        Param("sg_level_dbm", "SG Power", "float", -10.0, unit="dBm",
              rx_default=-50.0,
              help="fixed SG level = chip input (small-signal/linear). RX use low (-50)"),
        Param("max_gain_code", "Max-Gain Code", "int", 0,
              help="common gain code to hold fixed (0=max gain). beam-table attenuator stays at 0 (max gain)."),
        Param("beam", "Beam", "str", "",
              help="input beam port (b0/b1). Empty = use bench.toml [board].beam"),
        Param("common_target", "Common Gain Target", "choice", "",
              choices=["", "common"],
              help="beam-wide gain knob (0x1005 + beam index). BLANK = common "
                   "(also lets a legacy common_field override resolve its own "
                   "target instead of being masked by this default)."),
        Param("channel_mode", "Channel ON Mode", "choice", "all",
              choices=["all", "single"],
              help="all = all candidates ON (move cable only) / single = only measured channel ON"),
        Param("channels", "Channels", "str", "h0,h1,h2,h3,v0,v1,v2,v3",
              help="channel set to enable in 'all' mode. Comma-separated. "
                   "e.g. 'h0,h1,h2,h3' to limit to H-pol only."),
        Param("channels_script", "Scripted Channels", "str", "",
              help="empty = interactive. Comma-separated list = non-interactive scripted run "
                   "(for automation / regression testing)."),
        # path loss는 자동으로 SG/SA 오프셋에 적용된다(out_loss 는 채널마다 갱신).
        Param("sa_span_hz", "SA Span", "float", 100.0e6, unit="Hz",
              help="SA span (wide enough to contain the CW tone)"),
        Param("sa_ref_level_dbm", "SA Ref Level", "float", 20.0, unit="dBm",
              rx_default=10.0,
              help="SA reference level (above expected output). RX output is lower"),
        Param("settle_s", "Settle Time", "float", 0.3, unit="s",
              help="settle time after channel/cable change before SA read"),
    ]

    def run(self, ctx: TestContext, params: dict, log=print) -> TestResult:
        bench = ctx.bench
        sg = bench.sg
        sa = bench.sa
        chip = ctx.chip
        params, fh, beam, _channel = resolve_gain_params(params, bench, chip, log=log)
        beam = beam.lower()
        # Ruling 21: derive TX/RX from the chip's own identity register instead of
        # hardcoding "tx" -- route_channels()'s H/V bit positions are mirrored
        # between TX and RX, so a wrong/stale kind routes the opposite polarity
        # silently (the same bug found on real silicon during the Sivers trip).
        route_kind = chip_kind(fh)
        freq = float(params["freq_hz"])
        sg_level = float(params["sg_level_dbm"])
        max_code = int(params["max_gain_code"])
        common_target = params.get("common_target") or "common"
        mode = params.get("channel_mode", "all")
        chans = [c.strip().lower() for c in str(params["channels"]).split(",") if c.strip()]
        script = [c.strip().lower()
                  for c in str(params.get("channels_script", "")).split(",") if c.strip()]
        span = float(params["sa_span_hz"])
        ref = float(params["sa_ref_level_dbm"])
        settle = float(params["settle_s"])

        def setup_channels(on_list: list[str]) -> None:
            """주어진 채널만 ON(raw 라우팅) + center 바이어스 + RTPS 0 + common gain 고정.

            manual.chan()/bring-up 과 동일한 '측정 가능 상태' 시퀀스.
            """
            disable_all(fh)
            fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
            route_channels(fh, list(on_list), beam, route_kind)
            fh.load_beam_table(0, [[0, 0, 0, 0, 0, 0, 0, 0]])
            fh.beam_up()
            set_gain(fh, common_target, max_code, beam=beam)

        # 1) SG/SA 측정 준비(+경로손실 오프셋: SG=in_loss 고정, SA=채널별 measure 에서 갱신).
        sg.set_frequency(freq)
        bench.apply_path_loss(freq, channel=(chans[0] if chans else None), log=log)
        sg.set_level(sg_level)
        sa_cfg = getattr(bench, "sa_cfg", {})
        sa.configure(
            center_hz=freq,
            span_hz=span,
            rbw_hz=float(sa_cfg.get("rbw_hz", 1.0e6)),
            ref_level_dbm=ref,
            input_atten_db=float(sa_cfg.get("input_atten_db", 10.0)),
            spectrum_mode=bool(sa_cfg.get("spectrum_mode", True)),
            log=log,
        )
        sg.rf_output(True)

        # 2) 채널 ON 전략.
        if mode == "all":
            setup_channels(chans)
            log(f"[chan-align] ALL channels ON {chans} -> {beam}, "
                f"common gain MAX (code {max_code})")
        else:
            log(f"[chan-align] SINGLE-channel mode -> {beam}, "
                f"common gain MAX (code {max_code}) (only measured channel ON)")

        # 측정 컬럼: 기본 + PSU 전 레일 V/I + 합산 전류.
        try:
            rail_names = list(bench.read_all_vi().keys())
        except Exception:  # noqa: BLE001
            rail_names = []
        columns = ["channel", "SG_dBm", "Pin_dBm", "SA_raw_dBm", "out_loss_dB", "Pout_dBm"]
        for rn in rail_names:
            columns += [f"{rn}_V", f"{rn}_mA"]
        columns.append("Idd_mA")

        rows: list[list] = []
        per_ch: dict[str, float] = {}

        def measure(ch: str) -> None:
            """현재 ON 된 채널 ch 의 출력을 1회 측정해 행에 기록(채널은 호출 전 설정)."""
            time.sleep(settle)
            # 채널별 out_loss 를 SA 오프셋에 반영(빔 기반 in_loss 는 고정).
            _, out_loss = bench.apply_path_loss(freq, channel=ch, log=lambda *_a: None)
            pout = sa.measure_peak_dbm()   # SA 오프셋 적용됨 = 칩 출력
            raw = pout - out_loss          # 보정 전 SA 읽기(기록용)
            pin = sg_level                 # SG 오프셋 적용됨 = 칩 입력
            try:
                vi = bench.read_all_vi()
            except Exception as e:  # noqa: BLE001
                log(f"[chan-align] warn: PSU read failed: {e}")
                vi = {}
            row = [ch.upper(), round(sg_level, 2), round(pin, 2), round(raw, 2),
                   round(out_loss, 2), round(pout, 2)]
            idd = 0.0
            rail_strs: list[str] = []
            for rn in rail_names:
                v = vi.get(rn, {}).get("v", 0.0)
                i = vi.get(rn, {}).get("i", 0.0)
                ima = i * 1000
                row += [round(v, 3), round(ima, 1)]
                idd += ima
                rail_strs.append(f"{rn}={v:.3f}V/{ima:.1f}mA")
            row.append(round(idd, 1))
            rows.append(row)
            per_ch[ch] = pout
            log(f"  {ch.upper()}: SA_raw={raw:+.2f}  out_loss={out_loss:.2f}  "
                f"Pout={pout:+.2f} dBm  Idd={idd:.0f} mA")
            if rail_strs:
                log(f"    rails: {'  '.join(rail_strs)}  (sum Idd={idd:.1f} mA)")

        try:
            if script or ctx.fake:
                # --- 비대화: 스크립트(또는 fake 면 후보 채널) 순서대로 측정 ---
                seq = script or chans
                for ch in seq:
                    if ch not in VALID_CHANNELS:
                        log(f"[chan-align] skip invalid channel '{ch}'")
                        continue
                    if mode == "single":
                        setup_channels([ch])
                    measure(ch)
            else:
                # --- 인터랙티브: 채널 입력 → 케이블 이동 → 'y' 측정, 'n' 종료 ---
                print("\n=== Channel Gain Alignment (interactive) ===")
                print("  Enter a channel (H0..H3 / V0..V3), move the SA cable to that")
                print("  port, then 'y' to measure. Enter 'n' to stop and save.\n")
                while True:
                    try:
                        ch = input("channel to measure (or 'n' to stop): ").strip().lower()
                    except EOFError:
                        break
                    if ch in STOP_WORDS:
                        break
                    if not ch:
                        continue
                    if ch not in VALID_CHANNELS:
                        print(f"  '{ch}' is not valid. use H0..H3 / V0..V3, or 'n' to stop.")
                        continue
                    if mode == "single":
                        setup_channels([ch])  # 측정 채널만 ON(사용자가 포트 매핑 확인 가능)
                    conf = input(f"  move cable to {ch.upper()} port, then 'y' to "
                                 f"measure (anything else to cancel): ").strip().lower()
                    if conf != "y":
                        print("  cancelled.")
                        continue
                    measure(ch)
        finally:
            sg.rf_output(False)  # 측정 끝/중단 시 RF OFF(안전)

        # 결과: 채널 간 출력 편차(정렬도).
        if per_ch:
            pmax = max(per_ch.values())
            pmin = min(per_ch.values())
            ch_max = max(per_ch, key=per_ch.get)
            ch_min = min(per_ch, key=per_ch.get)
            spread = pmax - pmin
            summary = (f"alignment spread {spread:.2f} dB over {len(per_ch)} channel(s) "
                       f"(max {ch_max.upper()} {pmax:.2f} / min {ch_min.upper()} "
                       f"{pmin:.2f} dBm)")
        else:
            spread = None
            summary = "no channels measured"
        log(f"[chan-align] {summary}")
        measured = list(per_ch.keys())
        ch_tag = measured[0].upper() if len(measured) == 1 else "MULTI"
        return TestResult(self.id, self.title, None, summary, columns, rows,
                          meta={"spread_db": round(spread, 3) if spread is not None else None,
                                "channel_pout_dbm": {k.upper(): round(v, 2)
                                                     for k, v in per_ch.items()},
                                "beam": beam, "channel": ch_tag, "channel_mode": mode,
                                "freq_hz": freq, "sg_level_dbm": sg_level,
                                "max_gain_code": max_code})
