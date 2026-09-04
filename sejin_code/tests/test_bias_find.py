"""find_bias -- 한 채널의 bias 코드를 찾아 bench.toml 에 기록하는 절차의 오프라인 테스트.

두 덩어리를 검증한다:
  1) write_measured_bias() -- bench.toml 의 주석을 보존하는 in-place 기입
  2) find_bias() -- 4단계(PTAT 매칭 -> DIST 전류창 -> 게인창 -> OP1dB) 파이프라인

계측기는 fake 에서 정적이라 게인/OP1dB 는 주입 가능한 훅으로 대체하고, 전류는
test_bias_match.py 와 같은 합성 레일 모델(레지스터 코드 -> 전류)로 대체한다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


# ---------------------------------------------------------------------
# write_measured_bias
# ---------------------------------------------------------------------

def _copy_config(tmp_path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dst = tmp_path / "bench.toml"
    dst.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def _bias_table(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)["board"]["bias"]


def test_write_replaces_an_existing_section(tmp_path):
    from cloudchaser.board.bias_measured import write_measured_bias

    p = _copy_config(tmp_path)
    write_measured_bias(p, "h0", ptat=[1, 2, 3], dist=[4, 5, 6],
                        note="test run")
    table = _bias_table(p)
    assert table["h0"]["ptat"] == [1, 2, 3]
    assert table["h0"]["dist"] == [4, 5, 6]
    # 다른 섹션은 그대로다.
    with open(p, "rb") as f:
        doc = tomllib.load(f)
    assert doc["board"]["ch_gain"]["h0"] == 0x8
    assert doc["bias_match"]["targets_ma"]["DIST_1V8"] == 64.4


def test_write_preserves_surrounding_comments(tmp_path):
    """주석이 살아 있어야 한다 -- tomllib 재작성이면 전부 날아간다."""
    from cloudchaser.board.bias_measured import write_measured_bias

    p = _copy_config(tmp_path)
    before = p.read_text(encoding="utf-8")
    write_measured_bias(p, "h0", ptat=[1, 2, 3], dist=[4, 5, 6])
    after = p.read_text(encoding="utf-8")
    for marker in ("[bias_match]", "[board.ch_gain]",
                   "dist_st2_1 = 63 을 고른 이유"):
        assert marker in before and marker in after
    # 원래 값은 사라졌다.
    assert "ptat = [17, 55, 61]" not in after


def test_write_creates_a_new_channel_section(tmp_path):
    from cloudchaser.board.bias_measured import write_measured_bias

    p = _copy_config(tmp_path)
    write_measured_bias(p, "h1", ptat=[7, 8, 9], dist=[10, 11, 12])
    table = _bias_table(p)
    assert table["h0"]["ptat"] == [17, 55, 61]      # 기존 채널 불변
    assert table["h1"] == {"ptat": [7, 8, 9], "dist": [10, 11, 12]}
    # 새 섹션은 [board.ch_gain] 앞, 즉 bias 묶음 안에 들어간다.
    text = p.read_text(encoding="utf-8")
    assert text.index("[board.bias.h1]") < text.index("[board.ch_gain]")


def test_write_is_idempotent(tmp_path):
    """두 번 써도 provenance 주석이 쌓이지 않는다."""
    from cloudchaser.board.bias_measured import write_measured_bias

    p = _copy_config(tmp_path)
    write_measured_bias(p, "v2", ptat=[1, 2, 3], dist=[4, 5, 6], note="first")
    once = p.read_text(encoding="utf-8")
    write_measured_bias(p, "v2", ptat=[1, 2, 3], dist=[4, 5, 6], note="first")
    assert p.read_text(encoding="utf-8") == once
    assert once.count("[board.bias.v2]") == 1
    assert once.count("# find_bias") == 1


def test_write_result_is_loadable_by_the_parser(tmp_path):
    """기입한 값이 bring-up 이 쓰는 파서를 그대로 통과한다."""
    from cloudchaser.board.bias_measured import (parse_measured_bias,
                                                 write_measured_bias)

    p = _copy_config(tmp_path)
    write_measured_bias(p, "v0", ptat=[5, 6, 7], dist=[8, 9, 10])
    parsed = parse_measured_bias(_bias_table(p))
    assert parsed["v0"] == {"ptat": [5, 6, 7], "dist": [8, 9, 10]}


def test_write_rejects_bad_channel_and_codes(tmp_path):
    import pytest

    from cloudchaser.board.bias_measured import write_measured_bias

    p = _copy_config(tmp_path)
    with pytest.raises(ValueError):
        write_measured_bias(p, "z9", ptat=[1, 2, 3], dist=[4, 5, 6])
    with pytest.raises(ValueError):
        write_measured_bias(p, "h1", ptat=[1, 2], dist=[4, 5, 6])
    with pytest.raises(ValueError):
        write_measured_bias(p, "h1", ptat=[1, 2, 64], dist=[4, 5, 6])
    # 거절된 호출은 파일을 건드리지 않는다.
    assert "h1" not in _bias_table(p)


# ---------------------------------------------------------------------
# find_bias 파이프라인
# ---------------------------------------------------------------------

def _bench_chip_brought_up():
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    bench.board.active_channels = ["h0"]
    bench.board.beam = "b0"
    chip = make_chip(bench.board, fake=True)
    bring_up_tx(chip, bench.board, require_version=False, log=lambda *a, **k: None)
    fh = getattr(chip, "_fh", None) or __import__(
        "cloudchaser.board.firehawk", fromlist=["FH"]).FH(chip, 0)
    return bench, chip, fh


def _install_synthetic_rails(bench, fh, row, beam_idx):
    """test_bias_match.py 와 같은 '레지스터 코드 -> 전류' 모델.

    타깃(FE1 27.8 / FE2 18.35 / FE3 10.37)이 코드 0..63 안에서 도달 가능하다.
    """
    def read_all_vi():
        fe = fh.get_fe_bias()
        dist, _ctat = fh.get_dist_bias()
        c = [fe[row][0], fe[row][1], fe[row][2],
             dist[beam_idx][0], dist[beam_idx][1], dist[beam_idx][2]]
        return {
            "FE1_4V0":  {"v": 4.0, "i": (4.34 + 0.40 * c[0]) / 1000.0},
            "FE2_1V8":  {"v": 1.8, "i": (0.07 + 0.30 * c[1]) / 1000.0},
            "FE3_1V8":  {"v": 1.8, "i": (0.07 + 0.20 * c[2]) / 1000.0},
            "IO_ANA_1V8": {"v": 1.8, "i": 0.65 / 1000.0},
            "DIST_1V8": {"v": 1.8,
                         "i": (13.2 + 0.3 * c[3] + 0.3 * c[4] + 0.3 * c[5]) / 1000.0},
            "CORE_1V0": {"v": 1.0, "i": 3.2 / 1000.0},
        }
    bench.read_all_vi = read_all_vi


def _fake_hooks(gain_of, op1db_of):
    """(measure_gain, measure_op1db) 훅 쌍을 만든다. codes -> 값."""
    def measure_gain(codes):
        return gain_of(tuple(codes))

    def measure_op1db(codes):
        g = gain_of(tuple(codes))
        return {"g_ref": g, "op1db_pout": op1db_of(tuple(codes)),
                "ip1db_pin": op1db_of(tuple(codes)) - g,
                "sg_at_op1db": 0.0}, []
    return measure_gain, measure_op1db


def _run_find(tmp_path, *, gain_of, op1db_of, **opts):
    from cloudchaser.bias_find import FindBiasOpts, find_bias
    from cloudchaser.bias_match import beam_index, load_bias_match_cfg
    from cloudchaser.board.firehawk import fe_row, parse_ch

    bench, _chip, fh = _bench_chip_brought_up()
    # 합성 레일은 측정 대상 채널의 FE 행을 봐야 한다 -- h1 은 row 0 이 아니다.
    pol, idx = parse_ch("h1")
    row, bidx = fe_row(idx, pol), beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    p = _copy_config(tmp_path)
    mg, mo = _fake_hooks(gain_of, op1db_of)
    res = find_bias(bench, fh, channel="h1", beam="b0", cfg=cfg,
                    opts=FindBiasOpts(grid_step=32, settle_s=0.0, **opts),
                    config_path=p, measure_gain=mg, measure_op1db=mo,
                    log=lambda *a: None)
    bench.close_all()
    return res, p


def test_find_bias_matches_ptat_to_the_reference_currents(tmp_path):
    """A 단계: FE 3열이 타깃 전류(27.8/18.35/10.37 mA)로 수렴한다."""
    res, _p = _run_find(tmp_path, gain_of=lambda c: 22.0,
                        op1db_of=lambda c: 20.0)
    for rail in ("FE1_4V0", "FE2_1V8", "FE3_1V8"):
        assert abs(res.rails_ma[rail] - res.targets_ma[rail]) <= 0.5


def test_find_bias_rejects_out_of_window_gain(tmp_path):
    """C 단계: 게인창(19..25) 밖 조합은 OP1dB 후보가 되지 않는다."""
    # st2_1 이 클수록 게인이 창을 벗어난다.
    def gain_of(c):
        return 22.0 if c[2] <= 32 else 27.0

    res, _p = _run_find(tmp_path, gain_of=gain_of, op1db_of=lambda c: 20.0)
    assert res.dist[2] <= 32
    assert all(19.0 <= r["gain_db"] <= 25.0 for r in res.candidates)


def test_find_bias_picks_the_highest_op1db(tmp_path):
    """D 단계: 게인창 통과분 중 OP1dB 최대점을 고른다."""
    best = (32, 32, 0)

    def op1db_of(c):
        return 21.0 if c == best else 19.0

    res, _p = _run_find(tmp_path, gain_of=lambda c: 22.0, op1db_of=op1db_of,
                        max_op1db=27)
    assert tuple(res.dist) == best
    assert res.op1db_dbm == 21.0


def test_find_bias_breaks_ties_towards_the_reference_current(tmp_path):
    """OP1dB 가 동률이면 DIST 전류가 큰 쪽(레퍼런스에 가까운 쪽)을 고른다."""
    res, _p = _run_find(tmp_path, gain_of=lambda c: 22.0,
                        op1db_of=lambda c: 20.0)
    # 합성 모델에서 DIST 전류는 세 코드의 합에 비례한다 -> 최대 코드 조합.
    assert tuple(res.dist) == (63, 63, 63)


def test_find_bias_writes_the_result_into_bench_toml(tmp_path):
    from cloudchaser.board.bias_measured import parse_measured_bias

    res, p = _run_find(tmp_path, gain_of=lambda c: 22.0,
                       op1db_of=lambda c: 20.0)
    parsed = parse_measured_bias(_bias_table(p))
    assert parsed["h1"]["ptat"] == list(res.ptat)
    assert parsed["h1"]["dist"] == list(res.dist)


def test_find_bias_leaves_the_chosen_codes_on_the_chip(tmp_path):
    """탐색이 끝나면 칩은 확정 코드 상태로 남는다(바로 측정할 수 있게)."""
    from cloudchaser.bias_match import (DIST_KNOBS, FE_KNOBS, beam_index,
                                        read_knob)

    from cloudchaser.bias_find import FindBiasOpts, find_bias
    from cloudchaser.bias_match import load_bias_match_cfg

    bench, _chip, fh = _bench_chip_brought_up()
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    p = _copy_config(tmp_path)
    mg, mo = _fake_hooks(lambda c: 22.0, lambda c: 20.0)
    res = find_bias(bench, fh, channel="h0", beam="b0", cfg=cfg,
                    opts=FindBiasOpts(grid_step=32, settle_s=0.0),
                    config_path=p, measure_gain=mg, measure_op1db=mo,
                    log=lambda *a: None)
    on_chip_ptat = [read_knob(fh, k, row=row, beam_idx=bidx) for k in FE_KNOBS]
    on_chip_dist = [read_knob(fh, k, row=row, beam_idx=bidx) for k in DIST_KNOBS]
    assert on_chip_ptat == list(res.ptat)
    assert on_chip_dist == list(res.dist)
    bench.close_all()


def test_find_bias_restores_codes_when_a_stage_fails(tmp_path):
    """중단 시 원래 bias 코드로 되돌린다 -- 칩을 임의 코드에 남기지 않는다."""
    import pytest

    from cloudchaser.bias_find import FindBiasOpts, find_bias
    from cloudchaser.bias_match import (ALL_KNOBS, beam_index, load_bias_match_cfg,
                                        read_knob)

    bench, _chip, fh = _bench_chip_brought_up()
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    before = {k.name: read_knob(fh, k, row=row, beam_idx=bidx) for k in ALL_KNOBS}

    def boom(_codes):
        raise RuntimeError("SA went away")

    with pytest.raises(RuntimeError):
        find_bias(bench, fh, channel="h1", beam="b0", cfg=cfg,
                  opts=FindBiasOpts(grid_step=32, settle_s=0.0),
                  config_path=_copy_config(tmp_path),
                  measure_gain=boom, measure_op1db=boom, log=lambda *a: None)
    after = {k.name: read_knob(fh, k, row=row, beam_idx=bidx) for k in ALL_KNOBS}
    assert after == before
    bench.close_all()


def test_find_bias_reports_when_nothing_passes_the_gain_window(tmp_path):
    """게인창을 통과하는 조합이 없으면 예외 대신 빈 결과를 보고한다."""
    res, p = _run_find(tmp_path, gain_of=lambda c: 40.0,
                       op1db_of=lambda c: 20.0)
    assert res.dist is None
    assert res.candidates == []
    # 확정하지 못했으므로 bench.toml 도 건드리지 않는다.
    assert "h1" not in _bias_table(p)


# ---------------------------------------------------------------------
# A' 단계 -- DIST 확정 후 PTAT 재매칭
# ---------------------------------------------------------------------

def _install_coupled_rails(bench, fh, row, beam_idx):
    """FE1 이 DIST 코드에도 끌려가는 모델.

    실측(2026-09-04 h0)에서 FE1_4V0 은 DIST 코드에 따라 27.1~30.3 mA 로 움직였다.
    A 단계에서 타깃에 맞춰도 D 가 DIST 를 바꾸면 어긋난다는 뜻이라, A' 재매칭이
    없으면 최종 FE1 은 타깃을 벗어난다.
    """
    def read_all_vi():
        fe = fh.get_fe_bias()
        dist, _ctat = fh.get_dist_bias()
        c = [fe[row][0], fe[row][1], fe[row][2],
             dist[beam_idx][0], dist[beam_idx][1], dist[beam_idx][2]]
        dist_sum = c[3] + c[4] + c[5]
        return {
            "FE1_4V0":  {"v": 4.0,
                         "i": (4.34 + 0.40 * c[0] + 0.05 * dist_sum) / 1000.0},
            "FE2_1V8":  {"v": 1.8, "i": (0.07 + 0.30 * c[1]) / 1000.0},
            "FE3_1V8":  {"v": 1.8, "i": (0.07 + 0.20 * c[2]) / 1000.0},
            "IO_ANA_1V8": {"v": 1.8, "i": 0.65 / 1000.0},
            "DIST_1V8": {"v": 1.8, "i": (13.2 + 0.3 * dist_sum) / 1000.0},
            "CORE_1V0": {"v": 1.0, "i": 3.2 / 1000.0},
        }
    bench.read_all_vi = read_all_vi


def _run_coupled(tmp_path, *, gain_of, op1db_of, **opts):
    from cloudchaser.bias_find import FindBiasOpts, find_bias
    from cloudchaser.bias_match import beam_index, load_bias_match_cfg
    from cloudchaser.board.firehawk import fe_row, parse_ch

    bench, _chip, fh = _bench_chip_brought_up()
    pol, idx = parse_ch("h1")
    row, bidx = fe_row(idx, pol), beam_index("b0")
    _install_coupled_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    mg, mo = _fake_hooks(gain_of, op1db_of)
    res = find_bias(bench, fh, channel="h1", beam="b0", cfg=cfg,
                    opts=FindBiasOpts(grid_step=32, settle_s=0.0, **opts),
                    config_path=_copy_config(tmp_path), measure_gain=mg,
                    measure_op1db=mo, log=lambda *a: None)
    bench.close_all()
    return res


def test_rematch_pulls_fe1_back_onto_target(tmp_path):
    """A' 가 있으면 확정 DIST 위에서 FE1 이 다시 타깃으로 온다."""
    res = _run_coupled(tmp_path, gain_of=lambda c: 22.0, op1db_of=lambda c: 20.0)
    assert res.rematched is True
    assert abs(res.rails_ma["FE1_4V0"] - res.targets_ma["FE1_4V0"]) <= 0.5


def test_without_rematch_fe1_drifts_off_target(tmp_path):
    """A' 를 끄면 D 가 DIST 를 바꾼 만큼 FE1 이 어긋난 채로 끝난다."""
    res = _run_coupled(tmp_path, gain_of=lambda c: 22.0, op1db_of=lambda c: 20.0,
                       rematch_ptat=False)
    assert res.rematched is False
    assert abs(res.rails_ma["FE1_4V0"] - res.targets_ma["FE1_4V0"]) > 0.5


def test_rematch_reports_the_performance_it_actually_left_behind(tmp_path):
    """보고되는 게인/OP1dB 는 A' 이후 값이다 -- D 단계 값을 그대로 쓰지 않는다."""
    from cloudchaser.bias_find import FindBiasOpts, find_bias
    from cloudchaser.bias_match import beam_index, load_bias_match_cfg
    from cloudchaser.board.firehawk import fe_row, parse_ch

    bench, _chip, fh = _bench_chip_brought_up()
    pol, idx = parse_ch("h1")
    row, bidx = fe_row(idx, pol), beam_index("b0")
    _install_coupled_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    seen = []

    # 게인은 PTAT 이 바뀌면 같이 바뀐다 -> A' 전후 값이 달라야 한다.
    def gain_of(_codes):
        g = 20.0 + 0.05 * fh.get_fe_bias()[row][0]
        seen.append(g)
        return g

    def measure_op1db(codes):
        return {"g_ref": gain_of(codes), "op1db_pout": 20.0,
                "ip1db_pin": 0.0, "sg_at_op1db": 0.0}, []

    res = find_bias(bench, fh, channel="h1", beam="b0", cfg=cfg,
                    opts=FindBiasOpts(grid_step=32, settle_s=0.0),
                    config_path=_copy_config(tmp_path), measure_gain=gain_of,
                    measure_op1db=measure_op1db, log=lambda *a: None)
    # 마지막으로 잰 게인이 곧 보고값이고, 그건 A' 이후에 잰 것이다.
    assert res.gain_db == seen[-1]
    assert res.gain_db == 20.0 + 0.05 * res.ptat[0]
    bench.close_all()


# ---------------------------------------------------------------------
# B/C 한 번 순회 -- 조합마다 레일을 한 번만 읽는다
# ---------------------------------------------------------------------

def _counted_find(tmp_path, *, gain_of, op1db_of, **opts):
    """find_bias 를 돌리며 read_all_vi 호출 수와 게인 측정 코드를 센다."""
    from cloudchaser.bias_find import FindBiasOpts, find_bias
    from cloudchaser.bias_match import beam_index, load_bias_match_cfg
    from cloudchaser.board.firehawk import fe_row, parse_ch

    bench, _chip, fh = _bench_chip_brought_up()
    pol, idx = parse_ch("h1")
    row, bidx = fe_row(idx, pol), beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    inner = bench.read_all_vi
    n = {"reads": 0}

    def counting():
        n["reads"] += 1
        return inner()
    bench.read_all_vi = counting

    seen: list[tuple] = []

    def gain(codes):
        seen.append(tuple(codes))
        return gain_of(tuple(codes))

    _mg, mo = _fake_hooks(gain_of, op1db_of)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    res = find_bias(bench, fh, channel="h1", beam="b0", cfg=cfg,
                    opts=FindBiasOpts(settle_s=0.0, **opts),
                    config_path=_copy_config(tmp_path), measure_gain=gain,
                    measure_op1db=mo, log=lambda *a: None)
    bench.close_all()
    return res, n["reads"], seen


def test_each_combination_is_measured_once(tmp_path):
    """조합마다 게인을 한 번만 잰다 -- 두 번 순회하면 중복이 생긴다."""
    res, _reads, seen = _counted_find(tmp_path, gain_of=lambda c: 22.0,
                                      op1db_of=lambda c: 20.0, grid_step=32)
    # 마지막 한 번은 A' 의 확인 측정(확정 조합에서 다시 잰다) -- 순회는 그 앞이다.
    sweep, confirm = seen[:-1], seen[-1]
    assert len(sweep) == 27 == len(set(sweep))   # 축당 [0, 32, 63] -> 3^3
    assert confirm == tuple(res.dist)


def test_gain_is_skipped_outside_the_current_window(tmp_path):
    """전류 창 밖 조합은 게인을 재지 않는다 -- 창이 하는 유일한 절약이다."""
    # 합성 모델의 DIST 전류 = 13.2 + 0.3 * (코드 합). 타깃 64.4 +/- 6 이면
    # 코드 합 >= 151 인 조합만 남는다: (63,63,63) 과 (63,63,32) 의 3가지 순열.
    _res, _reads, seen = _counted_find(tmp_path, gain_of=lambda c: 22.0,
                                       op1db_of=lambda c: 20.0, grid_step=32,
                                       window_ma=6.0)
    assert sorted(seen[:-1]) == sorted([(32, 63, 63), (63, 32, 63),
                                        (63, 63, 32), (63, 63, 63)])


def test_grid_costs_one_rail_read_per_combination(tmp_path):
    """그리드를 키운 만큼만 레일 읽기가 는다(조합당 avg_n 회).

    두 번 순회하던 예전 구조는 조합당 2 * avg_n 회였다. 그리드 크기가 다른 두
    실행의 차이를 보면 A/A' 등 고정 비용이 상쇄돼 조합당 비용만 남는다.
    """
    from cloudchaser.bias_match import load_bias_match_cfg

    avg_n = load_bias_match_cfg(CONFIG).avg_n
    _r1, reads1, _s1 = _counted_find(tmp_path / "a", gain_of=lambda c: 22.0,
                                     op1db_of=lambda c: 20.0, grid_step=32)
    _r2, reads2, _s2 = _counted_find(tmp_path / "b", gain_of=lambda c: 22.0,
                                     op1db_of=lambda c: 20.0, grid_step=21)
    extra_combos = 4 ** 3 - 3 ** 3          # [0,21,42,63] vs [0,32,63]
    per_combo = (reads2 - reads1) / extra_combos
    # A/A' 의 이분탐색 경로가 조금 달라질 수 있어 여유를 둔다. 두 번 순회면
    # 2 * avg_n = 6 이 나오므로 4.5 를 넘지 않는지로 가른다.
    assert per_combo < avg_n * 1.5
