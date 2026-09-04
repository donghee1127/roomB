"""경로 손실 -> 계측기 오프셋 적용(Bench.apply_path_loss) 오프라인 테스트.

손실은 per-point 계산이 아니라 SG/SA 오프셋으로 '계측기에' 적용된다:
  - SG level offset = -(in_loss)  -> set_level(P) 가 칩 입력 P 를 의미(출력은 P+in_loss)
  - SA ref level offset = +out_loss -> 읽기 = 칩 출력
이 부호/매핑과 수동 override(set_loss) 우선순위를 고정한다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "bench.toml"


def _bench(monkeypatch, in_loss, out_loss):
    import cloudchaser.bench as bench_mod
    from cloudchaser.bench import Bench
    monkeypatch.setattr(bench_mod, "get_loss", lambda f, log=None: (in_loss, out_loss))
    B = Bench.from_toml(CONFIG, fake=True)
    B.connect_all(log=lambda *_a: None)
    sg_cmds: list[str] = []
    sa_cmds: list[str] = []
    B.sg.write = lambda c: sg_cmds.append(c)   # type: ignore[assignment]
    B.sa.write = lambda c: sa_cmds.append(c)   # type: ignore[assignment]
    return B, sg_cmds, sa_cmds


def test_offsets_sign(monkeypatch):
    B, sg_cmds, sa_cmds = _bench(monkeypatch, 5.0, 3.0)
    in_loss, out_loss = B.apply_path_loss(28e9, log=lambda *_a: None)
    assert (in_loss, out_loss) == (5.0, 3.0)
    # SG offset = -(in_loss)
    assert f"SOUR:POW:OFFS {-in_loss:.2f}" in sg_cmds
    # SA offset = +out_loss
    assert f"DISP:WIND:TRAC:Y:SCAL:RLEV:OFFS {out_loss:.2f}" in sa_cmds


def test_channel_kwarg_ignored(monkeypatch):
    # channel= 은 하위호환용으로 받기만 하고 값에 영향 없음.
    B, _sg, _sa = _bench(monkeypatch, 5.0, 3.0)
    a = B.apply_path_loss(28e9, channel="h0", log=lambda *_a: None)
    b = B.apply_path_loss(28e9, channel="v3", log=lambda *_a: None)
    assert a == b == (5.0, 3.0)


def test_manual_override_wins_and_clears(monkeypatch):
    B, _sg, _sa = _bench(monkeypatch, 5.0, 3.0)
    B.set_loss_override(9.0, 1.0)
    assert B.apply_path_loss(28e9, log=lambda *_a: None) == (9.0, 1.0)
    B.clear_loss_override()
    assert B.apply_path_loss(28e9, log=lambda *_a: None) == (5.0, 3.0)


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_op1db_pin_equals_command_no_perpoint_math(monkeypatch):
    """오프셋 적용 후 op1db 의 Pin = 명령 레벨(per-point in_loss 빼기 없음)."""
    import cloudchaser.bench as bench_mod
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_tx, make_chip
    from cloudchaser.test_items import TestContext, get_test

    monkeypatch.setattr(bench_mod, "get_loss", lambda f, log=None: (2.0, 1.0))
    B = Bench.from_toml(CONFIG, fake=True)
    B.chip_kind = "tx"
    B.connect_all(log=lambda *_a: None)
    C = make_chip(B.board, fake=True)
    bring_up_tx(C, B.board, require_version=False, log=lambda *_a: None)
    test = get_test("op1db")()
    res = test.run(TestContext(bench=B, chip=C, fake=True),
                   test.resolve({"pin_start_dbm": -5.0, "pin_stop_dbm": -3.0,
                                 "freq_hz": 28e9}), log=lambda *_a: None)
    assert res.columns[:2] == ["SG_dBm", "Pin_dBm"]
    for row in res.rows:
        assert row[0] == row[1]   # SG 명령 == Pin
    assert "in_loss_db" not in test.defaults()
