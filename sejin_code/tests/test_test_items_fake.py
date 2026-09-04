"""Test Item 프레임워크의 오프라인(fake) 테스트.

각 테스트의 run() 측정 로직을 하드웨어 없이 검증한다. (전원 램프업은 느리므로
건너뛰고, fake 보드 + fake 계측기로 TestContext 를 직접 만들어 run() 만 호출.)
sivers_api 가 없으면 skip.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None


def _seed_identity(chip, kind="tx"):
    """0x1000 identity 워드를 심는다 (fake SPI 는 전 레지스터 0 으로 시작하고 bring-up/
    chip.init() 은 이 워드를 읽기만 할 뿐 쓰지 않는다 -- tests/test_bringup_golden.py 의
    seed_efuse 와 동일 패턴). gain_map.chip_kind() 같은 런타임 TX/RX 판별(Ruling 21)이
    fake 모드에서도 동작하려면 필요하다."""
    from cloudchaser.board.firehawk import FH, VERSION_ID_RX, VERSION_ID_TX
    ident = VERSION_ID_RX if kind == "rx" else VERSION_ID_TX
    FH(chip, 0).wr(0x1000, (ident << 8) | 0x11)


def _make_ctx():
    """fake 보드 + fake 계측기로 TestContext 생성(전원 램프 생략)."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import make_chip
    from cloudchaser.test_items import TestContext

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    chip = make_chip(bench.board, fake=True)
    chip.init()
    _seed_identity(chip, kind="tx")   # CONFIG = bench.toml = TX board
    return TestContext(bench=bench, chip=chip, fake=True)


def _fake_bench_and_chip(beam="b0", kind="tx"):
    """fake bench + bring-up 된 chip 한 쌍. Task 8/9 도 이 헬퍼를 그대로 재사용한다."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_rx, bring_up_tx, make_chip, make_chip_rx
    cfgfile = "bench_rx.toml" if kind == "rx" else "bench.toml"
    bench = Bench.from_toml(
        Path(__file__).resolve().parents[1] / "config" / cfgfile, fake=True)
    bench.board.beam = beam
    chip = (make_chip_rx if kind == "rx" else make_chip)(bench.board, fake=True)
    (bring_up_rx if kind == "rx" else bring_up_tx)(chip, bench.board, require_version=False)
    _seed_identity(chip, kind=kind)
    return bench, chip


def run_item(test_id, bench, chip, overrides):
    """테스트 항목 1개를 fake 로 실행. Task 8/9 도 이 헬퍼를 그대로 재사용한다.

    get_test() 는 클래스(type[TestItem])를 반환하므로 run() 을 호출하려면
    인스턴스화해야 한다(브리프 스니펫에는 없던 () -- 없으면 run 이 언바운드로
    호출돼 self 자리에 ctx 가 들어가 TypeError 가 난다).
    """
    from cloudchaser.test_items import TestContext, get_test
    item = get_test(test_id)()
    params = {p.name: p.default for p in item.params}
    params.update(overrides)
    return item.run(TestContext(bench=bench, chip=chip, fake=True), params, log=print)


def test_registry_has_tests():
    from cloudchaser.test_items import REGISTRY
    assert "op1db" in REGISTRY
    assert "gain_index_accuracy" in REGISTRY
    assert "phase_index_accuracy" in REGISTRY


def test_coerce_types():
    from cloudchaser.test_items import coerce
    from cloudchaser.test_items.base import Param
    assert coerce(Param("x", "x", "int", 0), "0x20") == 0x20
    assert coerce(Param("x", "x", "int_list", []), "0,8,16") == [0, 8, 16]
    assert coerce(Param("x", "x", "float", 0.0), "28e9") == 28e9


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_accuracy_run():
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    test = get_test("gain_index_accuracy")()
    params = test.resolve({"common_codes": [0x00, 0x10, 0x20],
                           "channel_codes": [0x00, 0x08], "settle_s": 0.0})
    result = test.run(ctx, params, log=lambda *a, **k: None)
    assert result.test_id == "gain_index_accuracy"
    assert len(result.rows) == 6            # 3 common x 2 channel = 6
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_channel_gain_alignment_run():
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    test = get_test("channel_gain_alignment")()
    # channels_script -> 비대화식 측정(입력 프롬프트 없이 그 순서대로).
    params = test.resolve({"channels_script": "h0,h1,v0", "channel_mode": "single",
                           "settle_s": 0.0})
    result = test.run(ctx, params, log=lambda *a, **k: None)
    assert result.test_id == "channel_gain_alignment"
    assert len(result.rows) == 3                    # h0, h1, v0
    assert result.columns[:6] == ["channel", "SG_dBm", "Pin_dBm",
                                  "SA_raw_dBm", "out_loss_dB", "Pout_dBm"]
    assert set(result.meta["channel_pout_dbm"]) == {"H0", "H1", "V0"}
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_run():
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    test = get_test("op1db")()
    params = test.resolve({"pin_start_dbm": -30.0, "pin_stop_dbm": -25.0,
                           "pin_step_db": 1.0, "settle_s": 0.0})
    result = test.run(ctx, params, log=lambda *a, **k: None)
    assert result.test_id == "op1db"
    assert len(result.rows) == 6            # -30..-25 step 1 → 6 points
    assert "small_signal_gain_db" in result.meta
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_accuracy_axis_meta():
    """meta['axis'] reflects which gain axis was swept (for CSV filename tag)."""
    from cloudchaser.test_items import get_test
    test = get_test("gain_index_accuracy")

    def run(common, channel):
        ctx = _make_ctx()
        p = test().resolve({"common_codes": common, "channel_codes": channel,
                            "settle_s": 0.0})
        r = test().run(ctx, p, log=lambda *a, **k: None)
        ctx.bench.close_all()
        return r.meta.get("axis")

    assert run([0, 1, 2], [0]) == "common"
    assert run([0], [0, 1, 2]) == "chan"
    assert run([0, 1], [0, 1]) == "2d"
    assert run([0], [0]) is None


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_ip1db_defaults_max_gain_and_range():
    """ip1db defaults to max gain (common code 0) and a tighter RX sweep."""
    from cloudchaser.test_items import get_test
    d = {p.name: p.default for p in get_test("ip1db").params}
    assert d["gain_code"] == 0
    assert d["pin_start_dbm"] == -50.0
    assert d["pin_stop_dbm"] == -20.0


def test_fsva_has_select_nr5g():
    """FSVA exposes select_nr5g() so EVM can switch into the NR app from spectrum."""
    from cloudchaser.instruments.sa_fsva3030 import FSVA3030
    assert hasattr(FSVA3030, "select_nr5g")


def test_sg_has_modulation_on():
    """SG exposes modulation_on() to re-enable the loaded ARB waveform (CW<->mod)."""
    from cloudchaser.instruments.sg_smw200a import SMW200A
    assert hasattr(SMW200A, "modulation_on")


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_evm_resets_to_max_gain():
    """EVM fixes max gain at start (common=0) so it doesn't inherit a prior
    test's attenuation (e.g. gain_chan leaving RTPS at code 63 in rx_suite)."""
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    ctx.chip.fields.wr("b0_common_gain", 0x20)   # pre-set non-max gain
    test = get_test("evm")()
    p = test.resolve({"modulation": "manual", "setup_sa": False,
                      "pin_start_dbm": -40, "pin_stop_dbm": -39, "pin_step_db": 1,
                      "settle_s": 0.0})
    test.run(ctx, p, log=lambda *a, **k: None)
    assert ctx.chip.fields.rd("b0_common_gain") == 0
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_channel_sweep_logs_each_point():
    """Channel-axis sweep emits a real-time log line per channel code."""
    from cloudchaser.test_items import get_test
    lines = []
    ctx = _make_ctx()
    test = get_test("gain_index_accuracy")()
    p = test.resolve({"common_codes": [0], "channel_codes": [0, 1, 2],
                      "settle_s": 0.0})
    test.run(ctx, p, log=lambda *a, **k: lines.append(" ".join(str(x) for x in a)))
    pts = [l for l in lines if "channel=0x" in l and "gain=" in l]
    assert len(pts) >= 3
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_common_field_follows_beam():
    """common gain field auto-follows the active beam (b1 -> b1_common_gain)."""
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    ctx.bench.board.beam = "b1"
    ctx.bench.board.active_channels = ["v3"]
    test = get_test("gain_index_accuracy")()
    p = test.resolve({"common_codes": [7], "channel_codes": [0], "settle_s": 0.0})
    test.run(ctx, p, log=lambda *a, **k: None)
    assert ctx.chip.fields.rd("b1_common_gain") == 7
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_ip1db_gain_field_follows_beam():
    """ip1db common gain field auto-follows the active beam."""
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    ctx.bench.board.beam = "b1"
    ctx.bench.board.active_channels = ["v3"]
    test = get_test("ip1db")()
    p = test.resolve({"gain_code": 0, "pin_start_dbm": -40, "pin_stop_dbm": -39,
                      "pin_step_db": 1, "settle_s": 0.0})
    test.run(ctx, p, log=lambda *a, **k: None)
    assert ctx.chip.fields.rd("b1_common_gain") == 0
    ctx.bench.close_all()


# ----------------------------------------------------------------------
# phase_index_accuracy (VNA MS4644B) — fake 트레이스 = 11포인트 27.5..28.5 GHz
# ----------------------------------------------------------------------
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_phase_index_accuracy_marker():
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    test = get_test("phase_index_accuracy")()
    p = test.resolve({"phase_codes": [0, 32, 64, 96], "read_mode": "marker",
                      "settle_s": 0.0})
    result = test.run(ctx, p, log=lambda *a, **k: None)
    assert result.test_id == "phase_index_accuracy"
    assert len(result.rows) == 4                    # marker = 1 row / code
    assert result.columns[:4] == ["phase_code", "freq_Hz", "gain_dB", "phase_deg"]
    assert result.passed is None                    # raw data only
    # fake VNA 는 sweep 마다 +2.8125도 돌므로 mean step 이 그 값으로 나와야 한다.
    assert abs(result.meta["mean_step_deg"] - 2.8125) < 1e-3
    assert result.meta["axis"] == "marker"          # CSV 파일명 태그
    assert result.meta["freq_hz"] == 28.0e9         # 11포인트 중앙 = 28 GHz
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_phase_index_accuracy_trace():
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    test = get_test("phase_index_accuracy")()
    p = test.resolve({"phase_codes": [0, 1], "read_mode": "trace", "settle_s": 0.0})
    result = test.run(ctx, p, log=lambda *a, **k: None)
    assert len(result.rows) == 2 * 11               # full 11-pt trace / code
    assert result.meta["n_sweep_points"] == 11
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_phase_index_accuracy_point_grid():
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    test = get_test("phase_index_accuracy")()
    # 그리드 27.5/28.0/28.5 GHz -> fake 트레이스에서 3포인트.
    p = test.resolve({"phase_codes": [0, 1], "read_mode": "point",
                      "freq_start_hz": 27.5e9, "freq_stop_hz": 28.5e9,
                      "freq_step_hz": 0.5e9, "settle_s": 0.0})
    result = test.run(ctx, p, log=lambda *a, **k: None)
    assert len(result.rows) == 2 * 3
    freqs = {r[1] for r in result.rows}
    assert freqs == {27.5e9, 28.0e9, 28.5e9}
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_phase_index_accuracy_restores_phase_zero():
    """run() 종료 후 phase 는 0 으로 복원되고 attenuator bits 는 raw 레지스터에
    보존돼야 한다 (9-bit set_phase() 는 항상 현재 atten 을 읽어 되쓴다)."""
    from cloudchaser.board.firehawk import FH
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    fh = FH(ctx.chip, 0)
    quad = 0                                        # active channel h0 -> quad 0
    fh.wr(quad, fh.rd(quad) | 0x15)                 # atten bits 6:0 에 값 심기(raw)
    test = get_test("phase_index_accuracy")()
    p = test.resolve({"phase_codes": [64], "read_mode": "marker", "settle_s": 0.0})
    test.run(ctx, p, log=lambda *a, **k: None)
    w = fh.rd(quad)
    assert (w >> 7) & 0x7F == 0                     # coarse phase 복원
    assert w & 0x7F == 0x15                         # atten 보존
    ctx.bench.close_all()


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_phase_index_uses_nine_bit_phase():
    """9-bit 위상: coarse 는 beam-table, fine 은 phase-cal RAM 에 들어간다.

    run() 은 sweep 종료 후 phase 를 0 으로 복원한다(기존 동작, 유지됨 -- see
    test_phase_index_accuracy_restores_phase_zero), so 그 전 상태를 보려면 sweep
    루프 안에서 스냅을 떠야 한다. VNA read_s21() 은 매 코드의 apply_phase()
    직후에 호출되므로 그 지점을 스파이로 후킹해 레지스터 상태를 기록한다.
    """
    from cloudchaser.board.firehawk import FH, PHASE_CAL_ADDR
    bench, chip = _fake_bench_and_chip()
    fh = FH(chip, 0)
    snap: dict[str, int] = {}
    real_read_s21 = bench.vna.read_s21

    def spy_read_s21(*a, **k):
        snap["word0"] = fh.rd(0)
        snap["fine0"] = fh.rd(PHASE_CAL_ADDR + 0)
        return real_read_s21(*a, **k)

    bench.vna.read_s21 = spy_read_s21
    run_item("phase_index_accuracy", bench, chip, {"phase_codes": [13]})
    assert snap["word0"] >> 7 == 13 // 4                      # coarse -> beam-table
    assert snap["fine0"] == 0x2000 | (13 % 4)                 # fine -> phase-cal RAM


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_phase_index_accuracy_never_presets_vna():
    """캘리브레이션 보호: 측정 전 과정에서 VNA 에 *RST/preset 이 없어야 한다."""
    from cloudchaser.test_items import get_test
    ctx = _make_ctx()
    test = get_test("phase_index_accuracy")()
    p = test.resolve({"phase_codes": [0, 1], "read_mode": "marker", "settle_s": 0.0})
    test.run(ctx, p, log=lambda *a, **k: None)
    hist = ctx.bench.vna.history
    assert hist, "VNA was never used"
    assert "*RST" not in hist
    assert not any("PRES" in c.upper() for c in hist)
    # 기본(configure_freq=False)에서는 주파수 설정도 건드리지 않는다.
    assert not any("FREQ:STAR " in c for c in hist)
    ctx.bench.close_all()


# ----------------------------------------------------------------------
# op1db / ip1db -- Task 7: gain_target/beam/channel 마이그레이션
# ----------------------------------------------------------------------
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_gain_target_common_writes_beam_register():
    """gain_target=common 이면 0x1005+beam 에 코드가 들어간다."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b1")     # 기존 헬퍼 사용
    run_item("op1db", bench, chip, {"gain_target": "common", "gain_code": 0x2A})
    assert FH(chip, 0).rd(COMMON_GAIN + 1) == 0x2A


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_legacy_gain_field_still_works(capsys):
    """구 gain_field 는 경고와 함께 동작해야 한다."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b1")
    run_item("op1db", bench, chip, {"gain_field": "b1_common_gain", "gain_code": 0x11})
    assert FH(chip, 0).rd(COMMON_GAIN + 1) == 0x11
    assert "[deprecated] gain_field" in capsys.readouterr().out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_beam_param_overrides_board_beam():
    """beam override param must win over bench.board.beam (mutation-check gap:
    both brief tests use a beam override equal to the board beam, so a version
    that ignores the param and falls straight back to bench.board.beam still
    passes them)."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b0")     # board beam stays b0
    run_item("op1db", bench, chip, {"gain_target": "common", "gain_code": 0x15,
                                     "beam": "b2"})    # explicit override != board beam
    assert FH(chip, 0).rd(COMMON_GAIN + 2) == 0x15     # written to the OVERRIDE beam (b2)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_ip1db_gain_target_defaults_to_board_beam():
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b0", kind="rx")
    run_item("ip1db", bench, chip, {"gain_code": 0x00})
    assert FH(chip, 0).rd(COMMON_GAIN + 0) == 0x00


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_ip1db_resets_beam_table_to_max_gain():
    """ip1db must reset the channel RTPS (beam table) to max gain (atten=0) at
    start, so a leftover attenuation from a prior test doesn't skew the
    small-signal gain reference."""
    from cloudchaser.board.firehawk import FH
    bench, chip = _fake_bench_and_chip(beam="b0", kind="rx")
    fh = FH(chip, 0)
    fh.wr(1, 0x2A)          # h1 (ci=1, active_channels for RX) left at non-zero atten
    run_item("ip1db", bench, chip, {"gain_code": 0x00})
    assert fh.rd(1) & 0x7F == 0


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_legacy_gain_field_beam_differs_from_board_beam(capsys):
    """Task 7's legacy-field test used board beam == field beam (both b1), so a
    shim that drops the beam extraction entirely would still pass it. Use
    mismatched beams here so the extraction is actually exercised."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b0")     # board beam stays b0
    run_item("op1db", bench, chip, {"gain_field": "b1_common_gain", "gain_code": 0x33})
    assert FH(chip, 0).rd(COMMON_GAIN + 1) == 0x33     # written to the FIELD's beam (b1)
    assert FH(chip, 0).rd(COMMON_GAIN + 0) != 0x33      # NOT to the board's beam (b0)
    assert "[deprecated] gain_field" in capsys.readouterr().out


# ----------------------------------------------------------------------
# gain_index_accuracy / channel_gain_alignment -- Task 8: target/routing migration
# ----------------------------------------------------------------------
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_sweeps_beamtable_by_default():
    """channel_target 기본값 beamtable -> beam-table 워드가 마지막 코드로 남는다."""
    from cloudchaser.board.firehawk import FH
    bench, chip = _fake_bench_and_chip()
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0], "channel_codes": [7, 21], "channel_quad": 0,
              "log_psu": False})
    assert FH(chip, 0).rd(0) & 0x7F == 21


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_channel_target_fe():
    from cloudchaser.board.firehawk import FH, FE_GAIN_ADDR
    bench, chip = _fake_bench_and_chip()
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0], "channel_codes": [5], "channel_target": "fe",
              "channel": "h0", "log_psu": False})
    assert FH(chip, 0).rd(FE_GAIN_ADDR + 0) & 0xFF == 5


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_legacy_channel_kind(capsys):
    bench, chip = _fake_bench_and_chip()
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0], "channel_codes": [3], "channel_kind": "beamtable",
              "channel_quad": 0, "log_psu": False})
    assert "[deprecated] channel_kind" in capsys.readouterr().out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_common_target_writes_common_register():
    """common_target defaults to 'common' -> the last common code sweeps into
    0x1005 + beam index (mutation-check: catches a version that always writes
    'beamtable'/no-op for the common axis)."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b0")
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0x15], "channel_codes": [0], "log_psu": False})
    assert FH(chip, 0).rd(COMMON_GAIN + 0) == 0x15


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_legacy_common_field(capsys):
    """common_field (used by channel_gain_alignment historically) must also work
    as a legacy override for gain_index_accuracy's common axis."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b1")
    run_item("gain_index_accuracy", bench, chip,
             {"common_field": "b1_common_gain", "common_codes": [0x09],
              "channel_codes": [0], "log_psu": False})
    assert FH(chip, 0).rd(COMMON_GAIN + 1) == 0x09
    assert "[deprecated] common_field" in capsys.readouterr().out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_validates_channel_codes_before_sweep(capsys):
    """Ruling 20: an out-of-width channel code must fail BEFORE any measurement
    starts, not partway through the sweep (which would happen if set_gain()'s own
    per-write validation were the only check)."""
    bench, chip = _fake_bench_and_chip()
    with pytest.raises(ValueError, match="fe"):
        run_item("gain_index_accuracy", bench, chip,
                 {"common_codes": [0], "channel_codes": [5, 20],
                  "channel_target": "fe", "channel": "h0", "log_psu": False})
    out = capsys.readouterr().out
    assert "channel=0x5" not in out     # code 5 (valid, swept first) never ran
    assert "[gain-sw]" not in out       # failed before the sweep-start log line


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_validates_common_codes_before_sweep(capsys):
    """Same as above for the common axis (6-bit, max 63)."""
    bench, chip = _fake_bench_and_chip()
    with pytest.raises(ValueError, match="6-bit"):
        run_item("gain_index_accuracy", bench, chip,
                 {"common_codes": [0, 70], "channel_codes": [0], "log_psu": False})
    out = capsys.readouterr().out
    assert "[gain-sw]" not in out


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_channel_gain_alignment_routes_channels_raw():
    """path.enable 대신 raw 라우팅을 써야 한다 -- quad enable 레지스터로 확인."""
    from cloudchaser.board.firehawk import FH
    bench, chip = _fake_bench_and_chip()
    run_item("channel_gain_alignment", bench, chip,
             {"channels": "h1", "channels_script": "h1"})
    assert FH(chip, 0).rd(0x100C + 1) != 0


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_channel_gain_alignment_center_enables_raw():
    """centerbias_en/centermirror_en 를 fh.set_center_enables 로 raw 기입해야 한다."""
    from cloudchaser.board.firehawk import BEAM_ENABLES_ADDR, FH
    bench, chip = _fake_bench_and_chip()
    run_item("channel_gain_alignment", bench, chip,
             {"channels": "h1", "channels_script": "h1"})
    assert FH(chip, 0).rd(BEAM_ENABLES_ADDR) == 3   # centerbias(1) + centermirror(2)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_channel_gain_alignment_writes_common_gain_target():
    """max_gain_code must land on the resolved common_target register (0x1005+beam),
    not be silently dropped (mutation-check: catches a version that stops calling
    set_gain in setup_channels)."""
    from cloudchaser.board.firehawk import COMMON_GAIN, FH
    bench, chip = _fake_bench_and_chip(beam="b0")
    run_item("channel_gain_alignment", bench, chip,
             {"channels": "h1", "channels_script": "h1", "max_gain_code": 0x07})
    assert FH(chip, 0).rd(COMMON_GAIN + 0) == 0x07


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_channel_gain_alignment_routes_tx_polarity():
    """Ruling 21: kind is derived from the chip's own identity register (chip_kind),
    not hardcoded. On a TX (Stampede) chip, h1 routing must use TX bit positions
    (H=bits[5:3]) -- quad_pwrdn word = 0xF8 (pwrdn=0x38 | override<<6 | bias_en<<7)."""
    from cloudchaser.board.firehawk import FH, QUAD_PWRDN_ADDR
    bench, chip = _fake_bench_and_chip(kind="tx")
    run_item("channel_gain_alignment", bench, chip,
             {"channels": "h1", "channels_script": "h1"})
    assert FH(chip, 0).rd(QUAD_PWRDN_ADDR + 1) == 0xF8


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_channel_gain_alignment_routes_rx_polarity():
    """Ruling 21: same test on an RX (Blueway) chip must use the MIRRORED bit
    positions (H=bits[2:0]) -- quad_pwrdn word = 0xC7. A version that ignores
    chip_kind() and always routes as TX would write 0xF8 here instead, which is
    the exact silent TX/RX-inversion bug this ruling exists to prevent."""
    from cloudchaser.board.firehawk import FH, QUAD_PWRDN_ADDR
    bench, chip = _fake_bench_and_chip(kind="rx", beam="b0")
    run_item("channel_gain_alignment", bench, chip,
             {"channels": "h1", "channels_script": "h1"})
    assert FH(chip, 0).rd(QUAD_PWRDN_ADDR + 1) == 0xC7


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_channel_gain_alignment_chip_kind_rejects_unpowered():
    """chip_kind() must raise a clear English error (not silently default to TX)
    when the identity register reads 0x0 -- the common "board unpowered" case."""
    from cloudchaser.board.firehawk import FH
    from cloudchaser.board.gain_map import chip_kind
    bench, chip = _fake_bench_and_chip(kind="tx")
    fh = FH(chip, 0)
    fh.wr(0x1000, 0x0000)   # simulate unseeded/unpowered identity readback
    with pytest.raises(ValueError, match="0x0"):
        chip_kind(fh)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_beam_param_overrides_board_beam():
    """Ruling 22: gain_index_accuracy must take a beam override param (parity
    with op1db/ip1db), not just follow bench.board.beam."""
    from cloudchaser.board.firehawk import COMMON_GAIN, FH
    bench, chip = _fake_bench_and_chip(beam="b0")     # board beam stays b0
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0x11], "channel_codes": [0], "log_psu": False,
              "beam": "b2"})                          # explicit override != board beam
    assert FH(chip, 0).rd(COMMON_GAIN + 2) == 0x11     # written to the OVERRIDE beam (b2)
    assert FH(chip, 0).rd(COMMON_GAIN + 0) != 0x11     # NOT to the board's beam (b0)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_evm_sets_common_gain_raw():
    """evm resets to max gain via raw set_gain() (0x1005 + beam index), not
    chip.fields.wr -- the try/except vendor-write pattern is gone (Task 9)."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip()
    run_item("evm", bench, chip, {"pin_start_dbm": -10.0, "pin_stop_dbm": -10.0,
                                  "modulation": "manual", "setup_sa": False,
                                  "settle_s": 0.0})
    assert FH(chip, 0).rd(COMMON_GAIN + 0) == 0


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_session_namespace_exposes_fh():
    """build_namespace exposes the raw FH engine as 'fh' (manual.py write helpers
    all go through it now)."""
    from cloudchaser.manual import build_namespace
    bench, chip = _fake_bench_and_chip()
    ns = build_namespace(bench, chip, "b0")   # Ruling 6: 3-arg signature
    assert "fh" in ns
    from cloudchaser.board.firehawk import FH
    assert isinstance(ns["fh"], FH)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_manual_chan_routes_tx_polarity():
    """manual.chan() must derive TX/RX kind from the chip's own identity register
    (gain_map.chip_kind), not hardcode "tx" -- same Ruling 21 pattern as
    channel_gain_alignment. On a TX chip, h1 routing must use TX bit positions
    (H=bits[5:3]) -- quad_pwrdn word = 0xF8."""
    from cloudchaser.board.firehawk import FH, QUAD_PWRDN_ADDR
    from cloudchaser.manual import build_namespace
    bench, chip = _fake_bench_and_chip(kind="tx", beam="b0")
    ns = build_namespace(bench, chip, "b0")
    ns["chan"]("h1")
    assert FH(chip, 0).rd(QUAD_PWRDN_ADDR + 1) == 0xF8


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_manual_chan_routes_rx_polarity():
    """Same as above on an RX (Blueway) chip -- MIRRORED bit positions
    (H=bits[2:0]) -- quad_pwrdn word = 0xC7. A version that ignores chip_kind()
    and always routes as TX would write 0xF8 here instead."""
    from cloudchaser.board.firehawk import FH, QUAD_PWRDN_ADDR
    from cloudchaser.manual import build_namespace
    bench, chip = _fake_bench_and_chip(kind="rx", beam="b0")
    ns = build_namespace(bench, chip, "b0")
    ns["chan"]("h1")
    assert FH(chip, 0).rd(QUAD_PWRDN_ADDR + 1) == 0xC7


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_manual_enable_disable_use_raw_registers():
    """Ruling 28: enable()/disable() must drive the same raw quad_enables register
    chan()/route_channels() use -- not chip.path.enable/disable_all (vendor shadow
    cache, two calls deep into bias.py's Regs.wr). enable() is additive within the
    same beam; disable(ch) drops just that channel and re-routes the rest."""
    from cloudchaser.board.firehawk import FH, QUAD_ENABLES_ADDR
    from cloudchaser.manual import build_namespace
    bench, chip = _fake_bench_and_chip(kind="tx", beam="b0")
    ns = build_namespace(bench, chip, "b0")
    fh = FH(chip, 0)
    ns["disable"]()   # clean slate -- bring-up already routed bench.toml's default h0

    ns["enable"]("h1")
    assert fh.rd(QUAD_ENABLES_ADDR + 1) & 0x01 == 0x01     # h1 routed to beam 0
    ns["enable"]("h2")                                     # additive, same beam
    assert fh.rd(QUAD_ENABLES_ADDR + 1) & 0x01 == 0x01     # h1 still routed
    assert fh.rd(QUAD_ENABLES_ADDR + 2) & 0x01 == 0x01     # h2 also routed
    assert bench.board.active_channels == ["h1", "h2"]

    ns["disable"]("h1")
    assert fh.rd(QUAD_ENABLES_ADDR + 1) & 0x01 == 0x00     # h1 dropped
    assert fh.rd(QUAD_ENABLES_ADDR + 2) & 0x01 == 0x01     # h2 still routed
    assert bench.board.active_channels == ["h2"]

    ns["disable"]()                                        # all
    assert fh.rd(QUAD_ENABLES_ADDR + 2) & 0x01 == 0x00
    assert bench.board.active_channels == []


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_manual_paths_reads_registers_not_vendor_cache(capsys):
    """paths() must reconstruct the active set from raw registers, not the
    vendor's chip.path.active Python attribute -- that attribute is never
    updated by chan()'s raw routing and would silently show stale/empty state."""
    from cloudchaser.manual import build_namespace
    bench, chip = _fake_bench_and_chip(kind="tx", beam="b0")
    ns = build_namespace(bench, chip, "b0")
    ns["chan"]("h0")            # routes h0 entirely via raw fh writes
    assert all(not chs for chs in chip.path.active.values()), (
        f"sanity check: chan() must NOT touch the vendor path cache, "
        f"got {chip.path.active!r}"
    )
    capsys.readouterr()
    ns["paths"]()
    out = capsys.readouterr().out
    assert "h0" in out and "b0" in out


# Known vendor write entry points that bypass raw registers via a shadow-cache
# read-modify-write (spec section 2.3). Ruling 28: the original guard only
# grepped the literal "fields.wr" substring and missed chip.path.* (which
# reaches vendor bias.py's `self.regs.regs.wr("center_control", 3)` two calls
# deep) -- widened here to every write-shaped vendor entry point found by
# reading the vendor package. fields.rd / fields (read helpers) are deliberately
# NOT in this list -- reads go straight to hardware and are safe (spec section 2).
#
# These already match on the vendor ATTRIBUTE name, not the receiver, so they
# work regardless of what the chip variable is called (e.g. "fields.wr" hits
# both "chip.fields.wr(...)" and "C.fields.wr(...)").
_VENDOR_WRITE_LITERALS = (
    "fields.wr", "fields.set", "fields.clr", ".regs.wr(", "commit_table(",
)

# Ruling 31: "chip.path.", "chip.commit(", "chip.init(" were literal substrings
# with the receiver name "chip" baked in. session.py names the chip object C,
# so C.path.active -- the exact stale-shadow-cache bug Task 10 fixed -- would
# never have tripped this guard; any future file naming it `c`/`dut`/anything
# else has the identical hole. Anchored on the vendor attribute/method instead,
# so the receiver's spelling is irrelevant:
#   - .path.<method>: whitelisted to PathSpec's actual public write surface
#     (sivers_api/chips/cloudchaser/blocks/path.py) so a bare ".path." doesn't
#     also flag unrelated os.path.*/pathlib.Path.* usage elsewhere in the tree.
#     `active` is a read-only property, not a write, but it's included
#     deliberately -- reading it is exactly the stale-cache bug (a vendor
#     python-side cache raw writes never update), so surfacing any renewed
#     reliance on it is the point, same as the read-path exception this
#     module's docstring calls out for fields.rd not applying here.
#   - .commit(: any receiver's .commit() call (kept distinct from the already-
#     literal "commit_table(", which has no leading dot so can't collide).
#   - .init(): vendor chip.init() is always called with no arguments;
#     anchoring on empty parens keeps this from matching __init__(self, ...)
#     definitions/calls.
#   - .beam_table: the vendor BeamTable block. Round 3 found manual.rtps()
#     printing bt.table -- a Python-side copy of the beam table that the raw
#     writes in atten()/phase()/chan() never refresh -- and the guard missed it
#     because only the literal "commit_table(" was listed. Anchored on the
#     attribute name with a word boundary rather than ".beam_table." so the
#     binding form `bt = chip.beam_table` is caught too, not just chained calls.
_VENDOR_WRITE_REGEXES = (
    re.compile(r"\.path\.(enable_all|disable_all|disable_single|enable|disable|active|single|clear)\b"),
    re.compile(r"\.commit\("),
    re.compile(r"\.init\(\)"),
    re.compile(r"\.beam_table\b"),
)

# (filename, exact-stripped-line) -> why this one hit is allowed. Keyed by line
# CONTENT, not line number, so it survives unrelated edits shifting lines around
# (if the line moves, the check still finds and allows it where it landed; if
# the line's text changes, the check correctly stops allowing it).
_ALLOWED_VENDOR_WRITES = {
    ("bringup.py", "chip.init()"):
        "gated behind cfg.run_efuse_init (explicit opt-in flag, design spec "
        "section 5 open item) -- NOT on the default bring-up write path",
    ("manual.py", "chip.init()"):
        "manual.py's --no-enable branch: version-check-only path, no bring-up "
        "runs -- the exact case Ruling 1's chip._fh fallback exists for",
}


def _guard_targets():
    """가드가 검사할 파일 목록 = src/cloudchaser/ 아래 모든 .py (재귀).

    Ruling 38: 예전엔 손으로 유지하는 목록이었고(test_items/ + board/ + manual.py +
    session.py + regdump.py) 그래서 biasscan_compare.py 를 한 번도 안 봤다. 목록이
    아니라 트리에서 유도한다 -- 새 모듈이 자동으로 들어온다.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "cloudchaser"
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _scan_vendor_writes(paths):
    """(offenders, allowed_hit) 를 돌려준다. 테스트 본체와 mutation 테스트가 공유한다."""
    offenders = []
    allowed_hit = set()
    for p in paths:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            hit = None
            for pat in _VENDOR_WRITE_LITERALS:
                if pat in line:
                    hit = pat
                    break
            if hit is None:
                for rx in _VENDOR_WRITE_REGEXES:
                    m = rx.search(line)
                    if m:
                        hit = m.group(0)
                        break
            if hit is None:
                continue
            key = (p.name, stripped)
            if key in _ALLOWED_VENDOR_WRITES:
                allowed_hit.add(key)
            else:
                offenders.append(f"{p.name}:{i} (matched {hit!r}): {stripped}")
    return offenders, allowed_hit


def test_no_vendor_write_api_on_write_path():
    """쓰기 경로에 벤더 고수준 쓰기 API 가 남아 있으면 안 된다(shadow 캐시 위험).

    Task 9(Ruling 2)로 test_items/ 전체 + board/ + manual.py 가 raw 기입으로
    마이그레이션됐고 이 테스트가 xfail 없이 그걸 지켰다. Ruling 28: 리뷰에서
    manual.py 의 enable()/disable()/paths() 가 여전히 chip.path.* 를 거쳐 벤더
    shadow 캐시(Regs.wr)에 닿는다는 걸 찾았는데, "fields.wr" 리터럴만 보던 이전
    가드는 이걸 못 잡았다. 그래서 알려진 벤더 쓰기 진입점 전체로 넓힌다(제자리
    교체, 이전 이름 test_no_vendor_fields_wr_on_write_path 를 대체).

    Ruling 31: session.py 를 스코프에 넣었더니 "chip.path.active" 를 그대로
    되돌리는 mutation 이 가드를 통과했다 -- session.py 는 chip 객체를 C 로
    부르는데 "chip.path." 가 리시버 이름을 문자 그대로 박아둔 리터럴이었기
    때문이다(정확히 Task 10 이 고친 그 버그를 가드 자신은 못 잡았을 거란 뜻).
    chip-접두 3개(path./commit(/init()를 벤더 애트리뷰트에 앵커한 정규식으로
    바꿔 리시버 이름과 무관하게 잡히도록 한다(_VENDOR_WRITE_REGEXES 위 주석
    참고).

    Ruling 38: 스코프가 손으로 유지하는 파일 목록(test_items/ + board/ +
    manual.py + session.py + regdump.py)이었던 탓에 biasscan_compare.py 를 한
    번도 안 봤다 -- 그 파일은 bring_up_tx() 직후에 chip.path.* / chip.fields.wr
    를 계속 부르고 있었다. 가드가 너무 좁았던 게 이번이 세 번째이고, 손으로
    관리하는 목록은 다음에 누가 모듈을 추가하는 순간 또 낡는다. 그래서
    src/cloudchaser/ 아래 모든 .py 를 재귀적으로 검사한다. 정당한 예외는
    _ALLOWED_VENDOR_WRITES((파일, 줄) 키 + 아래 stale 검사로 자동 만료)로만
    처리한다.
    """
    targets = _guard_targets()
    assert targets, "guard scanned nothing -- its scope is broken"
    offenders, allowed_hit = _scan_vendor_writes(targets)
    assert not offenders, f"vendor write API found on write path: {offenders}"
    # An allowlist entry nobody actually hit is stale (the line it was written
    # for got deleted/changed) and should be removed, not left as dead cover.
    stale = set(_ALLOWED_VENDOR_WRITES) - allowed_hit
    assert not stale, f"stale allowlist entries (no longer matched anything): {stale}"


def test_vendor_write_guard_scope_is_derived_not_hand_listed():
    """스코프가 src/cloudchaser/ 전체에서 유도돼야 한다(Ruling 38).

    손으로 유지하던 목록이 biasscan_compare.py 를 놓쳤다. 목록으로 되돌리는
    회귀를 막기 위해, 패키지 안의 모든 .py 가 스코프에 들어오는지 직접 비교한다.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "cloudchaser"
    expected = {p for p in root.rglob("*.py") if "__pycache__" not in p.parts}
    assert set(_guard_targets()) == expected
    # 손으로 만든 목록에 한 번도 안 들어갔던 모듈들이 실제로 포함되는지 못박는다.
    for name in ("biasscan_compare.py", "bench.py", "runner.py", "setup_tx.py",
                 "driver_reg_diff.py", "sivers_report.py", "loss.py"):
        assert root / name in expected, f"{name} missing from the guard scope"


@pytest.mark.parametrize("line, why", [
    ("chip.path.single(ch, beam)", "path.single"),
    ("chip.path.disable_all()", "path.disable_all"),
    ('chip.fields.wr("centerbias_en", 1)', "fields.wr"),
    ("chip.beam_table.zero_table()", "beam_table (chained)"),
    ("bt = chip.beam_table", "beam_table (bound to a local)"),
    ("dut.commit()", "commit on a non-'chip' receiver"),
    ("C.init()", "init on a non-'chip' receiver"),
])
def test_vendor_write_guard_catches_a_violation_in_any_module(tmp_path, line, why):
    """새 모듈에 위반이 들어와도 잡혀야 한다 -- 파일 이름과 무관하게.

    가드 본체(_scan_vendor_writes)를 임시 파일에 그대로 돌린다. 이름이 예전
    손목록에 없던 모듈이어도(여기선 아예 존재한 적 없는 이름) 걸려야 한다.
    """
    f = tmp_path / "brand_new_module.py"
    f.write_text(line + "\n", encoding="utf-8")
    offenders, _ = _scan_vendor_writes([f])
    assert len(offenders) == 1, f"guard missed {why}: {line!r}"


def test_vendor_write_guard_ignores_comments_and_unrelated_paths(tmp_path):
    """주석과 os.path/pathlib 사용은 걸리면 안 된다(패턴이 무르지도, 과하지도 않게)."""
    f = tmp_path / "brand_new_module.py"
    f.write_text(
        "# chip.fields.wr('x', 1) -- 주석은 무시\n"
        "import os.path\n"
        "p = os.path.join(a, b)\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "chip.fields.rd('centerbias_en')\n",   # 읽기는 허용
        encoding="utf-8",
    )
    offenders, _ = _scan_vendor_writes([f])
    assert offenders == []


def test_op1db_sa_ref_level_defaults_to_25dbm():
    """압축점 측정 기본 ref level 은 25 dBm -- Psat ~24 dBm 을 덮어야 한다.

    낮게 잡히면 스윕 상단이 잘려 OP1dB 가 조용히 틀린다.
    """
    from cloudchaser.test_items import get_test
    p = {x.name: x for x in get_test("op1db").params}["sa_ref_level_dbm"]
    assert p.default == 25.0


def test_op1db_sa_ref_level_is_asked_by_wizard():
    """wizard 가 ref level 을 묻도록 숨김 목록에서 빠져 있어야 한다."""
    from cloudchaser.session import _WIZARD_HIDDEN
    assert "sa_ref_level_dbm" not in _WIZARD_HIDDEN["op1db"]


# ----------------------------------------------------------------------
# vdd_sensitivity -- OP1dB sweep repeated at several FE1 supply voltages
#
# 이 항목은 sivers_api 없이도 돌 수 있게 conftest 의 FakeChip(=fh fixture 의 fh.C)을
# 쓴다 -- 레일 램프/복구 같은 안전 동작은 벤치 PC 가 아닌 개발 PC 에서도 반드시
# 검증돼야 하기 때문(bring-up 이 필요 없는 측정이라 가능).
# ----------------------------------------------------------------------
def _vdd_bench_and_chip(fh):
    """fake bench + FakeChip(TX identity 심음)."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.firehawk import VERSION_ID_TX
    bench = Bench.from_toml(CONFIG, fake=True)      # CONFIG = bench.toml = TX board
    bench.connect_all(log=lambda *a, **k: None)
    bench.settle_s = 0.0                            # fake 라 램프 대기는 불필요
    # 실제 순서(power_up 이 이미 FE1 을 정격까지 올린 상태)를 흉내낸다 -- 그래야
    # 램프 기록이 '0V 에서의 최초 상승'이 아니라 '정격에서의 하강/복귀'로 읽힌다.
    psu = bench._psu_for_rail("FE1_4V0")
    psu._set_v[psu.rails["FE1_4V0"].ch] = 4.0
    fh.wr(0x1000, (VERSION_ID_TX << 8) | 0x11)      # gain_map 의 런타임 TX/RX 판별용
    return bench, fh.C


def _fe1_setpoints(bench):
    """fake PSU 가 FE1 채널에 보낸 VOLT 명령 값들[V]."""
    psu = bench._psu_for_rail("FE1_4V0")
    ch = psu.rails["FE1_4V0"].ch
    out = []
    for cmd in psu.history:
        m = re.match(rf"VOLT ([\d.]+),\(@{ch}\)$", cmd.strip())
        if m:
            out.append(round(float(m.group(1)), 3))
    return out


def _vdd_params(**over):
    """짧은 SG sweep + settle 0 으로 빠르게 도는 파라미터."""
    p = {"pin_start_dbm": -30.0, "pin_stop_dbm": -27.0, "pin_step_db": 1.0,
         "settle_s": 0.0, "vdd_settle_s": 0.0}
    p.update(over)
    return p


def test_vdd_sensitivity_rows_and_voltage_column(fh):
    """행 수 = 전압수 x sweep 점수, 첫 컬럼은 그 행이 측정된 FE1 전압."""
    bench, chip = _vdd_bench_and_chip(fh)
    result = run_item("vdd_sensitivity", bench, chip,
                      _vdd_params(vdd_list_v=[4.0, 3.3, 2.2]))
    assert result.columns[:5] == ["VDD_set_V", "SG_dBm", "Pin_dBm",
                                  "Pout_dBm", "Gain_dB"]
    assert len(result.rows) == 3 * 4                  # 3 voltages x 4 SG points
    assert [r[0] for r in result.rows[::4]] == [4.0, 3.3, 2.2]
    assert [e["vdd_v"] for e in result.meta["per_vdd"]] == [4.0, 3.3, 2.2]
    bench.close_all()


def test_vdd_sensitivity_ramps_rail_in_order_and_restores_nominal(fh):
    """전압은 리스트 순서대로 인가되고, 끝나면 정격 4.0V 로 복구된다."""
    bench, chip = _vdd_bench_and_chip(fh)
    run_item("vdd_sensitivity", bench, chip, _vdd_params(vdd_list_v=[4.0, 3.0]))
    v = _fe1_setpoints(bench)
    assert v, "no VOLT command reached the FE1 channel"
    # 정격(4.0)에서 시작하므로 첫 전압은 움직임이 없고, 3.0 까지 내려갔다 되돌아온다.
    assert max(v) <= 4.0, f"rail went above its 4.0 V target: {v}"
    assert 3.0 in v, f"rail never reached the requested 3.0 V: {v}"
    down = v[:v.index(3.0) + 1]
    assert down == sorted(down, reverse=True), f"not a monotonic ramp down: {down}"
    assert v[-1] == 4.0, f"rail not restored to nominal, ended at {v[-1]} V"
    bench.close_all()


def test_vdd_sensitivity_restores_nominal_on_failure(fh):
    """sweep 중 예외가 나도 finally 가 FE1 을 4.0V 로 되돌린다(보드 방치 금지)."""
    bench, chip = _vdd_bench_and_chip(fh)
    calls = {"n": 0}
    real_peak = bench.sa.measure_peak_dbm

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] > 5:            # 두 번째 전압 구간에서 터뜨린다
            raise RuntimeError("SA blew up mid-sweep")
        return real_peak(*a, **k)

    bench.sa.measure_peak_dbm = boom
    with pytest.raises(RuntimeError):
        run_item("vdd_sensitivity", bench, chip, _vdd_params(vdd_list_v=[4.0, 2.4]))
    assert _fe1_setpoints(bench)[-1] == 4.0
    bench.close_all()


def test_vdd_sensitivity_rejects_empty_voltage_list(fh):
    """전압 리스트가 비면 조용히 도는 대신 즉시 에러."""
    bench, chip = _vdd_bench_and_chip(fh)
    with pytest.raises(ValueError):
        run_item("vdd_sensitivity", bench, chip, _vdd_params(vdd_list_v=[]))
    bench.close_all()


def test_vdd_sensitivity_is_tx_only_and_registered():
    from cloudchaser.test_items import REGISTRY, get_test
    assert "vdd_sensitivity" in REGISTRY
    assert get_test("vdd_sensitivity").chips == ("tx",)


def test_vdd_sensitivity_wizard_asks_for_voltage_list():
    """전압 계단은 이 테스트의 본체이므로 wizard 가 반드시 물어야 한다."""
    from cloudchaser.session import _WIZARD_HIDDEN, _WIZARD_USES_LOSS
    assert "vdd_list_v" not in _WIZARD_HIDDEN["vdd_sensitivity"]
    assert "sa_ref_level_dbm" not in _WIZARD_HIDDEN["vdd_sensitivity"]
    assert "vdd_sensitivity" in _WIZARD_USES_LOSS


def test_set_rail_voltage_refuses_above_nominal():
    """정격(bench.toml v_target) 위로는 어떤 값을 넣어도 올라가지 않는다."""
    from cloudchaser.bench import Bench
    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    assert bench.rail_nominal_v("FE1_4V0") == 4.0
    with pytest.raises(ValueError):
        bench.set_rail_voltage("FE1_4V0", 4.5, log=lambda *a, **k: None)
    with pytest.raises(ValueError):
        bench.set_rail_voltage("FE1_4V0", -0.1, log=lambda *a, **k: None)
    bench.close_all()
