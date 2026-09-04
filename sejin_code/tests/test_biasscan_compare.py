"""biasscan_compare 의 오프라인(fake) 스모크 + raw 기입 회귀 테스트.

scan_channel 이 단별(PA/Driver/Comb) 구조를 올바로 돌려주는지, 그리고 그 셋업/스윕이
벤더 고수준 쓰기 API 가 아니라 raw 레지스터로 이뤄지는지 확인한다.
(fake PSU 전류는 static 이라 delta 는 검증하지 않고, 형태/필드/레지스터만 본다.)

Ruling 38 배경: `_setup_single()` 은 bring_up_tx() 직후에 chip.path.* / chip.fields.wr
를 불렀다. 그건 파이썬 shadow 캐시 기준 read-modify-write 라, bring-up 이 raw 로 쓴
0x1008/0x100C/0x1010 을 캐시 스냅샷으로 되돌릴 수 있다 -- 이 마이그레이션이 없애려던
바로 그 해저드다. 아래 테스트가 레지스터 결과를 직접 고정한다.
"""

from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def _fake_bench_chip():
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import make_chip

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    chip = make_chip(bench.board, fake=True)
    chip.init()
    return bench, chip


def _bench_chip_brought_up(channels=("h0", "h1")):
    """bring_up_tx 까지 마친 fake bench/chip -- 실행 경로(main)와 같은 상태."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    bench.board.active_channels = list(channels)
    bench.board.beam = "b0"
    chip = make_chip(bench.board, fake=True)
    bring_up_tx(chip, bench.board, require_version=False, log=lambda *a, **k: None)
    return bench, chip


def test_scan_channel_structure():
    from cloudchaser.biasscan_compare import STAGES, scan_channel

    bench, chip = _fake_bench_chip()
    rows = scan_channel(bench, chip, "b0", "h1", settle=0.0, restore=32)
    assert len(rows) == len(STAGES)
    assert [r["stage"] for r in rows] == [1, 2, 3]
    assert [r["rail"] for r in rows] == ["FE1_4V0", "FE2_1V8", "FE3_1V8"]
    for r in rows:
        assert {"stage", "rail", "desc", "i0", "i63", "delta"} <= r.keys()
    bench.close_all()


def test_main_fake_runs():
    from cloudchaser.biasscan_compare import main

    rc = main(["--fake", "--no-power", "--good", "h1", "--bad", "h0,v0"])
    assert rc == 0


def test_setup_single_routes_through_raw_registers():
    """셋업이 남기는 것은 레지스터 상태여야 한다 -- 벤더 캐시 경유가 아니라.

    확인 대상: 0x1008(center bias/mirror ON), 0x100C+i(요청 채널 quad 만 빔에 라우팅),
    0x1010+i(TX 극성 H=bits[5:3]), 0x1005+beam(common gain 최대=0).
    """
    from cloudchaser.biasscan_compare import _setup_single

    bench, chip = _bench_chip_brought_up()
    fh = chip._fh
    _setup_single(fh, "b0", "h1")

    assert fh.rd(0x1008) & 0b11 == 0b11, "centerbias_en/centermirror_en not set"
    assert fh.rd(0x100C + 1) & 0x07 == 0b001, "quad1 not routed to beam0"
    assert [fh.rd(0x100C + i) & 0x07 for i in (0, 2, 3)] == [0, 0, 0], \
        "other quads left routed"
    assert fh.rd(0x1010 + 1) & 0x3F == 0b111000, "TX H pwrdn bits wrong"
    assert fh.rd(0x1005) & 0x3F == 0, "common gain not driven to max"
    bench.close_all()


def test_setup_single_does_not_undo_bring_up_bias():
    """셋업이 bring-up 이 raw 로 기입한 FE bias 를 되돌리면 안 된다(shadow 캐시 회귀)."""
    from cloudchaser.biasscan_compare import _setup_single
    from cloudchaser.board.firehawk import fe_row

    bench, chip = _bench_chip_brought_up(channels=("h1",))
    fh = chip._fh
    before = fh.get_fe_bias()
    _setup_single(fh, "b0", "h1")
    after = fh.get_fe_bias()
    assert after == before
    # bring-up 이 Casper PTAT 를 실제로 남겼는지도 같이 고정(테스트가 0==0 을 보는 걸 방지)
    assert after[fe_row(1, "h")][0:3] == [15, 45, 55]
    bench.close_all()


def test_scan_channel_sweeps_the_raw_fe_bias_registers():
    """PTAT 스윕/복귀가 0x1038~ FE bias 레지스터에 실제로 남아야 한다.

    또한 CTAT/CBIAS(열 3/4)는 건드리지 않는다 -- 스펙의 "die eFuse 값 유지" 규칙.
    """
    from cloudchaser.biasscan_compare import scan_channel
    from cloudchaser.board.firehawk import fe_row

    bench, chip = _bench_chip_brought_up(channels=("h1",))
    fh = chip._fh
    row = fe_row(1, "h")
    ctat_cbias = fh.get_fe_bias()[row][3:5]

    scan_channel(bench, chip, "b0", "h1", settle=0.0, restore=17)

    bias = fh.get_fe_bias()
    assert bias[row][0:3] == [17, 17, 17], "restore value not written to PTAT St1-3"
    assert bias[row][3:5] == ctat_cbias, "CTAT/CBIAS must be left at the eFuse values"
    bench.close_all()


def test_setup_single_channel_is_shared():
    """gain_map.setup_single_channel 이 biasscan_compare._setup_single 과 같은
    레지스터 상태를 만든다(중복 셋업 방지)."""
    from cloudchaser.board.firehawk import FH
    from cloudchaser.board.gain_map import setup_single_channel

    bench_a, chip_a = _bench_chip_brought_up()
    fh_a = getattr(chip_a, "_fh", None) or FH(chip_a, 0)
    setup_single_channel(fh_a, "b0", "h1")
    regs_a = {a: fh_a.rd(a) for a in (0x1008, 0x100C, 0x1010)}

    bench_b, chip_b = _bench_chip_brought_up()
    from cloudchaser.biasscan_compare import _setup_single
    fh_b = getattr(chip_b, "_fh", None) or FH(chip_b, 0)
    _setup_single(fh_b, "b0", "h1")
    regs_b = {a: fh_b.rd(a) for a in (0x1008, 0x100C, 0x1010)}

    assert regs_a == regs_b
    bench_a.close_all()
    bench_b.close_all()
