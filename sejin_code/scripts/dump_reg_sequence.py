"""start(channels=['h1']) + channel_gain_alignment(channel_mode='all') 가 EVB(칩)에
보내는 SPI/레지스터 트랜잭션을 순서대로 캡처한다(fake 모드 = 실제와 동일한 레지스터
변환, 전송만 가짜). Sivers 문의용 시퀀스 추출.

실행: python scripts/dump_reg_sequence.py
"""
from __future__ import annotations

import contextlib
import io

from cloudchaser.bench import Bench
from cloudchaser.board.bringup import bring_up_tx, make_chip
from cloudchaser.setup_tx import DEFAULT_CONFIG
from cloudchaser.test_items import TestContext, get_test


def _spi_lines(text: str) -> list[str]:
    """캡처된 출력에서 칩 SPI 트랜잭션 줄만 추린다(reset/write/beam_update)."""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith(("spi0_reset", "spi0_write", "spi0_beam_upd")):
            out.append(s)
    return out


def main() -> None:
    bench = Bench.from_toml(DEFAULT_CONFIG, fake=True)
    bench.connect_all(log=lambda *a, **k: None)
    bench.board.active_channels = ["h1"]
    chip = make_chip(bench.board, fake=True)

    # --- Phase 1+2: start() 의 bring-up (init + eFuse + 구성 writes) ---
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        bring_up_tx(chip, bench.board, require_version=False,
                    log=lambda *a, **k: None)
    bringup = _spi_lines(buf.getvalue())

    # --- Phase 3: channel_gain_alignment(channel_mode='all') 의 채널 셋업 ---
    test = get_test("channel_gain_alignment")()
    params = test.resolve({"channel_mode": "all",
                           "channels_script": "h1,h0,v0,v1,h2,v2,h3,v3"})
    ctx = TestContext(bench=bench, chip=chip, fake=True)
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2), contextlib.redirect_stderr(buf2):
        test.run(ctx, params, log=lambda *a, **k: None)
    align = _spi_lines(buf2.getvalue())

    print("=" * 70)
    print("PHASE 1+2  start(channels=['h1'])  - init + bring-up")
    print("=" * 70)
    for s in bringup:
        print(s)
    print()
    print("=" * 70)
    print("PHASE 3  channel_gain_alignment(channel_mode='all') - channel setup")
    print("=" * 70)
    for s in align:
        print(s)


if __name__ == "__main__":
    main()
