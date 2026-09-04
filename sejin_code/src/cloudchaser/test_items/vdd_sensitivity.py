"""Test Item: VDD Sensitivity (OP1dB vs FE1 supply voltage).

목적: OP1dB 측정을 FE1(PA 공급, 정격 4.0V) 전압을 단계적으로 내리면서 반복해,
공급전압 강하가 출력 압축점/소신호 이득/소비전류에 얼마나 영향을 주는지 본다.
위성 단말처럼 배터리/DC-DC 출력이 흔들리는 조건의 마진 확인용.

측정 방식: op1db 와 완전히 동일한 sweep/계산(`run_power_sweep` + `compute_op1db`
공유)을 전압마다 한 번씩 돌린다. 게인 고정·SG 주파수·경로손실·SA 설정은 맨 앞에서
한 번만 하고, 칩은 다시 bring-up 하지 않는다 -- FE1 은 PA 공급 레일이라 SPI/디지털
상태는 유지되므로, '설정은 그대로 두고 공급전압만 흔든다'가 이 측정의 정의다.

안전: 레일은 bench.set_rail_voltage() 로 step_v 간격 램프로만 움직이고, 정격
(bench.toml v_target) 위로는 올라가지 않는다. 측정이 끝나거나 중간에 예외/Ctrl-C 가
나도 finally 에서 항상 정격으로 복구한다.

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
    rail_vi_columns,
)
from .op1db import OP1dBTest, compute_op1db, run_power_sweep

# 기본 전압 계단(V). 정격 4.0 에서 시작해 2.2 까지 7 점.
DEFAULT_VDD_LIST = [4.0, 3.6, 3.3, 3.0, 2.7, 2.4, 2.2]


def _op1db_param(name: str) -> Param:
    """op1db 의 파라미터 명세를 그대로 재사용(기본값/도움말이 갈라지지 않게)."""
    for p in OP1dBTest.params:
        if p.name == name:
            return p
    raise KeyError(f"op1db has no param '{name}'")


class VDDSensitivityTest(TestItem):
    id = "vdd_sensitivity"
    title = "VDD Sensitivity Test"
    description = ("TX: repeat the OP1dB sweep at several FE1 supply voltages "
                   "to see how OP1dB / gain / Idd degrade as VDD drops.")
    chips = ("tx",)   # FE1 = TX PA 공급 레일.

    params = [
        _op1db_param("freq_hz"),
        # --- VDD sweep (이 테스트 고유) ---
        Param("vdd_rail", "VDD Rail", "str", "FE1_4V0",
              help="PSU rail name to vary (must exist in bench.toml). "
                   "Default FE1_4V0 = the 4 V PA supply."),
        Param("vdd_list_v", "VDD List", "float_list", list(DEFAULT_VDD_LIST),
              unit="V",
              help="supply voltages to measure, in order (e.g. 4.0,3.6,3.3,3.0). "
                   "Values above the rail's configured target are rejected."),
        Param("vdd_settle_s", "VDD Settle Time", "float", 1.0, unit="s",
              help="wait after the rail reaches each voltage, before sweeping"),
        # --- 이하 op1db 와 동일 ---
        *[p for p in OP1dBTest.params if p.name != "freq_hz"],
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

        rail = str(params["vdd_rail"]).strip() or "FE1_4V0"
        vdds = [float(v) for v in (params["vdd_list_v"] or [])]
        if not vdds:
            raise ValueError("vdd_list_v is empty - give at least one voltage "
                             "(e.g. 4.0,3.6,3.3)")
        vdd_settle = float(params["vdd_settle_s"])
        nominal = bench.rail_nominal_v(rail)   # 없는 레일이면 여기서 KeyError

        # SG 출력 sweep 지점(op1db 와 동일한 정수 카운트 생성).
        n = int(round((p1 - p0) / step)) + 1
        sg_levels = [round(p0 + k * step, 3) for k in range(max(1, n))]

        # 1) 게인 고정 + SG 주파수 + 경로손실 -> SG/SA 오프셋. 전압 루프 밖에서 한 번만.
        set_gain(fh, target, code, beam=beam, channel=channel)
        sg.modulation_off(log=log)   # CW 보장(직전 EVM 등의 ARB 파형 잔류 방지)
        sg.set_frequency(freq)
        in_loss, out_loss = bench.apply_path_loss(freq, log=log)

        # 2) SA 설정(op1db 와 동일 — 안 하면 톤이 아니라 노이즈 플로어를 읽는다).
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

        log(f"[vddsens] beam={beam} ch={channel}  gain_target={target}={hex(code)}, "
            f"CW {freq/1e9:.3f} GHz, SG {p0}..{p1} dBm, "
            f"{rail} {vdds} V (nominal {nominal:.2f} V) "
            f"(in_loss={in_loss} out_loss={out_loss} dB)")

        columns = ["VDD_set_V", "SG_dBm", "Pin_dBm", "Pout_dBm", "Gain_dB"] + \
            rail_vi_columns(rail_names)
        rows: list[list] = []
        per_vdd: list[dict] = []
        try:
            for v in vdds:
                # 3) 전압을 바꾸는 동안에는 RF 를 끈다(구동 중 공급 변동 방지).
                sg.rf_output(False)
                bench.set_rail_voltage(rail, v, log=log)
                time.sleep(vdd_settle)
                sg.rf_output(True)
                log(f"[vddsens] --- {rail} = {v:.2f} V ---")

                srows, pins, pouts, gains, idds = run_power_sweep(
                    bench, sg_levels, settle=settle, rail_names=rail_names,
                    log=log, prefix=[round(v, 3)], tag=f"{v:.2f}V ")
                rows.extend(srows)

                r = compute_op1db(sg_levels, pins, pouts, gains, ref_skip, ref_avg)
                per_vdd.append({
                    "vdd_v": round(v, 3),
                    "op1db_dbm": None if r["op1db_pout"] is None
                    else round(r["op1db_pout"], 2),
                    "ip1db_dbm": None if r["ip1db_pin"] is None
                    else round(r["ip1db_pin"], 2),
                    "small_signal_gain_db": round(r["g_ref"], 2),
                    "idd_max_ma": round(max(idds), 1) if idds else None,
                })
        finally:
            # 4) 무슨 일이 있어도 RF OFF + 레일 정격 복구.
            try:
                sg.rf_output(False)
            except Exception as e:  # noqa: BLE001
                log(f"[warn   ] RF output off failed: {e}")
            try:
                bench.set_rail_voltage(rail, nominal, log=log)
                log(f"[vddsens] {rail} restored to nominal {nominal:.2f} V")
            except Exception as e:  # noqa: BLE001
                log(f"[ERROR  ] {rail} restore to {nominal:.2f} V FAILED: {e} "
                    f"- check the PSU before further measurements")

        # 5) 전압별 요약표 + 정격 대비 열화량.
        ref_op = per_vdd[0]["op1db_dbm"] if per_vdd else None
        ref_g = per_vdd[0]["small_signal_gain_db"] if per_vdd else None
        log(f"[vddsens] {'VDD[V]':>7}  {'OP1dB[dBm]':>11}  {'Gss[dB]':>8}  "
            f"{'Idd[mA]':>8}  {'dOP1dB':>7}  {'dGss':>6}")
        for e in per_vdd:
            op_s = "n/a" if e["op1db_dbm"] is None else f"{e['op1db_dbm']:.2f}"
            d_op = ("ref" if e is per_vdd[0] else
                    ("n/a" if (e["op1db_dbm"] is None or ref_op is None)
                     else f"{e['op1db_dbm'] - ref_op:+.2f}"))
            d_g = ("ref" if e is per_vdd[0]
                   else f"{e['small_signal_gain_db'] - ref_g:+.2f}")
            idd_s = "n/a" if e["idd_max_ma"] is None else f"{e['idd_max_ma']:.0f}"
            log(f"[vddsens] {e['vdd_v']:>7.2f}  {op_s:>11}  "
                f"{e['small_signal_gain_db']:>8.2f}  {idd_s:>8}  "
                f"{d_op:>7}  {d_g:>6}")

        # 6) 한 줄 요약: 정격 -> 최저 전압에서의 OP1dB 변화.
        last = per_vdd[-1]
        drop = (None if (ref_op is None or last["op1db_dbm"] is None)
                else round(last["op1db_dbm"] - ref_op, 2))
        if drop is not None:
            summary = (f"OP1dB {ref_op:.2f} -> {last['op1db_dbm']:.2f} dBm over "
                       f"{rail} {per_vdd[0]['vdd_v']:.2f} -> {last['vdd_v']:.2f} V "
                       f"({drop:+.2f} dB)")
        else:
            n_ok = sum(1 for e in per_vdd if e["op1db_dbm"] is not None)
            summary = (f"{rail} {per_vdd[0]['vdd_v']:.2f} -> {last['vdd_v']:.2f} V: "
                       f"compression found at {n_ok}/{len(per_vdd)} voltages "
                       f"(others need a wider SG sweep)")
        log(f"[vddsens] {summary}")

        return TestResult(self.id, self.title, None, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "vdd_rail": rail, "vdd_list_v": vdds,
                                "vdd_nominal_v": nominal,
                                "per_vdd": per_vdd,
                                "op1db_ref_dbm": ref_op,
                                "op1db_drop_db": drop,
                                "gain_code": code, "freq_hz": freq,
                                "in_loss_db": in_loss, "out_loss_db": out_loss})
