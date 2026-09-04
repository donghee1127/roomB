"""Test Item: Phase Index Accuracy.

목적: 채널의 RTPS(Reflective-Type Phase Shifter) phase index 를 sweep 하면서
Anritsu MS4644B VNA 로 S21 gain/phase 를 읽어, phase code 별 실제 위상/게인
변화를 기록한다. raw 데이터 저장이 목적이며 pass/fail 판정은 없다(요약 통계만).

phase 손잡이 출처(1차 문서 기준):
  - 9-bit RTPS phase: coarse 7-bit(beam-table word, phase_shifter_setting 자리,
    code//4) + fine 2-bit(phase-cal RAM, code%4). raw 기입(board.gain_map.set_phase,
    firehawk.FH.set_rtps_attn)으로만 fine 비트에 도달한다 — 이전 cloudchaser 는
    coarse(7-bit, 0..127)만 썼고 fine RAM 을 0으로 남겨(zero_phase_cal 누락)
    RTPS fine-phase 가 무반응이었다(Sivers 출장 중 확인, 설계 스펙 2/4장).
    attenuator_setting(진폭, beam-table 워드 bits[6:0])은 별개 필드로, 이 테스트는
    RMW 로 보존한다.
  - code -> degree 변환식은 벤더 문서에 없다(미검증). 명목상 LSB 는
    360/512 = 0.703125 deg 로 가정하고 요약 통계에서 비교 기준으로만 쓴다 —
    이 측정 자체가 그 매핑을 실측하는 것이다.

VNA 캘리브레이션 정책(중요):
  - 사용자가 측정 전에 현재 케이블링으로 VNA 를 '수동' 캘리브레이션해 둔다.
  - 코드는 절대 *RST/preset 을 보내지 않고, 기본(configure_freq=False)에서는
    주파수 설정도 건드리지 않는다(계기의 현재 sweep = cal 된 그리드 그대로 사용).
  - 경로 손실 보정(apply_path_loss)도 하지 않는다 — user cal 이 케이블을 이미
    de-embed 하므로 S21 = DUT 응답이다.

주의:
  - chan() 은 beam table 을 0 으로 초기화하므로(phase 도 리셋) 채널 bring-up 이
    끝난 뒤 이 테스트를 실행하고, 실행 중 chan() 을 부르지 말 것.
  - 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import time

from ..board.firehawk import FH
from ..board.gain_map import get_gain, set_phase
from .base import (
    Param,
    TestContext,
    TestItem,
    TestResult,
    psu_rail_names,
    rail_vi_columns,
    read_rail_vi,
)

# 명목 phase LSB [deg] — 9-bit 가 360도를 커버한다고 가정(벤더 미문서, 비교 기준용).
IDEAL_STEP_DEG = 360.0 / 512


def _unwrap_deg(seq: list[float]) -> list[float]:
    """위상 나열(deg)을 unwrap 한다 — 인접값 차이가 ±180 을 넘지 않게 360 보정."""
    if not seq:
        return []
    out = [seq[0]]
    for v in seq[1:]:
        prev = out[-1]
        d = v - prev
        while d > 180.0:
            d -= 360.0
        while d < -180.0:
            d += 360.0
        out.append(prev + d)
    return out


class PhaseIndexAccuracyTest(TestItem):
    id = "phase_index_accuracy"
    title = "Phase Index Accuracy"
    description = ("Sweep the RTPS phase code (9-bit: coarse beam-table + fine "
                   "phase-cal RAM) and record S21 gain/phase from the Anritsu "
                   "MS4644B VNA. "
                   "Calibrate the VNA manually BEFORE running -- the code never "
                   "presets it. Raw data only (no pass/fail).")

    # ----------------------------------------------------------------------
    # 파라미터 개요:
    #   phase code(0..511, 9-bit)를 sweep 하며 code 마다 VNA 단일 sweep + S21 읽기.
    #   read_mode 로 저장 범위를 고른다: marker(분석 주파수 1포인트만),
    #   point(freq_start..stop 을 freq_step 간격으로 뽑은 그리드), trace(전체).
    #   TX/RX 는 메커니즘이 같아 분기 없음 — 주파수 기본값만 rx_default 로 다르다
    #   (직접 호출 시 rx_default 는 적용 안 되므로 RX 는 주파수를 명시할 것).
    # ----------------------------------------------------------------------
    params = [
        # 기본값은 range(0, 512, 4) -- 128 점(구 버전과 동일 점수/실측 시간)으로
        # 9-bit 전체 범위를 4칸 간격으로 훑는다. range(512) 로 바꾸면 512점 전수
        # sweep 이 되어 실측 시간이 4배로 늘어난다(필요하면 명시적으로 지정).
        Param("phase_codes", "Phase Codes", "int_list", list(range(0, 512, 4)),
              help="RTPS phase code to sweep (9-bit, 0..511 = coarse beam-table "
                   "+ fine phase-cal RAM; 0 = phase zero). Default = "
                   "range(0,512,4) -- 128 points spanning the full 9-bit range "
                   "(same point count/duration as the old 128-point default). "
                   "Pass list(range(512)) for an exhaustive sweep (4x slower), "
                   "or a subset e.g. [0,64,128,...] for a quick look."),
        Param("read_mode", "Read Mode", "choice", "marker",
              choices=["marker", "point", "trace"],
              help="rows saved per code: 'marker' = 1 point at marker_freq_hz "
                   "(fast, default); 'point' = grid freq_start..freq_stop every "
                   "freq_step_hz (nearest trace points); 'trace' = full sweep."),
        Param("configure_freq", "Configure VNA Freq", "bool", False,
              help="False (default) = use the VNA's CURRENT sweep setup untouched "
                   "(your manual cal stays exact). True = program freq_start/stop/"
                   "points -- WARNING: may interpolate or invalidate the user cal."),
        Param("freq_start_hz", "Freq Start", "float", 27.5e9, unit="Hz",
              rx_default=19.0e9,
              help="sweep start (configure_freq=True) AND point-mode grid start. "
                   "NOTE: direct call ignores rx_default -> pass on RX."),
        Param("freq_stop_hz", "Freq Stop", "float", 28.5e9, unit="Hz",
              rx_default=20.0e9,
              help="sweep stop (configure_freq=True) AND point-mode grid stop. "
                   "NOTE: direct call ignores rx_default -> pass on RX."),
        Param("freq_points", "Sweep Points", "int", 201,
              help="number of sweep points, used only when configure_freq=True."),
        Param("freq_step_hz", "Point Grid Step", "float", 100.0e6, unit="Hz",
              help="point mode only: grid spacing between freq_start_hz and "
                   "freq_stop_hz. Each grid freq maps to the NEAREST trace point "
                   "(the actual trace freq is recorded in the CSV)."),
        Param("marker_freq_hz", "Marker/Analysis Freq", "float", None, unit="Hz",
              help="marker-mode read freq AND the frequency used for the summary "
                   "stats in every mode (nearest trace point). None = center "
                   "point of the sweep."),
        Param("channel_quad", "Beamtable Quad Index", "int", None,
              help="quad (0..3) whose beam-table phase_shifter_setting to address. "
                   "MUST match the routed channel. None = auto from active channel "
                   "(h0->0, h1->1, ...)."),
        Param("settle_s", "Settle Time", "float", 0.1, unit="s",
              help="wait [s] after beam_up before triggering the VNA sweep."),
        Param("log_psu", "Log PSU Rails", "bool", False,
              help="record every PSU rail's V/I + total Idd + Pdc once per phase code "
                   "(replicated on that code's rows). Default off -- the VNA "
                   "test does not need bias data and PSU reads slow the sweep."),
    ]

    def run(self, ctx: TestContext, params: dict, log=print) -> TestResult:
        bench = ctx.bench
        chip = ctx.chip
        # Ruling 1: chip._fh is set by bring_up_tx/bring_up_rx; fall back to a bare
        # FH wrapper when a caller skipped bring-up (e.g. manual.py --no-enable).
        fh = getattr(chip, "_fh", None) or FH(chip, getattr(bench.board, "chip_id", 0))
        codes = [int(c) for c in params["phase_codes"]]
        mode = params["read_mode"]
        log_psu = bool(params.get("log_psu", False))
        settle = float(params["settle_s"])
        beam = getattr(bench.board, "beam", "b0")
        chans = getattr(bench.board, "active_channels", []) or []
        channel = chans[0] if chans else "?"

        # channel_quad: routed 채널의 quad 와 일치해야 한다(gain_index_accuracy 와
        # 동일 규칙). None 이면 active 채널 이름의 숫자에서 자동 유도.
        chquad = params.get("channel_quad")
        if chquad is None:
            chquad = (int(channel[1]) if len(channel) >= 2 and channel[1].isdigit()
                      else 0)
            log(f"[phase ] channel_quad auto = {chquad} (from active channel {channel})")
        chquad = int(chquad)

        # channel_quad 는 라우팅 채널의 quad 인덱스일 뿐 편파는 담지 않는다. phase-cal
        # RAM 주소는 편파(hv)에 의존하므로(firehawk.set_rtps_attn), 실제 라우팅 채널의
        # 편파를 그대로 쓰고 인덱스만 chquad 로 덮는다(기본은 서로 같은 값이다).
        # active_channels 가 비어 channel="?" 인 극단적인 경우엔 h 로 기본한다
        # (gain_index_accuracy.set_channel() 의 beamtable 타깃과 동일한 관례).
        pol_char = channel[0].lower() if len(channel) >= 2 and channel[0].lower() in ("h", "v") else "h"
        phase_channel = f"{pol_char}{chquad}"

        def apply_phase(code: int) -> None:
            """phase 한 코드 적용: 9-bit(coarse beam-table + fine phase-cal RAM).

            attenuator_setting(진폭, beam-table 워드 bits[6:0])은 현재 값을 읽어
            그대로 다시 써서 보존한다(gain_index_accuracy/manual.phase() 와 동일 패턴).
            """
            cur_atten = get_gain(fh, "beamtable", channel=phase_channel)
            set_phase(fh, int(code), beam=beam, channel=phase_channel, atten=cur_atten)

        # 1) VNA 준비(lazy connect + 비파괴 S21 셋업). preset/경로손실 보정 없음.
        vna = bench.get_vna(log)
        log(f"[phase ] NOTE: the VNA must be user-calibrated for the current "
            f"cabling (no preset / no path-loss offsets are applied)")
        vna.setup_s21(log=log)
        if bool(params.get("configure_freq", False)):
            log("[phase ] WARNING: programming VNA sweep (configure_freq=True) "
                "-- verify your calibration still applies")
            vna.configure_sweep(float(params["freq_start_hz"]),
                                float(params["freq_stop_hz"]),
                                int(params["freq_points"]), log=log)
        vna.hold(log=log)

        # 2) 주파수축 1회 읽기 + 분석 인덱스/point 그리드 인덱스 결정.
        freqs = vna.read_freqs()
        if not freqs:
            raise RuntimeError("VNA returned an empty frequency axis -- check "
                               "trace/channel setup on the instrument")

        def nearest_idx(f: float) -> int:
            return min(range(len(freqs)), key=lambda i: abs(freqs[i] - f))

        mfreq = params.get("marker_freq_hz")
        a_idx = nearest_idx(float(mfreq)) if mfreq is not None else len(freqs) // 2
        a_freq = freqs[a_idx]

        if mode == "trace":
            sel_idx = list(range(len(freqs)))
        elif mode == "point":
            start = float(params["freq_start_hz"])
            stop = float(params["freq_stop_hz"])
            step = float(params["freq_step_hz"])
            if step <= 0:
                raise ValueError("freq_step_hz must be > 0 in point mode")
            grid = []
            f = start
            while f <= stop + 1e-3:
                grid.append(f)
                f += step
            sel_idx = sorted({nearest_idx(g) for g in grid})
        else:   # marker
            sel_idx = [a_idx]

        rail_names = psu_rail_names(bench) if log_psu else []
        columns = (["phase_code", "freq_Hz", "gain_dB", "phase_deg"]
                   + (rail_vi_columns(rail_names) if log_psu else []))
        rows: list[list] = []
        a_gain: list[float] = []   # 분석 주파수에서의 code 별 gain
        a_phase: list[float] = []  # 분석 주파수에서의 code 별 phase

        log(f"[phase ] beam={beam} ch={channel} quad={chquad}  mode={mode}  "
            f"{len(codes)} codes x {len(sel_idx)} freq pts  "
            f"(analysis @ {a_freq/1e9:.3f} GHz)")

        # 3) sweep 루프. 끝나면 phase 0 복원 + VNA 연속 sweep 복귀.
        try:
            for code in codes:
                apply_phase(code)
                time.sleep(settle)
                _, gain_db, phase_deg = vna.read_s21()
                if len(gain_db) != len(freqs):
                    raise RuntimeError(
                        f"VNA trace length changed mid-sweep "
                        f"({len(gain_db)} vs {len(freqs)} pts) -- was the "
                        f"instrument touched during the measurement?")
                rail = read_rail_vi(bench, rail_names, log) if log_psu else []
                for i in sel_idx:
                    rows.append([code, round(freqs[i], 1), round(gain_db[i], 3),
                                 round(phase_deg[i], 3)] + rail)
                a_gain.append(gain_db[a_idx])
                a_phase.append(phase_deg[a_idx])
                log(f"  phase={code:3d}: S21 {gain_db[a_idx]:+7.2f} dB  "
                    f"{phase_deg[a_idx]:+8.2f} deg @ {a_freq/1e9:.3f} GHz")
        finally:
            try:
                apply_phase(0)   # phase zero 복원(atten 은 보존됨)
            except Exception as e:
                log(f"[warn  ] could not restore phase code 0: {e}")
            try:
                vna.continuous(log=log)   # sweep 을 사용자에게 돌려준다
            except Exception as e:
                log(f"[warn  ] could not restore VNA continuous sweep: {e}")

        # 4) 요약 통계(분석 주파수 기준, unwrap 후). raw 데이터가 주산물이며
        #    통계는 참고용 — pass/fail 없음(passed=None).
        mean_step = std_step = span = ripple = None
        if len(a_phase) >= 2:
            unwrapped = _unwrap_deg(a_phase)
            deltas = [unwrapped[i + 1] - unwrapped[i]
                      for i in range(len(unwrapped) - 1)]
            mean_step = sum(deltas) / len(deltas)
            var = sum((d - mean_step) ** 2 for d in deltas) / len(deltas)
            std_step = var ** 0.5
            span = max(unwrapped) - min(unwrapped)
            ripple = max(a_gain) - min(a_gain)
            summary = (f"{len(codes)} phase codes: mean step "
                       f"{mean_step:+.3f} deg (ideal {IDEAL_STEP_DEG:.4f}), "
                       f"span {span:.1f} deg, gain ripple {ripple:.2f} dB "
                       f"@ {a_freq/1e9:.3f} GHz")
        elif len(a_phase) == 1:
            summary = (f"1 phase code: S21 {a_gain[0]:+.2f} dB "
                       f"{a_phase[0]:+.2f} deg @ {a_freq/1e9:.3f} GHz")
        else:
            summary = "no points measured"
        log(f"[phase ] {summary}")

        rnd = lambda v: round(v, 3) if v is not None else None
        return TestResult(self.id, self.title, None, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "channel_quad": chquad,
                                "read_mode": mode,
                                # axis -> CSV 파일명 태그 재사용(_marker/_point/_trace)
                                "axis": mode,
                                # freq_hz -> CSV 파일명 태그(다른 항목과 동일 관례)
                                "freq_hz": a_freq,
                                "analysis_freq_hz": a_freq,
                                "mean_step_deg": rnd(mean_step),
                                "std_step_deg": rnd(std_step),
                                "phase_span_deg": rnd(span),
                                "gain_ripple_db": rnd(ripple),
                                "ideal_step_deg": IDEAL_STEP_DEG,
                                "n_codes": len(codes),
                                "n_sweep_points": len(freqs),
                                "configure_freq": bool(params.get("configure_freq",
                                                                  False)),
                                "path_loss": "not applied (VNA user cal "
                                             "de-embeds cables)"})
