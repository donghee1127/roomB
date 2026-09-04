"""Smoke test: workbook STEP blocks work in fake=True mode.

sivers_api 없으면 전부 skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
_CONFIG    = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
_CONFIG_RX = Path(__file__).resolve().parents[1] / "config" / "bench_rx.toml"


def _make_fake_bench(chip: str = "tx", channels=None, beam: str = "b0"):
    """Simulate STEP 1 + 2 in fake mode (no power ramp, no TCP)."""
    from cloudchaser.bench import Bench
    channels = channels or ["h1"]
    cfg = _CONFIG_RX if chip == "rx" else _CONFIG
    bench = Bench.from_toml(cfg, fake=True)
    bench.board.active_channels = channels
    bench.board.beam = beam
    bench.board.ch_gain  = {ch: 0x08 for ch in channels}
    bench.board.ch_atten = {ch: 0x00 for ch in channels}
    bench.chip_kind = chip
    bench.connect_all(log=lambda *a, **k: None)
    return bench


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step1_connect_overrides_board_settings():
    """STEP 1: board settings from PARAMETERS override bench.toml defaults."""
    bench = _make_fake_bench(chip="tx", channels=["h1", "h3"], beam="b1")
    assert bench.board.active_channels == ["h1", "h3"]
    assert bench.board.beam == "b1"
    assert bench.chip_kind == "tx"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step1_rx_uses_rx_toml():
    """STEP 1 with chip='rx': RX bench config is loaded."""
    bench = _make_fake_bench(chip="rx", channels=["h1"])
    # RX bench must have rails present (bench_rx.toml has them)
    assert bench.chip_kind == "rx"
    assert bench.board.active_channels == ["h1"]


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step2_power_up_fake():
    """STEP 2: power_up() runs without error in fake mode."""
    bench = _make_fake_bench()
    # power_up() ramps all rails -- in fake mode just verifies the sequence runs
    bench.power_up(log=lambda *a, **k: None)
    vi = bench.read_all_vi()
    # fake PSU returns zeros but all rail names must be present
    assert "FE1_4V0" in vi
    assert "CORE_1V0" in vi
    assert "DIST_1V8" in vi


def _make_fake_chip(bench, chip_kind: str = "tx"):
    """Simulate STEP 3: init chip and build helpers."""
    assert bench.chip_kind == chip_kind, (
        f"bench.chip_kind={bench.chip_kind!r} does not match chip_kind={chip_kind!r}; "
        f"pass matching chip= to _make_fake_bench()"
    )
    from cloudchaser.board.bringup import make_chip, make_chip_rx, bring_up_tx, bring_up_rx
    from cloudchaser.board.firehawk import FH, VERSION_ID_RX, VERSION_ID_TX
    from cloudchaser.manual import build_namespace
    if chip_kind == "rx":
        chip = make_chip_rx(bench.board, fake=True)
        bring_up_rx(chip, bench.board, require_version=False)
    else:
        chip = make_chip(bench.board, fake=True)
        bring_up_tx(chip, bench.board, require_version=False)
    # fake SPI 는 전 레지스터 0 으로 시작하고 bring-up 은 identity(0x1000) 를 읽기만
    # 할 뿐 쓰지 않는다 -- gain_map.chip_kind() 의 런타임 TX/RX 판별(Ruling 21)이
    # fake 모드에서도 동작하려면 심어줘야 한다(tests/test_test_items_fake.py 의
    # _seed_identity 와 동일 패턴).
    ident = VERSION_ID_RX if chip_kind == "rx" else VERSION_ID_TX
    FH(chip, 0).wr(0x1000, (ident << 8) | 0x11)
    ns = build_namespace(bench, chip, bench.board.beam)
    return chip, ns


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step3_helpers_are_callable():
    """STEP 3: build_namespace produces all expected helper functions.

    wr()/latch()/commit() were removed in the raw-register migration (Task 9) --
    raw writes (fh.wr / fh.wr_verify) apply immediately, so no vendor field-name
    write, pulse_en latch, or staged-write flush helper is needed any more.
    """
    bench = _make_fake_bench()
    _, ns = _make_fake_chip(bench)
    assert "fh" in ns, "build_namespace must expose the raw register engine as 'fh'"
    for name in ("rd", "gain", "chgain", "atten", "phase", "rtps",
                 "chan", "enable", "disable", "paths", "biasscan",
                 "load_golden", "rf", "rfoff", "level", "saconf", "peak",
                 "vi", "shutdown"):
        assert callable(ns[name]), f"helper '{name}' not callable"
    for removed in ("wr", "latch", "commit"):
        assert removed not in ns, f"'{removed}' should have been removed (raw writes apply immediately)"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step3b_chan_runs_without_error(capsys):
    """STEP 3b: chan('h1') completes without exception in fake mode."""
    bench = _make_fake_bench(channels=["h1"])
    chip, ns = _make_fake_chip(bench)
    ns["chan"]("h1")   # should print path info
    out = capsys.readouterr().out
    assert "h1" in out or "b0" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step3c_gain_runs_raw(capsys):
    """STEP 3c: gain() runs without exception in fake mode and writes the raw
    common-gain register immediately (no latch() needed any more)."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    ns["gain"](0x10)
    out = capsys.readouterr().out
    assert "gain" in out.lower()
    assert FH(chip, 0).rd(COMMON_GAIN + 0) == 0x10


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step3e_phase_and_rtps(capsys):
    """STEP 3e: phase() writes the 9-bit RTPS phase (coarse beam-table + fine
    phase-cal RAM), preserving the current attenuator code; rtps() prints table."""
    from cloudchaser.board.firehawk import FH, PHASE_CAL_ADDR
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    fh = FH(chip, 0)
    # atten 비트를 미리 심어(raw) phase() 가 보존하는지 확인
    fh.wr(0, 0x15)          # quad 0 word: attenuator_setting bits 6:0 = 0x15
    ns["phase"]("h0", 0x104)   # 9-bit: coarse=0x104//4=65, fine=0x104%4=0
    word = fh.rd(0)
    assert (word >> 7) & 0x7F == 0x104 // 4, f"coarse phase bits wrong: {word:#06x}"
    assert word & 0x7F == 0x15, f"atten bits clobbered: {word:#06x}"
    assert fh.rd(PHASE_CAL_ADDR + 0) == 0x2000 | (0x104 % 4), "fine phase-cal bits wrong"
    # rtps() reads the beam-table registers on every call, so the raw fh writes
    # above show up without any "re-read from device" opt-in (Ruling 39 -- it
    # used to print the vendor beam_table object's stale Python-side copy, which
    # those raw writes never refresh).
    ns["rtps"]()
    out = capsys.readouterr().out
    assert "phase= 65" in out and "atten=21" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_rtps_reads_registers_and_prints_7bit_atten(capsys):
    """rtps() 는 beam-table 레지스터(워드 주소 = 채널 인덱스)를 직접 읽는다.

    두 가지를 한꺼번에 고정한다:
      1) atten 은 7-bit(0x7F)다 -- 다른 모든 곳과 같다. 예전엔 0x3F 로 찍어서
         코드 127 을 63 으로 보여줬다.
      2) 값이 raw fh.wr 로만 들어가도 보인다 -- 벤더 beam-table 객체의 파이썬
         복사본을 읽으면 atten()/phase()/chan() 의 raw 기입이 안 보인다.
    """
    from cloudchaser.board.firehawk import FH
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    fh = FH(chip, 0)
    fh.wr(2, 0x7F | (13 << 7))          # quad 2: atten=127(7-bit), coarse phase=13
    capsys.readouterr()
    ns["rtps"]()
    out = capsys.readouterr().out
    assert "quad 2: atten=127  phase= 13" in out, out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step4_rf_and_peak(capsys):
    """STEP 4: rf() sets SG state; peak() returns a float."""
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    ns["rf"](True, freq=28e9, level=-20)
    ns["saconf"](center=28e9, span=100e6, ref=20)
    p = ns["peak"]()
    assert isinstance(p, float), f"peak() should return float, got {type(p)}"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step5_fh_wr_verify_and_rd_field(capsys):
    """STEP 5: fh.wr_verify() (raw write, replaces removed wr()) + rd() (vendor
    field read, kept -- reads HW directly) run without exception in fake mode."""
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)
    ns["fh"].wr_verify(0x1005, 0x10)   # COMMON_GAIN + beam 0
    ns["rd"]("b0_common_gain")    # should print value without crashing
    out = capsys.readouterr().out
    assert "b0_common_gain" in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_step6_session_wiring_op1db(capsys):
    """STEP 6: session globals wired so op1db() runs in fake mode."""
    import cloudchaser.session as _sess
    bench = _make_fake_bench()
    chip, ns = _make_fake_chip(bench)

    # Wire session globals (same as STEP 6 block in workbook)
    _sess.B         = bench
    _sess.C         = chip
    _sess._fake     = True
    _sess._ns       = ns
    _sess._chip_kind = "tx"

    from cloudchaser.session import op1db
    result = op1db(freq_hz=28e9, gain_code=0)
    # In fake mode the test runs and returns a result object (not None)
    assert result is not None, "op1db() returned None in fake mode"
    out = capsys.readouterr().out
    assert "===" in out, f"Expected summary separator in op1db() output, got: {out!r}"


# --- 세션 dump()/regdiff(): 지금 상태를 bring-up 없이 뜬다 -------------------
def _fake_ns(tmp_path=None):
    from pathlib import Path
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.manual import build_namespace
    cfg = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
    b = Bench.from_toml(cfg, fake=True)
    c = make_chip(b.board, fake=True)
    bring_up_tx(c, b.board, require_version=False, log=lambda *a: None)
    return build_namespace(b, c, "b0"), c


def test_session_exposes_dump_and_regdiff():
    ns, _ = _fake_ns()
    assert "dump" in ns and "regdiff" in ns


def test_dump_reads_live_state_without_rerunning_bringup():
    """dump() 는 읽기 전용이어야 한다 -- 부르고 나서 레지스터가 그대로여야 한다."""
    ns, chip = _fake_ns()
    before = {a: chip.spi.rd(0, a) for a in range(0x1000, 0x1070)}
    regs = ns["dump"](b=0x1070)
    after = {a: chip.spi.rd(0, a) for a in range(0x1000, 0x1070)}
    assert before == after            # 아무것도 안 바뀐다
    assert regs == before             # 읽은 값이 실제 상태와 같다
    assert len(regs) == 0x70


def test_dump_reflects_a_manual_change(tmp_path):
    """손으로 만진 값이 dump 에 그대로 나와야 한다(= bring-up 을 다시 안 돈다)."""
    ns, _ = _fake_ns()
    ns["gain"](0x2A)                                  # common gain 을 손으로 변경
    regs = ns["dump"](b=0x1010)
    assert regs[0x1005] == 0x2A                       # bring-up 기본값이 아니라 변경값
    p = tmp_path / "regs.csv"
    ns["dump"](str(p), b=0x1010)
    assert "0x1005,0x002A" in p.read_text(encoding="utf-8")


def test_regdiff_against_live_state(tmp_path, capsys):
    """regdiff(파일) 는 파일 vs 현재 칩을 비교한다."""
    ns, _ = _fake_ns()
    p = tmp_path / "ref.csv"
    ns["dump"](str(p), b=0x1010)
    ns["gain"](0x3F)                                  # 뜬 뒤에 한 곳만 바꾼다
    diffs = ns["regdiff"](str(p), b=0x1010)
    assert diffs == [0x1005]
    assert "1 differing" in capsys.readouterr().out


# --- bias_test(): PTAT 3축 격자 스윕 ----------------------------------------
def _ns_connected():
    from pathlib import Path
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.manual import build_namespace
    cfg = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
    b = Bench.from_toml(cfg, fake=True)
    b.connect_all(log=lambda *a: None)
    c = make_chip(b.board, fake=True)
    bring_up_tx(c, b.board, require_version=False, log=lambda *a: None)
    return build_namespace(b, c, "b0"), c


def test_bias_test_is_exposed():
    ns, _ = _ns_connected()
    assert "bias_test" in ns


def test_bias_test_covers_the_coarse_grid_then_refines(tmp_path):
    ns, _ = _ns_connected()
    r = ns["bias_test"]("h0", coarse_step=24, lo=8, hi=56, settle_s=0,
                        idd_limit_ma=None, save=str(tmp_path / "b.csv"), top=3)
    # coarse 3^3=27, refine 는 best 주변 -- 최소한 coarse 만큼은 돈다
    assert len(r["rows"]) >= 27
    assert r["aborted"] is None
    assert (tmp_path / "b.csv").exists()
    head = (tmp_path / "b.csv").read_text(encoding="utf-8").splitlines()[0]
    assert head.startswith("ptat_st1,ptat_st2,ptat_st3")


def test_bias_test_restores_the_bias_row_on_exit():
    """스윕은 bias 를 헤집는다 -- 끝나면 원래대로 돌려놔야 한다."""
    ns, _ = _ns_connected()
    before = ns["fh"].get_fe_bias()[0]
    ns["bias_test"]("h0", coarse_step=24, lo=8, hi=56, settle_s=0,
                    idd_limit_ma=None, refine=False)
    assert ns["fh"].get_fe_bias()[0] == before


def test_bias_test_restores_the_bias_row_even_when_it_blows_up(monkeypatch):
    """측정 도중 예외가 나도 bias 가 스윕 중간값으로 남으면 안 된다."""
    ns, _ = _ns_connected()
    before = ns["fh"].get_fe_bias()[0]
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] > 3:
            raise RuntimeError("SA died mid-sweep")
        return -10.0

    monkeypatch.setattr(ns["sa"], "measure_peak_dbm", boom)
    with pytest.raises(RuntimeError, match="SA died"):
        ns["bias_test"]("h0", coarse_step=24, lo=8, hi=56, settle_s=0,
                        idd_limit_ma=None)
    assert ns["fh"].get_fe_bias()[0] == before


def test_bias_test_aborts_when_idd_exceeds_the_limit(monkeypatch):
    """전류 한계를 넘으면 스윕을 멈춘다(PSU 가 CC 로 들어가면 측정값이 조용히 망가진다).

    fake PSU 는 전원 미인가 상태에서 0 mA 를 돌려주므로, 과전류 상황을 직접 흉내낸다.
    """
    ns, _ = _ns_connected()
    monkeypatch.setattr(ns["bench"], "read_all_vi",
                        lambda: {"FE1_4V0": {"v": 4.0, "i": 0.5}})   # 500 mA
    r = ns["bias_test"]("h0", coarse_step=24, lo=8, hi=56, settle_s=0,
                        idd_every=1, idd_limit_ma=320.0, refine=False)
    assert r["aborted"] is not None and "Idd" in r["aborted"]
    assert len(r["rows"]) < 27          # 끝까지 돌지 않았다
