"""Test Item: ACP (인접채널전력비) vs 입력전력.

목적: 변조신호(기본 5G NR 100MHz)를 인가하고 SG 파워를 sweep 하면서 각 전력에서
채널전력과 인접채널전력비(ACP, dBc)를 측정한다. 전력이 커질수록 비선형으로 ACP 가
악화(스펙트럼 재성장)되는 지점을 본다.

측정 구성(TX): SG(변조) → 보드 → SA(스펙트럼 ACP 측정). Summit2629e 시험 스크립트
방법을 이식했다.

변조 모드(modulation): "setup"(코드가 NR설정, 기본) / "load"(ARB파일) /
"manual"(사용자 사전설정, 코드는 측정만). SA 는 manual 이 아니면 ACP 측정을 설정.

★ 5G NR / ACP SCPI 는 펌웨어/옵션에 따라 다를 수 있다 — 실측에서 안 맞으면
  modulation="manual" 로 두고 계측기를 손으로 설정(또는 SCPI Recorder 로 교체).
  ACP[dBc]는 상대값이라 경로 손실과 무관, 채널전력만 out_loss 로 보정한다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import time

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


class ACPTest(TestItem):
    id = "acp"
    title = "ACP Test (5G NR)"
    description = ("Apply a modulated signal and sweep SG power, measuring channel "
                   "power and adjacent-channel power ratio (ACP, dBc).")

    params = [
        Param("freq_hz", "CW Frequency", "float", 28.0e9, unit="Hz",
              rx_default=19.5e9,
              help="carrier frequency (= SA center). TX~28GHz, RX(Blueway)~19.5GHz"),
        Param("pin_start_dbm", "SG Power Start", "float", -40.0, unit="dBm",
              rx_default=-60.0),
        Param("pin_stop_dbm", "SG Power Stop", "float", 0.0, unit="dBm",
              rx_default=-25.0),
        Param("pin_step_db", "Power Step", "float", 2.0, unit="dB"),
        Param("modulation", "Modulation Mode", "choice", "setup",
              choices=["setup", "load", "manual"],
              help="setup=code configures NR / load=ARB file / manual=user pre-configured"),
        Param("waveform_path", "ARB Waveform Path", "str", "",
              help="ARB waveform file path on the SMW (used when modulation=load)"),
        Param("bw_mhz", "NR Bandwidth", "int", 100, unit="MHz"),
        # --- ACP channel settings (SA) ---
        Param("chan_bw_hz", "Channel BW", "float", 99.0e6, unit="Hz",
              help="channel bandwidth (occupied BW). ~99 MHz for 100 MHz NR"),
        Param("spacing_hz", "Channel Spacing", "float", 100.0e6, unit="Hz",
              help="adjacent channel spacing (center to center)"),
        Param("n_adj", "Adjacent Pairs", "int", 1,
              help="number of adjacent channel pairs (1 = one lower + one upper)"),
        # path loss는 자동으로 SG/SA 오프셋에 적용된다(bench.apply_path_loss).
        Param("settle_s", "Settle Time", "float", 0.3, unit="s"),
    ]

    def run(self, ctx: TestContext, params: dict, log=print) -> TestResult:
        bench = ctx.bench
        sg = bench.sg
        sa = bench.sa
        freq = float(params["freq_hz"])
        p0 = float(params["pin_start_dbm"])
        p1 = float(params["pin_stop_dbm"])
        step = float(params["pin_step_db"])
        mod = params["modulation"]
        bw = int(params["bw_mhz"])
        settle = float(params["settle_s"])
        beam = getattr(bench.board, "beam", "b0")
        chans = getattr(bench.board, "active_channels", []) or []
        channel = chans[0] if chans else "?"
        rail_names = psu_rail_names(bench)

        n = int(round((p1 - p0) / step)) + 1
        levels = [round(p0 + k * step, 3) for k in range(max(1, n))]

        # 1) 변조 설정(모드별)
        if mod == "setup":
            sg.setup_nr5g(bw_mhz=bw, log=log)
        elif mod == "load":
            sg.load_waveform(params["waveform_path"], log=log)
        sg.set_frequency(freq)
        in_loss, out_loss = bench.apply_path_loss(freq, log=log)

        # 2) SA: ACP 측정 설정(manual 이면 사용자 설정 사용)
        if mod != "manual":
            sa.setup_acp(center_hz=freq, chan_bw_hz=float(params["chan_bw_hz"]),
                         spacing_hz=float(params["spacing_hz"]),
                         n_adj=int(params["n_adj"]), log=log)

        sg.set_level(p0)
        sg.rf_output(True)
        time.sleep(settle)
        log(f"[acp   ] beam={beam} ch={channel}  {mod} NR{bw}MHz, "
            f"CW {freq/1e9:.3f} GHz, SG {p0}..{p1} dBm (out_loss={out_loss} dB)")

        columns = ["SG_dBm", "Pin_dBm", "ChPwr_dBm", "ACP_lower_dBc",
                   "ACP_upper_dBc"] + rail_vi_columns(rail_names)
        rows: list[list] = []
        worst = None  # (worst_acp_dbc, level)
        try:
            for lvl in levels:
                sg.set_level(lvl)
                time.sleep(settle)
                sa.measure_once()
                chp = sa.read_channel_power_dbm()   # SA 오프셋 적용됨 = 칩 출력
                lower, upper = sa.read_acp_dbc()
                pin = lvl                            # SG 오프셋 적용됨 = 칩 입력
                rail = read_rail_vi(bench, rail_names, log)  # 전 레일 mA + Idd
                rows.append([round(lvl, 2), round(pin, 2), round(chp, 2),
                             round(lower, 2), round(upper, 2)] + rail)
                # ACP 는 0 에 가까울수록(덜 음수) 나쁨 → 최댓값이 worst
                w = max(lower, upper)
                if worst is None or w > worst[0]:
                    worst = (w, lvl)
                log(f"  SG={lvl:+.1f}  ChPwr={chp:+.2f} dBm  "
                    f"ACP L/U={lower:.2f}/{upper:.2f} dBc  Idd={rail_idd_ma(rail):.0f} mA")
        finally:
            sg.rf_output(False)

        if worst is not None:
            summary = (f"worst ACP {worst[0]:.2f} dBc @ SG {worst[1]:.1f} dBm")
        else:
            summary = "no points measured"
        log(f"[acp   ] {summary}")
        return TestResult(self.id, self.title, None, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "worst_acp_dbc": round(worst[0], 3) if worst else None,
                                "worst_sg_dbm": worst[1] if worst else None,
                                "freq_hz": freq, "modulation": mod, "bw_mhz": bw,
                                "out_loss_db": out_loss})
