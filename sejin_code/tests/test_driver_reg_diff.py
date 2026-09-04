"""driver_reg_diff 의 오프라인(fake) 스모크 테스트.

필드 열거/매핑/diff 구조를 확인한다. (fake 레지스터 값은 shadow 기본값이라
'전부 동일'로 나오는 것까지만 검증.)
"""

from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def _fake_chip():
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import make_chip

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    chip = make_chip(bench.board, fake=True)
    chip.init()
    return bench, chip


def test_field_enumeration_and_belongs():
    from cloudchaser.driver_reg_diff import _all_field_names, _belongs, _to_ref

    _, chip = _fake_chip()
    names = _all_field_names(chip)
    assert "ch0_bias_en" in names and "d2a_ch0_h_ptat_st2" in names
    # h0 소유 필드: h 편파 + 채널공용, v 편파는 제외.
    assert _belongs("d2a_ch0_h_ptat_st2", 0, "h")
    assert _belongs("ch0_bias_en", 0, "h")
    assert not _belongs("ch0_v_pwrdn", 0, "h")
    assert not _belongs("d2a_ch1_h_ptat_st2", 0, "h")
    # 매핑: 채널 토큰만 치환.
    assert _to_ref("d2a_ch0_h_ptat_st2", 0, 1) == "d2a_ch1_h_ptat_st2"
    assert _to_ref("ch0_bias_en", 0, 1) == "ch1_bias_en"


def test_diff_channel_structure():
    from cloudchaser.driver_reg_diff import diff_channel

    _, chip = _fake_chip()
    res = diff_channel(chip, "h1", "h0")
    assert res["n_compared"] > 0
    assert res["n_diff"] == 0                      # fake: 전부 기본값 -> 동일
    assert any("st2 DRV" in r["label"] for r in res["key_rows"])
    for r in res["key_rows"]:
        assert r["same"] is True


def test_snapshot_read_injection():
    from cloudchaser.driver_reg_diff import diff_channel, snapshot_fields

    _, chip = _fake_chip()
    snap = snapshot_fields(chip)
    assert "d2a_ch0_h_ptat_st2" in snap and "ch0_bias_en" in snap
    # 스냅샷(.get)으로 읽어도 라이브와 동일 구조/결과(fake: 전부 동일).
    res = diff_channel(chip, "h1", "h0", read=snap.get)
    assert res["n_compared"] > 0
    assert res["n_diff"] == 0


def test_main_fake_runs():
    from cloudchaser.driver_reg_diff import main

    rc = main(["--fake", "--no-power", "--good", "h1,v1", "--bad", "h0,v0"])
    assert rc == 0
