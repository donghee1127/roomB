"""read_vi 의 측정 timeout 견고화 테스트.

E36313A.read_vi 는 측정 동안만 socket timeout 을 MEAS_TIMEOUT_S 로 올리고,
timeout(OSError) 이 나면 resync() 로 큐를 비운 뒤 예외를 올리며, 어느 경우든
원래 timeout 으로 복원해야 한다.
"""

from __future__ import annotations

import socket

import pytest

from cloudchaser.instruments.psu_e36313a import E36313A, Rail


def _psu():
    rails = [Rail(1, "FE1_4V0", 4.0, 0.3, 4.5),
             Rail(2, "FE2_1V8", 1.8, 0.4, 2.1),
             Rail(3, "FE3_1V8", 1.8, 0.4, 2.1)]
    psu = E36313A("127.0.0.1", rails, fake=False, name="PSU_T")
    psu._sock = object()  # set_timeout 가 settimeout 호출 안 하도록... 아래서 패치
    return psu


def test_read_vi_elevates_and_restores_timeout(monkeypatch):
    psu = _psu()
    psu.timeout = 5.0
    seen = {}

    # set_timeout 의 소켓 접근을 무력화하고, 측정 중 timeout 값을 캡처.
    monkeypatch.setattr(psu, "set_timeout",
                        lambda t: (psu.__dict__.__setitem__("timeout", t),
                                   seen.__setitem__("during", t)))

    def fake_query(cmd):
        seen["during_query"] = psu.timeout
        return "1.0,2.0,3.0" if "VOLT" in cmd else "0.1,0.2,0.3"

    monkeypatch.setattr(psu, "query", fake_query)
    out = psu.read_vi()
    assert out["FE2_1V8"] == {"v": 2.0, "i": 0.2}
    assert seen["during_query"] == E36313A.MEAS_TIMEOUT_S   # 측정 중 그 값 그대로
    assert psu.timeout == 5.0                               # 끝나면 복원


def test_read_vi_resyncs_on_timeout(monkeypatch):
    psu = _psu()
    psu.timeout = 5.0
    calls = {"resync": 0}

    monkeypatch.setattr(psu, "set_timeout",
                        lambda t: psu.__dict__.__setitem__("timeout", t))
    monkeypatch.setattr(psu, "resync", lambda *a, **k: calls.__setitem__(
        "resync", calls["resync"] + 1))

    def timeout_query(cmd):
        raise socket.timeout("timed out")

    monkeypatch.setattr(psu, "query", timeout_query)
    with pytest.raises(OSError):
        psu.read_vi()
    assert calls["resync"] == 1          # 큐 비움(다음 읽기 동기 보호)
    assert psu.timeout == 5.0            # 복원


# --- 일시적 MEAS timeout 재시도 (bench 계층) ---------------------------
# 실측 증상: verify 처럼 56점을 40분 도는 실행에서 MEAS:CURR? 가 딱 한 번
# timeout 나면 실행 전체가 죽는다. read_vi 가 이미 resync 로 소켓을 정리하고
# 예외를 올리므로, 그 위에서 유한 재시도하면 회복된다(재실행하면 되던 증상).

from pathlib import Path  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def _fake_bench():
    from cloudchaser.bench import Bench

    bench = Bench.from_toml(CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    return bench


def test_read_all_vi_retries_a_transient_timeout():
    """한 번 timeout 나도 재시도해서 값을 돌려준다."""
    bench = _fake_bench()
    psu = bench.psus[0]
    real = psu.read_vi
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise socket.timeout("timed out")
        return real()

    psu.read_vi = flaky
    logs: list[str] = []
    out = bench.read_all_vi(log=logs.append)

    assert calls["n"] == 2                     # 한 번 실패 후 재시도로 성공
    assert "FE1_4V0" in out
    assert any("retry" in ln for ln in logs)   # 조용히 넘어가지 않는다
    bench.close_all()


def test_read_all_vi_gives_up_after_retries():
    """계속 timeout 이면 결국 올린다 -- 죽은 계측기를 무한히 숨기지 않는다."""
    bench = _fake_bench()
    for psu in bench.psus:
        psu.read_vi = lambda: (_ for _ in ()).throw(socket.timeout("timed out"))

    with pytest.raises(OSError):
        bench.read_all_vi(retries=2, log=lambda *a: None)
    bench.close_all()


def test_tripped_resyncs_and_reports_when_it_self_disables(monkeypatch, capsys):
    """STAT:QUES:COND? 가 무응답이면 트립 폴링을 끄되, resync 하고 알린다.

    예전엔 조용히 _trip_supported=False 로 바꾸고 끝이라, (1) 늦게 온 응답이
    버퍼에 남아 이후 query 가 한 칸 밀리고 (2) 운영자는 트립 보호가 계속
    동작한다고 믿었다.
    """
    psu = _psu()
    calls = {"resync": 0}
    monkeypatch.setattr(psu, "resync", lambda *a, **k: calls.__setitem__(
        "resync", calls["resync"] + 1))
    monkeypatch.setattr(psu, "query",
                        lambda cmd: (_ for _ in ()).throw(socket.timeout("x")))

    assert psu.tripped(1) is False
    assert psu._trip_supported is False       # 이후엔 폴링 안 함
    assert calls["resync"] == 1               # desync 방지
    out = capsys.readouterr().out
    assert "trip polling disabled" in out     # 조용히 넘어가지 않는다


def test_meas_timeout_below_the_socket_timeout_is_applied(monkeypatch):
    """MEAS_TIMEOUT_S 가 기본 소켓 timeout 보다 낮아도 그대로 쓰여야 한다.

    예전 구현은 max(self.timeout, MEAS_TIMEOUT_S) 라 낮은 값을 조용히 무시했다.
    그래서 psu_probe --meas-timeout 3 이 실제로는 5s 로 돌아, 어떤 값을 시험한
    것인지 자체가 어긋났다(2026-09-04).
    """
    psu = _psu()
    psu.timeout = 5.0
    psu.MEAS_TIMEOUT_S = 2.0
    seen = {}

    monkeypatch.setattr(psu, "set_timeout",
                        lambda x: psu.__dict__.__setitem__("timeout", x))

    def fake_query(cmd):
        seen["during_query"] = psu.timeout
        return "1.0,2.0,3.0" if "VOLT" in cmd else "0.1,0.2,0.3"

    monkeypatch.setattr(psu, "query", fake_query)
    psu.read_vi()
    assert seen["during_query"] == 2.0
    assert psu.timeout == 5.0
