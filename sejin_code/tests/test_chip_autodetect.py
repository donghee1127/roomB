"""Chip auto-detect(전원 2단계 + version_id 매핑) 오프라인 테스트.

실제 감지(라이브 SPI 읽기)는 하드웨어가 필요하므로, 여기서는 하드웨어 없이
검증 가능한 부분만 다룬다:
  - version_id -> 보드 종류 매핑
  - detect 레일 파싱(detect_rail_names)
  - power_up(rails=...) 가 지정한 레일만 램프업하는지(2단계 전원의 핵심)
  - 감지 레일 전압이 TX/RX 양쪽에서 동일하다는 안전 불변식
sivers_api 가 없으면 session import 가 필요한 항목만 skip.
"""
from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "bench.toml"
CONFIG_RX = ROOT / "config" / "bench_rx.toml"


def _ramped_rails(log_lines: list[str]) -> list[str]:
    """power_up 로그에서 '[ramp-up] NAME -> ...' 의 NAME 만 순서대로 뽑는다."""
    out = []
    for line in log_lines:
        if line.startswith("[ramp-up]"):
            out.append(line.split()[1])
    return out


# ---- version_id -> kind 매핑 -------------------------------------------------
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_version_kind_mapping():
    from cloudchaser.session import _version_kind

    assert _version_kind(0xDC) == "tx"
    assert _version_kind(0xD4) == "rx"
    # 인식 불가 값은 None (-> 안전 중단 트리거)
    for bad in (0x00, 0xFF, 0xD5, 0xDD):
        assert _version_kind(bad) is None


# ---- detect 레일 파싱 -------------------------------------------------------
def test_detect_rail_names_rx():
    from cloudchaser.bench import Bench

    b = Bench.from_toml(CONFIG_RX, fake=True)
    assert b.detect_rail_names == ["DIG_1V0", "IO_1V3", "ANA_1V8"]


def test_detect_rail_names_tx():
    from cloudchaser.bench import Bench

    b = Bench.from_toml(CONFIG, fake=True)
    # power_up_order(스테이지 평탄화) 순서를 따른다: CORE_1V0, DIST_1V8, IO_ANA_1V8, ...
    assert b.detect_rail_names == ["CORE_1V0", "DIST_1V8", "IO_ANA_1V8"]


# ---- 안전 불변식: 감지 레일 전압이 TX/RX 동일(채널 기준) --------------------
def test_detect_rails_same_voltage_across_boards():
    """TX/RX 의 감지 레일은 같은 (psu, ch) 에서 '감지 단계 전압'이 동일해야 안전하다.

    이게 깨지면 보드 종류 확정 전에 켜는 레일이 한쪽 보드에 과전압이 될 수 있다.
    감지 단계 전압 = detect_v 가 있으면 그 값, 없으면 v_target. TX 의 VDD_IO 는
    2026-09-03 회의 후 목표가 1.8V 로 올라갔지만(CHIP ID 리워크 전제), 감지 단계에서는
    RX 와 같은 1.3V 까지만 올리고 보드 확정 뒤에 승압한다.
    """
    def detect_map(path):
        d = tomllib.load(open(path, "rb"))
        out = {}
        for psu in ("psu1", "psu2"):
            for r in d[psu]["rails"]:
                if r.get("detect"):
                    out[(psu, r["ch"])] = r.get("detect_v", r["v_target"])
        return out

    tx, rx = detect_map(CONFIG), detect_map(CONFIG_RX)
    assert set(tx) == set(rx), f"detect channels differ: {set(tx) ^ set(rx)}"
    for key in tx:
        assert tx[key] == rx[key], f"{key} voltage differs: TX={tx[key]} RX={rx[key]}"


# ---- 2단계 전원: power_up(rails=...) 가 지정한 레일만 올리는지 ---------------
def test_power_up_subset_only_ramps_given_rails():
    from cloudchaser.bench import Bench

    b = Bench.from_toml(CONFIG_RX, fake=True)
    b.connect_all(log=lambda *_: None)

    logs: list[str] = []
    b.power_up(log=logs.append, rails=b.detect_rail_names)
    # 감지 레일만 램프업됐는지(FE 레일은 빠졌는지)
    assert _ramped_rails(logs) == ["DIG_1V0", "IO_1V3", "ANA_1V8"]
    assert "FE2_1V0" not in _ramped_rails(logs)
    assert "FE3_1V5" not in _ramped_rails(logs)


def test_power_up_remaining_excludes_detect_rails():
    from cloudchaser.bench import Bench

    b = Bench.from_toml(CONFIG_RX, fake=True)
    b.connect_all(log=lambda *_: None)

    detect = set(b.detect_rail_names)
    remaining = [n for n in b.power_up_order if n not in detect]
    logs: list[str] = []
    b.power_up(log=logs.append, rails=remaining)
    ramped = _ramped_rails(logs)
    assert ramped == ["FE1_1V0", "FE2_1V0", "FE3_1V5"]
    # 감지 레일은 2단계에서 다시 올리지 않는다(글리치 방지)
    assert not (detect & set(ramped))


def test_power_up_full_ramps_everything():
    from cloudchaser.bench import Bench

    b = Bench.from_toml(CONFIG_RX, fake=True)
    b.connect_all(log=lambda *_: None)

    logs: list[str] = []
    b.power_up(log=logs.append)
    assert _ramped_rails(logs) == b.power_up_order
