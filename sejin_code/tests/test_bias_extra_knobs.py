"""solve 가 안 건드리는 5개 bias 열(fe_ctat/fe_cbias/dist_cbias*) 손잡이 테스트.

2026-09-03: gain/OP1dB 는 스펙 안이지만 Psat 이 min 22.5 dBm 에 못 미친다.
PTAT 6개로는 안 움직이는 게 확인돼서, 그동안 bring-up 값(FE=die eFuse,
DIST cbias=v4 Casper) 그대로 두던 나머지 열을 탐색 대상으로 연다.
"""
from __future__ import annotations

import pytest

from cloudchaser.bias_match import (
    ALL_KNOBS, CODE_MAX, CODE_MIN, DIST_KNOBS, EXTRA_KNOBS, FE_KNOBS,
)


def test_extra_knobs_cover_every_remaining_column():
    """FE 는 5열, DIST 는 6열이다. 6개는 solve 가, 5개는 여기서 다룬다."""
    fe_cols = {k.col for k in FE_KNOBS} | {k.col for k in EXTRA_KNOBS
                                           if k.kind == "fe"}
    dist_cols = {k.col for k in DIST_KNOBS} | {k.col for k in EXTRA_KNOBS
                                               if k.kind == "dist"}
    assert fe_cols == {0, 1, 2, 3, 4}
    assert dist_cols == {0, 1, 2, 3, 4, 5}
    assert len(EXTRA_KNOBS) == 5
    assert not {k.name for k in EXTRA_KNOBS} & {k.name for k in ALL_KNOBS}


def test_dist_cbias_is_three_bits_not_six():
    """firehawk 는 DIST cbias 를 (w2>>6)&0x7 로 읽는다 -- 0..7 이다.

    63 을 쓰면 인접 필드로 넘쳐 다른 bias 를 조용히 망가뜨린다.
    """
    for k in EXTRA_KNOBS:
        if k.name.startswith("dist_cbias"):
            assert k.code_max == 7, k.name
        else:
            assert k.code_max == CODE_MAX, k.name
    # solve 가 쓰는 6개는 전부 6비트다.
    assert all(k.code_max == CODE_MAX for k in ALL_KNOBS)


def test_write_knob_rejects_out_of_range_for_the_narrow_knobs():
    from cloudchaser.bias_match import write_knob

    cb = next(k for k in EXTRA_KNOBS if k.name == "dist_cbias1")
    with pytest.raises(ValueError, match=r"0\.\.7"):
        write_knob(object(), cb, 8, row=0, beam_idx=0)
    with pytest.raises(ValueError, match=r"0\.\.7"):
        write_knob(object(), cb, CODE_MAX, row=0, beam_idx=0)
    with pytest.raises(ValueError):
        write_knob(object(), cb, CODE_MIN - 1, row=0, beam_idx=0)
