"""RX(Blueway) bring-up 필드 매핑 오프라인 테스트.

과거엔 Blueway 벤더 필드 API(`chip.fields.wr(f"ch{i}_{pol}_fe_attn", ...)` 등)로
채널 게인을 잡았다. `bring_up_rx` 가 raw 레지스터 엔진(`FH`)으로 재작성되면서
(스펙 4장 RX 10단계 표) 검증 대상도 필드명이 아니라 레지스터 주소/바이트로
옮긴다. **테스트 이름과 "무엇을 지키려는가"는 그대로 유지한다** -- 필드명이
레지스터로 바뀐 것뿐이고 회귀 방지 취지는 같다.

의도적으로 사라진 동작: 예전엔 `cfg.ch_fe_attn` 값이 그대로 FE 게인 필드에
기입됐다(`ch{i}_{pol}_fe_attn`). 새 RX 10단계 시퀀스엔 FE gain 기입 단계가
없다 -- evb_full.py 도 그 필드를 안 쓴다. 그래서 `ch_fe_attn` 은 이제
'무시되는 knob'이 됐고, `bring_up_rx` 가 로그만 남긴다(Ruling 10 블록;
`tests/test_bringup_golden.py::test_rx_ignored_knobs_are_reported` 가 그
로그를 검증한다). 이 파일의 `test_rx_ch_fe_attn_no_longer_reaches_fe_gain_register`
가 그 동작 변경을 레지스터 레벨에서 고정한다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
CONFIG_RX = Path(__file__).resolve().parents[1] / "config" / "bench_rx.toml"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_rx_bringup_uses_fe_attn_no_warnings():
    """RX bring-up 이 (필드가 아니라) FE_GAIN_ADDR 레지스터로 채널 게인을 표현한다.

    예전엔 벤더 필드명이 틀리면 '[warn ... field ...]' 로그가 났다(필드명 오타
    회귀 방지 목적). raw 시퀀스는 필드 API 를 아예 쓰지 않으므로 그 경고 자체가
    발생할 수 없다 -- 그래서 여기선 (1) bring-up 이 필드 경고 없이 끝나고
    (2) summary 가 여전히 fe_attn 키(atten 아님, TX 의 gain/atten 과 다름)를
    쓰는지로 같은 취지(채널 레벨 = FE 감쇠, gain_control 아님)를 지킨다.
    """
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_rx, make_chip_rx

    B = Bench.from_toml(CONFIG_RX, fake=True)
    C = make_chip_rx(B.board, fake=True)
    logs: list[str] = []
    summary = bring_up_rx(C, B.board, require_version=False, log=logs.append)

    # 필드명 관련 경고가 날 수 있는 경로 자체가 없어졌다(raw 레지스터만 쓴다).
    field_warns = [l for l in logs if "[warn" in l and "field" in l]
    assert not field_warns, f"unexpected field warnings: {field_warns}"

    # readback 요약은 gain 이 아니라 fe_attn 키를 가져야 한다(bench_rx.toml 의
    # active_channels[0] = "h1").
    h1 = summary["channels"]["h1"]
    assert "fe_attn" in h1 and "gain" not in h1
    # FE_GAIN_ADDR(0x1018) 는 bring_up_rx 가 스스로 기입하지 않는다(스펙 4장
    # RX 표에 단계 없음) -- fake SPI 는 미기입 레지스터를 0 으로 돌려주므로
    # 기본값은 여전히 0x0(무감쇠=최대 게인)이다.
    assert h1["fe_attn"] == 0x0


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_rx_config_has_ch_fe_attn():
    from cloudchaser.bench import Bench

    B = Bench.from_toml(CONFIG_RX, fake=True)
    # RX config 는 (TX 잔재인) ch_gain 대신 ch_fe_attn 을 제공한다
    assert B.board.ch_fe_attn == {"h0": 0, "h1": 0, "h2": 0, "h3": 0}


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_rx_ch_fe_attn_no_longer_reaches_fe_gain_register():
    """의도적 동작 변경의 회귀 문서화.

    예전: cfg.ch_fe_attn 값이 `chip.fields.wr(f"ch{i}_{pol}_fe_attn", v)` 로 그대로
    기입됐다(FE_GAIN_ADDR 의 H/V 바이트).
    지금: 스펙 4장 RX 10단계 표에 FE gain 기입 단계가 없다(evb_full.py 도 안 쓴다)
    -- ch_fe_attn 은 무시되는 knob 이 됐다. 값을 바꿔도 FE_GAIN_ADDR(0x1018) 의
    해당 바이트가 그대로(0)인지로 그 사실을 고정한다.
    """
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_rx, make_chip_rx
    from cloudchaser.board.firehawk import FE_GAIN_ADDR

    B = Bench.from_toml(CONFIG_RX, fake=True)
    B.board.ch_fe_attn = {"h1": 0xB}          # 예전 같으면 0x1019 의 H 바이트에 실렸을 값
    C = make_chip_rx(B.board, fake=True)
    bring_up_rx(C, B.board, require_version=False, log=lambda *_a: None)

    fh = C._fh
    ci = 1  # active_channels[0] = "h1" -> channel index 1
    assert fh.rd(FE_GAIN_ADDR + ci) & 0xFF == 0x0   # ch_fe_attn=0xB 가 반영되지 않는다
