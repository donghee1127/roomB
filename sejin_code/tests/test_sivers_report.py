"""sivers_report 의 오프라인(fake) 스모크 테스트.

리포트가 끝까지 생성되고 핵심 섹션/파일이 만들어지는지만 본다(fake 값은 무의미).
"""

from __future__ import annotations


def test_main_fake_writes_report(tmp_path):
    from cloudchaser.sivers_report import main

    out = tmp_path / "report.txt"
    rc = main(["--fake", "--no-power", "--channels", "h0,h1,v0,v1",
               "--out", str(out)])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "TEST 1 - Per-stage bias response" in text
    assert "TEST 2 - Register comparison" in text
    assert "CONCLUSION" in text
    assert "St2 Driver (FE2_1V8)" in text
