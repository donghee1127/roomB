"""firehawk 레지스터 엔진 -- sivers_api 의 chip.spi 위에서 raw 주소로 기입한다.

MATLAB firehawk.m 의 "load_address(base) + N x write(auto-inc)" 를
Python 에서는 N x wr(base+k) 로 편다. 벤더 고수준 API(fields/path/commit/
beam_table)는 쓰지 않는다 -- 근거는 docs/superpowers/specs/
2026-08-20-cloudchaser-raw-register-bringup-design.md 2장.

비트팩은 C:\\claude_code\\Sivers_EVB\\evb_full.py 의 FH 클래스(실칩+Sivers
레지스터 덤프로 검증됨)에서 한 글자도 바꾸지 않고 그대로 이식했다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

# 레지스터 주소 (firehawk.m Constant)
COMMON_GAIN = 0x1005
BEAM_ENABLES_ADDR = 0x1008
QUAD_ENABLES_ADDR = 0x100C
QUAD_PWRDN_ADDR = 0x1010
FE_GAIN_ADDR = 0x1018
ADC_SET_ADDR = 0x1020
TEMP_CAL_ADDR = 0x1022
BEAM_BIAS_ADDR = 0x1038
DIST_BIAS_ADDR = 0x104C
EXTRA_ADDR = 0x1058
BEAM_CAL_ADDR = 0x105C
CAPTUNE_ADDR = 0x1068
PHASE_CAL_ADDR = 0x106C
SHORT_ID_ADDR = 0x1000
UID_ADDR = 0x1001

VERSION_ID_TX = 0xDC   # Stampede
VERSION_ID_RX = 0xD4   # Blueway


def parse_ch(ch: str) -> tuple[str, int]:
    """채널 문자열을 (편파, 인덱스)로 분해. 'h0' -> ('h', 0)."""
    s = str(ch).strip().lower()
    return s[0], int(s[1])


def fe_row(ch_idx: int, pol: str) -> int:
    """fe_bias 8행 중 해당 채널·편파의 행 인덱스 (H=2i, V=2i+1)."""
    return 2 * int(ch_idx) + (1 if pol == "v" else 0)


class FH:
    """firehawk register engine on top of a sivers_api chip's SPI transport."""

    def __init__(self, chip, chip_id: int = 0):
        self.C = chip
        self.chip_id = chip_id
        self._spi = chip.spi

    # -- 저수준 SPI (sivers_api 메서드명 방어 어댑터) --------------------
    def wr(self, addr: int, val: int) -> None:
        val &= 0xFFFF
        s = self._spi
        if hasattr(s, "wr"):
            s.wr(self.chip_id, addr, val)
        elif hasattr(s, "write"):
            s.write(self.chip_id, addr, val)
        else:
            # No vendor Regs.wr() fallback here on purpose (Ruling 28): that path
            # is the exact shadow-cache read-modify-write hazard this raw engine
            # exists to remove. Fail loud instead of silently reintroducing it.
            raise AttributeError(
                "chip.spi exposes neither wr() nor write() -- cannot issue a raw "
                "register write (refusing to fall back to the vendor shadow-cache "
                "regs.wr() path)"
            )

    def rd(self, addr: int) -> int:
        s = self._spi
        if hasattr(s, "rd"):
            v = s.rd(self.chip_id, addr)
        elif hasattr(s, "read"):
            v = s.read(self.chip_id, addr)
        else:
            v = self.C.regs.rd(addr)
        return int(v) & 0xFFFF

    def wr_verify(self, addr: int, val: int, tries: int = 3) -> bool:
        """Write then read back until they match (MATLAB integrity check)."""
        val &= 0xFFFF
        for _ in range(max(1, tries)):
            self.wr(addr, val)
            if getattr(self._spi, "fake", False):
                return True
            try:
                if self.rd(addr) == val:
                    return True
            except Exception as e:  # noqa: BLE001
                # evb_full.py 에서 그대로 이식한 폴백이다: 리드백이 불가능한 주소여도
                # 기입 자체는 성공으로 친다(여기서 동작을 바꾸면 레지스터 동일성이
                # 아니라 제어 흐름이 evb_full 과 갈린다). 다만 조용히 삼키면 실칩 첫
                # 실행에서 거짓 OK 가 되므로 한 줄 경고는 남긴다.
                print(f"  [warn] reg 0x{addr:04X} readback could not be verified "
                      f"({type(e).__name__}: {e}) -- assuming the write took")
                return True
        print(f"  [warn] reg 0x{addr:04X} readback != {hex(val)}")
        return False

    def beam_up(self) -> None:
        if hasattr(self._spi, "beam_up"):
            self._spi.beam_up()

    def reset(self) -> None:
        if hasattr(self._spi, "reset"):
            self._spi.reset()

    # -- IDs -------------------------------------------------------------
    def get_short_id(self):
        """(short_id, version_id). version: TX=0xDC / RX=0xD4."""
        v = self.rd(SHORT_ID_ADDR)
        return v & 0xFF, (v >> 8) & 0xFF

    def get_unique_id(self):
        return self.rd(UID_ADDR) + (self.rd(UID_ADDR + 1) << 16)

    # -- Enables -----------------------------------------------------------
    def set_center_enables(self, e):
        """center 제어(0x1008). e=1x10, 가중치 [1 2 4 8 16 32 128 256 1024 4096]."""
        w = [1, 2, 4, 8, 16, 32, 128, 256, 1024, 4096]
        self.wr_verify(BEAM_ENABLES_ADDR, sum(int(e[k]) * w[k] for k in range(len(e))))

    def set_beam_enables(self, rows):
        """beam_enables 3워드(0x1009~). 행=[beam_enables bias_en beam_pwrdn match]."""
        for i, r in enumerate(rows):
            self.wr_verify(BEAM_ENABLES_ADDR + 1 + i,
                           int(r[0]) + (int(r[1]) << 8) + (int(r[2]) << 9) + (int(r[3]) << 14))

    def set_quad_enables(self, rows):
        """quad_enables 4워드(0x100C~). 행=[quad_H_en quad_V_en pulse_en]."""
        for i, r in enumerate(rows):
            self.wr_verify(QUAD_ENABLES_ADDR + i,
                           int(r[0]) + (int(r[1]) << 8) + (int(r[2]) << 11))

    def set_quad_pwrdn(self, rows):
        """quad_pwrdn 4워드(0x1010~). 행=[pwrdn override bias_en pulse efuse_dis].

        pwrdn 6-bit 비트순서(MSB-first) [comb_V drv_V PA_V comb_H drv_H PA_H]:
        H full=0b000111=7, V full=0b111000=56.
        """
        for i, r in enumerate(rows):
            self.wr_verify(QUAD_PWRDN_ADDR + i,
                           int(r[0]) + (int(r[1]) << 6) + (int(r[2]) << 7)
                           + (int(r[3]) << 8) + (int(r[4]) << 9))

    # -- Gains ---------------------------------------------------------
    def set_common_gains(self, gains):
        """common gain 3워드(0x1005~) = B0/B1/B2 (raw 6-bit)."""
        for i, g in enumerate(gains):
            self.wr_verify(COMMON_GAIN + i, int(g) & 0xFFFF)

    def set_fe_gains(self, rows):
        """FE gain 4워드(0x1018~). 행=[Gain_H Gain_V pulse_en]."""
        for i, r in enumerate(rows):
            self.wr_verify(FE_GAIN_ADDR + i,
                           int(r[0]) + (int(r[1]) << 8) + (int(r[2]) << 12))

    # -- Bias ----------------------------------------------------------
    def set_fe_bias(self, bias):
        """FE bias 20워드(0x1038 base, 인터리브). bias=8x5 (행 CH0_H,CH0_V,..CH3_V;
        열 [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS])."""
        for i in range(4):
            h = bias[2 * i]
            v = bias[2 * i + 1]
            self.wr_verify(BEAM_BIAS_ADDR + i,      int(h[0]) + (int(h[1]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 4 + i,  int(h[2]) + (int(h[3]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 8 + i,  int(v[0]) + (int(v[1]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 12 + i, int(v[2]) + (int(v[3]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 16 + i, int(h[4]) + (int(v[4]) << 8))

    def get_fe_bias(self):
        """FE bias 8x5 read-back (set_fe_bias 역함수). reset 직후엔 eFuse 로드값."""
        efb = [[0] * 5 for _ in range(8)]
        for i in range(4):
            w0  = self.rd(BEAM_BIAS_ADDR + i)
            w4  = self.rd(BEAM_BIAS_ADDR + 4 + i)
            w8  = self.rd(BEAM_BIAS_ADDR + 8 + i)
            w12 = self.rd(BEAM_BIAS_ADDR + 12 + i)
            w16 = self.rd(BEAM_BIAS_ADDR + 16 + i)
            efb[2 * i]     = [w0 & 0x3F, (w0 >> 8) & 0x3F, w4 & 0x3F, (w4 >> 8) & 0x3F, w16 & 0x3F]
            efb[2 * i + 1] = [w8 & 0x3F, (w8 >> 8) & 0x3F, w12 & 0x3F, (w12 >> 8) & 0x3F, (w16 >> 8) & 0x3F]
        return efb

    def set_dist_bias(self, bias, ctat):
        """DIST bias 7워드(0x104C~). bias=3x6 (행 B0/B1/B2), ctat 스칼라."""
        for b in range(3):
            r = bias[b]
            self.wr_verify(DIST_BIAS_ADDR + 2 * b, int(r[0]) + (int(r[1]) << 8))
            self.wr_verify(DIST_BIAS_ADDR + 2 * b + 1,
                           int(r[2]) + (int(r[3]) << 6) + (int(r[4]) << 9) + (int(r[5]) << 12))
        self.wr_verify(DIST_BIAS_ADDR + 6, int(ctat))

    def get_dist_bias(self):
        """DIST bias (3x6, ctat) read-back (set_dist_bias 역함수)."""
        edb = [[0] * 6 for _ in range(3)]
        for b in range(3):
            w1 = self.rd(DIST_BIAS_ADDR + 2 * b)
            w2 = self.rd(DIST_BIAS_ADDR + 2 * b + 1)
            edb[b] = [w1 & 0x3F, (w1 >> 8) & 0x3F, w2 & 0x3F,
                      (w2 >> 6) & 0x7, (w2 >> 9) & 0x7, (w2 >> 12) & 0x7]
        return edb, self.rd(DIST_BIAS_ADDR + 6)

    def set_extra(self, extra):
        """extra 3워드(0x1058~). extra=[B0 B1 B2 misc]."""
        self.wr_verify(EXTRA_ADDR, int(extra[0]) + (int(extra[1]) << 8))
        self.wr_verify(EXTRA_ADDR + 1, int(extra[2]))
        self.wr_verify(EXTRA_ADDR + 2, int(extra[3]))

    def set_cal(self, cal):
        """cal atten 12워드(0x105C~). cal[ch][hv][beam], ch0..3, hv0/1, beam0..2."""
        for ch in range(4):
            self.wr_verify(BEAM_CAL_ADDR + ch,
                           int(cal[ch][0][0]) + (int(cal[ch][0][1]) << 8))
        for ch in range(4):
            self.wr_verify(BEAM_CAL_ADDR + 4 + ch,
                           int(cal[ch][0][2]) + (int(cal[ch][1][0]) << 8))
        for ch in range(4):
            self.wr_verify(BEAM_CAL_ADDR + 8 + ch,
                           int(cal[ch][1][1]) + (int(cal[ch][1][2]) << 8))

    def set_captune(self, captune):
        """captune 4워드(0x1068~) CH1..CH4 (raw 16-bit)."""
        for i, c in enumerate(captune):
            self.wr_verify(CAPTUNE_ADDR + i, int(c) & 0xFFFF)

    def set_temp_sensor(self, cal, enable):
        """temp sensor(0x1022). cal=[offset slope], enable=[core bandgap]."""
        self.wr_verify(TEMP_CAL_ADDR,
                       (int(cal[0]) | (int(cal[1]) << 4)
                        | (int(enable[0]) << 8) | (int(enable[1]) << 9)))

    def zero_phase_cal(self):
        """Clear the 280-word phase-cal RAM (0x106C~) -- required before set_rtps_attn.

        cloudchaser 가 놓쳐 RTPS fine-phase 무반응을 일으킨 단계다.
        """
        for k in range(280):
            self.wr(PHASE_CAL_ADDR + k, 0)

    # -- RTPS / beam table --------------------------------------------
    def load_beam_table(self, offset, lines):
        """beam table 라인 로드. lines[L]=[atn0 ph0 atn1 ph1 atn2 ph2 atn3 ph3].
        워드 주소=offset*4+4*L+k, 워드=atten|(phase<<7)."""
        base = offset * 4
        for L, row in enumerate(lines):
            for k in range(4):
                atn = int(row[2 * k]) & 0x7F
                ph = int(row[2 * k + 1]) & 0x7F
                self.wr(base + 4 * L + k, atn | (ph << 7))

    def set_rtps_attn(self, atn, ph, ch, beam, hv):
        """RTPS 감쇠+위상(beam pointer 0 가정). atn 0..126, ph 0..511, ch 0..3, beam 0..2, hv 0=H/1=V.

        beam-table 워드(addr=ch): atten | (coarse=ph//4)<<7.
        fine 2-bit는 phase-cal 3워드(+0/+4/+8)에 0x2000|(ph%4).
        """
        self.wr(ch, ((ph // 4) << 7) | (atn & 0x7F))
        base = PHASE_CAL_ADDR + (beam + hv * 3) * 12 + ch
        for d in (0, 4, 8):
            self.wr(base + d, 0x2000 | (ph % 4))
        self.beam_up()
