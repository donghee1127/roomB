"""게인 타깃 매핑 / 채널 라우팅 / 구 파라미터 shim 검증.

fh 픽스처는 tests/conftest.py 의 FH(FakeChip(), 0) 를 그대로 쓴다
(tests 는 패키지가 아니라서 다른 테스트 모듈에서 직접 import 할 수 없다).
"""
import pytest

from cloudchaser.board.firehawk import FH, COMMON_GAIN, FE_GAIN_ADDR, PHASE_CAL_ADDR
from cloudchaser.board.gain_map import (
    set_gain, get_gain, set_phase, route_channels, disable_all, resolve_legacy,
)


def test_set_gain_common_uses_beam_index(fh):
    set_gain(fh, "common", 0x20, beam="b1")
    assert fh.rd(COMMON_GAIN + 1) == 0x20


def test_set_gain_fe_h_preserves_v_byte(fh):
    fh.wr(FE_GAIN_ADDR + 1, 0x0900)          # V=9 미리 설정
    set_gain(fh, "fe", 0x3, beam="b0", channel="h1")
    assert fh.rd(FE_GAIN_ADDR + 1) == 0x0903


def test_set_gain_fe_v_preserves_h_byte(fh):
    fh.wr(FE_GAIN_ADDR + 1, 0x0007)
    set_gain(fh, "fe", 0x4, beam="b0", channel="v1")
    assert fh.rd(FE_GAIN_ADDR + 1) == 0x0407


def test_set_gain_fe_v_preserves_pulse_en_bit(fh):
    """FE gain 은 4-bit 다: gain_control_v{i} = 0x1018[11:8], pulse_en_ch{i}_4 = bit12.

    Ruling 41: V 분기가 상위 바이트를 통째로 갈아엎어(`(cur & 0x00FF) | (code << 8)`)
    pulse_en 을 지웠다 -- H 분기는 보존하는데 같은 함수 안에서 비대칭이었다.
    bringup.py 의 리드백은 같은 결함을 이미 `& 0xF` 로 고쳤다.
    """
    fh.wr(FE_GAIN_ADDR + 0, (1 << 12) | 0x0007)     # pulse_en ON, H=7
    set_gain(fh, "fe", 0xF, channel="v0")
    w = fh.rd(FE_GAIN_ADDR + 0)
    assert w & (1 << 12), f"pulse_en (bit12) cleared by the V write: {w:#06x}"
    assert (w >> 8) & 0xF == 0xF, f"V nibble wrong: {w:#06x}"
    assert w & 0xF == 0x7, f"H nibble clobbered: {w:#06x}"


def test_set_gain_fe_h_preserves_pulse_en_bit(fh):
    """H 분기도 자기 니블만 갈아끼워야 한다(V 니블/pulse_en 보존)."""
    fh.wr(FE_GAIN_ADDR + 1, (1 << 12) | (0xA << 8) | 0x2)
    set_gain(fh, "fe", 0x5, channel="h1")
    w = fh.rd(FE_GAIN_ADDR + 1)
    assert w & 0xF == 0x5 and (w >> 8) & 0xF == 0xA
    assert w & (1 << 12), f"pulse_en (bit12) cleared by the H write: {w:#06x}"


def test_get_gain_fe_masks_to_four_bits(fh):
    """읽기도 4-bit 여야 한다 -- 8-bit 로 읽으면 pulse_en 이 결과 bit4 로 샌다."""
    fh.wr(FE_GAIN_ADDR + 0, (1 << 12) | (0x3 << 8) | 0x7)
    assert get_gain(fh, "fe", channel="v0") == 0x3
    assert get_gain(fh, "fe", channel="h0") == 0x7


def test_set_gain_fe_roundtrips_through_get_gain_with_pulse_en_set(fh):
    """pulse_en 이 켜진 채로도 쓴 코드가 그대로 읽혀야 한다(쓰기·읽기 계약 일치)."""
    fh.wr(FE_GAIN_ADDR + 2, 1 << 12)
    for pol in ("h", "v"):
        for code in (0, 1, 0xF):
            set_gain(fh, "fe", code, channel=f"{pol}2")
            assert get_gain(fh, "fe", channel=f"{pol}2") == code
            assert fh.rd(FE_GAIN_ADDR + 2) & (1 << 12)


def test_set_gain_beamtable_preserves_phase(fh):
    fh.wr(2, (13 << 7) | 5)                  # quad2: phase=13, atten=5
    set_gain(fh, "beamtable", 40, channel="h2")
    assert fh.rd(2) == (13 << 7) | 40


def test_get_gain_roundtrip(fh):
    set_gain(fh, "common", 0x11, beam="b0")
    assert get_gain(fh, "common", beam="b0") == 0x11
    set_gain(fh, "fe", 0x5, channel="h0")
    assert get_gain(fh, "fe", channel="h0") == 0x5
    set_gain(fh, "beamtable", 33, channel="h0")
    assert get_gain(fh, "beamtable", channel="h0") == 33


def test_get_gain_roundtrip_top_legal_value(fh):
    """Ruling 16: pin the boundary so a truncating write can't hide behind
    in-range-only assertions -- common is 6-bit (max 63), fe 4-bit (max 15),
    beamtable 7-bit (max 127)."""
    set_gain(fh, "common", 63, beam="b0")
    assert get_gain(fh, "common", beam="b0") == 63
    set_gain(fh, "fe", 15, channel="h0")
    assert get_gain(fh, "fe", channel="h0") == 15
    set_gain(fh, "beamtable", 127, channel="h0")
    assert get_gain(fh, "beamtable", channel="h0") == 127


def test_unknown_target_raises(fh):
    with pytest.raises(ValueError, match="unknown gain target"):
        set_gain(fh, "bogus", 0)


def test_set_gain_common_rejects_oversize_code(fh):
    with pytest.raises(ValueError, match=r"does not fit target 'common'"):
        set_gain(fh, "common", 64, beam="b0")


def test_set_gain_fe_rejects_oversize_code(fh):
    with pytest.raises(ValueError, match=r"does not fit target 'fe'"):
        set_gain(fh, "fe", 16, channel="h0")


def test_set_gain_beamtable_rejects_oversize_code(fh):
    with pytest.raises(ValueError, match=r"does not fit target 'beamtable'"):
        set_gain(fh, "beamtable", 128, channel="h0")


def test_set_phase_coarse_writes_beam_table_word(fh):
    """coarse = code // 4 lives in the beam-table word's [13:7] bits, atten in [6:0]."""
    set_phase(fh, 37, beam="b0", channel="h2", atten=5)
    assert fh.rd(2) == ((37 // 4) << 7) | 5


def test_set_phase_fine_writes_phase_cal_words(fh):
    """fine = code % 4 lives in three phase-cal RAM words (+0/+4/+8) tagged with 0x2000."""
    set_phase(fh, 37, beam="b1", channel="h2")
    base = PHASE_CAL_ADDR + (1 + 0 * 3) * 12 + 2   # beam=1, hv=0 (h), ci=2
    for d in (0, 4, 8):
        assert fh.rd(base + d) == 0x2000 | (37 % 4)


def test_set_phase_hv_polarity_uses_different_phase_cal_base(fh):
    """A v-channel must land at a different phase-cal base than the same-index h-channel."""
    set_phase(fh, 10, beam="b0", channel="h1")
    set_phase(fh, 10, beam="b0", channel="v1")
    base_h = PHASE_CAL_ADDR + (0 + 0 * 3) * 12 + 1   # hv=0
    base_v = PHASE_CAL_ADDR + (0 + 1 * 3) * 12 + 1   # hv=1
    assert base_h != base_v
    assert fh.rd(base_h + 0) == 0x2000 | (10 % 4)
    assert fh.rd(base_v + 0) == 0x2000 | (10 % 4)


def test_route_channels_enables_only_listed(fh):
    route_channels(fh, ["h1"], "b0", "tx")
    assert fh.rd(0x100C + 1) == 1 | (1 << 8)     # quad1 enabled for beam0
    assert fh.rd(0x100C + 0) == 0                # quad0 off
    # TX(Stampede): H = bits[5:3] -> 0b111000 = 56 (bringup.py:211-213, REGISTERS.md)
    assert fh.rd(0x1010 + 1) == 0b111000 + (1 << 6) + (1 << 7)   # TX h -> bits[5:3] = 248


def test_route_channels_rx_polarity_is_opposite_of_tx(fh):
    route_channels(fh, ["h1"], "b0", "rx")
    # RX(Blueway): H = bits[2:0] -> 0b000111 = 7 (bringup.py:350-351) -- opposite of TX.
    assert fh.rd(0x1010 + 1) == 0b000111 + (1 << 6) + (1 << 7)   # RX h -> bits[2:0] = 199


def test_route_channels_tx_beam_enables_word(fh):
    """beam_enables[b0] pwrdn_stage must be 1 for tx (Ruling 15) -- the same
    TX/RX-conditional family that produced the on-silicon polarity bug."""
    route_channels(fh, ["h1"], "b0", "tx")
    # mask=1<<1=2 (ci=1), bias_en=1<<8, pwrdn_stage=1<<9, match=0
    assert fh.rd(0x1009) == (1 << 1) | (1 << 8) | (1 << 9)


def test_route_channels_rx_beam_enables_word(fh):
    """Same encoding as above but pwrdn_stage must be 4 for rx."""
    route_channels(fh, ["h1"], "b0", "rx")
    # mask=1<<1=2 (ci=1), bias_en=1<<8, pwrdn_stage=4<<9, match=0
    assert fh.rd(0x1009) == (1 << 1) | (1 << 8) | (4 << 9)


def test_disable_all_clears_pwrdn_and_beams(fh):
    route_channels(fh, ["h1"], "b0", "tx")
    disable_all(fh)
    for i in range(4):
        assert fh.rd(0x1010 + i) == 0
    for i in range(3):
        assert fh.rd(0x1009 + i) == 0


class Board:
    beam = "b0"
    active_channels = ["h0"]


def test_resolve_legacy_common_field():
    out = resolve_legacy({"gain_field": "b1_common_gain"}, Board())
    assert out["gain_target"] == "common"
    assert out["beam"] == "b1"


def test_resolve_legacy_gain_control_field():
    out = resolve_legacy({"gain_field": "gain_control_h1"}, Board())
    assert out["gain_target"] == "fe"
    assert out["channel"] == "h1"


def test_resolve_legacy_channel_kind():
    assert resolve_legacy({"channel_kind": "field"}, Board())["channel_target"] == "fe"
    assert resolve_legacy({"channel_kind": "beamtable"}, Board())["channel_target"] == "beamtable"


def test_resolve_legacy_passes_through_new_params():
    out = resolve_legacy({"gain_target": "beamtable"}, Board())
    assert out["gain_target"] == "beamtable"


def test_resolve_legacy_common_field_maps_beam():
    out = resolve_legacy({"common_field": "b1_common_gain"}, Board())
    assert out["common_target"] == "common"
    assert out["beam"] == "b1"


def test_resolve_legacy_common_field_empty_is_noop():
    """common_field="" is the actual default channel_gain_alignment/ip1db pass -- it must
    not trigger the deprecation path or set common_target."""
    logged = []
    out = resolve_legacy({"common_field": ""}, Board(), log=logged.append)
    assert "common_target" not in out
    assert "common_field" not in out
    assert logged == []


def test_resolve_legacy_common_field_does_not_override_existing_target():
    out = resolve_legacy({"common_field": "b1_common_gain", "common_target": "beamtable"},
                          Board())
    assert out["common_target"] == "beamtable"
    assert "beam" not in out


def test_resolve_legacy_channel_field_maps_channel():
    out = resolve_legacy({"channel_kind": "field", "channel_field": "gain_control_h1"},
                          Board())
    assert out["channel_target"] == "fe"
    assert out["channel"] == "h1"


def test_resolve_legacy_channel_field_empty_is_noop():
    logged = []
    out = resolve_legacy({"channel_kind": "field", "channel_field": ""}, Board(),
                          log=logged.append)
    assert out["channel_target"] == "fe"
    assert "channel" not in out
    # channel_kind itself still logs (it is not empty) -- only the empty channel_field
    # must not add a spurious mapping or a second log line for it.
    assert len(logged) == 1


def test_resolve_legacy_empty_legacy_fields_are_full_noop():
    logged = []
    out = resolve_legacy(
        {"gain_field": "", "common_field": "", "channel_kind": "", "channel_field": ""},
        Board(), log=logged.append,
    )
    assert out == {}
    assert logged == []
