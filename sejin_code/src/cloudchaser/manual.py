"""수동(인터랙티브) 제어 콘솔 — 신호가 제대로 나오는지 직접 확인용.

목적: 전원 인가 + 칩 init (+ 선택 채널 ON) 까지만 자동으로 해두고, 그 다음부터는
사용자가 Python 대화형 쉘에서 보드 레지스터와 계측기(SG/SA/PSU)를 '직접' 명령으로
제어하며 RF 신호가 나오는지 눈으로 확인하기 위한 도구다.

실행:
  python -m cloudchaser.manual                         # 전원+init+H0(기본) ON, 쉘 진입
  python -m cloudchaser.manual --channels h0,h1        # H0,H1 ON
  python -m cloudchaser.manual --no-enable             # init 만(채널 enable 안 함, 순수 수동)
  python -m cloudchaser.manual --no-power              # PSU 램프업 생략(이미 켜둔 경우)
  python -m cloudchaser.manual --fake                  # 하드웨어 없이 동작 점검

쉘에 들어가면 helpme() 를 치면 쓸 수 있는 명령(헬퍼)이 나온다. 주요 객체:
  bench, psu1, psu2, sg, sa, chip, fh  (계측기/보드 핸들. fh = raw 레지스터 엔진)
끝낼 때는 exit() 또는 Ctrl-Z Enter. (전원은 켜진 채로 둔다. 내리려면 shutdown())

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import code
import sys
import time
from pathlib import Path

from .bench import Bench
from .board.bias_measured import apply_measured_bias
from .board.bringup import apply_split_mode, bring_up_tx, make_chip
from .board.firehawk import FH, QUAD_ENABLES_ADDR, QUAD_PWRDN_ADDR, fe_row
from .regdump import load_dump, save_dump
from .regdump import regdiff as _regdiff
from .board.gain_map import chip_kind, disable_all, get_gain, route_channels, set_gain, set_phase
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout


def _parse_ch(ch: str) -> tuple[str, int]:
    """'h0' -> ('h', 0)."""
    return ch[0].lower(), int(ch[1])


# 정상 측정 mem_dump 에서 추출한 golden 레지스터 JSON(repo docs/).
_GOLDEN_PATH = Path(__file__).resolve().parents[2] / "docs" / "golden_h0b0_25g.json"


def build_namespace(bench: Bench, chip, beam: str) -> dict:
    """대화형 쉘에 노출할 객체 + 헬퍼 함수들을 만든다.

    헬퍼는 '한 줄짜리 흔한 동작'을 감싼 것뿐이다. 그 아래의 객체(chip/sg/sa/fh/...)를
    직접 호출해도 된다(예: fh.wr_verify(0x1005, 값) -- raw register write; 벤더
    chip.fields 쓰기 API 는 쓰기 경로에서 제거됐다, 근거는 설계 스펙 2장).
    """
    sg = bench.sg
    sa = bench.sa
    # Ruling 1: chip._fh is set by bring_up_tx/bring_up_rx; fall back to a bare
    # FH wrapper when a caller skipped bring-up. manual.py's --no-enable path is
    # exactly that case -- it calls chip.init() only, never bring_up_tx.
    fh = getattr(chip, "_fh", None) or FH(chip, getattr(bench.board, "chip_id", 0))
    # SG 의 현재 주파수/레벨을 기억(SA center 기본값 등에 사용). toml 기본값으로 초기화.
    st = {"freq": float(bench.sg_cfg.get("freq_hz", 28.0e9)),
          "level": float(bench.sg_cfg.get("level_dbm", -30.0))}

    # ---- 보드(레지스터) 제어 -------------------------------------------
    def rd(field: str):
        """Read a register field by name."""
        v = chip.fields.rd(field)
        print(f"  {field} = {hex(v)} ({v})")
        return v

    def wrf(field: str, value: int, verify: bool = True):
        """Write a register field by name, leaving the rest of the word alone.

        wrf('d2a_dist_b0_st1_ptat', 50)     one field of 0x104C, [13:8] untouched
        wrf('centerbias_en', 1)

        The field's address/bit position comes from the vendor field table, but the
        write itself is a raw read-modify-write through fh, so the vendor shadow-cache
        write path (its per-field setter plus commit) stays unused (Ruling 28).
        verify=False skips the readback (fh.wr instead of fh.wr_verify).
        Field names are lower case; the full table is in docs/COMMANDS.md appendix B.
        """
        # segments = [(addr, lsb, width), ...], LSB-first. 대부분 1개지만 워드에
        # 걸쳐 쪼개진 필드가 있어 벤더 getter 와 같은 순서로 훑는다.
        f = chip.fields._get_field(field)      # 이름이 틀리면 유효 필드 힌트와 함께 KeyError
        v = int(value)
        if not 0 <= v < (1 << f.width):
            raise ValueError(f"{field}: {v} does not fit in {f.width} bit(s) "
                             f"(0..{(1 << f.width) - 1})")
        bitpos = 0
        for addr, bit, width in f.segments:
            mask = (1 << width) - 1
            part = (v >> bitpos) & mask
            cur = fh.rd(addr)
            new = (cur & ~(mask << bit)) | (part << bit)
            if verify:
                fh.wr_verify(addr, new)
            else:
                fh.wr(addr, new)
            print(f"  0x{addr:04X}: 0x{cur:04X} -> 0x{new:04X}  "
                  f"[{bit + width - 1}:{bit}] = {part}")
            bitpos += width
        print(f"  {field} = {hex(v)} ({v})")
        return v

    def enable(*chs: str, b: str = beam):
        """Enable channel(s) routed to the beam (raw quad_enables/quad_pwrdn/
        beam_enables via route_channels()). Additive within the SAME beam --
        routing to a different beam replaces the routed set (this raw layer,
        like chan()/bring-up/gain_map, drives one active beam at a time).
        TX/RX polarity is auto-derived from the chip's own identity register
        (chip_kind) -- never hardcoded (Ruling 21). e.g. enable('h0') / enable('h0','h1')."""
        prev = bench.board.active_channels or []
        chs_set = (sorted(set(prev) | set(chs)) if b == bench.board.beam
                   else sorted(set(chs)))
        bench.board.active_channels = chs_set
        bench.board.beam = b
        kind = chip_kind(fh)
        route_channels(fh, chs_set, b, kind)
        # route_channels 가 0x1009 를 이 채널 분기만 남기도록 덮으므로, split 을
        # 쓰는 설정이면 여기서 되살린다(안 그러면 bench.toml 이 split 인데 조용히
        # thru 로 떨어진다 -- 실측 게인 차이 8 dB).
        apply_split_mode(fh, bench.board, kind=kind, log=print)
        paths()

    def disable(ch: str | None = None, b: str | None = None):
        """Disable channel(s) / beam (raw). No args = disable everything.
        ch alone = drop that one channel, keep the rest routed. b alone =
        disable the whole beam if it is the currently active one (this raw
        layer only drives one beam at a time, so there is nothing else to
        disable)."""
        if ch is None and b is None:
            disable_all(fh)
            bench.board.active_channels = []
        elif ch is not None:
            remaining = [c for c in (bench.board.active_channels or []) if c != ch]
            bench.board.active_channels = remaining
            if remaining:
                kind = chip_kind(fh)
                route_channels(fh, remaining, bench.board.beam, kind)
                apply_split_mode(fh, bench.board, kind=kind, log=print)
            else:
                disable_all(fh)
        else:   # beam only
            if b == bench.board.beam:
                disable_all(fh)
                bench.board.active_channels = []
        paths()

    def paths():
        """Print channels currently routed to each beam.

        Reconstructed from raw registers, not the vendor path object's cached
        `.active` Python attribute -- that cache is never updated by
        chan()/enable()'s raw writes and would silently show stale/empty state
        (the exact bug class this migration removes). Two registers are needed,
        not one:
        quad_enables (0x100C+i) says WHICH BEAM(S) a quad is routed to, but
        route_channels() sets its H_en/V_en halves identically regardless of
        which polarity was actually requested -- polarity only shows up in
        quad_pwrdn's (0x1010+i) power-stage bits, and those ARE TX/RX-mirrored
        (Ruling 21), so chip_kind() is needed here to read them correctly.
        """
        kind = chip_kind(fh)
        h_base, v_base = (3, 0) if kind == "tx" else (0, 3)
        active: dict[int, list[str]] = {}
        for i in range(4):
            beams_mask = fh.rd(QUAD_ENABLES_ADDR + i) & 0x07
            if not beams_mask:
                continue
            pwrdn = fh.rd(QUAD_PWRDN_ADDR + i) & 0x3F
            h_on = bool(pwrdn & (0b111 << h_base))
            v_on = bool(pwrdn & (0b111 << v_base))
            for beam_i in range(3):
                if not (beams_mask & (1 << beam_i)):
                    continue
                if h_on:
                    active.setdefault(beam_i, []).append(f"h{i}")
                if v_on:
                    active.setdefault(beam_i, []).append(f"v{i}")
        if not active:
            print("  active paths: none")
            return
        for beam_i in sorted(active):
            print(f"  active paths: b{beam_i} -> {sorted(active[beam_i])}")

    def gain(code: int, b: str = beam):
        """Set beam common gain (0x1005 + beam index). 6-bit attenuation code (0=max gain).
        e.g. gain(0x20) / gain(0x20, b='b1')"""
        set_gain(fh, "common", int(code), beam=b)
        print(f"  gain(common) beam={b} <- {hex(int(code))}")

    def chgain(ch: str, code: int):
        """Set per-channel FE gain (0x1018 + channel index, 4-bit). DEAD on this
        silicon -- the working per-path knob is atten() (beam-table RTPS
        attenuator). e.g. chgain('h0', 0x10)."""
        set_gain(fh, "fe", int(code), channel=ch)
        print(f"  chgain {ch} <- {hex(int(code))}")

    def atten(ch: str, code: int):
        """Set channel RTPS attenuator (beam-table word, 7-bit, 0=max gain).
        e.g. atten('h0', 0x0)."""
        set_gain(fh, "beamtable", int(code), channel=ch)
        print(f"  atten {ch} <- {hex(int(code))}")

    def phase(ch: str, code: int):
        """Set per-channel RTPS phase -- 9-bit (coarse beam-table + fine phase-cal RAM).

        code: raw phase code 0..511 (0 = phase zero). Code-to-degree mapping
        is NOT documented by the vendor (unverified). Preserves the current
        attenuator code (reads it back first, writes it unchanged).
        Note: chan() zeroes the beam table, so phase resets to 0 on channel
        re-selection. e.g. phase('h0', 0x100)
        """
        cur_atten = get_gain(fh, "beamtable", channel=ch)
        set_phase(fh, int(code), beam=beam, channel=ch, atten=cur_atten)
        print(f"  phase {ch} <- {int(code)} (beam {beam}, 9-bit, atten preserved={hex(cur_atten)})")

    def rtps():
        """Show beam-table beam 0 state: per-quad attenuator / phase codes.

        Read straight from the beam-table registers every call (word address =
        channel index, atten = bits[6:0], coarse phase = bits[13:7]). The vendor
        beam-table object keeps its own Python-side copy of the table, but
        atten()/phase()/chan() write those words raw and never refresh it, so
        printing that copy shows stale codes -- the same bug class paths()
        already documents and this migration removes.
        """
        print("  beam 0 (per quad):")
        for q in range(4):
            w = fh.rd(q)
            print(f"    quad {q}: atten={w & 0x7F:2d}  phase={(w >> 7) & 0x7F:3d}")

    def load_golden(path: str | None = None, *, do_reset: bool = True):
        """Load the full register state captured from a known-good measurement (MATLAB mem_dump).

        path : golden JSON file (default: repo docs/golden_h0b0_25g.json).
               Format: {'0x1008': 3, ...} -- RW registers only (RO/data excluded).
        Purpose: reproduce a known-good register state to verify the signal path.
        Every address is written raw via fh.wr() -- applied immediately, no
        latch/commit step needed. do_reset uses the raw SPI reset (fh.reset()),
        NOT the vendor chip.reset() -- that also runs load_efuse(), which writes
        registers through the vendor shadow-cache path this migration removes
        (same hazard as the vendor init call, see board/bringup.py's design-spec note).
        """
        import json
        p = Path(path) if path else _GOLDEN_PATH
        g = json.loads(p.read_text())
        if do_reset:
            fh.reset()
        n = 0
        for addr, val in sorted(g.items(), key=lambda kv: int(kv[0], 16)):
            fh.wr(int(addr, 16), int(val))
            n += 1
        print(f"  golden: {n} registers written raw (from {p.name})")
        print("  golden loaded. (set freq/SA, then peak())")

    # ---- 채널 선택 / 단별 진단 ----------------------------------------
    def chan(ch: str = "h0", b: str | None = None):
        """Bring ONE channel up to measurement-ready state (all others off).

        Steps: disable all -> centerbias_en ON -> route channel to beam
        -> beam_table zero + beam_up -> common gain max (code 0).
        Then move SA to the channel RF port and use rf()/saconf()/peak().
        e.g. chan('h1')  /  chan('v0')
        """
        bm = b or beam
        # 측정 대상 채널/빔을 bench 부기에 반영 -> 측정 아이템이 채널 meta(파일명)
        # 와 경로 손실 계산에 active_channels[0]/beam 을 그대로 쓴다.
        bench.board.active_channels = [ch]
        bench.board.beam = bm
        disable_all(fh)
        # centerbias_en/centermirror_en (0x1008 bits 0/1) ON. bring_up_tx/rx 가 이미
        # 켜두지만, --no-enable(bring-up 생략) 경로로 chip.init() 만 했을 수 있으므로
        # 여기서도 명시적으로 켠다 -- CLAUDE.md "보드 하드웨어 현황" 참고.
        fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
        # TX/RX 라우팅 극성(H/V pwrdn 비트 위치)은 칩 종류마다 반대다(Ruling 21) --
        # chip._fh 의 identity 레지스터로 런타임에 판별한다(하드코딩 금지).
        kind = chip_kind(fh)
        route_channels(fh, [ch], bm, kind)
        # ★ route_channels 는 0x1009 를 단일 채널 분기로 되돌린다 -- split 설정이면
        #   여기서 다시 적용해야 bring-up 과 같은 상태가 된다.
        apply_split_mode(fh, bench.board, kind=kind, log=print)
        # ★ DIST bias 는 빔당 1행이라 채널마다 다른 값을 동시에 못 가진다 --
        #   채널을 바꾸면 그 채널의 실측 코드로 다시 기입한다(split 과 같은 이유).
        apply_measured_bias(fh, bench.board, ch, beam_idx=int(bm[1]), log=print)
        fh.load_beam_table(0, [[0] * 8])
        fh.beam_up()
        set_gain(fh, "common", 0, beam=bm)
        pol, idx = _parse_ch(ch)
        port = f"RF_CH{idx}_{'HPOL' if pol == 'h' else 'VPOL'}"
        paths()
        mode = ("split" if getattr(bench.board, "split_mode", False)
                and kind == "tx" else "thru")
        print(f"  channel {ch} -> {bm} ready (center bias ON, RTPS=0, common gain max, DIST {mode}).")
        print(f"  >>> connect SA to {port}, then: rf(True,freq=28e9,level=-10); saconf(center=28e9,ref=20); peak()")

    def biasscan(ch: str = "h0"):
        """Sweep each amplifier stage PTAT bias 0->63, watch FE rail current delta.

        No current response for a stage = that stage is dead.
        Call chan(ch) first so only that channel is active.
        FE rails are shared across 4 channels -- isolate one at a time.
        """
        pol, idx = _parse_ch(ch)
        row = fe_row(idx, pol)   # FE bias 8x5 row index (H=2i, V=2i+1)
        print(f"  bias scan ch {ch}: per-stage PTAT 0->63, watch rail current")
        for st, rail, desc in [(1, "FE1_4V0", "PA 4V"),
                               (2, "FE2_1V8", "Driver 1.8V"),
                               (3, "FE3_1V8", "Comb 1.8V")]:
            col = st - 1   # bias columns = [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS]
            try:
                bias = fh.get_fe_bias()
                bias[row][col] = 0
                fh.set_fe_bias(bias); time.sleep(0.15)
                i0 = bench.read_all_vi()[rail]["i"] * 1000
                bias[row][col] = 63
                fh.set_fe_bias(bias); time.sleep(0.15)
                i63 = bench.read_all_vi()[rail]["i"] * 1000
                bias[row][col] = 32   # 중간값으로 복귀
                fh.set_fe_bias(bias)
                flag = "OK" if abs(i63 - i0) > 2 else "** NO RESPONSE **"
                print(f"    St{st} {desc:11} {rail}: {i0:5.1f} -> {i63:5.1f} mA   {flag}")
            except Exception as e:
                print(f"    St{st} ch{idx}_{pol}_ptat_st{st}: {e}")

    def bias_test(ch: str = "h0", *, freq_hz: float = 28.0e9,
                  sg_level_dbm: float = -10.0, coarse_step: int = 8,
                  lo: int = 8, hi: int = 56, refine: bool = True,
                  settle_s: float = 0.05, idd_every: int = 25,
                  idd_limit_ma: float | None = 320.0,
                  save: str | None = None, top: int = 10):
        """Sweep the three PA-stage PTAT biases and report the highest-gain combo.

        Two-stage COARSE -> REFINE grid over PTAT_St1 (PA) / St2 (driver) /
        St3 (combiner) of ONE channel, reading gain from the SA at a fixed CW
        input. Rough by design -- meant to show the trend, not to find the
        exact optimum.

          bias_test()                       h0, 28 GHz, ~470 points
          bias_test('v1', coarse_step=12)   coarser and faster
          bias_test(refine=False)           coarse grid only

        Gain = SA peak - SG level (path loss is already applied as SG/SA
        offsets, so SG level IS the chip input and the SA read IS the chip
        output). Restores the original bias row on exit, including on error.
        """
        pol, idx = _parse_ch(ch)
        row = fe_row(idx, pol)
        grid = list(range(lo, hi + 1, coarse_step))

        # 측정 준비: 경로손실 오프셋 -> SG/SA 설정 -> RF ON (op1db 와 같은 순서)
        bench.apply_path_loss(freq_hz, log=print)
        sg.set_frequency(freq_hz)
        sg.set_level(sg_level_dbm)
        sa_cfg = getattr(bench, "sa_cfg", {})
        sa.configure(center_hz=freq_hz, span_hz=100.0e6,
                     rbw_hz=float(sa_cfg.get("rbw_hz", 1.0e6)),
                     ref_level_dbm=25.0,
                     input_atten_db=float(sa_cfg.get("input_atten_db", 10.0)),
                     spectrum_mode=bool(sa_cfg.get("spectrum_mode", True)),
                     log=print)
        sg.rf_output(True)

        base = fh.get_fe_bias()
        keep = list(base[row])          # 원래 행(CTAT/CBIAS 유지 + 복원용)
        rows: list[list] = []
        best = None                     # (gain, st1, st2, st3)
        n_done = 0
        aborted = None

        def measure(st1, st2, st3):
            nonlocal n_done, best, aborted
            b = fh.get_fe_bias()
            b[row] = [st1, st2, st3, keep[3], keep[4]]
            fh.set_fe_bias(b)
            time.sleep(settle_s)
            pout = sa.measure_peak_dbm()
            gain = pout - sg_level_dbm
            n_done += 1
            idd = None
            if idd_limit_ma is not None and n_done % max(1, idd_every) == 0:
                idd = sum(d["i"] for d in bench.read_all_vi().values()) * 1000
                if idd > idd_limit_ma:
                    aborted = (f"total Idd {idd:.0f} mA exceeded the "
                               f"{idd_limit_ma:.0f} mA limit")
            rows.append([st1, st2, st3, round(pout, 2), round(gain, 2),
                         "" if idd is None else round(idd, 1)])
            if best is None or gain > best[0]:
                best = (gain, st1, st2, st3)
                print(f"    new best: St1={st1:2d} St2={st2:2d} St3={st3:2d}"
                      f"  gain={gain:6.2f} dB")
            return gain

        try:
            total = len(grid) ** 3
            print(f"  [bias_test] ch={ch} {freq_hz/1e9:.2f} GHz  SG={sg_level_dbm:+.1f} dBm")
            print(f"  [coarse] {grid} -> {total} points")
            for i, st1 in enumerate(grid):
                if aborted:
                    break
                for st2 in grid:
                    if aborted:
                        break
                    for st3 in grid:
                        measure(st1, st2, st3)
                        if aborted:
                            break
                print(f"    ...{n_done}/{total}  (St1={st1})")

            if refine and best and not aborted:
                half = max(1, coarse_step // 2)
                def around(v):
                    return sorted({min(63, max(0, v + d))
                                   for d in (-coarse_step, -half, 0, half, coarse_step)})
                g1, g2, g3 = around(best[1]), around(best[2]), around(best[3])
                print(f"  [refine] around St1={best[1]} St2={best[2]} St3={best[3]}"
                      f" -> {len(g1)*len(g2)*len(g3)} points")
                for st1 in g1:
                    if aborted:
                        break
                    for st2 in g2:
                        if aborted:
                            break
                        for st3 in g3:
                            measure(st1, st2, st3)
                            if aborted:
                                break
        finally:
            b = fh.get_fe_bias()
            b[row] = list(keep)
            fh.set_fe_bias(b)
            sg.rf_output(False)
            print(f"  [restore] {ch} bias -> {keep}, RF OFF")

        if aborted:
            print(f"  !! ABORTED: {aborted}")
        if not rows:
            print("  no points measured.")
            return None
        rows.sort(key=lambda r: -r[4])
        print(f"\n  top {min(top, len(rows))} of {len(rows)} points"
              f"   (baseline Casper = 15 / 45 / 55)")
        print("    St1  St2  St3   Pout    Gain")
        for r in rows[:top]:
            print(f"    {r[0]:3d}  {r[1]:3d}  {r[2]:3d}  {r[3]:7.2f} {r[4]:7.2f}")
        if save:
            p = Path(save)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8", newline="") as f:
                f.write("ptat_st1,ptat_st2,ptat_st3,pout_dbm,gain_db,total_idd_ma\n")
                for r in rows:
                    f.write(",".join(str(x) for x in r) + "\n")
            print(f"  saved {len(rows)} rows -> {p}")
        return {"best": best, "rows": rows, "aborted": aborted}

    # ---- 신호발생기(SG) -----------------------------------------------
    def rf(on: bool = True, freq: float | None = None, level: float | None = None):
        """Control SG RF output. e.g. rf(True, freq=28e9, level=-20) / rf(False).

        freq and level (if given) are applied before toggling the RF output.
        """
        if freq is not None:
            sg.set_frequency(freq); st["freq"] = float(freq)
        # 경로 손실 -> SG/SA 오프셋(SG level=칩 입력, SA read=칩 출력). 손실은 자동 적용.
        bench.apply_path_loss(st["freq"], log=lambda *_a: None)
        if level is not None:
            sg.set_level(level); st["level"] = float(level)
        sg.rf_output(on)
        print(f"  SG: {st['freq']/1e9:.3f} GHz @ {st['level']:.2f} dBm  RF={'ON' if on else 'OFF'}")

    def rfoff():
        """Turn RF output OFF (safe shortcut)."""
        sg.rf_output(False)
        print("  SG: RF OFF")

    def modoff():
        """Turn SG baseband modulation OFF -> back to CW. Run this after an EVM
        (waveform) test before any CW test (ip1db / gain / op1db) so the SG emits
        CW, not the leftover ARB waveform. (CW test items also do this on their own.)"""
        sg.modulation_off()
        print("  SG: baseband OFF (CW)")

    def modon():
        """Turn the SG baseband (loaded ARB waveform) back ON. Use before a manual
        EVM measurement if a prior CW test left the baseband off. (evm_rx/manual
        EVM does this on its own.) Assumes a waveform is already loaded."""
        sg.modulation_on()
        print("  SG: baseband ON (waveform)")

    def level(dbm: float):
        """Change SG output level [dBm] (RF on/off state unchanged)."""
        sg.set_level(dbm); st["level"] = float(dbm)
        print(f"  SG level <- {dbm:.2f} dBm")

    # ---- 스펙트럼분석기(SA) -------------------------------------------
    def saconf(center: float | None = None, span: float = 100e6,
               ref: float = 15.0, rbw: float | None = None,
               atten_db: float | None = None):
        """Configure SA for measurement. center defaults to current SG frequency. (Call once before measuring.)"""
        cfg = bench.sa_cfg
        sa.configure(
            center_hz=center if center is not None else st["freq"],
            span_hz=span,
            rbw_hz=rbw if rbw is not None else float(cfg.get("rbw_hz", 1.0e6)),
            ref_level_dbm=ref,
            input_atten_db=atten_db if atten_db is not None else float(cfg.get("input_atten_db", 10.0)),
            spectrum_mode=bool(cfg.get("spectrum_mode", True)),
        )
        # 출력 경로 손실 -> SA ref level offset (peak() 가 칩 출력 전력을 직접 반환).
        bench.apply_path_loss(center if center is not None else st["freq"],
                              log=lambda *_a: None)
        print(f"  SA: center={ (center if center is not None else st['freq'])/1e9:.3f} GHz "
              f"span={span/1e6:.1f} MHz ref={ref:.1f} dBm")

    def peak():
        """Single sweep + marker peak: returns SA peak power [dBm].
        Loss-compensated (= chip beam-port output) when offsets are applied via rf()/saconf()."""
        p = sa.measure_peak_dbm()
        print(f"  SA peak = {p:.2f} dBm")
        return p

    # ---- 전원(PSU) -----------------------------------------------------
    def vi():
        """Read and print all PSU rail voltage / current."""
        m = bench.read_all_vi()
        for name, d in m.items():
            print(f"  {name}: {d['v']:.3f} V  {d['i']*1000:.1f} mA")
        return m

    def shutdown():
        """Ramp all rails safely to 0 V (RF off first). Call at end of session."""
        rfoff()
        bench.power_down()
        print("  power down complete")

    # ---- 레지스터 덤프 / 대조 -------------------------------------------
    # CLI(`python -m cloudchaser.regdump`)는 항상 bring-up 을 다시 돌린다.
    # 벤치에서 손으로 만진(gain/phase/bias) 뒤 '지금 이 상태' 를 뜨려면
    # 그게 아니라 읽기만 해야 하므로, 세션용 헬퍼를 따로 둔다.
    def dump(path: str | None = None, a: int = 0x1000, b: int = 0x1204) -> dict:
        """Read the CURRENT register state and optionally save it (read-only).

        Does NOT re-run bring-up, so whatever you set by hand stays put.
          dump()                     read 0x1000..0x1203, return {addr: value}
          dump('out/regs.csv')       also write an addr,value CSV
          dump(b=0x1070)             config region only (112 regs, faster)
        """
        lo, hi = int(a), int(b)
        regs = {addr: fh.rd(addr) for addr in range(lo, hi)}
        print(f"  read {len(regs)} regs 0x{lo:04X}..0x{hi - 1:04X} (live, no bring-up)")
        if path:
            save_dump(regs, path)
        return regs

    def regdiff(theirs, ours=None, a: int = 0x1000, b: int = 0x1204):
        """Compare a reference dump against the CURRENT chip state.

          regdiff('reference/Data_260729_DoosanSTMP_RegDump.xlsx')
          regdiff('theirs.csv', 'ours.csv')     compare two files instead
        Accepts .csv / .xlsx / a dict. ours=None reads the chip live.
        Only differing registers are printed; returns the differing addresses.
        """
        t = load_dump(theirs)
        o = load_dump(ours) if ours is not None else dump(a=a, b=b)
        return _regdiff(t, o)

    def helpme():
        print(__HELP__)

    ns = {
        # 객체
        "bench": bench, "psu1": bench.psu1, "psu2": bench.psu2,
        "sg": sg, "sa": sa, "chip": chip, "fh": fh,
        # 보드
        "rd": rd, "wrf": wrf, "enable": enable, "disable": disable,
        "paths": paths,
        "gain": gain, "chgain": chgain, "atten": atten, "phase": phase,
        "rtps": rtps,
        "load_golden": load_golden,
        "chan": chan, "biasscan": biasscan, "bias_test": bias_test,
        "dump": dump, "regdiff": regdiff,
        # SG
        "rf": rf, "rfoff": rfoff, "modoff": modoff, "modon": modon, "level": level,
        # SA
        "saconf": saconf, "peak": peak,
        # PSU
        "vi": vi, "shutdown": shutdown,
        "helpme": helpme,
        "_sgstate": st,   # session.status() 가 현재 SG 주파수/레벨을 보여주기 위해 노출
    }
    return ns


__HELP__ = """\
=== Manual console commands (call like functions) ===
 Board:
   enable('h0'[, 'h1', ...])   turn channel(s) ON (route to beam)
   disable(['h0'])             turn channel/beam OFF (no args = all off)
   paths()                     show active beam->channel routing
   gain(0x20)                  set beam common gain (6-bit)
   chgain('h0', 0x10)          set per-channel FE gain (DEAD on this silicon)
   atten('h0', 0x0)            set channel RTPS attenuator (beam-table, 7-bit)
   phase('h0', 0x100)          set per-channel RTPS phase (9-bit code, beam table + phase-cal RAM)
   rtps()                      show beam-table atten/phase per quad (read from registers)
   rd('field')                 raw register field read (write via fh.wr_verify(addr, val))
   biasscan('h0')              per-stage PTAT 0->63, watch rail current (dead-stage check)
   bias_test('h0')             2-stage PTAT grid sweep -> highest-gain St1/St2/St3 combo
   fh.wr_verify(0x1005, 0x10)  raw register write, applied immediately (no latch/commit needed)
 Register dump / compare (live state, no bring-up):
   dump()                      read 0x1000..0x1203 -> {addr: value}
   dump('out/regs.csv')        read and save as addr,value CSV
   regdiff('ref/Data_260729_DoosanSTMP_RegDump.xlsx')   compare Sivers dump vs the chip now
 Signal generator (SG):
   rf(True, freq=28e9, level=-20)   set freq/level then RF ON
   rf(False) / rfoff()              RF OFF
   level(-15)                       change output level [dBm]
 Spectrum analyzer (SA):
   saconf(center=28e9, span=100e6, ref=15)   configure SA (center defaults to SG freq)
   peak()                                    single sweep, read marker peak [dBm]
 Power (PSU):
   vi()           read all rail V / I
   shutdown()     ramp all rails down to 0 V (RF off first)
 Objects: bench, psu1, psu2, sg, sa, chip, fh (raw register engine)
 Quit: exit()  (power stays ON; use shutdown() to power down)

 Typical signal check:
   rf(True, freq=28e9, level=-20)   # drive input
   saconf(center=28e9, ref=15)      # look at 28 GHz
   peak()                           # is there a real tone above noise floor?
   vi()                             # did FE current rise (amp drawing power)?
"""


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(description="CloudChaser manual interactive console")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--channels", default=None,
                   help="comma list to enable, e.g. 'h0,h1'. Default: bench.toml active_channels")
    p.add_argument("--beam", default=None, help="beam to route to (default: bench.toml beam)")
    p.add_argument("--no-power", action="store_true", help="skip PSU ramp-up (already powered)")
    p.add_argument("--no-enable", action="store_true", help="init only; do not enable channels")
    p.add_argument("--fake", action="store_true", help="run without hardware")
    args = p.parse_args(argv)

    bench = Bench.from_toml(args.config, fake=args.fake)
    beam = args.beam or bench.board.beam

    # 1) 연결
    bench.connect_all()

    # 2) 전원
    if not args.no_power:
        bench.power_up()
    else:
        print("[manual] skipping power-up (--no-power)")

    # 3) 보드 init (+ 선택 채널 enable)
    chip = make_chip(bench.board, fake=args.fake)
    if args.no_enable:
        # init 만: version 확인까지 하고 채널은 사용자가 직접 enable.
        chip.init()
        ver = chip.fields.rd("version_id")
        print(f"[manual] init done, version_id={hex(ver)} (no channels enabled)")
    else:
        # 선택 채널로 active_channels 를 덮어쓴 뒤 표준 bring-up 수행(게인/감쇠/cal 포함).
        if args.channels:
            bench.board.active_channels = [c.strip().lower() for c in args.channels.split(",") if c.strip()]
        bench.board.beam = beam
        bring_up_tx(chip, bench.board, require_version=not args.fake)
        print(f"[manual] bring-up done: channels {bench.board.active_channels} -> {beam}")

    # 4) 대화형 쉘
    ns = build_namespace(bench, chip, beam)
    banner = ("\n=== CloudChaser manual console ===\n"
              "Type helpme() for commands. exit() to quit (power stays ON).\n")
    try:
        code.interact(banner=banner, local=ns, exitmsg="")
    finally:
        # 쉘 종료 시: RF 는 안전하게 끄고 소켓만 닫는다(전원 출력은 유지).
        try:
            bench.sg.rf_output(False)
        except Exception:
            pass
        bench.close_all()
        print("[manual] sockets closed. (power left as-is)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
