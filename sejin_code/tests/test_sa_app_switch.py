"""SA measurement application 전환(spectrum <-> NR5G) 테스트.

freq-major suite 는 주파수마다 두 앱을 오간다. 예전 전환 경로는
  write_try("INST:SEL ...") -> wait_opc() -> resync()
였는데, ① write_try 가 전환 직후 SYST:ERR? 를 곧장 읽어 계측기가 바쁘면 OSError 로
측정 전체가 죽고 ② wait_opc 가 단발이라 5s 를 넘기면 늦게 온 '1' 이 다음 query 로
밀리며 ③ 전환 성공 여부를 아무도 확인하지 않았다. _switch_app 이 셋 다 막는다.
"""
from __future__ import annotations

import pytest

from cloudchaser.instruments import FSVA3030


def _sa():
    sa = FSVA3030("127.0.0.1", fake=True)
    sa.history.clear()
    return sa


def test_switch_verifies_the_app_with_a_query():
    sa = _sa()
    assert sa.select_nr5g(log=lambda *_a: None) is True
    assert "INST:SEL 'NR5G'" in sa.history
    assert "INST:SEL?" in sa.history, "the switch is never verified"


def test_switch_does_not_query_the_error_queue_before_the_app_is_up():
    """SYST:ERR? 는 전환이 확인된 뒤에만 나가야 한다(바쁜 계측기에서 timeout 사망 방지).

    예전 write_try 경로는 INST:SEL 바로 다음 줄에서 SYST:ERR? 를 읽었고, 그때 나는
    OSError 를 아무도 잡지 않아 측정이 통째로 죽었다. 순서를 여기서 고정한다.
    (fake 모드는 wait_opc_poll 이 즉시 반환하므로 *OPC? 는 히스토리에 안 남는다.)
    """
    sa = _sa()
    sa.enter_spectrum_mode(log=lambda *_a: None)
    sel = sa.history.index("INST:SEL SAN")
    verify = sa.history.index("INST:SEL?")
    errs = [i for i, c in enumerate(sa.history) if c.startswith("SYST:ERR")]
    assert sel < verify
    assert all(i > verify for i in errs), (
        f"SYST:ERR? was sent before the app switch was verified: {sa.history}")


def test_round_trip_between_the_two_apps():
    sa = _sa()
    sa.select_nr5g(log=lambda *_a: None)
    assert sa.query("INST:SEL?") == "NR5G"
    sa.enter_spectrum_mode(log=lambda *_a: None)
    assert sa.query("INST:SEL?") == "SAN"


def test_switch_retries_then_warns_when_the_app_never_takes(monkeypatch):
    """계측기가 계속 다른 앱을 보고하면 재시도하고, 끝내 안 되면 경고 후 False."""
    sa = _sa()
    monkeypatch.setattr(sa, "_fake_query", lambda cmd: (
        "SAN" if cmd.strip().upper().startswith("INST:SEL?")
        else FSVA3030._fake_query(sa, cmd)))
    warned = []
    assert sa.select_nr5g(log=warned.append) is False
    assert sa.history.count("INST:SEL 'NR5G'") == 3, "should retry the switch"
    assert any("still reports" in w for w in warned)


def test_switch_survives_an_unanswered_verify(monkeypatch):
    """INST:SEL? 가 응답을 못 줘도 예외를 던지지 않고 경고 후 진행한다."""
    sa = _sa()

    def dead(cmd):
        if cmd.strip().upper().startswith("INST:SEL?"):
            raise OSError("timed out")
        return FSVA3030._fake_query(sa, cmd)

    monkeypatch.setattr(sa, "_fake_query", dead)
    warned = []
    assert sa.select_nr5g(log=warned.append) is False
    assert any("did not answer" in w for w in warned)


def test_configure_enters_spectrum_mode_first():
    sa = _sa()
    sa.select_nr5g(log=lambda *_a: None)
    sa.configure(center_hz=28e9, span_hz=100e6, rbw_hz=1e6,
                 ref_level_dbm=25.0, input_atten_db=10.0, log=lambda *_a: None)
    span = sa.history.index("SENS:FREQ:SPAN 100000000")
    san = sa.history.index("INST:SEL SAN")
    assert san < span, "SPAN would be rejected while the NR app is selected"


@pytest.mark.parametrize("follow,expected", [(True, True), (False, False)])
def test_evm_follows_the_step_frequency_when_the_sa_is_manual(follow, expected):
    """setup_sa=False 경로는 SA 설정을 사용자에게 맡기지만, center 만은 따라가야 한다.

    안 따라가면 주파수를 여러 개 도는 suite 에서 29 GHz EVM 이 28 GHz 에 맞춰진
    NR 앱에서 조용히 측정된다.
    """
    import importlib.util
    if importlib.util.find_spec("sivers_api") is None:
        pytest.skip("sivers_api not installed")
    from pathlib import Path

    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.test_items import TestContext, get_test

    cfg = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
    b = Bench.from_toml(cfg, fake=True)
    b.connect_all(log=lambda *_a: None)
    chip = make_chip(b.board, fake=True)
    bring_up_tx(chip, b.board, require_version=False, log=lambda *_a: None)
    b.sa.history.clear()
    t = get_test("evm")()
    t.run(TestContext(bench=b, chip=chip, fake=True),
          t.resolve({"freq_hz": 29.0e9, "modulation": "manual", "setup_sa": False,
                     "sa_follow_center": follow, "pin_start_dbm": -50,
                     "pin_stop_dbm": -49, "settle_s": 0.0}),
          log=lambda *_a: None)
    sent = "SENS:FREQ:CENT 29000000000" in b.sa.history
    assert sent is expected
    b.close_all()
