"""docs/register_maps/*.xlsx 의 전체 레지스터/필드 맵을 마크다운 표로 덤프한다.

sivers_api 가 같은 xlsx 를 파싱해 REGISTERS({name:addr}) / FIELDS({name:[(addr,lsb,width)..]})
로 보관하므로, 그걸 그대로 뽑아 docs/COMMANDS.md 의 부록(레지스터/필드 표) 원본으로 쓴다.
fake 모드라 하드웨어 없이 동작한다(레지스터 변환은 실제와 동일).

실행: python scripts/dump_register_map.py
"""
from __future__ import annotations

from sivers_api.enums import BFIC
from sivers_api.registers import get_register_map


def _bits(segments: list[tuple[int, int, int]]) -> str:
    """필드 비트 범위 표기. 단일 세그먼트는 [msb:lsb], 멀티는 주소별로 나열."""
    parts = []
    for addr, lsb, width in segments:
        msb = lsb + width - 1
        rng = f"[{msb}:{lsb}]" if width > 1 else f"[{lsb}]"
        parts.append(rng if len(segments) == 1 else f"0x{addr:04X}{rng}")
    return " + ".join(parts)


def main() -> None:
    # REGISTERS: {name: addr},  FIELDS: {name: [(addr, lsb, width), ...]}
    regs, fields, _efuse = get_register_map(BFIC.STAMPEDE)

    print(f"registers: {len(regs)}   fields: {len(fields)}\n")

    # 검증: firehawk.m 의 알려진 주소와 대조.
    known = {0x1005: "common_gain", 0x1008: "beam_enables",
             0x100C: "quad_enables", 0x1018: "fe_gain"}
    addr_to_name = {a: n for n, a in regs.items()}
    print("# address cross-check (vs firehawk.m)")
    for a, label in known.items():
        print(f"  0x{a:04X} {label:14} -> {addr_to_name.get(a, '(missing)')}")
    print()

    print("## Appendix A - registers (name / hex / dec)\n")
    print("| Register | Addr (hex) | Addr (dec) |")
    print("|---|---|---|")
    for name, addr in sorted(regs.items(), key=lambda kv: kv[1]):
        print(f"| `{name}` | 0x{addr:04X} | {addr} |")

    print("\n## Appendix B - fields (name / addr / bits)\n")
    print("| Field | Addr (hex) | Bits |")
    print("|---|---|---|")
    # 첫 세그먼트 주소 기준 정렬 -> 같은 레지스터 필드가 모이도록.
    for name, segs in sorted(fields.items(), key=lambda kv: (kv[1][0][0], kv[0])):
        addr0 = segs[0][0]
        print(f"| `{name}` | 0x{addr0:04X} | {_bits(segs)} |")


if __name__ == "__main__":
    main()
