"""후처리 스크립트의 레일 열 판별 테스트.

rail_names() 가 '_V 로 끝나면 레일' 로 보던 시절, vdd_sensitivity CSV 의
'VDD_set_V'(인가 전압 열)까지 레일로 잡혀 짝이 없는 'VDD_set_mA' 를 찾다
IndexError 로 죽었다. 측정 항목에 열이 하나 늘 때마다 재발할 수 있는 실수라
여기서 고정한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from postprocess_tx import rail_names, rails_filled  # noqa: E402

RAILS = ["FE1_4V0", "CORE_1V0", "IO_1V3", "DIST_1V8", "FE2_1V8", "FE3_1V8"]


def _header(extra: list[str] | None = None) -> list[str]:
    h = list(extra or [])
    for r in RAILS:
        h += [f"{r}_V", f"{r}_mA"]
    return h + ["Idd_mA", "Pdc_mW"]


def test_rail_names_finds_the_six_rails():
    assert rail_names(_header(["SG_dBm", "Pin_dBm"])) == RAILS


def test_rail_names_ignores_a_v_column_with_no_current_pair():
    """VDD_set_V 는 인가 전압이지 레일이 아니다."""
    assert rail_names(_header(["VDD_set_V", "SG_dBm"])) == RAILS


def test_rails_filled_survives_a_vdd_sensitivity_header():
    """실제 vdd_sensitivity 열 구성으로 끝까지 돌아야 한다(예전엔 IndexError)."""
    header = _header(["VDD_set_V", "SG_dBm", "Pin_dBm", "Pout_dBm", "Gain_dB"])
    row = ["4.0", "-22", "-22", "-4.69", "17.31"]
    for _r in RAILS:
        row += ["1.8", "25.9"]
    row += ["90.0", "215.0"]
    d = {"header": header, "rows": [row, row]}
    rails, ma, v, timeout = rails_filled(d)
    assert rails == RAILS
    assert timeout == set()
    assert ma["FE1_4V0"] == [25.9, 25.9]


def test_rails_filled_interpolates_a_psu_timeout_row():
    """전 레일이 0 인 행(PSU 읽기 timeout)은 앞뒤로 보간된다."""
    header = _header(["SG_dBm"])
    def mk(cur):
        r = ["-22"]
        for _ in RAILS:
            r += ["1.8", str(cur)]
        return r + ["0", "0"]
    d = {"header": header, "rows": [mk(10.0), mk(0.0), mk(20.0)]}
    _rails, ma, _v, timeout = rails_filled(d)
    assert timeout == {1}
    assert ma["FE1_4V0"][1] == pytest.approx(15.0)
