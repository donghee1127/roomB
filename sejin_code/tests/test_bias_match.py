"""bias_match 의 오프라인(fake) 테스트.

전류계는 fake 에서 정적이라, 탐색 로직은 fh 레지스터 read-back 을 입력으로 쓰는
합성 레일 모델(_synthetic_read_all_vi)을 bench.read_all_vi 에 주입해 검증한다.
"""

from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def test_load_bias_match_cfg():
    from cloudchaser.bias_match import load_bias_match_cfg

    cfg = load_bias_match_cfg(CONFIG)
    assert cfg.targets_ma["FE1_4V0"] == 27.8
    assert cfg.targets_ma["FE2_1V8"] == 18.35
    assert cfg.targets_ma["FE3_1V8"] == 10.37
    # 2026-09-03 재배선으로 DIST_1V8 <-> IDC_Dist 가 1:1 이 되어 타깃이 생겼다.
    assert cfg.targets_ma["DIST_1V8"] == 64.4
    # IO_ANA_1V8(bandgap/LDO/IO 버퍼)은 bias knob 이 없어 계속 기록 전용이다.
    assert "IO_ANA_1V8" not in cfg.targets_ma
    assert cfg.report_only == ["IO_ANA_1V8", "CORE_1V0"]
    assert cfg.tol_ma == 0.5
    assert cfg.avg_n == 3
    assert cfg.max_iter == 3
    assert cfg.dist_ratio == [50, 13, 13]


def test_load_bias_match_cfg_defaults(tmp_path):
    """[bias_match] 섹션이 없는 toml 도 기본값으로 로드된다."""
    from cloudchaser.bias_match import load_bias_match_cfg

    p = tmp_path / "empty.toml"
    p.write_text("[ramp]\nstep_v = 0.2\n", encoding="utf-8")
    cfg = load_bias_match_cfg(p)
    assert cfg.targets_ma == {}
    assert cfg.tol_ma == 0.5
    assert cfg.dist_ratio == [50, 13, 13]


def _bench_chip_brought_up(channels=("h0",)):
    """bring_up_tx 까지 마친 fake bench/chip."""
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    bench.board.active_channels = list(channels)
    bench.board.beam = "b0"
    chip = make_chip(bench.board, fake=True)
    bring_up_tx(chip, bench.board, require_version=False, log=lambda *a, **k: None)
    return bench, chip


def _fh_of(chip):
    from cloudchaser.board.firehawk import FH
    return getattr(chip, "_fh", None) or FH(chip, 0)


def test_knob_roundtrip():
    from cloudchaser.bias_match import ALL_KNOBS, beam_index, read_knob, write_knob

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")     # h0 -> FE bias row 0
    for i, kn in enumerate(ALL_KNOBS):
        write_knob(fh, kn, 7 + i, row=row, beam_idx=bidx)
    for i, kn in enumerate(ALL_KNOBS):
        assert read_knob(fh, kn, row=row, beam_idx=bidx) == 7 + i
    bench.close_all()


def test_write_knob_rejects_out_of_range():
    import pytest

    from cloudchaser.bias_match import ALL_KNOBS, beam_index, write_knob

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    with pytest.raises(ValueError):
        write_knob(fh, ALL_KNOBS[0], 64, row=0, beam_idx=beam_index("b0"))
    bench.close_all()


def test_read_rails_ma_returns_all_rails():
    from cloudchaser.bias_match import read_rails_ma

    bench, _chip = _bench_chip_brought_up()
    rails = read_rails_ma(bench, avg_n=2, settle_s=0.0)
    for name in ("FE1_4V0", "FE2_1V8", "FE3_1V8", "IO_ANA_1V8", "DIST_1V8", "CORE_1V0"):
        assert name in rails
        assert isinstance(rails[name], float)
    bench.close_all()


def test_guard_rails_raises_at_current_limit():
    """i_limit 근처 전류는 이름을 밝히며 중단시킨다(보드 보호)."""
    import pytest

    from cloudchaser.bias_match import guard_rails, rail_limits_ma

    bench, _chip = _bench_chip_brought_up()
    limits = rail_limits_ma(bench)
    assert limits["FE1_4V0"] == 300.0        # bench.toml: 0.3 A
    guard_rails(bench, {"FE1_4V0": 27.8})    # 정상 -> 조용히 통과
    with pytest.raises(RuntimeError, match="FE1_4V0"):
        guard_rails(bench, {"FE1_4V0": 299.0})
    bench.close_all()


def _install_synthetic_rails(bench, fh, row, beam_idx):
    """bench.read_all_vi 를 '레지스터 코드 -> 전류' 합성 모델로 교체한다.

    계수는 bench.toml 타깃이 코드 0..63 안에서 도달 가능하도록 잡았다:
      FE1 27.8 -> code 59 / FE2 18.35 -> 61 / FE3 10.37 -> 51 / Dist 64.4 -> k=1.11
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
            # IO_ANA_1V8 = VDD_IO(SPI 버퍼): bias 와 무관한 상수. 실측 0.65 mA.
            "IO_ANA_1V8":   {"v": 1.3, "i": 0.65 / 1000.0},
            # DIST_1V8 = 디지털(13.2) + DIST. 이 EVB 는 분배망이 1.8V 에 물려 있다.
            # FE 의 미미한 기여(실측 0.0136 mA/code)는 테스트 산수를 흐려서 뺐다.
            "DIST_1V8":  {"v": 1.8,
                         "i": (13.2 + 0.9 * c[3] + 0.5 * c[4] + 0.5 * c[5]) / 1000.0},
            "CORE_1V0": {"v": 1.0, "i": 3.2 / 1000.0},
        }
    bench.read_all_vi = read_all_vi
    return read_all_vi


def test_jacobian_is_diagonally_dominant():
    from cloudchaser.bias_match import (
        ALL_KNOBS, beam_index, directions_from_jacobian, load_bias_match_cfg,
        measure_jacobian,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    base, codes, rows = measure_jacobian(bench, fh, row=row, beam_idx=bidx,
                                         cfg=cfg, delta=8, log=lambda *a: None)
    assert len(rows) == len(ALL_KNOBS)
    assert set(codes) == {k.name for k in ALL_KNOBS}
    by_name = {r["knob"]: r for r in rows}
    # 각 FE knob 은 자기 레일에서 가장 크게 반응한다.
    for kn in ALL_KNOBS[:3]:
        d = by_name[kn.name]["d"]
        assert abs(d[kn.rail]) == max(abs(x) for x in d.values())
    # 어떤 knob 도 CORE_1V0 을 움직이지 않는다.
    for r in rows:
        assert abs(r["d"]["CORE_1V0"]) < 1e-9
    # 코드는 원래 값으로 복원된다.
    from cloudchaser.bias_match import read_knob
    for kn in ALL_KNOBS:
        assert read_knob(fh, kn, row=row, beam_idx=bidx) == codes[kn.name]

    dirs = directions_from_jacobian(rows)
    assert all(dirs[k.name] is True for k in ALL_KNOBS)
    bench.close_all()


def test_directions_drop_dead_knobs():
    from cloudchaser.bias_match import directions_from_jacobian

    rows = [
        {"knob": "ptat_st1", "resp_ma": 3.2, "rising": True, "d": {}},
        {"knob": "ptat_st2", "resp_ma": 0.05, "rising": False, "d": {}},
    ]
    dirs = directions_from_jacobian(rows, noise_ma=0.2)
    assert dirs == {"ptat_st1": True}


NONMONO_FE1_TARGET_MA = 25.34      # = _nonmono_fe1(7), 코드 7 에서 정확히 맞는 값


def _nonmono_fe1(code: int) -> float:
    """FE1 전류가 코드 10 에서 정점을 찍고 다시 내려가는 접힌 응답.

    이분법의 첫 중점(31)은 하강 구간에 떨어지고, 거기서 전류는 이미 타깃보다
    낮다 -> 'rising' 가정 때문에 탐색은 위쪽(32..63)으로 잘못 내려간다.
    타깃은 상승 구간의 코드 7 에서만 제대로 맞는다.
    """
    return 4.34 + 3.0 * code if code <= 10 else 34.34 - 0.6 * (code - 10)


def _install_nonmonotonic_rails(bench, fh, row, beam_idx):
    """ptat_st1 만 접힌(non-monotonic) 응답으로 만든 합성 모델."""
    def read_all_vi():
        fe = fh.get_fe_bias()
        dist, _ctat = fh.get_dist_bias()
        c = [fe[row][0], fe[row][1], fe[row][2],
             dist[beam_idx][0], dist[beam_idx][1], dist[beam_idx][2]]
        fe1 = _nonmono_fe1(c[0])
        return {
            "FE1_4V0":  {"v": 4.0, "i": fe1 / 1000.0},
            "FE2_1V8":  {"v": 1.8, "i": (0.07 + 0.30 * c[1]) / 1000.0},
            "FE3_1V8":  {"v": 1.8, "i": (0.07 + 0.20 * c[2]) / 1000.0},
            "IO_ANA_1V8":   {"v": 1.3, "i": (0.9 * c[3] + 0.5 * c[4] + 0.5 * c[5]) / 1000.0},
            "DIST_1V8":  {"v": 1.8, "i": (0.9 + 0.02 * sum(c)) / 1000.0},
            "CORE_1V0": {"v": 1.0, "i": 3.2 / 1000.0},
        }
    bench.read_all_vi = read_all_vi
    return read_all_vi


def test_nonmonotonic_knob_falls_back_to_linear_scan():
    """접힌 응답은 감지돼야 하고, 그 knob 은 선형 스캔으로 타깃에 도달한다."""
    from cloudchaser.bias_match import (
        beam_index, directions_from_jacobian, load_bias_match_cfg,
        measure_jacobian, nonmonotonic_knobs, solve_bias, write_knob, FE_KNOBS,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_nonmonotonic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    cfg.targets_ma["FE1_4V0"] = NONMONO_FE1_TARGET_MA
    # 이 픽스처는 FE 레일만 모델링한다 -- DIST 타깃까지 쫓게 두면 수렴 판정이
    # DIST 쪽에서 실패해 FE 폴백 검증이 가려진다.
    cfg.targets_ma.pop("DIST_1V8", None)
    # 국소 기울기가 양(+)인 구간에서 자코비안을 뜬다 -> rising=True 로 보인다.
    write_knob(fh, FE_KNOBS[0], 5, row=row, beam_idx=bidx)

    _base, _codes, jrows = measure_jacobian(bench, fh, row=row, beam_idx=bidx,
                                            cfg=cfg, delta=8,
                                            log=lambda *a: None)
    assert nonmonotonic_knobs(jrows) == ["ptat_st1"]
    dirs = directions_from_jacobian(jrows)
    assert dirs["ptat_st1"] is True          # 국소만 보면 상승으로 보인다

    res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                     directions=dirs, nonmonotonic=["ptat_st1"],
                     log=lambda *a: None)
    assert res["nonmonotonic"] == ["ptat_st1"]
    # 선형 스캔은 접힌 곡선에서도 타깃을 찾아낸다(이분법은 못 찾는다).
    assert res["codes"]["ptat_st1"] == 7
    assert abs(res["errors_ma"]["FE1_4V0"]) <= cfg.tol_ma
    assert res["converged"] is True
    bench.close_all()


def test_scan_knob_beats_bisection_on_folded_response():
    """같은 모델에서 이분법은 실패하고 선형 스캔은 성공하는 것을 대비해 보인다."""
    from cloudchaser.bias_match import (
        beam_index, bisect_knob, FE_KNOBS, load_bias_match_cfg, scan_knob,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_nonmonotonic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    target = NONMONO_FE1_TARGET_MA
    _c, _cur, err_bis = bisect_knob(bench, fh, FE_KNOBS[0], target, row=row,
                                    beam_idx=bidx, cfg=cfg, rising=True,
                                    log=lambda *a: None)
    assert abs(err_bis) > cfg.tol_ma          # 접힌 곡선에서 이분법은 빗나간다
    code, cur, err = scan_knob(bench, fh, FE_KNOBS[0], target, row=row,
                               beam_idx=bidx, cfg=cfg, log=lambda *a: None)
    assert code == 7
    assert abs(err) <= cfg.tol_ma
    assert abs(cur - target) <= cfg.tol_ma
    bench.close_all()


def test_dist_ratio_length_is_validated():
    """짧은 dist_ratio 는 조용히 dist_st2_1 을 빼먹는 대신 오류가 된다."""
    import pytest

    from cloudchaser.bias_match import (
        beam_index, bisect_dist_scale, load_bias_match_cfg,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    cfg.dist_ratio = [50, 13]
    with pytest.raises(ValueError, match="dist_ratio"):
        bisect_dist_scale(bench, fh, 64.4, beam_idx=bidx, cfg=cfg,
                          rising=True, log=lambda *a: None)
    bench.close_all()


def test_solve_converges_on_synthetic_model():
    from cloudchaser.bias_match import (
        beam_index, directions_from_jacobian, load_bias_match_cfg,
        measure_jacobian, solve_bias,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    _base, _codes, jrows = measure_jacobian(bench, fh, row=row, beam_idx=bidx,
                                            cfg=cfg, delta=8, log=lambda *a: None)
    dirs = directions_from_jacobian(jrows)
    res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                     directions=dirs, log=lambda *a: None)

    assert res["converged"] is True
    assert res["skipped"] == []
    for rail, target in cfg.targets_ma.items():
        assert abs(res["rails_ma"][rail] - target) <= cfg.tol_ma, rail
        assert abs(res["errors_ma"][rail]) <= cfg.tol_ma
    assert res["codes"]["ptat_st1"] == 59
    assert res["codes"]["ptat_st2"] == 61
    assert res["codes"]["ptat_st3"] in (51, 52)
    bench.close_all()


def test_dist_scale_reaches_past_the_first_clamp():
    """가장 큰 ratio 항이 63 에 닿은 뒤에도 계속 올라갈 수 있어야 한다.

    2026-09-03 실측에서 레퍼런스 DIST 전류(64.4 mA)는 코드 (63,63,63) 부근이었다.
    k 상한을 max(ratio) 기준으로 잡으면 v4 Casper 비율 [50,13,13] 에서 k<=1.26,
    즉 코드 (63,16,16) 에서 탐색이 끝나 타깃에 영원히 못 닿는다.
    """
    from cloudchaser.bias_match import (
        beam_index, bisect_dist_scale, load_bias_match_cfg,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    # 합성 모델: 13.2 + 0.9*st1 + 0.5*st2_0 + 0.5*st2_1
    # 옛 상한이 낼 수 있는 최대는 (63,16,16) = 85.9 mA -> 그보다 높은 타깃을 쓴다.
    assert 13.2 + 0.9 * 63 + 0.5 * 16 + 0.5 * 16 < 110.0
    codes, k, cur, err = bisect_dist_scale(bench, fh, 110.0, beam_idx=bidx,
                                           cfg=cfg, rising=True,
                                           log=lambda *a: None)
    assert abs(err) <= cfg.tol_ma, f"unreachable: {codes} -> {cur} mA"
    assert codes[1] > 16 and codes[2] > 16      # 첫 clamp 를 넘어섰다
    assert all(0 <= c <= 63 for c in codes)
    bench.close_all()


def test_dist_solve_preserves_ratio():
    from cloudchaser.bias_match import (
        beam_index, bisect_dist_scale, load_bias_match_cfg,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    # 13.2(디지털) + 64.4(저쪽 DIST) = 77.6 -> k=1.110 에서 codes (56,14,14) 로 정확히 맞는다.
    target = 77.6
    codes, k, cur, err = bisect_dist_scale(bench, fh, target,
                                           beam_idx=bidx, cfg=cfg, rising=True,
                                           log=lambda *a: None)
    expected = tuple(max(0, min(63, int(round(k * r)))) for r in cfg.dist_ratio)
    assert codes == expected
    assert abs(err) <= cfg.tol_ma
    assert abs(cur - target) <= cfg.tol_ma
    bench.close_all()


def test_unreachable_target_reports_residual():
    """코드 63 으로도 못 미치는 타깃은 예외가 아니라 잔차 보고로 끝난다."""
    from cloudchaser.bias_match import (
        beam_index, bisect_knob, FE_KNOBS, load_bias_match_cfg,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    code, cur, err = bisect_knob(bench, fh, FE_KNOBS[0], 60.0, row=row,
                                 beam_idx=bidx, cfg=cfg, rising=True,
                                 log=lambda *a: None)
    assert code == 63
    assert err < -cfg.tol_ma      # 여전히 부족하다고 보고
    assert abs(cur - (4.34 + 0.40 * 63)) < 1e-6
    bench.close_all()


def test_solve_skips_dead_knobs():
    from cloudchaser.bias_match import (
        beam_index, load_bias_match_cfg, solve_bias,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    # ptat_st2 만 무응답으로 취급 -> 건너뛰고 나머지는 계속 푼다.
    dirs = {"ptat_st1": True, "ptat_st3": True,
            "dist_st1": True, "dist_st2_0": True, "dist_st2_1": True}
    res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                     directions=dirs, log=lambda *a: None)
    assert res["skipped"] == ["ptat_st2"]
    assert res["converged"] is False          # FE2 레일은 타깃에 못 맞음
    assert abs(res["errors_ma"]["FE1_4V0"]) <= cfg.tol_ma
    bench.close_all()


def test_main_jacobian_fake_runs(tmp_path):
    from cloudchaser.bias_match import main

    out = tmp_path / "jac.csv"
    rc = main(["jacobian", "--fake", "--config", str(CONFIG),
               "--csv", str(out), "--ambient-c", "25.0"])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "ptat_st1" in text and "dist_st2_1" in text
    assert "ambient_C" in text
    # 기본은 bench.toml 을 따른다(split_mode=true). Sivers 공유 결과가 전부 split.
    assert "# split_mode=True" in text


def test_main_jacobian_no_split_flag_overrides_toml(tmp_path):
    """--no-split 을 주면 bench.toml(split) 을 덮고 thru 로 측정, CSV 에 남는다."""
    from cloudchaser.bias_match import main

    out = tmp_path / "jac_thru.csv"
    rc = main(["jacobian", "--fake", "--no-split", "--config", str(CONFIG),
               "--csv", str(out), "--ambient-c", "25.0"])
    assert rc == 0
    assert "# split_mode=False" in out.read_text(encoding="utf-8")


def test_main_solve_fake_runs(tmp_path):
    """fake 는 전류가 정적이라 수렴하지 않는다 -- 예외 없이 max_iter 로 끝나야 한다."""
    from cloudchaser.bias_match import load_bias_match_cfg, main

    out = tmp_path / "solve.csv"
    rc = main(["solve", "--fake", "--config", str(CONFIG),
               "--csv", str(out), "--ambient-c", "25.0"])
    assert rc == 0
    meta = {ln[2:].split("=", 1)[0]: ln[2:].split("=", 1)[1]
            for ln in out.read_text(encoding="utf-8").splitlines()
            if ln.startswith("# ")}
    # 정적 전류 -> 수렴 실패를 CSV 메타에 그대로 기록해야 한다.
    assert meta["converged"] == "False"
    assert meta["iterations"] == str(load_bias_match_cfg(CONFIG).max_iter)
    assert meta["split_mode"] == "True"       # 기본 = bench.toml 값(split)


def test_main_solve_rejects_unknown_target_rail(tmp_path):
    """오타난 레일 이름은 bring-up 전에 잡아서 non-zero 로 끝난다."""
    from cloudchaser.bias_match import main

    cfg = tmp_path / "bad.toml"
    text = CONFIG.read_text(encoding="utf-8").replace(
        "targets_ma  = { FE1_4V0 = 27.8,", "targets_ma  = { FE1_4VO = 27.8,")
    assert "FE1_4VO" in text                  # 치환이 실제로 일어났는지 확인
    cfg.write_text(text, encoding="utf-8")
    out = tmp_path / "solve.csv"
    rc = main(["solve", "--fake", "--config", str(cfg),
               "--csv", str(out), "--ambient-c", "25.0"])
    assert rc == 1
    assert not out.exists()                   # 측정도 기록도 시작하지 않는다


def test_main_solve_rejects_empty_targets(tmp_path):
    """타깃이 하나도 없으면 '수렴했다'가 아니라 오류로 끝난다."""
    import re

    from cloudchaser.bias_match import main

    cfg = tmp_path / "notargets.toml"
    text = re.sub(r"(?m)^targets_ma .*$", "targets_ma  = { }",
                  CONFIG.read_text(encoding="utf-8"))
    cfg.write_text(text, encoding="utf-8")
    out = tmp_path / "solve.csv"
    rc = main(["solve", "--fake", "--config", str(cfg),
               "--csv", str(out), "--ambient-c", "25.0"])
    assert rc == 1
    assert not out.exists()


def test_solve_bias_empty_targets_never_converges():
    """빈 targets 로 all() 이 True 가 되는 함정을 막는다."""
    from cloudchaser.bias_match import (
        beam_index, load_bias_match_cfg, solve_bias,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    cfg.targets_ma = {}

    res = solve_bias(bench, fh, row=row, beam_idx=bidx, cfg=cfg,
                     directions={k: True for k in
                                 ("ptat_st1", "ptat_st2", "ptat_st3",
                                  "dist_st1", "dist_st2_0", "dist_st2_1")},
                     log=lambda *a: None)
    assert res["converged"] is False
    bench.close_all()


def test_main_verify_fake_runs(tmp_path):
    from cloudchaser.bias_match import SIVERS_COLUMNS, main

    out = tmp_path / "verify.csv"
    rc = main(["verify", "--fake", "--config", str(CONFIG), "--csv", str(out),
               "--ambient-c", "25.0", "--vdd", "4.0,3.6",
               "--freqs", "27.5,28.0"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    header = [ln for ln in text.splitlines() if not ln.startswith("#")][0]
    assert header == ",".join(SIVERS_COLUMNS)
    # 2 VDD x 2 freq = 4 data rows
    data = [ln for ln in text.splitlines()
            if not ln.startswith("#") and not ln.startswith("measurement_name")]
    assert len(data) == 4
    for ln in data:
        assert len(ln.split(",")) == len(SIVERS_COLUMNS)
    # VDD 열은 요청한 두 전압을 순서대로 담는다(각 전압당 2 주파수).
    vdd_col = SIVERS_COLUMNS.index("VDD_FE1[V]")
    assert [ln.split(",")[vdd_col] for ln in data] == ["4.0", "4.0", "3.6", "3.6"]
    # Gain 은 SG 레벨 기준으로 계산되므로 메타에 그 값이 남아 있어야 한다.
    assert "# sg_level_dbm=" in text


def test_sivers_columns_match_reference_file():
    """레퍼런스 CSV 에 실제로 있는 컬럼 이름만 쓴다(오탈자 방지)."""
    from cloudchaser.bias_match import SIVERS_COLUMNS

    ref = (Path(__file__).resolve().parents[1] / "reference"
           / "Stampede_T582616915_25_Aug_26_09_30_19.csv")
    if not ref.exists():
        import pytest
        pytest.skip("reference CSV not present")
    head = ref.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    for col in SIVERS_COLUMNS:
        assert col in head, col


def test_screen_dist_grid_keeps_only_in_window():
    from cloudchaser.bias_match import (
        beam_index, load_bias_match_cfg, screen_dist_grid,
    )

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_synthetic_rails(bench, fh, row, bidx)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0

    # step=16 그리드(0/16/32/48)에서 합성 모델이 낼 수 있는 값은 64.4 에서 최소
    # 2.0 mA 떨어져 있다 -> window 2.0 은 부동소수 경계라 불안정하다. 4.0 으로 잡는다.
    grid = list(range(0, 64, 16))
    kept = screen_dist_grid(bench, fh, beam_idx=bidx, cfg=cfg,
                            target_ma=77.6, window_ma=4.0,
                            axes=[grid, grid, grid], log=lambda *a: None)
    assert kept, "expected at least one in-window combination"
    for codes, rails in kept:
        assert abs(rails["DIST_1V8"] - 77.6) <= 4.0
        assert all(0 <= c <= 63 for c in codes)
        # DIST 를 고르려면 딸려오는 FE 전류도 같이 봐야 하므로 전 레일이 남아야 한다.
        assert {"FE1_4V0", "FE2_1V8", "FE3_1V8"} <= rails.keys()
    # 합성 모델은 0.9*c0 + 0.5*c1 + 0.5*c2 이므로 직접 재계산과 일치해야 한다.
    for codes, rails in kept:
        assert abs(rails["DIST_1V8"] - (13.2 + 0.9 * codes[0]
                                       + 0.5 * codes[1]
                                       + 0.5 * codes[2])) < 1e-6
    bench.close_all()


def test_main_dist_gain_fake_runs(tmp_path):
    """fake PSU 는 모든 레일이 50 mA 이므로, --target-ma 50 + window 20 이면 창에 든다.

    창이 좁으면 in-window 조합이 하나도 없어 RF 분기가 통째로 스킵된다 --
    그러면 rf_output/sa.configure/measure_peak_dbm/최적점 선택이 전혀
    검증되지 않는다. bench.toml 에는 지금 DIST_1V8 타깃이 없으므로(대응 미확정)
    --target-ma 로 준다.
    """
    from cloudchaser.bias_match import main

    out = tmp_path / "distgain.csv"
    rc = main(["dist-gain", "--fake", "--config", str(CONFIG),
               "--csv", str(out), "--ambient-c", "25.0", "--grid-step", "32",
               "--target-ma", "50", "--window-ma", "20",
               "--sg-level-dbm", "-28"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    # 컬럼 순서: 코드 3개 -> Gain -> (op1db 모드면 OP1dB/IP1dB, 아니면 Pout) -> 레일들
    assert lines[0].startswith("dist_st1,dist_st2_0,dist_st2_1,"
                               "Gain_dB,Pout_dBm,")
    for rail in ("FE1_4V0_mA", "DIST_1V8_mA", "IO_ANA_1V8_mA"):
        assert rail in lines[0]
    data = [ln.split(",") for ln in lines[1:]]
    assert len(data) == 8            # step 32 -> 코드 {0,32} 의 3중 곱 = 8 조합
    head = lines[0].split(",")
    for r in data:
        assert len(r) == len(head)
        assert all(int(c) in (0, 32) for c in r[:3])
        # 컬럼은 이름으로 찾는다 -- 레일 컬럼이 늘어도 깨지지 않게.
        pout = float(r[head.index("Pout_dBm")])
        gain = float(r[head.index("Gain_dB")])
        assert gain == pout - (-28.0)                    # Gain = Pout - SG level
        for rail in ("FE1_4V0_mA", "DIST_1V8_mA"):
            assert float(r[head.index(rail)]) == 50.0    # fake PSU 전류


def test_dist_gain_without_a_target_reports_instead_of_guessing(tmp_path):
    """DIST 레일 타깃이 없고 --target-ma 도 없으면 조용히 추측하지 말고 알리고 끝낸다.

    bench.toml 에는 2026-09-03 재배선 이후 DIST_1V8 = 64.4 타깃이 있으므로, 여기서는
    그 줄만 지운 임시 config 로 '타깃 없음' 경로를 확인한다.
    """
    from cloudchaser.bias_match import main

    cfg_txt = CONFIG.read_text(encoding="utf-8").replace(", DIST_1V8 = 64.4", "")
    assert "DIST_1V8 = 64.4" not in cfg_txt
    no_target = tmp_path / "bench_no_dist_target.toml"
    no_target.write_text(cfg_txt, encoding="utf-8")

    rc = main(["dist-gain", "--fake", "--config", str(no_target),
               "--csv", str(tmp_path / "x.csv")])
    assert rc == 1


def test_dist_knobs_target_the_rail_they_actually_drive():
    """DIST knob 의 담당 레일은 DIST_1V8 이다(이 EVB 는 분배망이 1.8V 에 물림).

    2026-09-02 실측: DIST 코드가 DIST_1V8 을 0.26~0.41 mA/code 로 움직이는 반면
    IO_ANA_1V8(VDD_IO, SPI 버퍼)는 0.002 mA/code = 노이즈였다.
    """
    from cloudchaser.bias_match import DIST_KNOBS, DIST_RAIL, FE_KNOBS

    assert DIST_RAIL == "DIST_1V8"
    assert {k.rail for k in DIST_KNOBS} == {"DIST_1V8"}
    assert [k.rail for k in FE_KNOBS] == ["FE1_4V0", "FE2_1V8", "FE3_1V8"]


def test_verify_applies_the_codes_it_is_given(tmp_path):
    """--ptat/--dist 가 bring-up 기본값을 덮어써야 한다.

    이게 없으면 verify 는 solve 가 찾은 코드가 아니라 v4 Casper(15/45/55)로
    측정한다 -- 매칭 전 바이어스를 재는 셈이라 비교가 무의미해진다.
    """
    from cloudchaser.bias_match import main

    out = tmp_path / "verify.csv"
    rc = main(["verify", "--fake", "--config", str(CONFIG), "--csv", str(out),
               "--ptat", "18,55,61", "--dist", "50,13,13",
               "--vdd", "4.0", "--freqs", "27.5"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "# ptat_override=18,55,61" in text   # 어떤 코드로 잰 CSV 인지 남는다
    assert "# dist_override=50,13,13" in text


def test_code_override_rejects_bad_input():
    import pytest

    from cloudchaser.bias_match import DIST_KNOBS, FE_KNOBS, _codes_arg

    assert _codes_arg("18,55,61", FE_KNOBS, "ptat") == [18, 55, 61]
    with pytest.raises(ValueError, match="needs 3"):
        _codes_arg("18,55", FE_KNOBS, "ptat")
    with pytest.raises(ValueError, match="out of range"):
        _codes_arg("18,55,64", DIST_KNOBS, "dist")


def test_verify_skips_frequencies_above_the_sa_limit(tmp_path, capsys):
    """SA 상한(30 GHz) 위 점은 잡음바닥을 -40 dB 게인으로 기록할 뿐이라 건너뛴다."""
    from cloudchaser.bias_match import main

    out = tmp_path / "verify.csv"
    rc = main(["verify", "--fake", "--config", str(CONFIG), "--csv", str(out),
               "--vdd", "4.0", "--freqs", "29.0,29.5,30.0,30.5,31.0"])
    assert rc == 0
    assert "skipping 3 point(s) above the SA limit" in capsys.readouterr().out
    data = [ln for ln in out.read_text(encoding="utf-8").splitlines()
            if not ln.startswith("#") and not ln.startswith("measurement_name")]
    assert len(data) == 2          # 29.0 과 29.5 만 남는다


def test_dist_axis_codes_supports_a_one_dimensional_sweep():
    """--st1/--st2-0/--st2-1 로 한 축만 훑을 수 있어야 한다.

    코너 스캔만으로는 게인이 -38 ~ +29 dB 로 튀는 구간의 중간을 못 본다.
    전류와 게인을 동시에 맞추려면 그 사이를 훑어야 한다.
    """
    import argparse
    import pytest

    from cloudchaser.bias_match import dist_axis_codes

    a = argparse.Namespace(grid_step=16, st1="63", st2_0="0,16,32,48,63",
                           st2_1="0")
    assert dist_axis_codes(a) == [[63], [0, 16, 32, 48, 63], [0]]

    # 주지 않은 축은 --grid-step 격자를 쓴다.
    b = argparse.Namespace(grid_step=32, st1=None, st2_0=None, st2_1="7")
    assert dist_axis_codes(b) == [[0, 32], [0, 32], [7]]

    with pytest.raises(ValueError, match="out of range"):
        dist_axis_codes(argparse.Namespace(grid_step=16, st1="64",
                                           st2_0=None, st2_1=None))


def test_dist_gain_reads_currents_with_rf_on(tmp_path, monkeypatch):
    """dist-gain 의 전류는 RF 를 건 상태에서 다시 읽어야 한다.

    스크리닝은 RF OFF 정지전류를 잰다. 그 값을 그대로 CSV 에 실으면 DIST 를 올릴 때
    따라 오르는 PA 전류가 안 보인다 -- 실측으로 (63,63,0) 에서 FE1 이 RF OFF 26.8 mA,
    RF ON 31.3 mA 였다. Sivers 레퍼런스도 구동 상태 값이라 그쪽에 맞춰야 한다.
    """
    import cloudchaser.bias_match as bm

    calls = {"rf_on": False, "after_rf": 0}
    real_read = bm.read_rails_ma

    def counting_read(bench, **kw):
        if calls["rf_on"]:
            calls["after_rf"] += 1
        return real_read(bench, **kw)

    monkeypatch.setattr(bm, "read_rails_ma", counting_read)

    real_open = bm.open_bench

    def open_and_hook(args):
        got = real_open(args)
        bench = got[0]
        real_rf = bench.sg.rf_output

        def rf(on, *a, **k):
            calls["rf_on"] = bool(on)
            return real_rf(on, *a, **k)

        bench.sg.rf_output = rf
        return got

    monkeypatch.setattr(bm, "open_bench", open_and_hook)

    rc = bm.main(["dist-gain", "--fake", "--config", str(CONFIG),
                  "--csv", str(tmp_path / "dg.csv"), "--target-ma", "50",
                  "--window-ma", "20", "--st1", "0,63", "--st2-0", "0",
                  "--st2-1", "0"])
    assert rc == 0
    # 2개 조합 -> RF ON 상태에서 조합당 한 번씩 다시 읽어야 한다.
    assert calls["after_rf"] >= 2


def test_gain_sensitivity_finds_the_steep_and_flat_points():
    """같은 게인이라도 급경사에 앉은 점과 평탄한 점을 구분할 수 있어야 한다.

    실측(2026-09-02, st1=63 고정)에서 st2_0=16 은 0.65 dB/code 로 가파르고
    st2_0=40 근처는 0.13 dB/code 로 평탄했다. 드리프트에 대한 민감도가 5배 다르다.
    """
    from cloudchaser.bias_match import gain_sensitivity

    pts = [((63, c, 0), g) for c, g in
           [(8, 17.93), (16, 23.10), (24, 25.36), (32, 26.80), (40, 27.83)]]
    sens = gain_sensitivity(pts)
    # 16 은 8~24 중앙차분 -> (25.36-17.93)/16 = 0.464
    assert abs(sens[(63, 16, 0)] - 0.464) < 0.01
    # 32 는 24~40 -> (27.83-25.36)/16 = 0.154
    assert abs(sens[(63, 32, 0)] - 0.154) < 0.01
    assert sens[(63, 16, 0)] > 3 * sens[(63, 32, 0)]
    # 이웃이 한쪽뿐인 끝점도 전방/후방 차분으로 값을 낸다.
    assert sens[(63, 8, 0)] is not None


def test_gain_sensitivity_handles_an_isolated_point():
    from cloudchaser.bias_match import gain_sensitivity

    assert gain_sensitivity([((1, 2, 3), 10.0)]) == {(1, 2, 3): None}


def test_solve_rf_turns_the_signal_generator_on_and_off(tmp_path, monkeypatch):
    """--rf 는 RF 를 켠 채로 풀고, 끝나면(예외가 나도) 반드시 끈다.

    레퍼런스 전류는 구동 상태 값이라 정지전류로 맞추면 어긋난다 -- 실측으로
    dist (63,16,0) 에서 FE1 이 RF OFF 26.8 mA vs RF ON 29.1 mA 였다.
    """
    import cloudchaser.bias_match as bm

    seen = []
    real_open = bm.open_bench

    def open_and_hook(args):
        got = real_open(args)
        bench = got[0]
        real_rf = bench.sg.rf_output

        def rf(on, *a, **k):
            seen.append(bool(on))
            return real_rf(on, *a, **k)

        bench.sg.rf_output = rf
        return got

    monkeypatch.setattr(bm, "open_bench", open_and_hook)
    rc = bm.main(["solve", "--rf", "--fake", "--config", str(CONFIG),
                  "--csv", str(tmp_path / "s.csv")])
    assert rc == 0
    assert seen[0] is True            # 풀기 전에 켜고
    assert seen[-1] is False          # 끝나면 끈다


def test_solve_without_rf_leaves_the_generator_alone(tmp_path, monkeypatch):
    import cloudchaser.bias_match as bm

    seen = []
    real_open = bm.open_bench

    def open_and_hook(args):
        got = real_open(args)
        bench = got[0]
        bench.sg.rf_output = lambda on, *a, **k: seen.append(bool(on))
        return got

    monkeypatch.setattr(bm, "open_bench", open_and_hook)
    assert bm.main(["solve", "--fake", "--config", str(CONFIG),
                    "--csv", str(tmp_path / "s.csv")]) == 0
    assert seen == []


def test_dist_gain_op1db_mode_reports_compression(tmp_path):
    """--op1db 는 조합마다 전력 스윕을 돌려 소신호 게인과 OP1dB 를 같이 낸다.

    소신호 한 점만 재면 "게인은 맞는데 출력이 안 나오는" 조합을 구분할 수 없다.
    실측(2026-09-02)에서 게인 23.17 dB 인데 OP1dB 가 17.33 dBm 으로 스펙(19.5)에
    못 미쳤고, 그걸 조합별로 비교하려면 압축점이 필요했다.
    """
    from cloudchaser.bias_match import main

    out = tmp_path / "dg.csv"
    rc = main(["dist-gain", "--op1db", "--fake", "--config", str(CONFIG),
               "--csv", str(out), "--target-ma", "50", "--window-ma", "20",
               "--st1", "63", "--st2-0", "16", "--st2-1", "0,8",
               "--pin-start-dbm", "-16", "--pin-stop-dbm", "-8",
               "--gain-target-db", "23.1", "--gain-tol-db", "1.0"])
    assert rc == 0
    head = out.read_text(encoding="utf-8").splitlines()
    cols = [ln for ln in head if not ln.startswith("#")][0].split(",")
    assert "Gain_dB" in cols and "OP1dB_dBm" in cols and "IP1dB_dBm" in cols
    assert "Pout_dBm" not in cols          # op1db 모드에선 단일 Pout 이 의미 없다
    # 스윕 원본이 별도 파일로 남아야 압축 시작 지점을 볼 수 있다.
    sweep = out.with_name(out.stem + "_sweep" + out.suffix)
    assert sweep.exists()
    scols = [ln for ln in sweep.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("#")][0].split(",")
    for c in ("SG_dBm", "Pin_dBm", "Pout_dBm", "Gain_dB", "dist_st1"):
        assert c in scols
    # Pin -16..-8 step 1 = 9점 x 2조합 = 18행
    sdata = [ln for ln in sweep.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("#") and not ln.startswith("dist_st1")]
    assert len(sdata) == 18


def test_dist_gain_op1db_raises_the_sa_reference_level(tmp_path, capsys):
    """압축까지 밀면 Pout 이 20 dBm 근처라, 소신호용 ref level 이면 SA 가 클리핑한다."""
    from cloudchaser.bias_match import main

    rc = main(["dist-gain", "--op1db", "--fake", "--config", str(CONFIG),
               "--csv", str(tmp_path / "dg.csv"), "--target-ma", "50",
               "--window-ma", "20", "--st1", "63", "--st2-0", "16",
               "--st2-1", "0", "--sa-ref-dbm", "10",
               "--pin-start-dbm", "-16", "--pin-stop-dbm", "-12"])
    assert rc == 0
    assert "SA ref level -> 25.0 dBm" in capsys.readouterr().out


# ---------------------------------------------------------------------
# refine_knob -- 이분탐색 뒤의 국소 보정
# ---------------------------------------------------------------------
# 2026-09-04 v1 실측. 타깃 27.8 은 코드 13(-0.51)이 최선인데 실행은 12(-1.20)를
# 골랐다. 13->14 에서 3.3 mA 가 한 번에 뛰어(다른 구간은 0.4~0.7) 읽기가 조금만
# 흔들려도 12/13 순위가 뒤집히는 구간이다.
_V1_FE1 = {11: 26.19, 12: 26.60, 13: 27.29, 14: 30.62}


def _install_table_rail(bench, fh, row, beam_idx, table, *, default=0.0):
    """ptat_st1 코드 -> FE1 전류를 표로 주는 합성 레일."""
    def read_all_vi():
        code = fh.get_fe_bias()[row][0]
        ma = table.get(code, default if code not in table else 0.0)
        if code not in table:
            # 표 밖은 양끝으로 외삽(단조 가정) -- 탐색이 표 밖을 짚어도 죽지 않게.
            lo, hi = min(table), max(table)
            ma = table[lo] - (lo - code) if code < lo else table[hi] + (code - hi)
        return {
            "FE1_4V0": {"v": 4.0, "i": ma / 1000.0},
            "FE2_1V8": {"v": 1.8, "i": 18.35 / 1000.0},
            "FE3_1V8": {"v": 1.8, "i": 10.37 / 1000.0},
            "IO_ANA_1V8": {"v": 1.8, "i": 0.65 / 1000.0},
            "DIST_1V8": {"v": 1.8, "i": 40.0 / 1000.0},
            "CORE_1V0": {"v": 1.0, "i": 3.2 / 1000.0},
        }
    bench.read_all_vi = read_all_vi


def _refine_setup(table=None):
    from cloudchaser.bias_match import beam_index, load_bias_match_cfg

    bench, chip = _bench_chip_brought_up()
    fh = _fh_of(chip)
    row, bidx = 0, beam_index("b0")
    _install_table_rail(bench, fh, row, bidx, table or _V1_FE1)
    cfg = load_bias_match_cfg(CONFIG)
    cfg.settle_s = 0.0
    return bench, fh, row, bidx, cfg


def test_refine_moves_to_the_better_neighbour():
    """이분탐색이 한 칸 못 미쳐 멈춘 경우를 바로잡는다(v1 실측 재현)."""
    from cloudchaser.bias_match import FE_KNOBS, read_knob, refine_knob

    bench, fh, row, bidx, cfg = _refine_setup()
    code, cur, err = refine_knob(bench, fh, FE_KNOBS[0], 27.8, row=row,
                                 beam_idx=bidx, cfg=cfg, start=12,
                                 log=lambda *a: None)
    assert code == 13
    assert abs(cur - 27.29) < 1e-6
    assert abs(err) < 0.52
    # 찾은 코드가 칩에 남아 있어야 한다.
    assert read_knob(fh, FE_KNOBS[0], row=row, beam_idx=bidx) == 13
    bench.close_all()


def test_refine_leaves_an_already_optimal_code_alone():
    from cloudchaser.bias_match import FE_KNOBS, read_knob, refine_knob

    bench, fh, row, bidx, cfg = _refine_setup()
    code, _cur, _err = refine_knob(bench, fh, FE_KNOBS[0], 27.8, row=row,
                                   beam_idx=bidx, cfg=cfg, start=13,
                                   log=lambda *a: None)
    assert code == 13
    assert read_knob(fh, FE_KNOBS[0], row=row, beam_idx=bidx) == 13
    bench.close_all()


def test_refine_walks_several_codes_but_stops_at_max_steps():
    """이웃이 계속 이기면 그 방향으로 가되, 상한을 넘지 않는다."""
    from cloudchaser.bias_match import FE_KNOBS, refine_knob

    # 20 에서 30 까지 1 mA/code 로 오르는 표. 타깃 30 -> 최적은 코드 30.
    table = {c: 20.0 + (c - 20) for c in range(20, 41)}
    bench, fh, row, bidx, cfg = _refine_setup(table)
    code, _cur, _err = refine_knob(bench, fh, FE_KNOBS[0], 30.0, row=row,
                                   beam_idx=bidx, cfg=cfg, start=20,
                                   max_steps=4, log=lambda *a: None)
    assert code == 24            # 20 에서 4칸까지만
    bench.close_all()


def test_refine_stays_inside_the_code_range():
    from cloudchaser.bias_match import FE_KNOBS, refine_knob

    # 코드가 낮을수록 타깃에 가깝다 -> 0 아래로 내려가려 한다.
    table = {c: 20.0 + c for c in range(0, 64)}
    bench, fh, row, bidx, cfg = _refine_setup(table)
    code, _cur, _err = refine_knob(bench, fh, FE_KNOBS[0], 5.0, row=row,
                                   beam_idx=bidx, cfg=cfg, start=1,
                                   log=lambda *a: None)
    assert code == 0
    bench.close_all()


def test_refine_disabled_by_zero_steps():
    from cloudchaser.bias_match import FE_KNOBS, refine_knob

    bench, fh, row, bidx, cfg = _refine_setup()
    code, _cur, _err = refine_knob(bench, fh, FE_KNOBS[0], 27.8, row=row,
                                   beam_idx=bidx, cfg=cfg, start=12,
                                   max_steps=0, log=lambda *a: None)
    assert code == 12
    bench.close_all()
