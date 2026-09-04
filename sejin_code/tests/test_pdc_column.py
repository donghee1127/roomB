"""Pdc(총 소비전력) 열 규격 테스트.

CSV 마지막 열 Pdc_mW = sum(레일별 V x I) [mW]. 매 측정마다 엑셀에서 손으로
계산하던 값을 코드가 채운다. 콘솔 로그에는 안 나오고 CSV(=TestResult.rows)에만
들어간다.

Idd 회귀 가드도 여기 있다: Pdc 를 꼬리에 붙이면서 예전에 rail[-1] 로 Idd 를 읽던
호출부가 전부 Pdc 를 Idd 로 읽게 될 뻔했다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"

RAILS = ["FE1_4V0", "CORE_1V0", "IO_ANA_1V8", "DIST_1V8", "FE2_1V8", "FE3_1V8"]


class _StubBench:
    """read_all_vi() 만 흉내내는 최소 bench."""

    def __init__(self, vi):
        self._vi = vi

    def read_all_vi(self):
        return self._vi


def test_rail_vi_columns_end_with_idd_then_pdc():
    from cloudchaser.test_items.base import rail_vi_columns
    cols = rail_vi_columns(RAILS)
    assert cols[-2:] == ["Idd_mA", "Pdc_mW"]
    assert len(cols) == 2 * len(RAILS) + 2


def test_read_rail_vi_computes_pdc_as_sum_of_v_times_i():
    from cloudchaser.test_items.base import (rail_idd_ma, rail_pdc_mw,
                                             read_rail_vi)
    # 6 레일, 각각 다른 전압/전류 -- 전압이 같으면 잘못된 식도 우연히 맞는다.
    vi = {"FE1_4V0": {"v": 4.0, "i": 0.300},
          "CORE_1V0": {"v": 1.0, "i": 0.120},
          "IO_ANA_1V8": {"v": 1.3, "i": 0.010},
          "DIST_1V8": {"v": 1.8, "i": 0.045},
          "FE2_1V8": {"v": 1.8, "i": 0.220},
          "FE3_1V8": {"v": 1.8, "i": 0.180}}
    rail = read_rail_vi(_StubBench(vi), RAILS, log=lambda *_a: None)
    assert len(rail) == 2 * len(RAILS) + 2
    expect_mw = sum(d["v"] * d["i"] for d in vi.values()) * 1000.0
    assert rail_pdc_mw(rail) == pytest.approx(expect_mw, abs=0.05)
    # 총 전류(mA) 와 헷갈리면 안 된다 -- 값이 다르다는 것도 같이 고정한다.
    expect_ma = sum(d["i"] for d in vi.values()) * 1000.0
    assert rail_idd_ma(rail) == pytest.approx(expect_ma, abs=0.05)
    assert rail_idd_ma(rail) != rail_pdc_mw(rail)


def test_rail_accessors_on_empty_list():
    """log_psu=False 인 항목은 rail=[] 를 넘긴다 -- 인덱스 에러가 나면 안 된다."""
    from cloudchaser.test_items.base import rail_idd_ma, rail_pdc_mw
    assert rail_idd_ma([]) is None
    assert rail_pdc_mw([]) is None


def test_read_rail_vi_is_zero_filled_when_the_psu_read_fails():
    """PSU 읽기가 실패해도 길이는 유지된다(컬럼 정렬이 깨지면 CSV 가 밀린다)."""
    from cloudchaser.test_items.base import rail_pdc_mw, read_rail_vi

    class Boom:
        def read_all_vi(self):
            raise OSError("psu timeout")

    rail = read_rail_vi(Boom(), RAILS, log=lambda *_a: None)
    assert len(rail) == 2 * len(RAILS) + 2
    assert rail_pdc_mw(rail) == 0.0


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_csv_carries_pdc_and_matches_the_rail_columns():
    """실제 측정 항목이 채운 행에서 Pdc 가 그 행의 레일 값들과 일치해야 한다."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.test_items import TestContext, get_test

    b = Bench.from_toml(CONFIG, fake=True)
    b.connect_all(log=lambda *_a: None)
    b.power_up(log=lambda *_a: None)          # fake PSU 가 0 이 아닌 V/I 를 돌려주도록
    chip = make_chip(b.board, fake=True)
    bring_up_tx(chip, b.board, require_version=False, log=lambda *_a: None)
    t = get_test("op1db")()
    res = t.run(TestContext(bench=b, chip=chip, fake=True),
                t.resolve({"pin_start_dbm": -30, "pin_stop_dbm": -29,
                           "settle_s": 0.0}), log=lambda *_a: None)

    assert res.columns[-1] == "Pdc_mW"
    d = dict(zip(res.columns, res.rows[0]))
    expect = sum(float(d[f"{n}_V"]) * float(d[f"{n}_mA"]) for n in RAILS)  # V * mA = mW
    assert d["Pdc_mW"] == pytest.approx(expect, abs=0.5)
    assert d["Pdc_mW"] > 0, "fake PSU should report a powered rail here"
    b.close_all()
