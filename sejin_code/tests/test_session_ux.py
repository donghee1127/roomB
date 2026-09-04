"""Session UX 개선(wizard/help/banner) + RX 지원 오프라인 테스트.

sivers_api 가 없으면 전부 skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
CONFIG_RX = Path(__file__).resolve().parents[1] / "config" / "bench_rx.toml"


def _start_fake():
    """fake TX 세션 시작 헬퍼. power=False 로 PSU 램프업 없이 연결+bring-up 만."""
    from cloudchaser import session
    session.start(channels=["h1"], chip="tx", fake=True, power=False, config=CONFIG)
    return session


def _start_fake_rx():
    """fake RX 세션 시작 헬퍼."""
    from cloudchaser import session
    session.start(channels=["h1"], chip="rx", fake=True, power=False, config=CONFIG_RX)
    return session


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_help_measure_section_shows_purpose(capsys):
    """help() 의 measure 섹션이 목적(desc)과 힌트(hint) 두 줄을 출력해야 한다."""
    sess = _start_fake()
    sess.help()
    out = capsys.readouterr().out
    # 3-tuple 항목: sig 다음 줄에 desc 가 들여쓰기로 나와야 함
    assert "CW power sweep" in out          # op1db desc
    assert "gain_code(0=max)" in out        # op1db hint
    assert "tx_suite" in out               # suite entry listed


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_help_detail_shows_param_table(capsys):
    """help('op1db') 가 파라미터 표를 포함해야 한다."""
    sess = _start_fake()
    sess.help("op1db")
    out = capsys.readouterr().out
    assert "freq_hz" in out
    assert "gain_code" in out
    assert "pin_start_dbm" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_start_banner_shows_wizard_and_flows(capsys):
    """start() 완료 후 배너에 wizard(), help(), typical flows 가 있어야 한다.
    구 EVB 불량 채널 경고는 새 TX EVB 교체로 제거됨(회귀 가드)."""
    _start_fake()
    out = capsys.readouterr().out
    assert "wizard()" in out
    assert "help()" in out
    assert "Broken HW" not in out
    assert "op1db" in out          # typical flow 예시


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_op1db_fake(monkeypatch):
    """wizard() selects op1db with all defaults -> returns a TestResult."""
    from cloudchaser.test_items import TestResult
    sess = _start_fake()

    # Prompt-aware responder: select test 1, keep every param default, confirm 'y'.
    # (Robust to the exact number of parameter prompts.)
    def respond(prompt):
        if prompt.lstrip().startswith(">"):
            return "1"
        if "Run now" in prompt:
            return "y"
        return ""
    monkeypatch.setattr("builtins.input", respond)

    result = sess.wizard()
    assert result is not None
    assert isinstance(result, TestResult)
    assert result.test_id == "op1db"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_quit(monkeypatch):
    """wizard() returns None when user enters 'q' to quit."""
    sess = _start_fake()
    monkeypatch.setattr("builtins.input", lambda _prompt: "q")
    result = sess.wizard()
    assert result is None


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_cancel_at_confirm(monkeypatch):
    """wizard() returns None when user cancels at the confirmation prompt."""
    sess = _start_fake()
    def respond(prompt):
        if prompt.lstrip().startswith(">"):
            return "1"
        if "Run now" in prompt:
            return "n"   # cancel at the confirmation prompt
        return ""
    monkeypatch.setattr("builtins.input", respond)
    result = sess.wizard()
    assert result is None


# ---------------------------------------------------------------------------
# RX (Blueway) tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_start_rx_fake_sets_chip_kind(capsys):
    """start(chip='rx') should set _chip_kind='rx' and show RX banner hints."""
    sess = _start_fake_rx()
    out = capsys.readouterr().out
    assert sess._chip_kind == "rx"
    assert "Blueway" in out or "rx" in out.lower()
    assert "ip1db" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_ip1db_fake_returns_result():
    """ip1db() in fake mode should return a TestResult."""
    from cloudchaser.test_items import TestResult
    sess = _start_fake_rx()
    result = sess.ip1db(freq_hz=19.5e9, gain_code=0x20,
                        pin_start_dbm=-40.0, pin_stop_dbm=-35.0, pin_step_db=1.0,
                        in_loss_db=0.0, out_loss_db=0.0)
    assert result is not None
    assert isinstance(result, TestResult)
    assert result.test_id == "ip1db"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_start_tx_unchanged_after_rx(capsys):
    """TX start() still works after an RX session (chip kind switches back)."""
    _start_fake_rx()
    capsys.readouterr()  # clear RX output
    sess = _start_fake()
    out = capsys.readouterr().out
    assert sess._chip_kind == "tx"
    assert "op1db" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_rx_hides_op1db_shows_ip1db(monkeypatch, capsys):
    """RX wizard lists ip1db (RX) and hides op1db (TX-only)."""
    sess = _start_fake_rx()
    monkeypatch.setattr("builtins.input", lambda _p: "q")  # quit right after the list
    sess.wizard()
    out = capsys.readouterr().out
    assert "ip1db" in out
    assert "op1db" not in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_tx_hides_ip1db_shows_op1db(monkeypatch, capsys):
    """TX wizard lists op1db and hides ip1db (RX-only)."""
    sess = _start_fake()
    monkeypatch.setattr("builtins.input", lambda _p: "q")
    sess.wizard()
    out = capsys.readouterr().out
    assert "op1db" in out
    assert "ip1db" not in out


def test_test_item_chips_and_rx_defaults():
    """op1db=TX-only, ip1db=RX-only; shared tests carry RX defaults (freq 19.5GHz)."""
    from cloudchaser.test_items import get_test
    assert get_test("op1db").chips == ("tx",)
    assert get_test("ip1db").chips == ("rx",)
    for tid in ("gain_index_accuracy", "channel_gain_alignment", "evm", "acp"):
        assert get_test(tid).chips == ("tx", "rx")
        freq = next(p for p in get_test(tid).params if p.name == "freq_hz")
        assert freq.rx_default == 19.5e9


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_chan_updates_active_channel():
    """chan() must update bench.board.active_channels/beam so test items
    pick up the right channel for CSV meta and path-loss."""
    from cloudchaser import session
    _start_fake_rx()
    session._ns["chan"]("h0")
    assert session.B.board.active_channels == ["h0"]
    session._ns["chan"]("v3", "b1")
    assert session.B.board.active_channels == ["v3"]
    assert session.B.board.beam == "b1"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_rx_suite_runs_four_steps(tmp_path, monkeypatch):
    """rx_suite runs 4 steps for one channel, each saving its own CSV with
    the right axis tags, and sets the active channel."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake_rx()
    tiny = dict(settle_s=0.0)
    results = session.rx_suite(
        "h0", freq_hz=19.5e9,
        linearity={"pin_start_dbm": -40, "pin_stop_dbm": -38, **tiny},
        gain_common={"common_codes": [0, 1], **tiny},
        gain_chan={"channel_codes": [0, 1], **tiny},
        evm={"pin_start_dbm": -40, "pin_stop_dbm": -38, "pin_step_db": 2,
             "modulation": "manual", **tiny},
    )
    assert len(results) == 4
    assert session.B.board.active_channels == ["h0"]
    names = sorted(p.name for p in tmp_path.glob("*.csv"))
    assert len(names) == 4
    assert any("ip1db" in n for n in names)
    assert any("gain_index_accuracy" in n and "_common_" in n for n in names)
    assert any("gain_index_accuracy" in n and "_chan_" in n for n in names)
    assert any("evm" in n for n in names)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_accuracy_rx_helpers(tmp_path, monkeypatch):
    """RX gain-accuracy helpers default to 19.5 GHz, tag CSVs by axis, save 2 files."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake_rx()
    session._ns["chan"]("h0")
    rc = session.gain_index_accuracy_common(common_codes=[0, 1], settle_s=0.0)
    rch = session.gain_index_accuracy_channel(channel_codes=[0, 1], settle_s=0.0)
    assert rc.meta["axis"] == "common" and rch.meta["axis"] == "chan"
    assert rc.meta["freq_hz"] == 19.5e9 and rch.meta["freq_hz"] == 19.5e9
    assert rc.meta["sg_level_dbm"] == -45.0
    names = sorted(p.name for p in tmp_path.glob("*.csv"))
    assert any("gain_index_accuracy" in n and "_common_" in n for n in names)
    assert any("gain_index_accuracy" in n and "_chan_" in n for n in names)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_evm_rx_helper(tmp_path, monkeypatch):
    """evm_rx defaults to 19.5 GHz / load / setup_sa=False and saves a CSV."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake_rx()
    session._ns["chan"]("h0")
    r = session.evm_rx(waveform_path="x.wv", pin_start_dbm=-40, pin_stop_dbm=-38,
                       pin_step_db=1, settle_s=0.0)
    assert r.test_id == "evm"
    assert r.meta["freq_hz"] == 19.5e9 and r.meta["modulation"] == "load"
    assert any("evm" in p.name for p in tmp_path.glob("*.csv"))


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_evm_setup_sa_param_exists():
    """evm test item exposes setup_sa (load + manual-SA decoupling)."""
    from cloudchaser.test_items import get_test
    names = {p.name for p in get_test("evm").params}
    assert "setup_sa" in names


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_evm_rx_default_sweep_range(tmp_path, monkeypatch):
    """evm_rx default sweep is -75..-45 dBm, 1 dB step."""
    import inspect
    from cloudchaser import session
    sig = inspect.signature(session.evm_rx)
    assert sig.parameters["pin_start_dbm"].default == -75.0
    assert sig.parameters["pin_stop_dbm"].default == -45.0
    assert sig.parameters["pin_step_db"].default == 1.0


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_modoff_helper_present():
    """modoff() is available to return the SG to CW (baseband off)."""
    from cloudchaser import session
    _start_fake_rx()
    assert "modoff" in session._ns
    session._ns["modoff"]()   # must not raise in fake mode


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_evm_rx_manual_when_no_waveform(tmp_path, monkeypatch):
    """evm_rx() with no waveform_path uses modulation=manual (use pre-loaded)."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake_rx()
    session._ns["chan"]("h0")
    r = session.evm_rx(pin_start_dbm=-40, pin_stop_dbm=-38, pin_step_db=1, settle_s=0.0)
    assert r.meta["modulation"] == "manual"
    r2 = session.evm_rx(waveform_path="x.wv", pin_start_dbm=-40, pin_stop_dbm=-38,
                        pin_step_db=1, settle_s=0.0)
    assert r2.meta["modulation"] == "load"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_rx_suite_beam_b1(monkeypatch, tmp_path):
    """rx_suite uses the given beam, and inherits the current beam when omitted."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake_rx()
    tiny = dict(settle_s=0.0)
    session.rx_suite("v3", beam="b1",
                     linearity={"pin_start_dbm": -40, "pin_stop_dbm": -39, **tiny},
                     gain_common={"common_codes": [0, 1], **tiny},
                     gain_chan={"channel_codes": [0, 1], **tiny},
                     evm={"modulation": "manual", "pin_start_dbm": -40,
                          "pin_stop_dbm": -39, **tiny})
    assert session.B.board.beam == "b1"
    assert session.B.board.active_channels == ["v3"]
    # beam 생략 시 현재 beam(b1) 유지
    session.rx_suite("v3",
                     linearity={"pin_start_dbm": -40, "pin_stop_dbm": -39, **tiny},
                     gain_common={"common_codes": [0, 1], **tiny},
                     gain_chan={"channel_codes": [0, 1], **tiny},
                     evm={"modulation": "manual", "pin_start_dbm": -40,
                          "pin_stop_dbm": -39, **tiny})
    assert session.B.board.beam == "b1"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_tx_suite_runs_four_steps(tmp_path, monkeypatch):
    """tx_suite runs 4 steps for one channel, each saving its own CSV with
    the right axis tags, and sets the active channel."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake()
    tiny = dict(settle_s=0.0)
    results = session.tx_suite(
        "h1", freq_hz=28e9,
        linearity={"pin_start_dbm": -22, "pin_stop_dbm": -20, **tiny},
        gain_common={"common_codes": [0, 1], **tiny},
        gain_chan={"channel_codes": [0, 1], **tiny},
        evm={"pin_start_dbm": -10, "pin_stop_dbm": -8, "pin_step_db": 2,
             "modulation": "manual", **tiny},
    )
    assert len(results) == 4
    assert session.B.board.active_channels == ["h1"]
    names = sorted(p.name for p in tmp_path.glob("*.csv"))
    assert len(names) == 4
    assert any("op1db" in n for n in names)
    assert any("gain_index_accuracy" in n and "_common_" in n for n in names)
    assert any("gain_index_accuracy" in n and "_chan_" in n for n in names)
    assert any("evm" in n for n in names)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_tx_suite_beam_inherit(monkeypatch, tmp_path):
    """tx_suite uses the given beam (incl. op1db gain_target='common' + beam
    passthrough), and inherits the current beam when omitted."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake()
    tiny = dict(settle_s=0.0)
    results = session.tx_suite(
        "v3", beam="b1",
        linearity={"pin_start_dbm": -22, "pin_stop_dbm": -21, **tiny},
        gain_common={"common_codes": [0, 1], **tiny},
        gain_chan={"channel_codes": [0, 1], **tiny},
        evm={"modulation": "manual", "pin_start_dbm": -10,
             "pin_stop_dbm": -9, **tiny})
    assert session.B.board.beam == "b1"
    assert session.B.board.active_channels == ["v3"]
    # linearity(op1db) 가 b1 common gain 으로 실행됐는지 CSV 헤더로 확인
    assert results[0] is not None
    op_csv = next(p for p in tmp_path.glob("*.csv") if "op1db" in p.name)
    op_csv_text = op_csv.read_text(encoding="utf-8")
    assert "param.gain_target: common" in op_csv_text
    assert "param.beam: b1" in op_csv_text
    # beam 생략 시 현재 beam(b1) 유지
    session.tx_suite("v3",
                     linearity={"pin_start_dbm": -22, "pin_stop_dbm": -21, **tiny},
                     gain_common={"common_codes": [0, 1], **tiny},
                     gain_chan={"channel_codes": [0, 1], **tiny},
                     evm={"modulation": "manual", "pin_start_dbm": -10,
                          "pin_stop_dbm": -9, **tiny})
    assert session.B.board.beam == "b1"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_set_loss_override_roundtrip(capsys):
    """set_loss(in,out) sets the bench override; set_loss() clears it."""
    sess = _start_fake()
    sess.set_loss(7.0, 2.0)
    assert sess.B._loss_override == (7.0, 2.0)
    out = capsys.readouterr().out
    assert "override set" in out.lower()
    sess.set_loss()
    assert sess.B._loss_override is None
    out = capsys.readouterr().out
    assert "cleared" in out.lower()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_hides_new_gain_params():
    """_WIZARD_HIDDEN must reference the new gain_target/channel_target param
    names (Task 7/8), not the old gain_field/channel_kind/common_field names --
    the wizard would otherwise prompt for a dead legacy alias instead of hiding
    the real (auto-defaulted) param."""
    from cloudchaser.session import _WIZARD_HIDDEN
    assert "gain_target" in _WIZARD_HIDDEN["op1db"]
    assert "gain_field" not in _WIZARD_HIDDEN["op1db"]
    assert "gain_target" in _WIZARD_HIDDEN["ip1db"]
    assert "gain_field" not in _WIZARD_HIDDEN["ip1db"]
    assert "channel_target" in _WIZARD_HIDDEN["gain_index_accuracy"]
    assert "common_target" in _WIZARD_HIDDEN["gain_index_accuracy"]
    assert "common_field" not in _WIZARD_HIDDEN["gain_index_accuracy"]
    assert "channel_field" not in _WIZARD_HIDDEN["gain_index_accuracy"]
    assert "common_target" in _WIZARD_HIDDEN["channel_gain_alignment"]
    assert "common_field" not in _WIZARD_HIDDEN["channel_gain_alignment"]


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_status_active_paths_from_registers(capsys):
    """status()'s active-paths line must be re-derived from raw registers
    (quad_enables/quad_pwrdn, same as manual.py's paths()) on every call, not
    read from the vendor chip.path.active Python attribute. Raw writes
    (chan()/route_channels) never update that vendor cache, so on the raw
    write path it stays stale (empty) forever -- printing it would silently
    lie to the user about what's actually routed (Ruling 28's bug class)."""
    sess = _start_fake()
    # sanity: the vendor cache really is stale/empty on the raw write path,
    # so a naive C.path.active readback would NOT show h1/b0 here.
    stale = sess.C.path.active
    assert not any(chans for chans in stale.values())
    capsys.readouterr()  # drain start() banner
    sess.status()
    out = capsys.readouterr().out
    assert "active paths" in out
    assert "b0" in out
    assert "h1" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_status_common_gain_follows_the_current_beam(capsys):
    """status() 의 common_gain 이 현재 빔을 따라가야 한다.

    Ruling 43: "b0_common_gain" 이 하드코딩돼 있어서 chan('h0','b1') 뒤에도 B0 의
    게인을 현재 값인 척 보여줬다. 두 빔에 서로 다른 코드를 심고 확인한다.
    """
    from cloudchaser.board.firehawk import COMMON_GAIN, FH

    sess = _start_fake()
    fh = FH(sess.C, 0)
    fh.wr(COMMON_GAIN + 0, 0x11)
    fh.wr(COMMON_GAIN + 1, 0x22)

    sess.B.board.beam = "b1"
    capsys.readouterr()
    sess.status()
    out = capsys.readouterr().out
    assert "0x22" in out and "beam b1" in out, out
    assert "0x11" not in out, out

    sess.B.board.beam = "b0"
    capsys.readouterr()
    sess.status()
    out = capsys.readouterr().out
    assert "0x11" in out and "beam b0" in out, out


def test_vdd_sensitivity_session_function_exists():
    """세션 함수가 있어야 wizard 가 선택 결과를 호출할 수 있다(_ns 키 = test id)."""
    from cloudchaser import session
    assert callable(getattr(session, "vdd_sensitivity", None))


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_vdd_sensitivity_fake(monkeypatch):
    """wizard() 로 vdd_sensitivity 를 골라 끝까지 실행된다(전압 2점 + 짧은 sweep)."""
    from cloudchaser.test_items import TestResult, list_tests
    sess = _start_fake()

    # 메뉴 번호는 목록 순서에 따라 바뀌므로 wizard 와 같은 방식으로 계산한다.
    tx_tests = [t for t in list_tests() if "tx" in getattr(t, "chips", ("tx", "rx"))]
    pick = str([t.id for t in tx_tests].index("vdd_sensitivity") + 1)

    def respond(prompt):
        if prompt.lstrip().startswith(">"):
            return pick
        if "Run now" in prompt:
            return "y"
        if "vdd_list_v" in prompt:
            return "4.0,3.0"            # 전압 2점만
        if "pin_start_dbm" in prompt:
            return "-30"
        if "pin_stop_dbm" in prompt:
            return "-28"
        return ""                        # 나머지는 기본값
    monkeypatch.setattr("builtins.input", respond)

    result = sess.wizard()
    assert isinstance(result, TestResult)
    assert result.test_id == "vdd_sensitivity"
    assert [e["vdd_v"] for e in result.meta["per_vdd"]] == [4.0, 3.0]


# ----------------------------------------------------------------------
# split() -- DIST splitter mode toggle (TX only)
# ----------------------------------------------------------------------
def _split_regs(sess):
    """현재 칩에서 split 두 워드를 읽는다."""
    from cloudchaser.board.firehawk import FH
    f = FH(sess.C, 0)
    return f.rd(0x1009), f.rd(0x1068)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_split_query_reports_without_rerunning_bringup(capsys):
    """split() 는 조회만 한다 -- 설정도 칩도 건드리지 않는다."""
    sess = _start_fake()
    before = _split_regs(sess)
    assert sess.split() is True                 # bench.toml 기본값 = true
    assert sess.B.board.split_mode is True
    assert _split_regs(sess) == before
    assert "split mode: ON" in capsys.readouterr().out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_split_off_then_on_rewrites_the_two_words():
    """split(False) 는 두 워드를 남기지 않고, split(True) 는 다시 쓴다."""
    sess = _start_fake()
    assert _split_regs(sess) == (783, 0x8888)   # 시작이 split ON

    assert sess.split(False) is False
    assert sess.B.board.split_mode is False
    reg1009, reg1068 = _split_regs(sess)
    assert reg1009 != 783, "0x1009 still holds the split value after thru"
    assert reg1068 == 0, "0x1068 (ch0_captune) should be back to the zeroed value"

    assert sess.split(True) is True
    assert _split_regs(sess) == (783, 0x8888)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_split_same_value_is_a_noop(capsys):
    """이미 그 모드면 bring-up 을 다시 돌리지 않는다(게인 설정이 헛되이 날아가지 않게)."""
    sess = _start_fake()
    sess.split(True)
    out = capsys.readouterr().out
    assert "already ON" in out
    assert "re-running bring-up" not in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_split_is_tx_only(capsys):
    """RX bring-up 은 split_mode 를 읽지 않으므로, 조용히 통과시키지 않고 말해준다."""
    sess = _start_fake_rx()
    assert sess.split(False) is None
    out = capsys.readouterr().out
    assert "TX (Stampede) only" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_split_is_in_namespace_and_help():
    from cloudchaser.session import _HELP
    sess = _start_fake()
    assert callable(sess._ns.get("split"))
    assert any("split(" in item[0] for items in _HELP.values() for item in items)


# ----------------------------------------------------------------------
# wrf() -- write ONE register field by name (masked read-modify-write)
# ----------------------------------------------------------------------
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wrf_leaves_the_neighbour_field_alone():
    """0x104C 는 st1_ptat[5:0] 과 st2_0_ptat[13:8] 을 같이 담는다 -- 한 쪽만 바뀌어야 한다."""
    from cloudchaser.board.firehawk import FH
    sess = _start_fake()
    ns = sess._ns
    f = FH(sess.C, 0)
    assert f.rd(0x104C) == 3378                     # bring-up 이 쓴 값 (0x0D32)
    ns["wrf"]("d2a_dist_b0_st1_ptat", 40)
    assert f.rd(0x104C) == 0x0D28
    assert ns["rd"]("d2a_dist_b0_st2_0_ptat") == 13  # 이웃 필드 보존


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wrf_single_bit_field():
    from cloudchaser.board.firehawk import FH
    sess = _start_fake()
    f = FH(sess.C, 0)
    before = f.rd(0x1008)
    sess._ns["wrf"]("centerbias_en", 0)              # [0]
    assert f.rd(0x1008) == before & ~1


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wrf_rejects_out_of_range_value():
    """필드 폭을 넘는 값은 이웃 비트를 오염시키기 전에 막는다."""
    sess = _start_fake()
    with pytest.raises(ValueError):
        sess._ns["wrf"]("d2a_dist_b0_st1_ptat", 64)  # 6-bit -> 0..63


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wrf_rejects_unknown_field_name():
    """대문자 레지스터맵 표기를 그대로 넣는 실수는 조용히 통과하면 안 된다."""
    sess = _start_fake()
    with pytest.raises(KeyError):
        sess._ns["wrf"]("d2a_DIST_B0_St1_PTAT", 50)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_register_write_commands_advertised_by_help_exist():
    """help() 가 광고하는 레지스터 명령이 실제로 네임스페이스에 있어야 한다.

    구 vendor write API(wr/commit/latch)가 사라졌는데 help 표에는 남아 있던 적이
    있다 -- 문서만 낡는 것을 막는 가드다."""
    sess = _start_fake()
    for name in ("rd", "wrf", "fh", "dump", "regdiff"):
        assert name in sess._ns, f"help() advertises {name}() but it is not exposed"
    for gone in ("wr", "commit", "latch"):
        assert gone not in sess._ns, f"{gone}() is the removed vendor write path"
