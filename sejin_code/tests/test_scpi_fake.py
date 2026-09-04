"""오프라인(fake) 테스트 — 하드웨어/계측기 없이 SCPI 동작 검증.

sivers_api 에 의존하지 않는다 (계측기 레이어만 검증).
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import pytest

from cloudchaser.bench import Bench
from cloudchaser.instruments import E36313A, FSVA3030, MS4644B, Rail, SMW200A
from cloudchaser.instruments.scpi import ScpiError
from cloudchaser.instruments.vna_ms4644b import _parse_block_ascii


def make_psu() -> E36313A:
    rails = [
        Rail(ch=1, name="A", v_target=4.0, i_limit=0.5, ovp=4.5),
        Rail(ch=2, name="B", v_target=1.0, i_limit=1.0, ovp=1.3),
        Rail(ch=3, name="C", v_target=1.8, i_limit=0.5, ovp=2.1),
    ]
    return E36313A("0.0.0.0", rails, fake=True).connect()


def test_chanlist_parsing():
    assert E36313A._chanlist("MEAS:VOLT? (@1,2,3)") == [1, 2, 3]
    assert E36313A._chanlist("MEAS:VOLT? (@1:3)") == [1, 2, 3]
    assert E36313A._chanlist("VOLT 1.0,(@2)") == [2]
    assert E36313A._chanlist("no channel list") == []


def test_apply_protection_commands():
    psu = make_psu()
    psu.apply_protection()
    h = psu.history
    assert "CURR 0.5,(@1)" in h
    assert "VOLT:PROT 4.5,(@1)" in h
    assert "CURR 1.0,(@2)" in h


def test_ramp_reaches_target_without_trip():
    psu = make_psu()
    psu.apply_protection()
    psu.ramp_rail("A", step_v=1.0, settle_s=0.0)
    # 마지막 인가 전압이 목표여야 함
    assert psu._set_v[1] == 4.0
    # 출력 ON 명령이 있어야 함
    assert "OUTP ON,(@1)" in psu.history


def test_ramp_reaches_non_divisible_target():
    # 1.3V 목표 / 0.2V 스텝: round(6.5)=6 이면 1.2V 에서 멈추는 버그 → ceil 로 1.3V 도달
    rails = [Rail(ch=1, name="IO", v_target=1.3, i_limit=0.5, ovp=1.6)]
    psu = E36313A("0.0.0.0", rails, fake=True).connect()
    psu.apply_protection()
    psu.ramp_rail("IO", step_v=0.2, settle_s=0.0)
    assert abs(psu._set_v[1] - 1.3) < 1e-6


def test_read_vi_returns_set_voltages():
    psu = make_psu()
    psu.apply_protection()
    psu.ramp_rail("B", step_v=0.5, settle_s=0.0)
    vi = psu.read_vi()
    assert abs(vi["B"]["v"] - 1.0) < 1e-6
    assert vi["B"]["i"] > 0  # 전압 인가됐으니 fake 전류 > 0
    assert vi["A"]["v"] == 0.0  # 안 올린 레일은 0


def test_sg_configure_rf_off_by_default():
    sg = SMW200A("0.0.0.0", fake=True).connect()
    sg.configure(freq_hz=28e9, level_dbm=-30, rf_output=False)
    assert "SOUR:FREQ 28000000000" in sg.history
    assert "OUTP:STAT OFF" in sg.history


def test_sa_configure_commands():
    sa = FSVA3030("0.0.0.0", fake=True).connect()
    sa.configure(center_hz=28e9, span_hz=100e6, rbw_hz=1e6,
                 ref_level_dbm=0, input_atten_db=10)
    assert "SENS:FREQ:CENT 28000000000" in sa.history
    assert "SENS:BAND:RES 1000000" in sa.history


def test_query_float_or_nan():
    # 'NAN'/9.91E37(R&S 결과없음)은 nan, 정상 응답은 값으로.
    sa = FSVA3030("0.0.0.0", fake=True).connect()
    sa.query = lambda cmd: "NAN"
    assert math.isnan(sa.query_float_or_nan("X?"))
    sa.query = lambda cmd: "9.91E37"
    assert math.isnan(sa.query_float_or_nan("X?"))
    sa.query = lambda cmd: "-12.3 dBm"
    assert sa.query_float_or_nan("X?") == -12.3


def test_read_evm_db_percent_to_db():
    # FSVA 가 %로 주면 dB 변환, 이미 dB(<=0)면 그대로, NAN 은 nan.
    sa = FSVA3030("0.0.0.0", fake=True).connect()
    sa.query = lambda cmd: "1.34"
    assert abs(sa.read_evm_db() - 20.0 * math.log10(0.0134)) < 1e-6
    sa.query = lambda cmd: "-30.0"
    assert sa.read_evm_db() == -30.0
    sa.query = lambda cmd: "NAN"
    assert math.isnan(sa.read_evm_db())


def test_resync_noop_in_fake():
    # fake/미연결에서는 버릴 게 없으니 0 을 반환하고 예외도 없어야 한다.
    sa = FSVA3030("0.0.0.0", fake=True).connect()
    assert sa.resync() == 0


def test_sa_auto_adjust_safe_and_polls():
    # auto_evm/auto_level/measure_once 는 fake 에서 예외 없이 돌고,
    # 블로킹 *WAI 대신 폴링(INIT:CONT OFF + INIT:IMM)을 써야 한다.
    sa = FSVA3030("0.0.0.0", fake=True).connect()
    sa.auto_level()
    sa.auto_evm()
    sa.measure_once()
    assert "SENS:ADJ:EVM" in sa.history
    assert "INIT:IMM" in sa.history
    assert "INIT:IMM;*WAI" not in sa.history  # 블로킹 *WAI 제거 확인


def test_vna_block_parse():
    # IEEE-488.2 definite-length 헤더 + 평문 CSV 둘 다 파싱, 빈 응답은 빈 리스트.
    assert _parse_block_ascii("1.0,2.0,3.0") == [1.0, 2.0, 3.0]
    assert _parse_block_ascii("#212" + "1.0,2.0,3.0") == [1.0, 2.0, 3.0]
    assert _parse_block_ascii("") == []
    assert _parse_block_ascii("  \n") == []


def test_vna_block_parse_multiline_pairs():
    # VectorStar 실측 포맷: 'real, imag' 쌍이 줄바꿈으로 구분되어 온다.
    # 콤마만으로 split 하면 ' 4.005E-003\n 1.0E-3' 이 한 토큰이 되어 죽었다.
    s = " 5.031721E-004, 4.005447E-003\n 1.0E-3, -2.0E-3\n"
    assert _parse_block_ascii(s) == [5.031721e-4, 4.005447e-3, 1.0e-3, -2.0e-3]


def test_vna_fake_read_s21():
    vna = MS4644B("0.0.0.0", fake=True).connect()
    vna.setup_s21()
    freqs, gain, phase = vna.read_s21()
    assert len(freqs) == len(gain) == len(phase) == 11
    assert freqs[0] == 27.5e9 and freqs[-1] == 28.5e9
    assert all(abs(g - (-20.0)) < 0.01 for g in gain)  # |S|=0.1 -> -20 dB
    # 연속 sweep 간 phase 는 fake 스텝(2.8125도)만큼 돌아야 한다.
    _, _, phase2 = vna.read_s21()
    d = phase2[0] - phase[0]
    while d > 180:
        d -= 360
    while d < -180:
        d += 360
    assert abs(d - 2.8125) < 1e-6
    # 캘리브레이션 보호: 어떤 경로에서도 *RST/preset 을 보내면 안 된다.
    assert "*RST" not in vna.history
    assert not any("PRES" in c.upper() for c in vna.history)


def test_vna_read_sdata_rejects_odd_count():
    vna = MS4644B("0.0.0.0", fake=True).connect()
    vna.query_block = lambda cmd: "1.0,2.0,3.0"   # real/imag 쌍이 아님(홀수)
    with pytest.raises(ScpiError):
        vna.read_sdata()


def test_vna_read_freqs_rejects_implausible_point_count():
    # 실측 사고 재현: FREQ:DATA? 블록 쿼리가 타임아웃한 뒤 늦게 도착한 응답이
    # 버퍼에 남아 fallback 쿼리가 밀린 응답을 읽으면(desync) POIN? 이 주파수
    # 값을 돌려받는다 -> 수십억 포인트 linspace 를 만들다 MemoryError 가 났다.
    # 포인트 수가 비상식적이면 즉시 ScpiError 로 실패해야 한다.
    vna = MS4644B("0.0.0.0", fake=True).connect()

    def failing_block(cmd):
        raise ScpiError("timeout")

    def desynced_query(cmd):
        if "POIN" in cmd:
            return "21500000000"   # 21.5 GHz 주파수 값이 포인트 수 자리에
        return "17500000000"

    vna.query_block = failing_block
    vna.query = desynced_query
    with pytest.raises(ScpiError):
        vna.read_freqs()


def test_vna_read_freqs_resyncs_before_fallback():
    # 블록 쿼리 실패 후에는 반드시 resync(잔여 응답 폐기)를 거친 뒤 fallback
    # 쿼리(STAR?/STOP?/POIN?)를 보내야 desync 를 막을 수 있다.
    vna = MS4644B("0.0.0.0", fake=True).connect()
    calls: list[str] = []
    orig_query = vna.query

    def failing_block(cmd):
        calls.append(cmd)
        raise OSError("timed out")

    def recording_query(cmd):
        calls.append(cmd)
        return orig_query(cmd)

    vna.query_block = failing_block
    vna.query = recording_query
    vna.resync = lambda **kw: (calls.append("RESYNC"), 0)[1]
    freqs = vna.read_freqs()
    assert "RESYNC" in calls
    star = next(i for i, c in enumerate(calls) if "FREQ:STAR" in c)
    assert calls.index("RESYNC") < star
    assert len(freqs) == 11   # fake fallback: 11포인트 linspace


class _ScriptedSock:
    """query_block 검증용 가짜 소켓: 준비된 chunk 를 차례로 돌려준다."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, n: int) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        import socket as _socket
        raise _socket.timeout("no more scripted data")

    def settimeout(self, t) -> None:
        pass

    def close(self) -> None:
        pass


def test_vna_query_block_reads_past_newline_chunk_boundary():
    # 실측 사고 재현: VectorStar ASCII 트레이스는 여러 줄이라, 한 줄용 리더
    # (_read)는 chunk 가 \n 으로 끝나는 순간 응답을 잘라 먹었다. query_block 은
    # definite-length 헤더가 알려주는 길이까지 끝까지 읽어야 한다.
    vna = MS4644B("0.0.0.0", fake=False)
    # payload " 1.0, 2.0\n 3.0, 4.0" = 19 bytes -> header "#219"
    vna._sock = _ScriptedSock([b"#219 1.0, 2.0\n", b" 3.0, 4.0\n"])
    resp = vna.query_block(":CALC1:DATA:SDAT?")
    assert _parse_block_ascii(resp) == [1.0, 2.0, 3.0, 4.0]


def test_vna_query_block_headerless_reads_until_idle():
    # 헤더 없는 여러 줄 응답도 idle timeout 까지 전부 모아야 한다.
    vna = MS4644B("0.0.0.0", fake=False)
    vna._sock = _ScriptedSock([b" 1.0, 2.0\n", b" 3.0, 4.0\n"])
    resp = vna.query_block(":SENS1:FREQ:DATA?")
    assert _parse_block_ascii(resp) == [1.0, 2.0, 3.0, 4.0]


def test_bench_vna_optional(tmp_path: Path):
    # [vna] 섹션이 없으면 vna=None + get_vna 가 안내 에러, 있으면 lazy 핸들 제공.
    base = """
        [ramp]
        step_v = 1.0
        settle_s = 0.0
        power_up_order = ["A"]

        [psu1]
        host = "1.1.1.1"
        [[psu1.rails]]
        ch = 1
        name = "A"
        v_target = 1.0
        i_limit = 0.5
        ovp = 1.3

        [psu2]
        host = "2.2.2.2"
        [[psu2.rails]]
        ch = 1
        name = "B"
        v_target = 1.0
        i_limit = 0.5
        ovp = 1.3

        [sg]
        host = "3.3.3.3"
        freq_hz = 28.0e9
        level_dbm = -30.0

        [sa]
        center_hz = 28.0e9
        host = "4.4.4.4"
        span_hz = 100.0e6
        rbw_hz = 1.0e6
        ref_level_dbm = 0.0
        input_atten_db = 10.0

        [board]
        chip_id = 0
        beam = "b0"
        active_channels = ["h0"]
    """
    cfg = tmp_path / "no_vna.toml"
    cfg.write_text(textwrap.dedent(base), encoding="utf-8")
    bench = Bench.from_toml(cfg, fake=True)
    assert bench.vna is None
    with pytest.raises(ScpiError, match="no \\[vna\\] section"):
        bench.get_vna(log=lambda *a, **k: None)
    bench.close_all()   # vna=None 이어도 안전해야 함

    cfg2 = tmp_path / "with_vna.toml"
    cfg2.write_text(textwrap.dedent(base) + textwrap.dedent("""
        [vna]
        host = "5.5.5.5"
        port = 5001
    """), encoding="utf-8")
    bench2 = Bench.from_toml(cfg2, fake=True)
    assert bench2.vna is not None and bench2.vna.port == 5001
    # connect_all 은 VNA 를 건드리지 않는다(옵션 장비).
    bench2.connect_all(log=lambda *a, **k: None)
    vna = bench2.get_vna(log=lambda *a, **k: None)
    assert vna is bench2.vna
    bench2.close_all()


def test_bench_power_up_fake(tmp_path: Path):
    toml = textwrap.dedent("""
        [ramp]
        step_v = 1.0
        settle_s = 0.0
        power_up_order = ["B", "C", "A"]

        [psu1]
        host = "1.1.1.1"
        [[psu1.rails]]
        ch = 1
        name = "A"
        v_target = 4.0
        i_limit = 0.5
        ovp = 4.5
        [[psu1.rails]]
        ch = 2
        name = "B"
        v_target = 1.0
        i_limit = 1.0
        ovp = 1.3

        [psu2]
        host = "2.2.2.2"
        [[psu2.rails]]
        ch = 1
        name = "C"
        v_target = 1.8
        i_limit = 0.5
        ovp = 2.1

        [sg]
        host = "3.3.3.3"
        freq_hz = 28.0e9
        level_dbm = -30.0
        rf_output = false

        [sa]
        host = "4.4.4.4"
        center_hz = 28.0e9
        span_hz = 100.0e6
        rbw_hz = 1.0e6
        ref_level_dbm = 0.0
        input_atten_db = 10.0

        [board]
        chip_id = 0
        beam = "b0"
        active_channels = ["h0"]
    """)
    cfg = tmp_path / "bench.toml"
    cfg.write_text(toml, encoding="utf-8")

    bench = Bench.from_toml(cfg, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    vi = bench.power_up(log=lambda *a, **k: None)
    assert abs(vi["A"]["v"] - 4.0) < 1e-6
    assert abs(vi["C"]["v"] - 1.8) < 1e-6
    bench.setup_sg(log=lambda *a, **k: None)
    bench.setup_sa(log=lambda *a, **k: None)
    bench.close_all()
