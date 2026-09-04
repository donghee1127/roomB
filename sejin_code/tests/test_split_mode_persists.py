"""채널 라우팅 후에도 split 모드가 유지되는지 (실측 회귀 가드).

route_channels() 는 0x1009(center_dist_b0)를 '그 채널 분기만' 으로 다시 쓴다.
bring-up 이 걸어둔 split(dist_b0_st1_en=0xF)이 그 순간 조용히 풀려서,
bench.toml 이 split 인데 chan()/tx_suite() 를 부르면 thru 로 떨어졌다.
실측에서 게인이 8 dB 차이났다(1:4 분배 = 10*log10(4) + 분배망 손실).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
CONFIG_RX = Path(__file__).resolve().parents[1] / "config" / "bench_rx.toml"

SPLIT_WORD = 0x030F        # dist_b0_st1_en = 0xF (CH0..CH3 전부)
DIST_B0 = 0x1009


def _tx(split_mode=True):
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.board.firehawk import FH
    b = Bench.from_toml(CONFIG, fake=True)
    b.board.split_mode = split_mode
    b.connect_all(log=lambda *_a: None)
    chip = make_chip(b.board, fake=True)
    bring_up_tx(chip, b.board, require_version=False, log=lambda *_a: None)
    return b, chip, FH(chip, 0)


def test_bring_up_leaves_split_on():
    b, _chip, fh = _tx()
    assert fh.rd(DIST_B0) == SPLIT_WORD
    b.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_chan_keeps_split_on():
    """이게 이번 버그의 핵심 -- chan() 뒤에도 0x030F 여야 한다."""
    from cloudchaser.manual import build_namespace
    b, chip, fh = _tx()
    ns = build_namespace(b, chip, b.board.beam)
    ns["chan"]("h1", "b0")
    assert fh.rd(DIST_B0) == SPLIT_WORD, (
        f"chan() dropped split: 0x{fh.rd(DIST_B0):04X} (expected 0x030F)")
    b.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_enable_and_disable_keep_split_on():
    from cloudchaser.manual import build_namespace
    b, chip, fh = _tx()
    ns = build_namespace(b, chip, b.board.beam)
    ns["enable"]("h1")
    assert fh.rd(DIST_B0) == SPLIT_WORD
    ns["enable"]("h2")
    assert fh.rd(DIST_B0) == SPLIT_WORD
    ns["disable"]("h2")                      # 남은 채널로 재라우팅되는 경로
    assert fh.rd(DIST_B0) == SPLIT_WORD
    b.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_split_mode_false_still_routes_a_single_branch():
    """split_mode=false 면 예전대로 그 채널 분기만 (기능을 강제로 켜면 안 된다)."""
    from cloudchaser.manual import build_namespace
    b, chip, fh = _tx(split_mode=False)
    ns = build_namespace(b, chip, b.board.beam)
    ns["chan"]("h1", "b0")
    word = fh.rd(DIST_B0)
    assert word & 0xF == 0x2, f"h1 should route CH1 only, got 0x{word:04X}"
    b.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_tx_suite_runs_with_split_still_on(tmp_path, monkeypatch):
    """suite 는 시작할 때 chan() 을 부른다 -- 그 뒤로도 split 이 살아 있어야 한다."""
    from cloudchaser import runner, session
    from cloudchaser.board.firehawk import FH
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    session.start(channels=["h1"], chip="tx", fake=True, power=False, config=CONFIG)
    assert session.B.board.split_mode is True
    session.tx_suite("h1", steps="op1db", freqs="28e9",
                     op1db={"pin_start_dbm": -30, "pin_stop_dbm": -29,
                            "settle_s": 0.0})
    assert FH(session.C, 0).rd(DIST_B0) == SPLIT_WORD


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_rx_never_gets_the_tx_split_registers():
    """bring_up_rx 는 split_mode 를 읽지 않는다 -- 라우팅 후에도 TX 값이 들어가면 안 된다."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_rx, make_chip_rx
    from cloudchaser.board.firehawk import FH
    from cloudchaser.manual import build_namespace
    b = Bench.from_toml(CONFIG_RX, fake=True)
    b.chip_kind = "rx"
    b.board.split_mode = True                 # 켜져 있어도 RX 에는 적용되면 안 됨
    b.connect_all(log=lambda *_a: None)
    chip = make_chip_rx(b.board, fake=True)
    bring_up_rx(chip, b.board, require_version=False, log=lambda *_a: None)
    ns = build_namespace(b, chip, b.board.beam)
    ns["chan"]("h1", "b0")
    assert FH(chip, 0).rd(DIST_B0) != SPLIT_WORD
    b.close_all()
