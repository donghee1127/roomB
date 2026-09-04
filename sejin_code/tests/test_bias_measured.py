"""실측으로 확정한 채널별 bias 코드가 bring-up / chan() 에서 실제로 기입되는지.

배경: bring-up step 18 의 DIRECT_REGS_TX 가 0x104C=3378(= DIST st1=50, st2_0=13,
v4 Casper 값)을 하드코딩으로 덮어쓴다. 그래서 bench.toml 만 고쳐선 실측 DIST 코드가
칩에 안 들어간다. 실측값은 그 뒤에 한 번 더 덮어써야 한다.

DIST 는 빔당 3행이라 채널마다 다른 값을 동시에 가질 수 없다 -- 채널을 바꾸면 같이
바꿔야 한다. split 모드가 route_channels() 에 덮여 게인이 8 dB 어긋났던 것과 같은
구조다(main d7b76c5).

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"

FE_BIAS_ADDR = 0x1038      # BEAM_BIAS_ADDR
DIST_BIAS_ADDR = 0x104C


def _fh_after_bringup(channels, *, bias=None, beam="b0"):
    """fake bring-up 을 끝낸 FH 를 돌려준다. bias 는 [board.bias] 대체값."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.board.firehawk import FH

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    bench.board.active_channels = list(channels)
    bench.board.beam = beam
    if bias is not None:
        bench.board.measured_bias = bias
    chip = make_chip(bench.board, fake=True)
    bring_up_tx(chip, bench.board, require_version=False, log=lambda *a, **k: None)
    fh = getattr(chip, "_fh", None) or FH(chip, 0)
    return bench, chip, fh


def _read_fe_ptat(fh, row):
    """FE bias 행의 PTAT 3개를 읽는다."""
    return fh.get_fe_bias()[row][:3]


def _read_dist_ptat(fh, beam_idx=0):
    dist, _ctat = fh.get_dist_bias()
    return dist[beam_idx][:3]


def test_measured_bias_overrides_the_hardcoded_dist_regs():
    """[board.bias.h0] 이 있으면 DIRECT_REGS_TX 의 Casper 값을 덮어써야 한다."""
    bench, _chip, fh = _fh_after_bringup(
        ["h0"], bias={"h0": {"ptat": [17, 55, 61], "dist": [63, 16, 0]}})
    assert _read_fe_ptat(fh, 0) == [17, 55, 61]      # h0 -> FE bias row 0
    assert _read_dist_ptat(fh) == [63, 16, 0]
    # DIRECT_REGS 가 쓰던 cbias1(=6, 0x104D[11:9])은 유지돼야 한다.
    assert (fh.rd(DIST_BIAS_ADDR + 1) >> 9) & 0x7 == 6
    bench.close_all()


def test_without_measured_bias_nothing_changes():
    """설정이 없으면 예전 그대로 -- 골든 레지스터 픽스처가 깨지면 안 된다."""
    bench, _chip, fh = _fh_after_bringup(["v1"], bias={})
    # v1 -> FE bias row 3, v4 Casper 15/45/55
    assert _read_fe_ptat(fh, 3) == [15, 45, 55]
    # DIRECT_REGS_TX 0x104C = 3378 -> st1=50, st2_0=13; 0x104D[5:0] = 13
    assert _read_dist_ptat(fh) == [50, 13, 13]
    bench.close_all()


def test_only_configured_channels_are_overridden():
    """엔트리가 있는 채널만 바뀌고, 나머지 행은 Casper 그대로."""
    bench, _chip, fh = _fh_after_bringup(
        ["h0", "h1"], bias={"h0": {"ptat": [17, 55, 61], "dist": [63, 16, 0]}})
    assert _read_fe_ptat(fh, 0) == [17, 55, 61]      # h0
    assert _read_fe_ptat(fh, 2) == [15, 45, 55]      # h1 -> row 2, 손 안 댐
    bench.close_all()


def test_dist_follows_the_first_configured_active_channel_and_warns():
    """DIST 는 빔당 1행뿐이라 채널마다 못 갖는다 -- 충돌하면 알리고 첫 채널을 쓴다."""
    logs: list[str] = []
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.board.firehawk import FH

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    bench.board.active_channels = ["h0", "h1"]
    bench.board.beam = "b0"
    bench.board.measured_bias = {
        "h0": {"ptat": [17, 55, 61], "dist": [63, 16, 0]},
        "h1": {"ptat": [20, 50, 60], "dist": [40, 24, 0]},
    }
    chip = make_chip(bench.board, fake=True)
    bring_up_tx(chip, bench.board, require_version=False, log=logs.append)
    fh = getattr(chip, "_fh", None) or FH(chip, 0)
    assert _read_dist_ptat(fh) == [63, 16, 0]        # 첫 활성 채널의 값
    assert any("DIST" in ln and "h1" in ln for ln in logs)
    bench.close_all()


def test_chan_reapplies_the_bias_of_the_channel_it_switches_to():
    """chan('h1') 이 h1 의 bias 를 다시 기입해야 한다.

    route_channels() 는 bias 를 안 건드리지만 DIST 는 빔 공용이라, 채널을 바꾸면
    그 채널용 DIST 로 갈아줘야 한다. 안 그러면 tx_suite() 가 h1 을 h0 의 DIST 로
    측정한다.
    """
    from cloudchaser.board.bias_measured import apply_measured_bias

    bench, _chip, fh = _fh_after_bringup(
        ["h0", "h1"],
        bias={"h0": {"ptat": [17, 55, 61], "dist": [63, 16, 0]},
              "h1": {"ptat": [20, 50, 60], "dist": [40, 24, 0]}})
    assert _read_dist_ptat(fh) == [63, 16, 0]
    apply_measured_bias(fh, bench.board, "h1", beam_idx=0, log=lambda *a: None)
    assert _read_dist_ptat(fh) == [40, 24, 0]
    assert _read_fe_ptat(fh, 2) == [20, 50, 60]      # h1 -> row 2
    bench.close_all()


def test_bad_entries_are_rejected_loudly():
    import pytest

    from cloudchaser.board.bias_measured import parse_measured_bias

    assert parse_measured_bias({}) == {}
    ok = parse_measured_bias({"h0": {"ptat": [17, 55, 61], "dist": [63, 16, 0]}})
    assert ok["h0"]["ptat"] == [17, 55, 61]

    with pytest.raises(ValueError, match="ptat"):
        parse_measured_bias({"h0": {"ptat": [17, 55]}})
    with pytest.raises(ValueError, match="out of range"):
        parse_measured_bias({"h0": {"dist": [63, 16, 64]}})
    with pytest.raises(ValueError, match="channel"):
        parse_measured_bias({"z9": {"ptat": [1, 2, 3]}})


def test_bench_toml_carries_the_confirmed_h0_codes():
    """확정 코드가 실제 bench.toml 에 들어있는지 -- 이게 tx_suite 가 쓰는 값이다."""
    from cloudchaser.bench import Bench

    bench = Bench.from_toml(CONFIG, fake=True)
    h0 = bench.board.measured_bias.get("h0")
    assert h0 is not None, "config/bench.toml needs [board.bias.h0]"
    assert h0["ptat"] == [17, 55, 61]
    # 2026-09-03 확정. st2_1=63 은 DIST 전류를 올리면서 게인은 조금 낮추는 유일한
    # 축이라(26.8->48.7 mA / 게인 23.90->22.14), 게인 19~25 와 OP1dB >= 19.5 를
    # 지킨 채 Sivers IDC_Dist(64.4)에 가장 가까이 간다. 그 위 전류는 전부 게인
    # max 25 를 깬다. (09-02 의 [63,16,6] 은 SA loss 1 dB 오차 시절의 값이다.)
    assert h0["dist"] == [63, 16, 63]
