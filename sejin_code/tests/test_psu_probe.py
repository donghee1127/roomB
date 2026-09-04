"""psu_probe 의 --vi 모드(read_all_vi 소요시간 분포).

MEAS_TIMEOUT_S 를 몇 초로 잡을지는 추측이 아니라 이 분포로 정한다. 하드웨어가
없어도 구조는 확인할 수 있어야 해서 --fake 경로를 테스트한다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_pct_picks_the_nearest_rank():
    from psu_probe import _pct

    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _pct(vals, 0.0) == 1.0
    assert _pct(vals, 0.5) == 3.0
    assert _pct(vals, 1.0) == 5.0
    # 정렬돼 있지 않아도 된다.
    assert _pct([5.0, 1.0, 3.0], 0.5) == 3.0


def test_pct_survives_an_empty_sample():
    from psu_probe import _pct

    assert _pct([], 0.5) != _pct([], 0.5)      # NaN


def test_vi_mode_reports_a_distribution(capsys):
    from psu_probe import main

    rc = main(["--fake", "--config", str(CONFIG), "--vi", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "read_all_vi x5" in out
    assert "samples=5" in out and "ok=5" in out
    assert "p95" in out
    # 후보 timeout 을 제안하는 줄이 있어야 이 도구를 쓴 의미가 있다.
    assert "MEAS timeout of" in out


def test_meas_timeout_override_is_applied(capsys):
    """--meas-timeout 은 코드를 고치기 전에 후보 값을 시험하기 위한 것이다."""
    from psu_probe import main

    assert main(["--fake", "--config", str(CONFIG), "--vi", "2",
                 "--meas-timeout", "3"]) == 0
    assert "MEAS timeout 3.0s" in capsys.readouterr().out


def test_per_command_probe_still_runs_without_vi(capsys):
    from psu_probe import main

    assert main(["--fake", "--config", str(CONFIG)]) == 0
    out = capsys.readouterr().out
    assert "*IDN?" in out and "MEAS:CURR?" in out
