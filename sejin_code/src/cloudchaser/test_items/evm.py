"""Test Item: EVM (5G NR 변조품질) vs 입력전력.

목적: 변조신호(기본 5G NR 100MHz, Ka 유사 FR2)를 인가하고 SG 파워를 sweep 하면서
각 전력에서 EVM[dB]과 출력전력을 측정한다(EVM bathtub: 저전력은 노이즈, 고전력은
압축으로 EVM 악화 → 중간이 최적).

측정 구성(TX): SG(변조) → 보드 → SA(5G NR 변조분석). Summit2629e 시험 스크립트의
측정 방법을 이식했다.

변조 모드(modulation):
  - "setup"  : 코드가 SMW 에 5G NR 신호를 직접 설정(기본).
  - "load"   : waveform_path 의 ARB 파형을 SMW 에 로드.
  - "manual" : SMW/FSVA 를 사용자가 미리 설정해 둔 상태로 두고 코드는 측정만.
FSVA(SA)는 manual 이 아니면 NR 분석 모드로 맞추고, Auto Level/Auto EVM 후 측정.

★ R&S 5G NR(K144) SCPI 는 펌웨어/옵션에 따라 다를 수 있다 — 실측에서 안 맞으면
  modulation="manual" 로 두고 계측기를 손으로 설정(또는 SCPI Recorder 로 시퀀스
  교체). EVM 값 자체는 경로 손실과 무관(비율), 출력전력만 out_loss 로 보정한다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import math
import time

from ..board.firehawk import FH
from ..board.gain_map import set_gain
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


class EVMTest(TestItem):
    id = "evm"
    title = "EVM Test (5G NR)"
    description = ("Apply a modulated signal (default 5G NR 100MHz) and sweep SG "
                   "power, measuring EVM and output power at each level.")

    params = [
        Param("freq_hz", "CW Frequency", "float", 28.0e9, unit="Hz",
              rx_default=19.5e9,
              help="carrier frequency (= SA center). TX~28GHz, RX(Blueway)~19.5GHz"),
        Param("pin_start_dbm", "SG Power Start", "float", -40.0, unit="dBm",
              rx_default=-75.0),
        Param("pin_stop_dbm", "SG Power Stop", "float", 0.0, unit="dBm",
              rx_default=-45.0),
        Param("pin_step_db", "Power Step", "float", 2.0, unit="dB"),
        Param("modulation", "Modulation Mode", "choice", "setup",
              choices=["setup", "load", "manual"],
              help="setup=code configures NR / load=ARB file / manual=user pre-configured"),
        Param("waveform_path", "ARB Waveform Path", "str", "",
              help="ARB waveform file path on the SMW (used when modulation=load)"),
        Param("sa_follow_center", "SA Follow Center", "bool", True,
              help="when the SA is left in manual/setup_sa=False mode, still move "
                   "its NR center frequency to this test's freq_hz. Turn off only "
                   "if you deliberately measure off-center; leaving it off while "
                   "sweeping frequencies silently measures at the old center."),
        Param("setup_sa", "Setup SA Analyzer", "bool", True,
              help="let the code configure the FSVA NR analyzer. False = leave the SA "
                   "as you set it up by hand (use with modulation=load to load the "
                   "waveform on the SG but keep a manual SA setup; e.g. UL waveforms)."),
        Param("bw_mhz", "NR Bandwidth", "int", 100, unit="MHz",
              help="5G NR bandwidth in MHz (setup mode)"),
        Param("auto_evm_each", "Auto EVM Each Step", "bool", False,
              help="re-run Auto EVM at each step (default False = once at start, more stable)"),
        # path loss는 자동으로 SG/SA 오프셋에 적용된다(bench.apply_path_loss).
        Param("settle_s", "Settle Time", "float", 0.3, unit="s"),
    ]

    def run(self, ctx: TestContext, params: dict, log=print) -> TestResult:
        bench = ctx.bench
        sg = bench.sg
        sa = bench.sa
        chip = ctx.chip
        freq = float(params["freq_hz"])
        p0 = float(params["pin_start_dbm"])
        p1 = float(params["pin_stop_dbm"])
        step = float(params["pin_step_db"])
        mod = params["modulation"]
        setup_sa = bool(params.get("setup_sa", True))
        bw = int(params["bw_mhz"])
        settle = float(params["settle_s"])
        auto_each = bool(params["auto_evm_each"])
        beam = getattr(bench.board, "beam", "b0")
        chans = getattr(bench.board, "active_channels", []) or []
        channel = chans[0] if chans else "?"
        rail_names = psu_rail_names(bench)
        # Ruling 1: chip._fh is set by bring_up_tx/bring_up_rx; fall back to a bare
        # FH wrapper when a caller skipped bring-up (e.g. manual.py --no-enable).
        fh = getattr(chip, "_fh", None) or FH(chip, getattr(bench.board, "chip_id", 0))

        n = int(round((p1 - p0) / step)) + 1
        levels = [round(p0 + k * step, 3) for k in range(max(1, n))]

        # 0) 최대 게인으로 고정해 측정(직전 테스트의 게인 상태에 의존하지 않게).
        #    common gain = 0, 채널 RTPS(beam table) = 0. 특히 rx_suite 에서 직전
        #    gain_chan(채널 sweep)이 RTPS 를 코드 63(최대 감쇠)에 남겨두므로 필수.
        #    raw 기입은 즉시 반영되므로(shadow 캐시 없음) try/except 로 감쌀 필요가 없다.
        set_gain(fh, "common", 0, beam=beam)
        fh.load_beam_table(0, [[0] * 8])
        fh.beam_up()

        # 1) 변조 설정(모드별)
        if mod == "setup":
            sg.setup_nr5g(bw_mhz=bw, log=log)
        elif mod == "load":
            sg.load_waveform(params["waveform_path"], log=log)
        else:  # manual: 파형은 사용자가 미리 로드. 단 CW 테스트가 baseband 를 꺼뒀을 수
            # 있으므로, 선택돼 있는 ARB 파형을 다시 켠다(안 그러면 CW 가 나간다).
            sg.modulation_on(log=log)
        sg.set_frequency(freq)
        in_loss, out_loss = bench.apply_path_loss(freq, log=log)

        # 2) SA: NR 분석 모드. manual 이거나 setup_sa=False 면 사용자가 손으로 설정한
        #    FSVA NR 앱을 그대로 쓴다(코드가 안 건드림). load + setup_sa=False 조합 =
        #    파형은 코드가 SG 에 로드하되 SA 는 수동(UL 파형 등 자동설정이 안 맞을 때).
        if mod != "manual" and setup_sa:
            sa.setup_nr5g_analyzer(center_hz=freq, bw_mhz=bw, log=log)
        else:
            # 사용자가 FSVA 를 직접 세팅한 경우라도, SA 가 spectrum(SAN) 모드 등 다른
            # 앱에 있으면 EVM fetch 가 막힌다 -> NR 앱으로 전환만 한다(설정은 유지).
            sa.select_nr5g(log=log)
            # ★ center 주파수만은 이 측정의 주파수로 맞춘다. 이 분기는 SA 설정을
            #   사용자에게 맡기는데, 그러면 주파수를 여러 개 도는 suite 에서 29/30 GHz
            #   EVM 이 28 GHz 에 맞춰진 NR 앱에서 측정된다(조용히 틀린 값). 주파수는
            #   suite 가 sweep 하는 축이므로 코드가 소유해야 한다. BW/레벨/트리거 등
            #   손으로 잡은 설정은 그대로 둔다.
            if bool(params.get("sa_follow_center", True)):
                sa.write_try(f"SENS:FREQ:CENT {freq:.0f}", log)

        sg.set_level(p0)
        sg.rf_output(True)
        time.sleep(settle)
        # SA 를 코드가 관리할 때만 Auto Level/EVM. manual 또는 setup_sa=False(사용자가
        # FSVA 를 직접 세팅)면 건드리지 않는다 -- 안 그러면 최저 파워(p0)에서 ref level 을
        # 잡아 고파워 점에서 SA 과입력이 날 수 있다.
        if mod != "manual" and setup_sa:
            sa.auto_level(log=log)
            sa.auto_evm(log=log)   # 시작 전 1회
        log(f"[evm   ] beam={beam} ch={channel}  {mod} NR{bw}MHz, "
            f"CW {freq/1e9:.3f} GHz, SG {p0}..{p1} dBm (out_loss={out_loss} dB)")

        columns = ["SG_dBm", "Pin_dBm", "NR_Pout_dBm", "EVM_dB", "EVM_pct"] + \
            rail_vi_columns(rail_names)
        rows: list[list] = []
        best = None  # (evm, level, pout, evm_pct)
        n_skip = 0
        try:
            for lvl in levels:
                sg.set_level(lvl)
                time.sleep(settle)
                if auto_each:
                    sa.auto_evm(log=log)
                sa.measure_once()
                evm = sa.read_evm_db()
                praw = sa.read_nr_power_dbm()
                # 락 미동기(저전력 등)면 FSVA 가 NaN 을 준다 → 그 점만 건너뛰고 계속.
                if math.isnan(evm) or math.isnan(praw):
                    n_skip += 1
                    log(f"  SG={lvl:+.1f}  no valid result "
                        f"(EVM={evm} NR_Pow={praw}) -> skip")
                    continue
                evm_pct = 100.0 * 10 ** (evm / 20.0)  # dB -> EVM[%]
                pout = praw   # SA 오프셋 적용됨 = 칩 출력 (NR 앱 반영여부 HW 검증)
                pin = lvl     # SG 오프셋 적용됨 = 칩 입력
                rail = read_rail_vi(bench, rail_names, log)  # 전 레일 mA + Idd
                rows.append([round(lvl, 2), round(pin, 2), round(pout, 2),
                             round(evm, 2), round(evm_pct, 3)] + rail)
                if best is None or evm < best[0]:
                    best = (evm, lvl, pout, evm_pct)
                log(f"  SG={lvl:+.1f}  Pout={pout:+.2f} dBm  "
                    f"EVM={evm:.2f} dB ({evm_pct:.2f}%)  Idd={rail_idd_ma(rail):.0f} mA")
        finally:
            sg.rf_output(False)

        if n_skip:
            log(f"[evm   ] {n_skip}/{len(levels)} points had no demod lock "
                f"(NaN); raise pin_start_dbm or check NR demod config if all skipped")

        if best is not None:
            summary = (f"best EVM {best[0]:.2f} dB ({best[3]:.2f}%) @ "
                       f"SG {best[1]:.1f} dBm (Pout {best[2]:.2f} dBm)")
        else:
            summary = "no points measured"
        log(f"[evm   ] {summary}")
        return TestResult(self.id, self.title, None, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "best_evm_db": round(best[0], 3) if best else None,
                                "best_evm_pct": round(best[3], 3) if best else None,
                                "best_sg_dbm": best[1] if best else None,
                                "freq_hz": freq, "modulation": mod, "bw_mhz": bw,
                                "out_loss_db": out_loss})
