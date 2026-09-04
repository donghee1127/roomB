"""측정 로깅 규격 테스트: 전 PSU 레일 전류 컬럼 + CSV 파일명(빔/채널/주파수).

- 모든 측정 아이템은 측정점마다 전 레일 전류(<rail>_mA) + 총 Idd_mA 를 기록한다.
- CSV 파일명은 <test_id>_<yymmdd>_<BEAM>_<CHANNEL>_<freq>_<HHMMSS>.csv 로,
  파일명만 보고 무엇을 측정했는지 알 수 있어야 한다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
CONFIG_RX = Path(__file__).resolve().parents[1] / "config" / "bench_rx.toml"


def test_csv_filename_encodes_beam_channel_freq(tmp_path):
    from cloudchaser.runner import _save_csv
    from cloudchaser.test_items import TestResult

    res = TestResult("op1db", "OP1dB", None, "summary",
                     ["SG_dBm"], [[-5.0]],
                     meta={"beam": "b0", "channel": "h1", "freq_hz": 28.0e9})
    path = _save_csv(res, {}, tmp_path, log=lambda *_a: None)
    # op1db_<yymmdd>_B0_H1_28000MHz_<hhmmss>.csv
    assert path.name.startswith("op1db_")
    assert "_B0_H1_28000MHz_" in path.name
    assert path.name.endswith(".csv")


def test_csv_filename_falls_back_when_meta_missing(tmp_path):
    from cloudchaser.runner import _save_csv
    from cloudchaser.test_items import TestResult

    res = TestResult("acp", "ACP", None, "s", ["a"], [[1]], meta={})
    path = _save_csv(res, {}, tmp_path, log=lambda *_a: None)
    assert path.name.startswith("acp_")
    assert "_Bx_CHx_FREQx_" in path.name   # 없을 때 파일명-안전 placeholder('?' 금지)


def _run_fake(test_id, cfg, chip_kind, kw):
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import (bring_up_rx, bring_up_tx,
                                           make_chip, make_chip_rx)
    from cloudchaser.test_items import TestContext, get_test
    B = Bench.from_toml(cfg, fake=True)
    B.chip_kind = chip_kind
    B.connect_all(log=lambda *_a: None)
    if chip_kind == "rx":
        C = make_chip_rx(B.board, fake=True)
        bring_up_rx(C, B.board, require_version=False, log=lambda *_a: None)
    else:
        C = make_chip(B.board, fake=True)
        bring_up_tx(C, B.board, require_version=False, log=lambda *_a: None)
    t = get_test(test_id)()
    return t.run(TestContext(bench=B, chip=C, fake=True),
                 t.resolve(kw), log=lambda *_a: None)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
@pytest.mark.parametrize("test_id,cfg,kind,kw", [
    ("op1db", CONFIG, "tx", {"pin_start_dbm": -5, "pin_stop_dbm": -4}),
    ("ip1db", CONFIG_RX, "rx", {"pin_start_dbm": -50, "pin_stop_dbm": -49}),
    ("gain_index_accuracy", CONFIG, "tx",
     {"common_codes": [0], "channel_codes": [0]}),
])
def test_all_items_log_per_rail_current(test_id, cfg, kind, kw):
    res = _run_fake(test_id, cfg, kind, kw)
    # 총 Idd + 적어도 4개 이상의 개별 레일 전류 컬럼이 있어야 한다.
    assert "Idd_mA" in res.columns
    rail_cols = [c for c in res.columns if c.endswith("_mA") and c != "Idd_mA"]
    assert len(rail_cols) >= 4, f"{test_id}: rail current columns missing: {res.columns}"
    # 각 행 길이 == 컬럼 수(전 레일 값이 정렬되어 채워졌는지)
    for row in res.rows:
        assert len(row) == len(res.columns)
    # beam/channel 이 meta 에 기록됨(파일명/추적용)
    assert "beam" in res.meta and "channel" in res.meta


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
@pytest.mark.parametrize("active_ch,expected_quad", [("h0", 0), ("h3", 3)])
def test_gain_index_accuracy_channel_quad_auto(active_ch, expected_quad):
    """channel_quad 미지정(None) 이면 active 채널에서 자동 유도(h0->0, h3->3)."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.test_items import TestContext, get_test
    B = Bench.from_toml(CONFIG, fake=True)
    B.chip_kind = "tx"
    B.board.active_channels = [active_ch]
    B.connect_all(log=lambda *_a: None)
    C = make_chip(B.board, fake=True)
    bring_up_tx(C, B.board, require_version=False, log=lambda *_a: None)
    t = get_test("gain_index_accuracy")()
    res = t.run(TestContext(bench=B, chip=C, fake=True),
                t.resolve({"common_codes": [0], "channel_codes": [0]}),
                log=lambda *_a: None)
    assert res.meta["channel_quad"] == expected_quad


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_accuracy_channel_quad_explicit_override():
    """channel_quad 명시하면 그 값을 그대로 사용(자동 유도 안 함)."""
    res = _run_fake("gain_index_accuracy", CONFIG, "tx",
                    {"common_codes": [0], "channel_codes": [0], "channel_quad": 2})
    assert res.meta["channel_quad"] == 2


def test_gain_index_accuracy_default_is_1d_common_sweep():
    """기본 sweep 은 channel 고정([0]) + common 64점 1D (wizard 가 4096점으로 멈춘 듯
    보이던 문제 방지)."""
    from cloudchaser.test_items import get_test
    defaults = get_test("gain_index_accuracy")().defaults()
    assert defaults["channel_codes"] == [0]        # 채널 고정 -> 1D
    assert len(defaults["common_codes"]) == 64     # common 전체 sweep


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_accuracy_log_psu_false_skips_rail_columns():
    """log_psu=False 면 PSU V/I 읽기/컬럼을 통째로 생략(빠르고 timeout 회피)."""
    res = _run_fake("gain_index_accuracy", CONFIG, "tx",
                    {"common_codes": [0], "channel_codes": [0], "log_psu": False})
    # 레일/Idd 컬럼이 전혀 없어야 한다.
    assert not any(c.endswith("_mA") for c in res.columns), res.columns
    assert not any(c.endswith("_V") for c in res.columns), res.columns
    # 측정 컬럼(Gain_dB 등)은 그대로 있고, 행 길이도 컬럼 수와 일치.
    assert "Gain_dB" in res.columns
    for row in res.rows:
        assert len(row) == len(res.columns)


def test_save_csv_axis_tag(tmp_path):
    """_save_csv inserts meta['axis'] into the filename; absent axis = unchanged."""
    from cloudchaser import runner
    from cloudchaser.test_items.base import TestResult

    def save(meta):
        r = TestResult("gain_index_accuracy", "Gain Index Accuracy", None,
                       "ok", ["a"], [[1]], meta=meta)
        return runner._save_csv(r, {}, tmp_path, log=lambda *a, **k: None).name

    base = {"beam": "b0", "channel": "h0", "freq_hz": 19.5e9}
    assert "_common_" in save({**base, "axis": "common"})
    assert "_chan_" in save({**base, "axis": "chan"})
    name_none = save({**base, "axis": None})
    assert "_None_" not in name_none and "_common_" not in name_none
