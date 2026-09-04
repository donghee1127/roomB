"""tx_suite 조합 실행 테스트 (항목 선택 / 순서 / 주파수 확장 / 대화형 빌더).

tx_suite 는 세 갈래다:
  tx_suite()                                 대화형 빌더
  tx_suite('h1')                             예전 4단계 프리셋(변경 없음 -- 회귀 가드)
  tx_suite('h1', steps=..., freqs=...)       조합 실행
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"

# fake 에서 빨리 도는 파라미터(스윕 점 2~3개).
FAST = {
    "vdd_sensitivity": {"vdd_list_v": [4.0, 3.0], "pin_start_dbm": -30,
                        "pin_stop_dbm": -29, "settle_s": 0.0, "vdd_settle_s": 0.0},
    "evm": {"pin_start_dbm": -50, "pin_stop_dbm": -49, "settle_s": 0.0},
    "op1db": {"pin_start_dbm": -30, "pin_stop_dbm": -29, "settle_s": 0.0},
}


def _start(tmp_path, monkeypatch):
    from cloudchaser import runner, session
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    session.start(channels=["h1"], chip="tx", fake=True, power=False, config=CONFIG)
    return session


def _order(results):
    """실행된 (test_id, freq_GHz) 순서."""
    return [(r.test_id, round(r.meta["freq_hz"] / 1e9, 3)) for r in results if r]


# ---------------------------------------------------------------- parsing
def test_parse_steps_accepts_names_and_menu_numbers():
    from cloudchaser.session import _parse_steps
    from cloudchaser.test_items import list_tests
    tx = [t.id for t in list_tests() if "tx" in t.chips]
    assert _parse_steps("vdd_sensitivity,evm", "tx") == ["vdd_sensitivity", "evm"]
    assert _parse_steps([str(tx.index("evm") + 1)], "tx") == ["evm"]


def test_parse_steps_rejects_unknown_and_out_of_range():
    from cloudchaser.session import _parse_steps
    with pytest.raises(ValueError):
        _parse_steps("no_such_test", "tx")
    with pytest.raises(ValueError):
        _parse_steps("99", "tx")
    with pytest.raises(ValueError):
        _parse_steps("", "tx")


def test_parse_steps_rejects_an_rx_only_item_for_tx():
    """ip1db 는 RX 전용이라 TX suite 목록에 없어야 한다."""
    from cloudchaser.session import _parse_steps
    with pytest.raises(ValueError):
        _parse_steps("ip1db", "tx")


def test_parse_freqs_forms():
    from cloudchaser.session import _parse_freqs
    assert _parse_freqs(None, 28e9) == [28e9]
    assert _parse_freqs("28e9,29e9", 0) == [28e9, 29e9]
    assert _parse_freqs([28e9, 30e9], 0) == [28e9, 30e9]
    assert _parse_freqs(29e9, 0) == [29e9]


# ---------------------------------------------------------------- running
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_freq_major_is_the_default_order(tmp_path, monkeypatch):
    """기본은 freq-major: 한 주파수에서 전 항목을 돌고 다음 주파수로."""
    sess = _start(tmp_path, monkeypatch)
    res = sess.tx_suite("h1", steps="vdd_sensitivity,evm", freqs="28e9,29e9",
                        **FAST)
    assert _order(res) == [("vdd_sensitivity", 28.0), ("evm", 28.0),
                           ("vdd_sensitivity", 29.0), ("evm", 29.0)]


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step_major_order(tmp_path, monkeypatch):
    """order='step': 한 항목을 전 주파수에서 돌고 다음 항목으로(SA 앱 전환 최소화)."""
    sess = _start(tmp_path, monkeypatch)
    res = sess.tx_suite("h1", steps="vdd_sensitivity,evm", freqs=[28e9, 29e9],
                        order="step", **FAST)
    assert _order(res) == [("vdd_sensitivity", 28.0), ("vdd_sensitivity", 29.0),
                           ("evm", 28.0), ("evm", 29.0)]


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_each_step_saves_its_own_csv_named_by_frequency(tmp_path, monkeypatch):
    sess = _start(tmp_path, monkeypatch)
    sess.tx_suite("h1", steps="op1db", freqs="28e9,29e9", **FAST)
    names = sorted(p.name for p in tmp_path.glob("op1db_*.csv"))
    assert len(names) == 2
    assert any("28000MHz" in n for n in names)
    assert any("29000MHz" in n for n in names)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_a_failing_step_does_not_stop_the_rest(tmp_path, monkeypatch, capsys):
    sess = _start(tmp_path, monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("SA exploded")

    monkeypatch.setattr(sess.B.sa, "measure_peak_dbm", boom)
    res = sess.tx_suite("h1", steps="op1db,evm", freqs="28e9", **FAST)
    assert res[0] is None                    # op1db 실패
    assert res[1] is not None                # evm 은 계속 진행
    assert "FAIL" in capsys.readouterr().out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_overrides_are_keyed_by_test_id(tmp_path, monkeypatch):
    sess = _start(tmp_path, monkeypatch)
    res = sess.tx_suite("h1", steps="op1db", freqs="28e9",
                        op1db={"pin_start_dbm": -30.0, "pin_stop_dbm": -28.0,
                               "settle_s": 0.0, "gain_code": 0x11})
    assert res[0].meta["gain_code"] == 0x11
    assert len(res[0].rows) == 3            # -30..-28 step 1


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_classic_preset_is_unchanged_when_steps_is_omitted(tmp_path, monkeypatch):
    """인자를 주고 steps 를 생략하면 예전 4단계 그대로 (회귀 가드)."""
    sess = _start(tmp_path, monkeypatch)
    res = sess.tx_suite("h1", freq_hz=28e9,
                        linearity={"pin_start_dbm": -30, "pin_stop_dbm": -29,
                                   "settle_s": 0.0},
                        gain_common={"common_codes": [0], "channel_codes": [0]},
                        gain_chan={"common_codes": [0], "channel_codes": [0]},
                        evm={"pin_start_dbm": -50, "pin_stop_dbm": -49,
                             "settle_s": 0.0})
    assert len(res) == 4
    assert [r.test_id for r in res if r] == [
        "op1db", "gain_index_accuracy", "gain_index_accuracy", "evm"]


# ---------------------------------------------------------------- builder
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_interactive_builder_picks_items_channel_and_frequencies(tmp_path,
                                                                 monkeypatch):
    """tx_suite() 무인자 -> 빌더. 항목/채널/빔/주파수/파라미터를 순서대로 묻는다."""
    sess = _start(tmp_path, monkeypatch)
    answers = {
        "Select tests": "vdd_sensitivity,op1db",
        "Channel": "h1",
        "Beam": "b0",
        "Frequencies": "28e9,29e9",
        "Run now": "y",
        # 항목 파라미터는 전부 Enter(기본값) -- 단 스윕을 짧게 만들 두 개만 채운다
        "pin_start_dbm": "-30",
        "pin_stop_dbm": "-29",
        "vdd_list_v": "4.0",
        "settle_s": "0",
        "vdd_settle_s": "0",
    }

    def respond(prompt):
        for key, val in answers.items():
            if key in prompt:
                return val
        return ""

    monkeypatch.setattr("builtins.input", respond)
    res = sess.tx_suite()
    assert _order(res) == [("vdd_sensitivity", 28.0), ("op1db", 28.0),
                           ("vdd_sensitivity", 29.0), ("op1db", 29.0)]


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_builder_quits_without_running(tmp_path, monkeypatch, capsys):
    sess = _start(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _p: "q")
    assert sess.tx_suite() is None
    assert "cancelled" in capsys.readouterr().out
    assert list(tmp_path.glob("*.csv")) == []


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_builder_declining_the_confirmation_runs_nothing(tmp_path, monkeypatch):
    sess = _start(tmp_path, monkeypatch)

    def respond(prompt):
        if "Select tests" in prompt:
            return "op1db"
        if "Run now" in prompt:
            return "n"
        return ""

    monkeypatch.setattr("builtins.input", respond)
    assert sess.tx_suite() is None
    assert list(tmp_path.glob("*.csv")) == []
