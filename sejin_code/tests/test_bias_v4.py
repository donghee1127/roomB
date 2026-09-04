"""v4 시트(Casper/NF_OPTIM) bias 적용 규칙 검증."""
from cloudchaser.board.bias_v4 import (
    CASPER_FE, NF_OPTIM_FE, CASPER_DIST_B0, NF_OPTIM_DIST_B0,
    apply_fe_bias, apply_dist_bias,
)

# die eFuse 리드백을 흉내낸 8x5 (열: PTAT1 PTAT2 PTAT3 CTAT CBIAS)
EFUSE_FE = [[10, 20, 30, 32, 5] for _ in range(8)]
EFUSE_DIST = [[12, 13, 14, 1, 1, 1] for _ in range(3)]


def test_casper_values_match_sheet():
    assert CASPER_FE == {"ptat_st1": 15, "ptat_st2": 45, "ptat_st3": 55}
    assert CASPER_DIST_B0["st1_ptat"] == 50
    assert CASPER_DIST_B0["st2_0_ptat"] == 13


def test_nf_optim_values_match_sheet():
    assert NF_OPTIM_FE == {"ptat_st1": 34, "ptat_st2": 24, "ptat_st3": 48}
    assert NF_OPTIM_DIST_B0["st1_ptat"] == 44


def test_fe_bias_only_active_rows_filled():
    """활성 채널(v1 -> 행 3)만 채우고 나머지 행은 0."""
    out = apply_fe_bias(EFUSE_FE, ["v1"], "tx")
    assert out[3] == [15, 45, 55, 32, 5]          # PTAT는 Casper, CTAT/CBIAS는 eFuse
    for r in range(8):
        if r != 3:
            assert out[r] == [0, 0, 0, 0, 0]


def test_fe_bias_rx_uses_nf_optim():
    out = apply_fe_bias(EFUSE_FE, ["h0"], "rx")
    assert out[0] == [34, 24, 48, 32, 5]


def test_fe_bias_multiple_active_channels():
    out = apply_fe_bias(EFUSE_FE, ["h0", "h1"], "tx")
    assert out[0] == [15, 45, 55, 32, 5]
    assert out[2] == [15, 45, 55, 32, 5]
    assert out[1] == [0, 0, 0, 0, 0]


def test_dist_bias_tx_beam0():
    """활성 빔(B0)만 채우고, TX는 B2 PTAT=[6,6,6] 하드코딩."""
    out = apply_dist_bias(EFUSE_DIST, 0, "tx", st2_1_ptat=13)
    assert out[0][0] == 50            # st1_ptat = Casper
    assert out[0][1] == 13            # st2_0_ptat
    assert out[0][2] == 13            # st2_1_ptat (인자)
    assert out[1] == [0, 0, 0, 0, 0, 0]
    assert out[2][0:3] == [6, 6, 6]


def test_dist_bias_st2_1_ptat_override():
    """MATLAB 값 28로 바꿀 수 있어야 한다(열린 항목)."""
    out = apply_dist_bias(EFUSE_DIST, 0, "tx", st2_1_ptat=28)
    assert out[0][2] == 28


def test_dist_bias_rx_beam0():
    out = apply_dist_bias(EFUSE_DIST, 0, "rx", st2_1_ptat=13)
    assert out[0][0] == 44            # NF_OPTIM
    assert out[2][0:3] == [0, 0, 0]   # RX는 B2 하드코딩 없음
