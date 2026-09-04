r"""PSU 채널별 허용범위 진단 (읽기 전용 — 전원 인가 없음).

각 채널의 전압/전류/OVP 설정 가능 MIN..MAX 를 질의해서 출력한다.
-222 "Data out of range" 의 원인(특히 OVP 최솟값)을 확인하는 용도.

실행 (repo 루트에서):
    python scripts\psu_ranges.py
    python scripts\psu_ranges.py config\bench.toml
"""

from __future__ import annotations

import sys

from cloudchaser.bench import Bench


def q(psu, cmd: str) -> str:
    try:
        return psu.query(cmd).strip()
    except Exception as e:  # 한 질의가 실패해도 나머지는 계속
        return f"<err: {type(e).__name__}>"


def main() -> int:
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/bench.toml"
    bench = Bench.from_toml(cfg, fake=False)
    for psu in (bench.psu1, bench.psu2):
        psu.connect()
        psu.clear_status()
        print(f"\n=== {psu.name} @ {psu.host} ===")
        print("  *IDN?:", q(psu, "*IDN?"))
        for r in psu.rails.values():
            c = r.ch
            vmin = q(psu, f"VOLT? MIN,(@{c})")
            vmax = q(psu, f"VOLT? MAX,(@{c})")
            imin = q(psu, f"CURR? MIN,(@{c})")
            imax = q(psu, f"CURR? MAX,(@{c})")
            omin = q(psu, f"VOLT:PROT? MIN,(@{c})")
            omax = q(psu, f"VOLT:PROT? MAX,(@{c})")
            print(f"  ch{c} [{r.name}]  V:{vmin}..{vmax}  "
                  f"I:{imin}..{imax}  OVP:{omin}..{omax}")
        psu.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
