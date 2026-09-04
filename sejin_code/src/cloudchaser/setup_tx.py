"""CloudChaser Stampede(TX) — "측정 직전"까지의 셋업을 한 번에 수행하는 진입점.

전체 순서:
  1) bench.toml 로드
  2) 계측기 4대(전원 2대 / SG / SA) 연결
  3) PSU 보호 설정 → 램프업 → 레일 V/I 확인
  4) 보드 bring-up (Stampede 초기화 + version 확인 + 경로/게인/감쇠 구성)
  5) SG / SA 셋업 (SG RF 출력은 기본 OFF) — best-effort(실패해도 보드 유지)
  6) "READY" 출력 후 종료 ← 실제 측정(RF 인가/sweep)은 다음 마일스톤

성공 시 전원은 켜진 상태로 남는다('측정 직전 상태' 유지). 도중 치명적 실패가 나면
자동으로 전원을 0V 로 내리고 종료한다.

실행:
  python -m cloudchaser.setup_tx --fake   # 하드웨어 없이 dry-run (개발 PC)
  python -m cloudchaser.setup_tx          # 실제 하드웨어 (실험 PC)

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bench import Bench
from .board.bringup import bring_up_tx, make_chip

# 기본 bench.toml 경로: 이 파일 기준으로 repo 루트의 config/bench.toml 을 가리킨다.
# parents[2] = .../cloudchaser (repo 루트), 그 아래 config/bench.toml.
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "bench.toml"


def run(config: Path, *, fake: bool, log=print) -> int:
    """셋업 전체 시퀀스를 실행한다. 성공 0, 실패 1 반환."""
    log(f"=== CloudChaser Stampede(TX) setup === (config={config}, fake={fake})")
    bench = Bench.from_toml(config, fake=fake)
    powered = False  # 전원이 인가됐는지 표시(실패 시 안전 종료 여부 결정)
    try:
        # 2) 계측기 연결
        bench.connect_all(log=log)

        # 3) 전원 램프업.
        #    이 시점부터 출력이 켜질 수 있으므로 powered 를 먼저 True 로 둔다 →
        #    램프 도중 실패해도 except 블록에서 power_down 으로 안전하게 내려간다.
        powered = True
        bench.power_up(log=log)

        # 4) 보드 bring-up (fake 모드에서는 version 불일치를 통과시킨다)
        chip = make_chip(bench.board, fake=fake)
        bring_up_tx(chip, bench.board, require_version=not fake, log=log)

        # 5) SG / SA 셋업 — best-effort.
        #    계측기 SCPI 거부(예: SA 모드 문제)는 경고만 남기고, 이미 성공한
        #    전원/보드 bring-up 을 무너뜨리지 않도록 try 로 감싼다.
        try:
            bench.setup_sg(log=log)
            bench.setup_sa(log=log)
        except Exception as e:
            log(f"[warn  ] instrument (SG/SA) setup partially failed "
                f"(board kept up): {type(e).__name__}: {e}")

        log("\n>>> READY - board powered & configured. (check SG/SA warnings above)")
        log(">>> Next: turn SG RF output ON, then start measurement (sweep/marker).")
        return 0

    except Exception as e:
        # 치명적 실패: 가능하면 전원을 안전하게 내린다.
        log(f"\n[ERROR] {type(e).__name__}: {e}")
        if powered:
            log("[safe  ] attempting power ramp-down...")
            try:
                bench.power_down(log=log)
            except Exception as e2:
                log(f"[safe  ] ramp-down failed: {e2}")
        return 1
    finally:
        # 성공/실패와 무관하게 소켓은 닫는다(전원 출력 상태는 건드리지 않음).
        bench.close_all()


def _force_utf8_stdout() -> None:
    """표준출력을 UTF-8 로 재설정.

    Windows 콘솔 기본 코드페이지(cp949)에서 일부 유니코드 기호 출력 시 예외가
    날 수 있으므로 UTF-8 + errors='replace' 로 바꿔 안전하게 만든다. (한글 자체는
    렌더링이 깨질 수 있어, 실제 로그 문자열은 영어/ASCII 로 작성한다.)
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 인자를 파싱해 run() 을 호출한다."""
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="CloudChaser Stampede(TX) measurement-ready setup")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                   help=f"path to bench.toml (default: {DEFAULT_CONFIG})")
    p.add_argument("--fake", action="store_true",
                   help="dry-run without hardware (fake instruments + fake_spi)")
    args = p.parse_args(argv)
    return run(args.config, fake=args.fake)


if __name__ == "__main__":
    sys.exit(main())
