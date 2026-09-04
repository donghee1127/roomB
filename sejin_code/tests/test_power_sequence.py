"""파워 시퀀스(스테이지 램프업 / 계단식 파워다운) 오프라인 테스트.

기준: Sivers 확정 "STAMPEDE 2731 Power Supply Sequencing Timing Diagram"
(2026-09-03 Reza 회의에서 확정, `_reference/00_inbox/Stampede Power Sequence
timing diagram.png`).

  POWER-UP    ① VDD_DIG 1.0V
              ② VDD_FE2 / FE3 / 1p8_DIST / 1p8_ANA / 1p8_IO = 1.8V (SPI active)
              ③ VDD_FE1 4V
  POWER-DOWN  ① FE1 4->1.8  ② 전 1.8V 레일 ->1.0  ③ 전체 ->0
  각 스텝 사이 최소 500 ms.

이 EVB 는 PSU 가 6채널뿐이라 칩의 DIST/ANA/디지털 1.8V 가 DIST_1V8 한 채널에 묶여 있다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cloudchaser.bench import Bench

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "bench.toml"
CONFIG_RX = ROOT / "config" / "bench_rx.toml"


def _bench(path, *, fast=True):
    b = Bench.from_toml(path, fake=True)
    if fast:                    # 테스트에서는 실제로 기다리지 않는다
        b.settle_s = 0.0
        b.stage_delay_s = 0.0
    b.connect_all(log=lambda *_: None)
    return b


def _ramp_log(lines):
    """'[ramp-up] NAME -> 1.80V' 에서 (NAME, 목표전압) 을 순서대로 뽑는다."""
    out = []
    for line in lines:
        if line.startswith("[ramp-up]"):
            parts = line.split()
            out.append((parts[1], float(parts[3].rstrip("V"))))
    return out


def _volts(b):
    """레일 이름 -> 현재 설정 전압."""
    return {r.name: psu._set_v[r.ch]
            for psu in b.psus for r in psu.rails.values()}


# ---- toml 이 다이어그램대로인지 ---------------------------------------------
def test_tx_stages_match_timing_diagram():
    b = Bench.from_toml(CONFIG, fake=True)
    assert b.power_up_stages == [
        ["CORE_1V0"],
        ["DIST_1V8", "IO_ANA_1V8", "FE2_1V8", "FE3_1V8"],
        ["FE1_4V0"],
    ]
    # 다이어그램 note: minimum 500 ms between each successive step
    assert b.stage_delay_s >= 0.5
    assert b.power_down_stages == [1.8, 1.0, 0.0]
    # 1.8V 스테이지의 레일은 전부 1.8V 목표여야 한다(IO 포함).
    for name in b.power_up_stages[1]:
        assert b.rail(name).v_target == pytest.approx(1.8), name
    assert b.rail("CORE_1V0").v_target == pytest.approx(1.0)
    assert b.rail("FE1_4V0").v_target == pytest.approx(4.0)


def test_power_up_order_is_flattened_stages():
    b = Bench.from_toml(CONFIG, fake=True)
    assert b.power_up_order == [n for s in b.power_up_stages for n in s]


def test_rx_config_without_stages_keeps_old_behaviour():
    """bench_rx.toml 은 power_up_order 만 있다 -> 레일 1개 = 스테이지 1개, 대기 0."""
    b = Bench.from_toml(CONFIG_RX, fake=True)
    assert b.power_up_stages == [[n] for n in b.power_up_order]
    assert b.stage_delay_s == 0.0
    assert b.rail("IO_1V3").v_target == pytest.approx(1.3)   # RX 는 1.3V 유지


# ---- 램프업 ------------------------------------------------------------------
def test_full_power_up_follows_stages():
    b = _bench(CONFIG)
    logs: list[str] = []
    b.power_up(log=logs.append)
    assert _ramp_log(logs) == [
        ("CORE_1V0", 1.0),
        ("DIST_1V8", 1.8), ("IO_ANA_1V8", 1.8), ("FE2_1V8", 1.8), ("FE3_1V8", 1.8),
        ("FE1_4V0", 4.0),
    ]
    v = _volts(b)
    assert v["CORE_1V0"] == pytest.approx(1.0)
    assert v["IO_ANA_1V8"] == pytest.approx(1.8)
    assert v["FE1_4V0"] == pytest.approx(4.0)


def test_stage_rails_rise_together():
    """한 스테이지의 레일은 lockstep 으로 올라간다 — 한 레일이 목표에 도달할 때까지
    다른 레일이 0V 에 머무르면 안 된다."""
    b = _bench(CONFIG)
    b.power_up(rails=["CORE_1V0"], log=lambda *_: None)

    seen: list[dict[str, float]] = []
    orig = {}
    for psu in b.psus:
        orig[id(psu)] = psu.set_voltage

    def make(psu, fn):
        def wrapped(ch, v):
            fn(ch, v)
            seen.append(_volts(b))
        return wrapped

    for psu in b.psus:
        psu.set_voltage = make(psu, orig[id(psu)])
    b.power_up(rails=["DIST_1V8", "IO_ANA_1V8", "FE2_1V8", "FE3_1V8"],
               log=lambda *_: None)

    group = ["DIST_1V8", "IO_ANA_1V8", "FE2_1V8", "FE3_1V8"]
    # 어느 순간에도 그룹 안 최대/최소 전압 차이가 한 스텝(step_v)을 넘지 않는다.
    for snap in seen:
        vs = [snap[n] for n in group]
        assert max(vs) - min(vs) <= b.step_v + 1e-6


def test_detect_stage_caps_io_at_detect_v():
    """보드 종류 확정 전에는 VDD_IO 를 TX/RX 공용 안전 전압(1.3V)까지만 올린다."""
    b = _bench(CONFIG)
    logs: list[str] = []
    b.power_up(rails=b.detect_rail_names, detect_stage=True, log=logs.append)
    assert _ramp_log(logs) == [
        ("CORE_1V0", 1.0), ("DIST_1V8", 1.8), ("IO_ANA_1V8", 1.3),
    ]
    assert _volts(b)["IO_ANA_1V8"] == pytest.approx(1.3)
    assert _volts(b)["FE1_4V0"] == 0.0      # FE 레일은 아직 OFF


def test_topup_from_detect_v_never_dips():
    """감지 후 IO 승압(1.3->1.8)은 0V 로 떨어졌다 올라가지 않아야 한다."""
    b = _bench(CONFIG)
    b.power_up(rails=b.detect_rail_names, detect_stage=True, log=lambda *_: None)

    lows: list[float] = []
    io = b.rail("IO_ANA_1V8")
    psu = b._psu_for_rail("IO_ANA_1V8")
    orig = psu.set_voltage

    def spy(ch, v):
        orig(ch, v)
        if ch == io.ch:
            lows.append(v)

    psu.set_voltage = spy
    remaining = [n for n in b.power_up_order
                 if n not in set(b.detect_rail_names) or n == "IO_ANA_1V8"]
    b.power_up(rails=remaining, log=lambda *_: None)

    assert lows, "IO rail was never topped up"
    assert min(lows) >= 1.3 - 1e-6      # 1.3V 아래로 내려간 적 없음
    assert _volts(b)["IO_ANA_1V8"] == pytest.approx(1.8)


def test_already_powered_rail_is_not_re_ramped():
    """이미 목표 전압인 레일을 다시 넘겨도 램프하지 않는다(글리치 방지)."""
    b = _bench(CONFIG)
    b.power_up(log=lambda *_: None)
    logs: list[str] = []
    b.power_up(log=logs.append)
    assert _ramp_log(logs) == []


# ---- 파워다운 ----------------------------------------------------------------
def test_power_down_plateaus():
    b = _bench(CONFIG)
    b.power_up(log=lambda *_: None)

    seen: list[dict[str, float]] = []
    for psu in b.psus:
        orig = psu.set_voltage

        def wrapped(ch, v, _fn=orig):
            _fn(ch, v)
            seen.append(_volts(b))
        psu.set_voltage = wrapped

    b.power_down(log=lambda *_: None)
    assert all(v == 0.0 for v in _volts(b).values())

    # ① FE1 이 1.8V 에 닿기 전까지 다른 레일은 자기 목표전압을 유지한다.
    idx = next(i for i, s in enumerate(seen) if s["FE1_4V0"] <= 1.8 + 1e-6)
    assert seen[idx]["IO_ANA_1V8"] == pytest.approx(1.8)
    assert seen[idx]["CORE_1V0"] == pytest.approx(1.0)
    # ② 1.8V 군이 1.0V 에 닿을 때까지 VDD_DIG(1.0V)는 안 내려간다.
    idx = next(i for i, s in enumerate(seen) if s["IO_ANA_1V8"] <= 1.0 + 1e-6)
    assert seen[idx]["CORE_1V0"] == pytest.approx(1.0)


# ---- strict 시퀀스(보드 명시)용 스테이지 분할 -------------------------------
def test_tx_config_is_staged_rx_is_not():
    """staged=True 는 'toml 이 벤더 스테이지를 직접 선언했다'는 뜻이다.

    session.start(chip='tx'/'rx') 는 이 플래그가 True 일 때만 데이터시트 시퀀스를
    그대로 따른다(마지막 스테이지 = PA 만 남기고 전부 인가 -> SPI 확인 -> PA).
    """
    assert Bench.from_toml(CONFIG, fake=True).staged is True
    assert Bench.from_toml(CONFIG_RX, fake=True).staged is False


def test_strict_split_puts_only_the_pa_after_the_spi_check():
    """SPI 확인 전에 올라가는 레일과 확인 후에 올라가는 레일."""
    b = Bench.from_toml(CONFIG, fake=True)
    pre = [n for s in b.power_up_stages[:-1] for n in s]
    last = b.power_up_stages[-1]
    assert pre == ["CORE_1V0", "DIST_1V8", "IO_ANA_1V8", "FE2_1V8", "FE3_1V8"]
    assert last == ["FE1_4V0"]          # 4V PA 만 SPI 확인 뒤로 남는다
    assert b.rail(last[0]).v_target == pytest.approx(4.0)


def test_strict_pre_stage_reaches_full_voltage_not_detect_v():
    """보드가 확정됐으므로 detect_v(1.3V) 로 낮추지 않고 바로 1.8V 로 간다."""
    b = _bench(CONFIG)
    pre = [n for s in b.power_up_stages[:-1] for n in s]
    b.power_up(rails=pre, log=lambda *_: None)
    v = _volts(b)
    assert v["IO_ANA_1V8"] == pytest.approx(1.8)
    assert v["FE2_1V8"] == pytest.approx(1.8)
    assert v["FE1_4V0"] == 0.0          # PA 는 아직 OFF


# ---- trip_poll (bench.toml) --------------------------------------------------
def test_trip_poll_disabled_by_config_skips_the_query():
    """trip_poll=false 면 STAT:QUES:COND? 를 아예 보내지 않는다.

    이 벤치의 E36313A 는 그 조회에 응답하지 않아 매 세션 소켓 타임아웃(5s)을
    기다렸다가 폴링을 껐다. 설정으로 미리 꺼서 그 대기를 없앤다.
    """
    b = Bench.from_toml(CONFIG, fake=True)
    for psu in b.psus:
        assert psu._trip_poll_cfg is False
        sent = []
        psu.query = lambda cmd, _s=sent: (_s.append(cmd), "0")[1]
        assert psu.tripped(1) is False
        assert sent == []          # 질의 자체가 안 나간다


def test_trip_poll_off_is_announced_not_silent():
    """조용히 끄면 운영자가 트립 보호가 도는 줄 안다 -- 한 번은 알려야 한다."""
    b = _bench(CONFIG)
    logs: list[str] = []
    b.power_up(log=logs.append)
    said = [l for l in logs if "trip polling off by config" in l]
    assert len(said) == 2                      # PSU1 / PSU2 각각 한 번씩
    assert all("current limit remains" in l for l in said)


def test_trip_poll_defaults_to_on_when_not_configured():
    """설정이 없으면 기존 동작(폴링 시도 -> 실패하면 런타임에 끄기)을 유지한다."""
    from cloudchaser.instruments import E36313A, Rail

    psu = E36313A("127.0.0.1", [Rail(ch=1, name="X", v_target=1.0,
                                     i_limit=0.1, ovp=1.2)], fake=True)
    assert psu._trip_poll_cfg is True
    assert psu._trip_supported is True
