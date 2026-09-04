"""FH 레지스터 비트팩 검증. 기대값은 MATLAB firehawk.m / Sivers 덤프에서 확정된 값."""
from cloudchaser.board.firehawk import (
    parse_ch, fe_row,
    BEAM_BIAS_ADDR, DIST_BIAS_ADDR, PHASE_CAL_ADDR, QUAD_PWRDN_ADDR,
)


def test_parse_ch_and_fe_row():
    assert parse_ch("h0") == ("h", 0)
    assert parse_ch("V3") == ("v", 3)
    assert fe_row(0, "h") == 0
    assert fe_row(0, "v") == 1
    assert fe_row(3, "v") == 7


def test_quad_pwrdn_rx_h_and_v(fh):
    """RX H full = 0b000111 -> 199, V full = 0b111000 -> 248 (bias_en+override 포함)."""
    rows = [[0, 1, 0, 0, 0] for _ in range(4)]
    rows[0] = [0b000111, 1, 1, 0, 0]
    fh.set_quad_pwrdn(rows)
    assert fh.rd(QUAD_PWRDN_ADDR + 0) == 199

    rows[0] = [0b111000, 1, 1, 0, 0]
    fh.set_quad_pwrdn(rows)
    assert fh.rd(QUAD_PWRDN_ADDR + 0) == 248


def test_quad_pwrdn_other_quads_override_only(fh):
    """활성이 아닌 quad 는 override 비트만 -> 64."""
    rows = [[0, 1, 0, 0, 0] for _ in range(4)]
    fh.set_quad_pwrdn(rows)
    assert fh.rd(QUAD_PWRDN_ADDR + 1) == 64


def test_center_enables(fh):
    """가중치 [1 2 4 8 16 32 128 256 1024 4096]. TX=[1,1,0..]=3, RX=[1,1,1,0..]=7."""
    fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    assert fh.rd(0x1008) == 3
    fh.set_center_enables([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    assert fh.rd(0x1008) == 7


def test_beam_enables_rx_ch0_b0(fh):
    """RX CH0/B0: [1, 1, 4, 0] -> 1 | 1<<8 | 4<<9 = 2305."""
    rows = [[0, 0, 0, 0] for _ in range(3)]
    rows[0] = [1, 1, 4, 0]
    fh.set_beam_enables(rows)
    assert fh.rd(0x1009) == 2305


def test_quad_enables_rx_ch0_b0(fh):
    """RX CH0/B0: [1, 1, 0] -> 1 | 1<<8 = 257."""
    rows = [[0, 0, 0] for _ in range(4)]
    rows[0] = [1, 1, 0]
    fh.set_quad_enables(rows)
    assert fh.rd(0x100C) == 257


def test_fe_bias_roundtrip(fh):
    """set_fe_bias -> get_fe_bias 왕복이 동일해야 한다(인터리브 규칙 검증)."""
    bias = [[i + 1, i + 2, i + 3, i + 4, (i % 8) + 1] for i in range(8)]
    fh.set_fe_bias(bias)
    assert fh.get_fe_bias() == bias


def test_fe_bias_packing_ch0_h(fh):
    """CH0-H Casper: PTAT1=15, PTAT2=45 -> 0x1038 = 15 | 45<<8 = 11535."""
    bias = [[0, 0, 0, 0, 0] for _ in range(8)]
    bias[0] = [15, 45, 55, 32, 5]
    fh.set_fe_bias(bias)
    assert fh.rd(BEAM_BIAS_ADDR + 0) == 15 | (45 << 8)
    assert fh.rd(BEAM_BIAS_ADDR + 4 + 0) == 55 | (32 << 8)


def test_dist_bias_roundtrip(fh):
    bias = [[10, 11, 12, 1, 2, 3], [20, 21, 22, 4, 5, 6], [6, 6, 6, 0, 0, 0]]
    fh.set_dist_bias(bias, 8)
    got, ctat = fh.get_dist_bias()
    assert got == bias
    assert ctat == 8


def test_dist_bias_b0_casper_word(fh):
    """Casper B0: St1=50, St2_0=13 -> 0x104C = 50 | 13<<8 = 3378."""
    bias = [[50, 13, 13, 6, 0, 0], [0] * 6, [0] * 6]
    fh.set_dist_bias(bias, 8)
    assert fh.rd(DIST_BIAS_ADDR) == 3378


def test_zero_phase_cal_writes_280_words(fh):
    fh.zero_phase_cal()
    for k in range(280):
        assert fh.rd(PHASE_CAL_ADDR + k) == 0
    assert len([w for w in fh.C.spi.writes if w[0] >= PHASE_CAL_ADDR]) == 280


def test_temp_sensor(fh):
    """offset=8, slope=8, core=1, bandgap=1 -> 8 | 8<<4 | 1<<8 | 1<<9 = 904."""
    fh.set_temp_sensor([8, 8], [1, 1])
    assert fh.rd(0x1022) == 8 | (8 << 4) | (1 << 8) | (1 << 9)


def test_set_rtps_attn_coarse_and_fine(fh):
    """phase 9-bit: coarse=ph//4 는 beam-table 워드, fine=ph%4 는 phase-cal 3워드."""
    fh.set_rtps_attn(0, 13, ch=1, beam=0, hv=0)
    assert fh.rd(1) == (13 // 4) << 7
    base = PHASE_CAL_ADDR + (0 + 0 * 3) * 12 + 1
    for d in (0, 4, 8):
        assert fh.rd(base + d) == 0x2000 | (13 % 4)


def test_wr_verify_warns_when_readback_raises(capsys):
    """리드백에서 예외가 나면 True 를 유지하되(evb_full 과 동일한 폴백) 경고는 찍어야 한다.

    Ruling 44: 예전엔 조용히 True 였다 -- 실칩 첫 실행에서 거짓 OK 다. 동작(반환값)은
    바꾸지 않는다: 여기서 제어 흐름이 갈리면 레지스터 동일성이 아니라 시퀀스가 달라진다.
    """
    from cloudchaser.board.firehawk import FH

    class _BlindSPI:
        fake = False

        def __init__(self):
            self.written = {}

        def wr(self, cid, addr, val):
            self.written[addr] = val

        def rd(self, cid, addr):
            raise OSError("SPI readback not supported at this address")

    class _Chip:
        def __init__(self):
            self.spi = _BlindSPI()

    chip = _Chip()
    f = FH(chip, 0)
    assert f.wr_verify(0x1005, 0x20) is True
    assert chip.spi.written[0x1005] == 0x20
    out = capsys.readouterr().out
    assert "readback could not be verified" in out
    assert "0x1005" in out
