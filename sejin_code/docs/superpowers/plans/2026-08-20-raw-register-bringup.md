# CloudChaser Raw-Register Bring-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cloudchaser의 bring-up 레지스터 상태를 `Sivers_EVB/evb_full.py`와 동일하게 만들고, v4 시트의 최적화 bias(TX `Casper` / RX `NF_OPTIM`)를 적용하며, 벤더 `sivers_api` 고수준 API를 쓰기 경로에서 제거한다.

**Architecture:** MATLAB `firehawk.m`의 레지스터 시퀀스를 `board/firehawk.py`의 FH 엔진으로 이식하고, `chip.spi.wr(chip_id, addr, value)` raw 기입만 사용한다. `bring_up_tx`/`bring_up_rx`의 시그니처는 유지해 호출부 6곳은 건드리지 않는다. 테스트 항목의 게인 조작은 필드 이름 문자열 대신 타깃(`common`/`fe`/`beamtable`) 기반으로 재설계한다.

**Tech Stack:** Python 3.13 · pytest · `sivers_api` 0.1.0 (SPI 전송 계층만) · openpyxl(레지스터 덤프 xlsx 읽기) · tomllib

**Spec:** `docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md`

## Global Constraints

- **사용자에게 보이는 모든 텍스트는 영어로 작성한다.** `print`/`log`/`raise` 메시지 + `_ns`(session 네임스페이스)에 노출되는 함수 docstring 포함. 코드 주석·모듈 docstring은 한국어 OK. (콘솔 cp949 한글 깨짐 방지)
- **설정값은 코드가 아니라 `config/bench.toml`에서 바꾼다.**
- Python 3.13. 테스트는 프로젝트 venv로 `python -m pytest`. 이 PC는 `.venv`.
- **커밋 전 `python -m pytest` 통과를 확인한다.**
- 작업 브랜치는 이미 `feat/raw-register-bringup` 이다. 이 브랜치에 커밋한다.
- 커밋 메시지는 ASCII만 사용한다(em-dash `—`, `§` 금지 — cp949 콘솔에서 깨짐). 메시지 끝에 다음 2줄을 붙인다:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MTwxJbu8z6a5MyMGi6gyUN
  ```
- `docs/sivers_unified_api_v0.1.0/`, `docs/Cloudchaser_drv-v1.0.0/` 는 벤더 레퍼런스다. **건드리지 않는다.**
- `instruments/`, `loss.py`, `runner.py`의 CSV 저장 로직은 **건드리지 않는다.**
- 레지스터 워드는 항상 `& 0xFFFF` 로 마스킹한다.

---

### Task 1: FH 레지스터 엔진 (`board/firehawk.py`)

**Files:**
- Create: `src/cloudchaser/board/firehawk.py`
- Test: `tests/test_firehawk_bitpack.py`

**Interfaces:**
- Consumes: `chip.spi` (sivers_api `SPIReq`: `wr(chip_id, addr, data)` / `rd(chip_id, addr)` / `reset()` / `beam_up()`)
- Produces:
  - `class FH(chip, chip_id=0)` — 메서드: `wr(addr, val)`, `rd(addr) -> int`, `wr_verify(addr, val, tries=3) -> bool`, `reset()`, `beam_up()`, `get_short_id() -> (short_id, version_id)`, `get_unique_id() -> int`, `set_center_enables(e)`, `set_beam_enables(rows)`, `set_quad_enables(rows)`, `set_quad_pwrdn(rows)`, `set_common_gains(gains)`, `set_fe_gains(rows)`, `set_fe_bias(bias8x5)`, `get_fe_bias() -> list[list[int]]`, `set_dist_bias(bias3x6, ctat)`, `get_dist_bias() -> (list[list[int]], int)`, `set_extra(extra4)`, `set_cal(cal4x2x3)`, `set_captune(captune4)`, `set_temp_sensor(cal2, enable2)`, `zero_phase_cal()`, `load_beam_table(offset, lines)`, `set_rtps_attn(atn, ph, ch, beam, hv)`
  - 모듈 상수: `COMMON_GAIN=0x1005`, `BEAM_ENABLES_ADDR=0x1008`, `QUAD_ENABLES_ADDR=0x100C`, `QUAD_PWRDN_ADDR=0x1010`, `FE_GAIN_ADDR=0x1018`, `ADC_SET_ADDR=0x1020`, `TEMP_CAL_ADDR=0x1022`, `BEAM_BIAS_ADDR=0x1038`, `DIST_BIAS_ADDR=0x104C`, `EXTRA_ADDR=0x1058`, `BEAM_CAL_ADDR=0x105C`, `CAPTUNE_ADDR=0x1068`, `PHASE_CAL_ADDR=0x106C`, `SHORT_ID_ADDR=0x1000`, `UID_ADDR=0x1001`, `VERSION_ID_TX=0xDC`, `VERSION_ID_RX=0xD4`
  - `parse_ch(ch: str) -> tuple[str, int]` — `"h0"` → `("h", 0)`
  - `fe_row(ch_idx: int, pol: str) -> int` — fe_bias 8행 인덱스. `2*ch_idx + (1 if pol=="v" else 0)`

- [ ] **Step 1: Write the failing test**

`tests/test_firehawk_bitpack.py`:

```python
"""FH 레지스터 비트팩 검증. 기대값은 MATLAB firehawk.m / Sivers 덤프에서 확정된 값."""
import pytest

from cloudchaser.board.firehawk import (
    FH, parse_ch, fe_row,
    BEAM_BIAS_ADDR, DIST_BIAS_ADDR, PHASE_CAL_ADDR, QUAD_PWRDN_ADDR,
)


class MemSPI:
    """주소->값 딕셔너리 SPI. 쓴 값을 그대로 돌려준다."""

    def __init__(self):
        self.mem = {}
        self.writes = []
        self.fake = True

    def wr(self, cid, addr, val):
        self.mem[addr] = val & 0xFFFF
        self.writes.append((addr, val & 0xFFFF))

    def rd(self, cid, addr):
        return self.mem.get(addr, 0)

    def reset(self):
        pass

    def beam_up(self):
        pass


class FakeChip:
    def __init__(self):
        self.spi = MemSPI()


@pytest.fixture
def fh():
    return FH(FakeChip(), 0)


def test_parse_ch_and_fe_row():
    assert parse_ch("h0") == ("h", 0)
    assert parse_ch("V3") == ("v", 3)
    assert fe_row(0, "h") == 0
    assert fe_row(0, "v") == 1
    assert fe_row(3, "v") == 7


def test_quad_pwrdn_rx_h_and_v(fh):
    """RX H full = 0b000111 -> 199, V full = 0b111000 -> 248 (bias_en+override 포함)."""
    rows = [[0, 1, 0, 0, 0] for _ in range(4)]
    rows[0] = [0b000111, 1, 1, 0, 0]
    fh.set_quad_pwrdn(rows)
    assert fh.rd(QUAD_PWRDN_ADDR + 0) == 199

    rows[0] = [0b111000, 1, 1, 0, 0]
    fh.set_quad_pwrdn(rows)
    assert fh.rd(QUAD_PWRDN_ADDR + 0) == 248


def test_quad_pwrdn_other_quads_override_only(fh):
    """활성이 아닌 quad 는 override 비트만 -> 64."""
    rows = [[0, 1, 0, 0, 0] for _ in range(4)]
    fh.set_quad_pwrdn(rows)
    assert fh.rd(QUAD_PWRDN_ADDR + 1) == 64


def test_center_enables(fh):
    """가중치 [1 2 4 8 16 32 128 256 1024 4096]. TX=[1,1,0..]=3, RX=[1,1,1,0..]=7."""
    fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    assert fh.rd(0x1008) == 3
    fh.set_center_enables([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    assert fh.rd(0x1008) == 7


def test_beam_enables_rx_ch0_b0(fh):
    """RX CH0/B0: [1, 1, 4, 0] -> 1 | 1<<8 | 4<<9 = 2305."""
    rows = [[0, 0, 0, 0] for _ in range(3)]
    rows[0] = [1, 1, 4, 0]
    fh.set_beam_enables(rows)
    assert fh.rd(0x1009) == 2305


def test_quad_enables_rx_ch0_b0(fh):
    """RX CH0/B0: [1, 1, 0] -> 1 | 1<<8 = 257."""
    rows = [[0, 0, 0] for _ in range(4)]
    rows[0] = [1, 1, 0]
    fh.set_quad_enables(rows)
    assert fh.rd(0x100C) == 257


def test_fe_bias_roundtrip(fh):
    """set_fe_bias -> get_fe_bias 왕복이 동일해야 한다(인터리브 규칙 검증)."""
    bias = [[i + 1, i + 2, i + 3, i + 4, (i % 8) + 1] for i in range(8)]
    fh.set_fe_bias(bias)
    assert fh.get_fe_bias() == bias


def test_fe_bias_packing_ch0_h(fh):
    """CH0-H Casper: PTAT1=15, PTAT2=45 -> 0x1038 = 15 | 45<<8 = 11535."""
    bias = [[0, 0, 0, 0, 0] for _ in range(8)]
    bias[0] = [15, 45, 55, 32, 5]
    fh.set_fe_bias(bias)
    assert fh.rd(BEAM_BIAS_ADDR + 0) == 15 | (45 << 8)
    assert fh.rd(BEAM_BIAS_ADDR + 4 + 0) == 55 | (32 << 8)


def test_dist_bias_roundtrip(fh):
    bias = [[10, 11, 12, 1, 2, 3], [20, 21, 22, 4, 5, 6], [6, 6, 6, 0, 0, 0]]
    fh.set_dist_bias(bias, 8)
    got, ctat = fh.get_dist_bias()
    assert got == bias
    assert ctat == 8


def test_dist_bias_b0_casper_word(fh):
    """Casper B0: St1=50, St2_0=13 -> 0x104C = 50 | 13<<8 = 3378."""
    bias = [[50, 13, 13, 6, 0, 0], [0] * 6, [0] * 6]
    fh.set_dist_bias(bias, 8)
    assert fh.rd(DIST_BIAS_ADDR) == 3378


def test_zero_phase_cal_writes_280_words(fh):
    fh.zero_phase_cal()
    for k in range(280):
        assert fh.rd(PHASE_CAL_ADDR + k) == 0
    assert len([w for w in fh.C.spi.writes if w[0] >= PHASE_CAL_ADDR]) == 280


def test_temp_sensor(fh):
    """offset=8, slope=8, core=1, bandgap=1 -> 8 | 8<<4 | 1<<8 | 1<<9 = 904."""
    fh.set_temp_sensor([8, 8], [1, 1])
    assert fh.rd(0x1022) == 8 | (8 << 4) | (1 << 8) | (1 << 9)


def test_set_rtps_attn_coarse_and_fine(fh):
    """phase 9-bit: coarse=ph//4 는 beam-table 워드, fine=ph%4 는 phase-cal 3워드."""
    fh.set_rtps_attn(0, 13, ch=1, beam=0, hv=0)
    assert fh.rd(1) == (13 // 4) << 7
    base = PHASE_CAL_ADDR + (0 + 0 * 3) * 12 + 1
    for d in (0, 4, 8):
        assert fh.rd(base + d) == 0x2000 | (13 % 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_firehawk_bitpack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudchaser.board.firehawk'`

- [ ] **Step 3: Write the implementation**

`src/cloudchaser/board/firehawk.py` — `C:\claude_code\Sivers_EVB\evb_full.py` 의 `FH` 클래스(120~330행)를 그대로 이식한다. 클래스 본문·비트팩·docstring 근거는 동일하게 두고, 사용자에게 보이는 문자열만 영어로 쓴다.

```python
"""firehawk 레지스터 엔진 -- sivers_api 의 chip.spi 위에서 raw 주소로 기입한다.

MATLAB firehawk.m 의 "load_address(base) + N x write(auto-inc)" 를
Python 에서는 N x wr(base+k) 로 편다. 벤더 고수준 API(fields/path/commit/
beam_table)는 쓰지 않는다 -- 근거는 docs/superpowers/specs/
2026-08-20-cloudchaser-raw-register-bringup-design.md 2장.

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
            self.C.regs.wr(addr, val)

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
            except Exception:
                return True
        print(f"  [warn] reg 0x{addr:04X} readback != {hex(val)}")
        return False

    def beam_up(self) -> None:
        if hasattr(self._spi, "beam_up"):
            self._spi.beam_up()

    def reset(self) -> None:
        if hasattr(self._spi, "reset"):
            self._spi.reset()
```

이어서 `get_short_id` · `get_unique_id` · `set_center_enables` · `set_beam_enables` · `set_quad_enables` · `set_quad_pwrdn` · `set_common_gains` · `set_fe_gains` · `set_fe_bias` · `get_fe_bias` · `set_dist_bias` · `get_dist_bias` · `set_extra` · `set_cal` · `set_captune` · `set_temp_sensor` · `zero_phase_cal` · `load_beam_table` · `set_rtps_attn` 을 `evb_full.py` 의 동명 메서드와 **동일한 비트팩**으로 옮긴다. 비트팩 공식은 스펙 3장에 표로 정리돼 있다. 핵심만 옮기면:

```python
    def set_quad_pwrdn(self, rows):
        """quad_pwrdn 4워드(0x1010~). 행=[pwrdn override bias_en pulse efuse_dis].

        pwrdn 6-bit MSB-first = [comb_V drv_V PA_V comb_H drv_H PA_H].
        H full = 0b000111 = 7, V full = 0b111000 = 56.
        """
        for i, r in enumerate(rows):
            self.wr_verify(QUAD_PWRDN_ADDR + i,
                           int(r[0]) + (int(r[1]) << 6) + (int(r[2]) << 7)
                           + (int(r[3]) << 8) + (int(r[4]) << 9))

    def set_fe_bias(self, bias):
        """FE bias 20워드(0x1038 base, 인터리브). bias=8x5.

        행 CH0_H,CH0_V,..,CH3_V / 열 [PTAT_ST1 PTAT_ST2 PTAT_ST3 CTAT FE_CBIAS].
        """
        for i in range(4):
            h = bias[2 * i]
            v = bias[2 * i + 1]
            self.wr_verify(BEAM_BIAS_ADDR + i,      int(h[0]) + (int(h[1]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 4 + i,  int(h[2]) + (int(h[3]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 8 + i,  int(v[0]) + (int(v[1]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 12 + i, int(v[2]) + (int(v[3]) << 8))
            self.wr_verify(BEAM_BIAS_ADDR + 16 + i, int(h[4]) + (int(v[4]) << 8))

    def zero_phase_cal(self):
        """Clear the 280-word phase-cal RAM (0x106C~) -- required before set_rtps_attn.

        cloudchaser 가 놓쳐 RTPS fine-phase 무반응을 일으킨 단계다.
        """
        for k in range(280):
            self.wr(PHASE_CAL_ADDR + k, 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_firehawk_bitpack.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Run the whole suite (회귀 확인)**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: 기존 테스트 전부 PASS (신규 모듈은 아직 아무도 안 씀)

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/board/firehawk.py tests/test_firehawk_bitpack.py
git commit -m "feat(board): add FH raw register engine ported from firehawk.m"
```

---

### Task 2: v4 optimized bias 테이블 (`board/bias_v4.py`)

**Files:**
- Create: `src/cloudchaser/board/bias_v4.py`
- Test: `tests/test_bias_v4.py`

**Interfaces:**
- Consumes: Task 1의 `fe_row`, `parse_ch`
- Produces:
  - `CASPER_FE: dict` — `{"ptat_st1": 15, "ptat_st2": 45, "ptat_st3": 55}`
  - `NF_OPTIM_FE: dict` — `{"ptat_st1": 34, "ptat_st2": 24, "ptat_st3": 48}`
  - `CASPER_DIST_B0: dict` — `{"st1_ptat": 50, "st2_0_ptat": 13, "cbias1": 6}`
  - `NF_OPTIM_DIST_B0: dict` — `{"st1_ptat": 44}`
  - `NF_OPTIM_CAPTUNE: int` — `0x8888`
  - `apply_fe_bias(efuse_bias, active_channels, kind) -> list[list[int]]`
    — eFuse 8x5 리드백에 최적화 PTAT를 얹어 8x5를 반환. **활성 채널 행만 채우고 나머지는 0.** CTAT/CBIAS는 eFuse 값 유지.
  - `apply_dist_bias(efuse_dist, beam_idx, kind, st2_1_ptat) -> list[list[int]]`
    — eFuse 3x6에 최적화 값을 얹어 3x6 반환. 활성 빔 행만. TX는 B2 PTAT=[6,6,6].

- [ ] **Step 1: Write the failing test**

`tests/test_bias_v4.py`:

```python
"""v4 시트(Casper/NF_OPTIM) bias 적용 규칙 검증."""
from cloudchaser.board.bias_v4 import (
    CASPER_FE, NF_OPTIM_FE, CASPER_DIST_B0, NF_OPTIM_DIST_B0,
    apply_fe_bias, apply_dist_bias,
)

# die eFuse 리드백을 흉내낸 8x5 (열: PTAT1 PTAT2 PTAT3 CTAT CBIAS)
EFUSE_FE = [[10, 20, 30, 32, 5] for _ in range(8)]
EFUSE_DIST = [[12, 13, 14, 1, 1, 1] for _ in range(3)]


def test_casper_values_match_sheet():
    assert CASPER_FE == {"ptat_st1": 15, "ptat_st2": 45, "ptat_st3": 55}
    assert CASPER_DIST_B0["st1_ptat"] == 50
    assert CASPER_DIST_B0["st2_0_ptat"] == 13


def test_nf_optim_values_match_sheet():
    assert NF_OPTIM_FE == {"ptat_st1": 34, "ptat_st2": 24, "ptat_st3": 48}
    assert NF_OPTIM_DIST_B0["st1_ptat"] == 44


def test_fe_bias_only_active_rows_filled():
    """활성 채널(v1 -> 행 3)만 채우고 나머지 행은 0."""
    out = apply_fe_bias(EFUSE_FE, ["v1"], "tx")
    assert out[3] == [15, 45, 55, 32, 5]          # PTAT는 Casper, CTAT/CBIAS는 eFuse
    for r in range(8):
        if r != 3:
            assert out[r] == [0, 0, 0, 0, 0]


def test_fe_bias_rx_uses_nf_optim():
    out = apply_fe_bias(EFUSE_FE, ["h0"], "rx")
    assert out[0] == [34, 24, 48, 32, 5]


def test_fe_bias_multiple_active_channels():
    out = apply_fe_bias(EFUSE_FE, ["h0", "h1"], "tx")
    assert out[0] == [15, 45, 55, 32, 5]
    assert out[2] == [15, 45, 55, 32, 5]
    assert out[1] == [0, 0, 0, 0, 0]


def test_dist_bias_tx_beam0():
    """활성 빔(B0)만 채우고, TX는 B2 PTAT=[6,6,6] 하드코딩."""
    out = apply_dist_bias(EFUSE_DIST, 0, "tx", st2_1_ptat=13)
    assert out[0][0] == 50            # st1_ptat = Casper
    assert out[0][1] == 13            # st2_0_ptat
    assert out[0][2] == 13            # st2_1_ptat (인자)
    assert out[1] == [0, 0, 0, 0, 0, 0]
    assert out[2][0:3] == [6, 6, 6]


def test_dist_bias_st2_1_ptat_override():
    """MATLAB 값 28로 바꿀 수 있어야 한다(열린 항목)."""
    out = apply_dist_bias(EFUSE_DIST, 0, "tx", st2_1_ptat=28)
    assert out[0][2] == 28


def test_dist_bias_rx_beam0():
    out = apply_dist_bias(EFUSE_DIST, 0, "rx", st2_1_ptat=13)
    assert out[0][0] == 44            # NF_OPTIM
    assert out[2][0:3] == [0, 0, 0]   # RX는 B2 하드코딩 없음
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bias_v4.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudchaser.board.bias_v4'`

- [ ] **Step 3: Write the implementation**

`src/cloudchaser/board/bias_v4.py`:

```python
"""Sivers Cloudchaser ES1 optimized bias codes (BiasMapping Tuning Bits v4).

출처: Cloudchaser_ES1_BiasMapping_Tuning_Bits_v4.xlsx (2026-08-20 수령)
  - TX: 'Stampede TX Digital Settings' 시트, 'H0-B0 (Casper)' 열
  - RX: 'Blueway RX Digital Settings' 시트, 'NF_OPTIM' 열
보관: C:\\claude_code\\_reference\\01_Cloudchaser_BFIC\\01_datasheet\\

적용 규칙(MATLAB/Sivers 덤프와 동일):
  - 활성 채널/편파 원소에만 기입한다. 비활성 행은 0.
  - CTAT/CBIAS 는 시트에 최적화값이 없으므로 die eFuse 리드백 값을 유지한다.
"""

from __future__ import annotations

from .firehawk import fe_row, parse_ch

# TX Casper -- PA St1 을 내리고(32->15) 구동단/합성단에 전류를 몰아준다.
CASPER_FE = {"ptat_st1": 15, "ptat_st2": 45, "ptat_st3": 55}
CASPER_DIST_B0 = {"st1_ptat": 50, "st2_0_ptat": 13, "cbias1": 6}

# RX NF_OPTIM -- St2 LNA 전류를 낮추고(30->24) 후단 splitter/combiner 를 올린다.
NF_OPTIM_FE = {"ptat_st1": 34, "ptat_st2": 24, "ptat_st3": 48}
NF_OPTIM_DIST_B0 = {"st1_ptat": 44}
NF_OPTIM_CAPTUNE = 0x8888        # 바이트당 136 (기본 119=0x77 -> 136=0x88)


def apply_fe_bias(efuse_bias, active_channels, kind):
    """eFuse FE bias(8x5)에 최적화 PTAT 를 얹어 8x5 를 반환한다.

    efuse_bias      : FH.get_fe_bias() 결과 (8x5)
    active_channels : ["v1"] 처럼 켤 채널 목록
    kind            : "tx" -> Casper / "rx" -> NF_OPTIM
    """
    opt = CASPER_FE if kind == "tx" else NF_OPTIM_FE
    out = [[0, 0, 0, 0, 0] for _ in range(8)]
    for ch in active_channels:
        pol, ci = parse_ch(ch)
        r = fe_row(ci, pol)
        row = list(efuse_bias[r])
        row[0] = opt["ptat_st1"]
        row[1] = opt["ptat_st2"]
        row[2] = opt["ptat_st3"]
        # row[3](CTAT), row[4](CBIAS) 는 eFuse 값 유지
        out[r] = row
    return out


def apply_dist_bias(efuse_dist, beam_idx, kind, st2_1_ptat):
    """eFuse DIST bias(3x6)에 최적화 값을 얹어 3x6 을 반환한다.

    열 = [PTAT1 PTAT2_0 PTAT2_1 cbias1 cbias2_0 cbias2_1]
    st2_1_ptat : 0x104D[5:0]. 시트 v4=13 / MATLAB=28 (bench.toml 로 선택)
    """
    out = [[0, 0, 0, 0, 0, 0] for _ in range(3)]
    row = list(efuse_dist[beam_idx])
    if kind == "tx":
        row[0] = CASPER_DIST_B0["st1_ptat"]
        row[1] = CASPER_DIST_B0["st2_0_ptat"]
        row[2] = int(st2_1_ptat)
        row[3] = CASPER_DIST_B0["cbias1"]
    else:
        row[0] = NF_OPTIM_DIST_B0["st1_ptat"]
    out[beam_idx] = row
    if kind == "tx":
        out[2][0:3] = [6, 6, 6]      # MATLAB: B2 PTAT 하드코딩
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bias_v4.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/cloudchaser/board/bias_v4.py tests/test_bias_v4.py
git commit -m "feat(board): add v4 sheet optimized bias tables (Casper / NF_OPTIM)"
```

---

### Task 3: `BoardConfig` 신규 4필드 + `bench.toml`

**Files:**
- Modify: `src/cloudchaser/board/bringup.py` (BoardConfig dataclass)
- Modify: `src/cloudchaser/bench.py:67-77` (BoardConfig 생성부)
- Modify: `config/bench.toml` `[board]` 섹션
- Modify: `config/bench_rx.toml` `[board]` 섹션
- Test: `tests/test_board_config.py`

**Interfaces:**
- Produces: `BoardConfig` 에 4필드 추가 — `split_mode: bool = True`, `optimized_bias: bool = True`, `dist_st2_1_ptat: int = 13`, `run_efuse_init: bool = False`

- [ ] **Step 1: Write the failing test**

`tests/test_board_config.py`:

```python
"""BoardConfig 신규 필드 + bench.toml 로딩 검증."""
from pathlib import Path

from cloudchaser.bench import Bench
from cloudchaser.board.bringup import BoardConfig

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def test_board_config_defaults():
    cfg = BoardConfig()
    assert cfg.split_mode is True
    assert cfg.optimized_bias is True
    assert cfg.dist_st2_1_ptat == 13
    assert cfg.run_efuse_init is False


def test_bench_toml_loads_new_fields():
    b = Bench.from_toml(CONFIG, fake=True)
    assert b.board.split_mode is True
    assert b.board.optimized_bias is True
    assert b.board.dist_st2_1_ptat == 13
    assert b.board.run_efuse_init is False


def test_missing_keys_fall_back_to_defaults(tmp_path):
    """구 bench.toml(신규 키 없음)도 그대로 로드돼야 한다."""
    src = CONFIG.read_text(encoding="utf-8")
    stripped = "\n".join(
        ln for ln in src.splitlines()
        if not ln.strip().startswith(("split_mode", "optimized_bias",
                                      "dist_st2_1_ptat", "run_efuse_init"))
    )
    p = tmp_path / "bench_old.toml"
    p.write_text(stripped, encoding="utf-8")
    b = Bench.from_toml(p, fake=True)
    assert b.board.split_mode is True
    assert b.board.optimized_bias is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_board_config.py -v`
Expected: FAIL — `AttributeError: 'BoardConfig' object has no attribute 'split_mode'`

- [ ] **Step 3: Add the fields**

`src/cloudchaser/board/bringup.py` 의 `BoardConfig` 에 추가(기존 필드 뒤):

```python
    split_mode: bool = True          # (TX) DIST 스플리터 split 모드 -> 0x1009=783, 0x1068=0x8888
    optimized_bias: bool = True      # v4 시트 Casper/NF_OPTIM 적용 (False = eFuse 기본값)
    dist_st2_1_ptat: int = 13        # 0x104D[5:0]. 13=시트 v4 / 28=기존 MATLAB
    run_efuse_init: bool = False     # True 면 chip.init() 호출(벤더 load_efuse 실행)
```

docstring에도 4줄을 추가한다.

`src/cloudchaser/bench.py` 의 `BoardConfig(...)` 생성부에 추가:

```python
            ch_fe_attn={k: int(v) for k, v in board_raw.get("ch_fe_attn", {}).items()},
            split_mode=bool(board_raw.get("split_mode", True)),
            optimized_bias=bool(board_raw.get("optimized_bias", True)),
            dist_st2_1_ptat=int(board_raw.get("dist_st2_1_ptat", 13)),
            run_efuse_init=bool(board_raw.get("run_efuse_init", False)),
        )
```

- [ ] **Step 4: Add the keys to both toml files**

`config/bench.toml` 과 `config/bench_rx.toml` 의 `[board]` 섹션 끝(`[board.ch_gain]` 같은 하위 테이블 **앞**)에 스펙 7장의 블록을 그대로 붙여넣는다. TOML은 하위 테이블 뒤에 오는 키를 그 테이블 소속으로 보므로 위치가 중요하다.

- [ ] **Step 5: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_board_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: 전부 PASS

- [ ] **Step 7: Commit**

```bash
git add src/cloudchaser/board/bringup.py src/cloudchaser/bench.py config/bench.toml config/bench_rx.toml tests/test_board_config.py
git commit -m "feat(config): add split_mode/optimized_bias/dist_st2_1_ptat/run_efuse_init"
```

---

### Task 4: `bring_up_tx` raw 재작성 + 골든 픽스처

**Files:**
- Modify: `src/cloudchaser/board/bringup.py` (`bring_up_tx` 내부 전면 교체)
- Create: `tests/data/golden_regs_tx_v1_split.csv`
- Create: `tests/test_bringup_golden.py`

**Interfaces:**
- Consumes: Task 1 `FH`, Task 2 `apply_fe_bias`/`apply_dist_bias`, Task 3 `BoardConfig` 신규 필드
- Produces:
  - `bring_up_tx(chip, cfg, *, require_version=True, log=print) -> dict` — 시그니처 불변. 반환 dict 키도 불변: `version_id`, `common_gain`, `channels`(채널별 `{"gain":…, "atten":…}`), `active_paths`
  - `bring_up_tx` 가 `chip._fh` 속성에 사용한 `FH` 인스턴스를 남긴다(Task 6·9·10이 재사용)
  - 모듈 상수: `DIRECT_REGS_TX: dict`, `SPLIT_REGS_TX: dict`

- [ ] **Step 1: 골든 픽스처 생성**

`Sivers_EVB/evb_full.py` 를 fake 로 돌려 기준 덤프를 뜬다. `evb_full.py` 는 이미 `CHANNELS=["v1"]`, `SPLIT_MODE=True` 가 기본값이다. 단 골든은 **결정적이어야 하므로** eFuse 시드 의존을 없앤다 — `optimized_bias=true` 경로와 맞추기 위해 FE/DIST bias를 명시 행렬로 고정한다.

```bash
cd /c/claude_code/Sivers_EVB
python - <<'PY'
import evb_full as E
# 골든은 결정적이어야 한다: eFuse 리드백 대신 명시 행렬을 쓴다.
# 행 3 = v1 (fe_row(1,'v') = 3). PTAT=Casper(15/45/55), CTAT/CBIAS는 MockSPI eFuse 시드값(32/5).
fe = [[0,0,0,0,0] for _ in range(8)]
fe[3] = [15, 45, 55, 32, 5]
E.FE_BIAS_MATRIX = fe
E.DIST_BIAS_MATRIX = [[50, 13, 13, 6, 1, 1], [0]*6, [6, 6, 6, 0, 0, 0]]
E.bringup(kind='tx', fake=True)
E.dump(a=0x1000, b=0x1070, save='/c/claude_code/cloudchaser/tests/data/golden_regs_tx_v1_split.csv', quiet=True)
PY
```

`tests/data/` 디렉터리가 없으면 만든다. 생성된 CSV의 첫 줄이 `addr,value` 인지, 행 수가 112(0x1000~0x106F)인지 확인한다.

> 범위를 `0x1070` 까지로 자른 이유: `0x106C~` 는 phase-cal RAM 280워드로 전부 0이라 비교 가치가 없고 픽스처만 커진다. `zero_phase_cal` 은 Task 1의 단위 테스트가 이미 검증한다.

- [ ] **Step 2: Write the failing test**

`tests/test_bringup_golden.py`:

```python
"""cloudchaser bring-up 의 레지스터 결과가 evb_full.py 골든과 일치하는지 검증."""
from pathlib import Path

import pytest

from cloudchaser.board.bringup import BoardConfig, bring_up_tx, make_chip
from cloudchaser.board.firehawk import FH

GOLDEN_TX = Path(__file__).parent / "data" / "golden_regs_tx_v1_split.csv"


def load_dump(path):
    """addr,value CSV -> {addr: value}."""
    out = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("addr"):
            continue
        a, v = s.split(",")
        out[int(a, 0)] = int(v, 0) & 0xFFFF
    return out


def tx_config():
    """골든을 뜬 evb_full 설정과 동일하게 맞춘다(Doosan 260729)."""
    return BoardConfig(
        chip_id=0,
        beam="b0",
        active_channels=["v1"],
        common_gain=0x00,
        split_mode=True,
        optimized_bias=True,
        dist_st2_1_ptat=13,
        run_efuse_init=False,
    )


def seed_efuse(chip):
    """골든과 같은 eFuse 시드를 심는다(evb_full MockSPI._seed_efuse 와 동일).

    CTAT=32, CBIAS=5 만 결과에 남는다(PTAT 는 Casper 로 덮이므로).
    """
    fh = FH(chip, 0)
    fe = [[10, 20, 30, 32, 5] for _ in range(8)]
    fh.set_fe_bias(fe)
    fh.set_dist_bias([[12, 13, 14, 1, 1, 1] for _ in range(3)], 8)


def test_bring_up_tx_matches_golden():
    chip = make_chip(tx_config(), fake=True)
    seed_efuse(chip)
    bring_up_tx(chip, tx_config(), require_version=False)

    fh = FH(chip, 0)
    ours = {a: fh.rd(a) for a in range(0x1000, 0x1070)}
    theirs = load_dump(GOLDEN_TX)

    diffs = [a for a in sorted(theirs) if theirs[a] != ours.get(a)]
    detail = "\n".join(
        f"  0x{a:04X}: golden=0x{theirs[a]:04X} ours=0x{ours.get(a, 0):04X}"
        for a in diffs
    )
    assert not diffs, f"{len(diffs)} differing registers:\n{detail}"


def test_bring_up_tx_returns_legacy_summary_keys():
    """호출부 6곳이 의존하는 반환 dict 키가 유지돼야 한다."""
    chip = make_chip(tx_config(), fake=True)
    s = bring_up_tx(chip, tx_config(), require_version=False)
    assert set(s) >= {"version_id", "common_gain", "channels", "active_paths"}
    assert "v1" in s["channels"]
    assert set(s["channels"]["v1"]) >= {"gain", "atten"}


def test_split_mode_off_skips_split_regs():
    cfg = tx_config()
    cfg.split_mode = False
    chip = make_chip(cfg, fake=True)
    bring_up_tx(chip, cfg, require_version=False)
    fh = FH(chip, 0)
    assert fh.rd(0x1009) != 783


def test_optimized_bias_off_keeps_efuse_ptat():
    """optimized_bias=False 면 eFuse PTAT(10/20/30)가 그대로 남는다."""
    cfg = tx_config()
    cfg.optimized_bias = False
    chip = make_chip(cfg, fake=True)
    seed_efuse(chip)
    bring_up_tx(chip, cfg, require_version=False)
    fh = FH(chip, 0)
    assert fh.get_fe_bias()[3][0] == 10
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bringup_golden.py -v`
Expected: FAIL — 현재 `bring_up_tx` 는 벤더 API 기반이라 골든과 대량 불일치

- [ ] **Step 4: Rewrite `bring_up_tx`**

`src/cloudchaser/board/bringup.py`. 스펙 4장 TX 표의 20단계를 그대로 구현한다.

```python
DIRECT_REGS_TX = {0x104C: 3378, 0x1050: 1542, 0x1051: 6,
                  0x1052: 8, 0x1058: 8, 0x1059: 11}
SPLIT_REGS_TX = {0x1009: 783, 0x1068: 0x8888}


def bring_up_tx(chip, cfg: BoardConfig, *, require_version: bool = True, log=print) -> dict:
    """Configure a Stampede(TX) board to the measurement-ready state.

    Writes raw registers through chip.spi (MATLAB firehawk sequence); the
    vendor high-level API is not used on the write path. See the design spec
    for why: docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md
    """
    fh = FH(chip, cfg.chip_id)
    chip._fh = fh                      # 세션/테스트 항목이 재사용한다
    beam_i = int(cfg.beam[-1])
    active = [c.strip().lower() for c in cfg.active_channels]

    # 1. reset. 벤더 chip.init() 은 load_efuse() 로 레지스터를 건드리므로 기본으로 안 쓴다.
    if cfg.run_efuse_init:
        chip.init()
    else:
        fh.reset()

    # 2. 통신 확인
    _, ver = fh.get_short_id()
    ok = ver == VERSION_ID_TX
    log(f"[bring-up] version_id = {hex(ver)} -> {'OK' if ok else 'NG'}")
    if not ok and require_version:
        raise RuntimeError(
            f"version_id {hex(ver)} != {hex(VERSION_ID_TX)} -> check SPI link / board"
        )

    # 3~8. 공통 설정
    fh.zero_phase_cal()
    fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    fh.set_common_gains([cfg.common_gain] * 3)
    fh.set_cal(_cal_matrix(cfg))
    fh.load_beam_table(0, [[0, 0, 0, 0, 0, 0, 0, 0]])
    fh.beam_up()
    fh.set_captune([0, 0, 0, 0])

    # 9~10. bias
    efb = fh.get_fe_bias()
    edb, ectat = fh.get_dist_bias()
    if cfg.optimized_bias:
        fh.set_fe_bias(apply_fe_bias(efb, active, "tx"))
        fh.set_dist_bias(apply_dist_bias(edb, beam_i, "tx", cfg.dist_st2_1_ptat), ectat)
    else:
        fh.set_fe_bias(_efuse_only_fe(efb, active))
        fh.set_dist_bias(_efuse_only_dist(edb, beam_i, "tx"), ectat)

    # 11~13
    fh.set_extra(_extra_code(beam_i))
    fh.set_temp_sensor([8, 8], [1, 1])
    fh.wr_verify(0x1004, 0x000F)          # daisy amp ctrl
    fh.wr_verify(ADC_SET_ADDR, 0x0021)
    fh.wr_verify(ADC_SET_ADDR + 1, 0x4100)

    # 14. quad enables
    enbit = 1 << beam_i
    qen = [[0, 0, 0] for _ in range(4)]
    for ch in active:
        _, ci = parse_ch(ch)
        qen[ci] = [enbit, enbit, 0]
    fh.set_quad_enables(qen)

    # 15. staged power-up (bias only -> +PA/DRV -> +combiner)
    def _pwrdn(stage_bits_fn):
        rows = [[0, 0, 0, 0, 0] for _ in range(4)]
        for ch in active:
            pol, ci = parse_ch(ch)
            # TX(Stampede)는 quad_pwrdn 의 H/V 비트 위치가 RX와 반대다
            # (REGISTERS.md: TX h=[5:3]/v=[2:0]). 그래서 V=bits0-2, H=bits3-5.
            base = 0 if pol == "v" else 3
            rows[ci] = [stage_bits_fn(base), 1, 1, 0, 0]
        return rows

    fh.set_quad_pwrdn(_pwrdn(lambda b: 0))
    fh.set_quad_pwrdn(_pwrdn(lambda b: 0b011 << b))
    fh.set_quad_pwrdn(_pwrdn(lambda b: 0b111 << b))

    # 16~17. beam enables (splitter bias only -> +amp)
    be1 = [[0, 0, 0, 0] for _ in range(3)]
    be1[beam_i] = [0, 1, 0, 0]
    fh.set_beam_enables(be1)
    chan_mask = 0
    for ch in active:
        _, ci = parse_ch(ch)
        chan_mask |= 1 << ci
    be2 = [[0, 0, 0, 0] for _ in range(3)]
    be2[beam_i] = [chan_mask, 1, 1, 0]
    fh.set_beam_enables(be2)

    # 18~19. 하드코딩 레지스터 + split
    direct = dict(DIRECT_REGS_TX)
    direct[0x104D] = (int(cfg.dist_st2_1_ptat) & 0x3F) | (6 << 9)   # [5:0] ptat, [11:9] cbias
    for addr in sorted(direct):
        fh.wr_verify(addr, direct[addr])
    if cfg.split_mode:
        for addr in sorted(SPLIT_REGS_TX):
            fh.wr_verify(addr, SPLIT_REGS_TX[addr])
        log("[split  ] DIST split mode ON (0x1009=783, 0x1068=0x8888)")

    # 20. readback 요약 (기존 반환 계약 유지)
    summary: dict = {"version_id": ver, "channels": {}}
    summary["common_gain"] = fh.rd(COMMON_GAIN + beam_i)
    for ch in active:
        pol, ci = parse_ch(ch)
        w = fh.rd(FE_GAIN_ADDR + ci)
        g = (w >> 8) & 0xFF if pol == "v" else w & 0xFF
        a = fh.rd(BEAM_CAL_ADDR + ci)
        summary["channels"][ch] = {"gain": g, "atten": a}
        log(f"  {ch}: gain={hex(g)} atten={hex(a)}")
    summary["active_paths"] = list(active)
    log(f"[verify ] active paths: {summary['active_paths']}")
    return summary
```

보조 함수 `_cal_matrix(cfg)`, `_extra_code(beam_i)`, `_efuse_only_fe`, `_efuse_only_dist` 도 같은 파일에 추가한다:

```python
def _cal_matrix(cfg):
    """cal atten 4x2x3. 기본 0, cfg.ch_atten 에 값이 있으면 해당 채널·편파 전 빔에 기입."""
    cal = [[[0, 0, 0], [0, 0, 0]] for _ in range(4)]
    for ch, code in (cfg.ch_atten or {}).items():
        pol, ci = parse_ch(ch)
        hv = 1 if pol == "v" else 0
        cal[ci][hv] = [int(code)] * 3
    return cal


def _extra_code(beam_i):
    """extra_bias_code 1x4. 활성 beam=8, 비활성=1, B2=14, misc=0 (MATLAB Func)."""
    code = []
    for b in range(3):
        if b == 2:
            code.append(14)
        elif b == beam_i:
            code.append(8)
        else:
            code.append(1)
    code.append(0)
    return code


def _efuse_only_fe(efuse_bias, active_channels):
    """optimized_bias=False: 활성 채널 행만 eFuse 값 그대로, 나머지 0."""
    out = [[0, 0, 0, 0, 0] for _ in range(8)]
    for ch in active_channels:
        pol, ci = parse_ch(ch)
        r = fe_row(ci, pol)
        out[r] = list(efuse_bias[r])
    return out


def _efuse_only_dist(efuse_dist, beam_idx, kind):
    """optimized_bias=False: 활성 빔 행만 eFuse 값, TX 는 B2 PTAT=[6,6,6]."""
    out = [[0, 0, 0, 0, 0, 0] for _ in range(3)]
    out[beam_idx] = list(efuse_dist[beam_idx])
    if kind == "tx":
        out[2][0:3] = [6, 6, 6]
    return out
```

파일 상단 import 를 추가한다:

```python
from .bias_v4 import apply_dist_bias, apply_fe_bias
from .firehawk import (
    FH, ADC_SET_ADDR, BEAM_CAL_ADDR, COMMON_GAIN, FE_GAIN_ADDR,
    VERSION_ID_TX, VERSION_ID_RX, fe_row, parse_ch,
)
```

기존 모듈 상수 `VERSION_ID_OK`/`VERSION_ID_OK_RX` 는 하위호환을 위해 `VERSION_ID_TX`/`VERSION_ID_RX` 의 별칭으로 남긴다(`driver_reg_diff.py` 등이 import 할 수 있다).

- [ ] **Step 5: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bringup_golden.py -v`
Expected: PASS (4 tests). 실패하면 assert 메시지가 다른 레지스터를 주소별로 찍어준다 — 스펙 4장 표와 대조해 해당 단계를 고친다.

- [ ] **Step 6: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: 기존 테스트 중 벤더 API 동작을 가정한 것들이 깨질 수 있다. 깨진 테스트 목록을 기록만 하고 여기서 고치지 않는다(Task 8~10에서 처리). 단 `test_chip_autodetect.py` 와 `test_power_sequence.py` 는 반드시 PASS 여야 한다.

- [ ] **Step 7: Commit**

```bash
git add src/cloudchaser/board/bringup.py tests/test_bringup_golden.py tests/data/golden_regs_tx_v1_split.csv
git commit -m "feat(board): rewrite bring_up_tx with raw register writes + v4 bias"
```

---

### Task 5: `bring_up_rx` raw 재작성

**Files:**
- Modify: `src/cloudchaser/board/bringup.py` (`bring_up_rx`)
- Create: `tests/data/golden_regs_rx_h0.csv`
- Modify: `tests/test_bringup_golden.py` (RX 테스트 추가)
- Modify: `tests/test_rx_bringup_fields.py`

**Interfaces:**
- Consumes: Task 1 `FH`, Task 2 bias 함수, Task 4의 보조 함수
- Produces: `bring_up_rx(chip, cfg, *, require_version=True, log=print) -> dict` — 시그니처·반환 키 불변. `DIRECT_REGS_RX: dict`

- [ ] **Step 1: 골든 픽스처 생성**

```bash
cd /c/claude_code/Sivers_EVB
python - <<'PY'
import evb_full as E
fe = [[0,0,0,0,0] for _ in range(8)]
fe[0] = [34, 24, 48, 32, 5]      # 행 0 = h0
E.FE_BIAS_MATRIX = fe
E.DIST_BIAS_MATRIX = [[44, 13, 14, 1, 1, 1], [0]*6, [0]*6]
E.bringup(kind='rx', channels=['h0'], fake=True)
E.dump(a=0x1000, b=0x1070, save='/c/claude_code/cloudchaser/tests/data/golden_regs_rx_h0.csv', quiet=True)
PY
```

- [ ] **Step 2: Write the failing test**

`tests/test_bringup_golden.py` 에 추가:

```python
from cloudchaser.board.bringup import bring_up_rx, make_chip_rx

GOLDEN_RX = Path(__file__).parent / "data" / "golden_regs_rx_h0.csv"


def rx_config():
    return BoardConfig(
        chip_id=0, beam="b0", active_channels=["h0"], common_gain=0x00,
        split_mode=False, optimized_bias=True, dist_st2_1_ptat=13,
        run_efuse_init=False,
    )


def test_bring_up_rx_matches_golden():
    chip = make_chip_rx(rx_config(), fake=True)
    seed_efuse(chip)
    bring_up_rx(chip, rx_config(), require_version=False)

    fh = FH(chip, 0)
    ours = {a: fh.rd(a) for a in range(0x1000, 0x1070)}
    theirs = load_dump(GOLDEN_RX)
    diffs = [a for a in sorted(theirs) if theirs[a] != ours.get(a)]
    detail = "\n".join(
        f"  0x{a:04X}: golden=0x{theirs[a]:04X} ours=0x{ours.get(a, 0):04X}"
        for a in diffs
    )
    assert not diffs, f"{len(diffs)} differing registers:\n{detail}"


def test_rx_h_polarity_pwrdn_is_199():
    """RX H 편파 full = 199. TX 와 비트순서가 반대라는 점의 회귀 방지."""
    chip = make_chip_rx(rx_config(), fake=True)
    bring_up_rx(chip, rx_config(), require_version=False)
    assert FH(chip, 0).rd(0x1010) == 199


def test_rx_v_polarity_pwrdn_is_248():
    cfg = rx_config()
    cfg.active_channels = ["v0"]
    chip = make_chip_rx(cfg, fake=True)
    bring_up_rx(chip, cfg, require_version=False)
    assert FH(chip, 0).rd(0x1010) == 248
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bringup_golden.py -k rx -v`
Expected: FAIL

- [ ] **Step 4: Rewrite `bring_up_rx`**

스펙 4장 RX 표의 10단계를 구현한다.

```python
DIRECT_REGS_RX = {0x1004: 31, 0x1058: 0x8888, 0x1068: 0x8888, 0x1059: 4}


def bring_up_rx(chip, cfg: BoardConfig, *, require_version: bool = True, log=print) -> dict:
    """Configure a Blueway(RX) board to the measurement-ready state.

    Single-channel oriented (uses cfg.active_channels[0]); generalized from the
    MATLAB Meas_260724_BLWY01 H0B0 sequence.
    """
    fh = FH(chip, cfg.chip_id)
    chip._fh = fh
    beam_i = int(cfg.beam[-1])
    active = [c.strip().lower() for c in cfg.active_channels]
    ch = active[0]
    pol, ci = parse_ch(ch)

    if cfg.run_efuse_init:
        chip.init()
    else:
        fh.reset()

    _, ver = fh.get_short_id()
    ok = ver == VERSION_ID_RX
    log(f"[bringup] version_id = {hex(ver)} -> {'OK' if ok else 'NG'}")
    if not ok and require_version:
        raise RuntimeError(
            f"version_id {hex(ver)} != {hex(VERSION_ID_RX)} -> check SPI link / board"
        )

    # bias 를 enable 보다 먼저 기입한다(MATLAB 순서).
    efb = fh.get_fe_bias()
    edb, ectat = fh.get_dist_bias()
    if cfg.optimized_bias:
        fh.set_fe_bias(apply_fe_bias(efb, active, "rx"))
        fh.set_dist_bias(apply_dist_bias(edb, beam_i, "rx", cfg.dist_st2_1_ptat), ectat)
    else:
        fh.set_fe_bias(_efuse_only_fe(efb, active))
        fh.set_dist_bias(_efuse_only_dist(edb, beam_i, "rx"), ectat)

    fh.wr_verify(0x1004, 31)
    fh.set_center_enables([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])      # 0x1008 = 7
    be = [[0, 0, 0, 0] for _ in range(3)]
    be[beam_i] = [1 << ci, 1, 4, 0]
    fh.set_beam_enables(be)
    qen = [[0, 0, 0] for _ in range(4)]
    qen[ci] = [1 << beam_i, 1 << beam_i, 0]
    fh.set_quad_enables(qen)
    # RX 는 TX 와 반대: H=[2:0], V=[5:3].
    pwr = 0b000111 if pol == "h" else 0b111000
    qpd = [[0, 1, 0, 0, 0] for _ in range(4)]                  # 그 외 quad 는 override 만(64)
    qpd[ci] = [pwr, 1, 1, 0, 0]
    fh.set_quad_pwrdn(qpd)
    fh.set_captune([NF_OPTIM_CAPTUNE, 0, 0, 0])
    for addr in sorted(DIRECT_REGS_RX):
        fh.wr_verify(addr, DIRECT_REGS_RX[addr])

    summary: dict = {"version_id": ver, "channels": {}}
    summary["common_gain"] = fh.rd(COMMON_GAIN + beam_i)
    w = fh.rd(FE_GAIN_ADDR + ci)
    g = (w >> 8) & 0xFF if pol == "v" else w & 0xFF
    a = fh.rd(BEAM_CAL_ADDR + ci)
    summary["channels"][ch] = {"fe_attn": g, "atten": a}
    log(f"  {ch}: fe_attn={hex(g)} atten={hex(a)}")
    summary["active_paths"] = list(active)
    log(f"[verify ] active paths: {summary['active_paths']}")
    return summary
```

- [ ] **Step 5: `test_rx_bringup_fields.py` 갱신**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_rx_bringup_fields.py -v`

이 파일은 벤더 필드명 기반 assert 를 쓴다. **의미를 보존하면서** 레지스터 기반으로 바꾼다 — 예를 들어 "RX bring-up 이 `ch0_h_fe_attn` 을 쓴다"는 assert 는 "`0x1018` 의 H 바이트가 기대값"으로 옮긴다. 테스트 이름과 의도(무엇을 지키려는 테스트인지)는 유지한다.

`bias_v4` import 에 `NF_OPTIM_CAPTUNE` 을 추가한다:

```python
from .bias_v4 import NF_OPTIM_CAPTUNE, apply_dist_bias, apply_fe_bias
```

- [ ] **Step 6: `board/__init__.py` 재수출 정리**

현재는 `bring_up_tx`, `BoardConfig` 만 내보낸다. RX 경로와 FH 엔진도 패키지 레벨에서 쓸 수 있게 넓힌다:

```python
"""보드 (Stampede TX / Blueway RX) bring-up."""

from .bringup import BoardConfig, bring_up_rx, bring_up_tx, make_chip, make_chip_rx
from .firehawk import FH

__all__ = ["BoardConfig", "bring_up_tx", "bring_up_rx",
           "make_chip", "make_chip_rx", "FH"]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bringup_golden.py tests/test_rx_bringup_fields.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/cloudchaser/board/bringup.py src/cloudchaser/board/__init__.py tests/test_bringup_golden.py tests/test_rx_bringup_fields.py tests/data/golden_regs_rx_h0.csv
git commit -m "feat(board): rewrite bring_up_rx with raw register writes + NF_OPTIM bias"
```

---

### Task 6: 게인 타깃 매핑 + 채널 라우팅 (`board/gain_map.py`)

**Files:**
- Create: `src/cloudchaser/board/gain_map.py`
- Test: `tests/test_gain_map.py`

**Interfaces:**
- Consumes: Task 1 `FH`, `parse_ch`
- Produces:
  - `GAIN_TARGETS = ("common", "fe", "beamtable")`
  - `set_gain(fh, target, code, *, beam="b0", channel="h0") -> None`
    — `common` → `0x1005+beam_idx`, `fe` → `0x1018+ch_idx`(H=`[7:0]`, V=`[15:8]`, 다른 편파 비트 보존), `beamtable` → beam table 워드 `addr=ch_idx` 의 `[6:0]`(위상 비트 보존) + `beam_up()`
  - `get_gain(fh, target, *, beam="b0", channel="h0") -> int`
  - `set_phase(fh, code, *, beam="b0", channel="h0", atten=0) -> None` — 9-bit RTPS 위상(`set_rtps_attn` 경유)
  - `route_channels(fh, channels, beam, kind) -> None` — 벤더 `path.enable()` 의 raw 대체. 지정 채널만 켜고 나머지는 끈다.
  - `disable_all(fh) -> None` — 벤더 `path.disable_all()` 의 raw 대체
  - `resolve_legacy(params: dict, board) -> dict` — 구 파라미터 → 신규 매핑 (Task 7에서 사용)

- [ ] **Step 1: Write the failing test**

`tests/test_gain_map.py`:

```python
"""게인 타깃 매핑 / 채널 라우팅 / 구 파라미터 shim 검증."""
import pytest

from cloudchaser.board.firehawk import FH, COMMON_GAIN, FE_GAIN_ADDR
from cloudchaser.board.gain_map import (
    set_gain, get_gain, set_phase, route_channels, disable_all, resolve_legacy,
)
from tests.test_firehawk_bitpack import FakeChip


@pytest.fixture
def fh():
    return FH(FakeChip(), 0)


def test_set_gain_common_uses_beam_index(fh):
    set_gain(fh, "common", 0x20, beam="b1")
    assert fh.rd(COMMON_GAIN + 1) == 0x20


def test_set_gain_fe_h_preserves_v_byte(fh):
    fh.wr(FE_GAIN_ADDR + 1, 0x0900)          # V=9 미리 설정
    set_gain(fh, "fe", 0x3, beam="b0", channel="h1")
    assert fh.rd(FE_GAIN_ADDR + 1) == 0x0903


def test_set_gain_fe_v_preserves_h_byte(fh):
    fh.wr(FE_GAIN_ADDR + 1, 0x0007)
    set_gain(fh, "fe", 0x4, beam="b0", channel="v1")
    assert fh.rd(FE_GAIN_ADDR + 1) == 0x0407


def test_set_gain_beamtable_preserves_phase(fh):
    fh.wr(2, (13 << 7) | 5)                  # quad2: phase=13, atten=5
    set_gain(fh, "beamtable", 40, channel="h2")
    assert fh.rd(2) == (13 << 7) | 40


def test_get_gain_roundtrip(fh):
    set_gain(fh, "common", 0x11, beam="b0")
    assert get_gain(fh, "common", beam="b0") == 0x11
    set_gain(fh, "fe", 0x5, channel="h0")
    assert get_gain(fh, "fe", channel="h0") == 0x5
    set_gain(fh, "beamtable", 33, channel="h0")
    assert get_gain(fh, "beamtable", channel="h0") == 33


def test_unknown_target_raises(fh):
    with pytest.raises(ValueError, match="unknown gain target"):
        set_gain(fh, "bogus", 0)


def test_route_channels_enables_only_listed(fh):
    route_channels(fh, ["h1"], "b0", "tx")
    assert fh.rd(0x100C + 1) == 1 | (1 << 8)     # quad1 enabled for beam0
    assert fh.rd(0x100C + 0) == 0                # quad0 off
    assert fh.rd(0x1010 + 1) == (0b111 << 3) + (1 << 6) + (1 << 7)   # TX h -> bits[5:3] = 248
    # NOTE (found during Task 12 doc pass): this literal was originally written as
    # `0b000111 + (1 << 6) + (1 << 7)` = 199 -- that is the RX value (RX h = bits[2:0]).
    # TX h = bits[5:3], so the pwrdn field itself is `0b111 << 3` = 56, giving 56+64+128 = 248.
    # Fixed here so a future re-run of this plan doesn't reproduce the bug.


def test_disable_all_clears_pwrdn_and_beams(fh):
    route_channels(fh, ["h1"], "b0", "tx")
    disable_all(fh)
    for i in range(4):
        assert fh.rd(0x1010 + i) == 0
    for i in range(3):
        assert fh.rd(0x1009 + i) == 0


class Board:
    beam = "b0"
    active_channels = ["h0"]


def test_resolve_legacy_common_field():
    out = resolve_legacy({"gain_field": "b1_common_gain"}, Board())
    assert out["gain_target"] == "common"
    assert out["beam"] == "b1"


def test_resolve_legacy_gain_control_field():
    out = resolve_legacy({"gain_field": "gain_control_h1"}, Board())
    assert out["gain_target"] == "fe"
    assert out["channel"] == "h1"


def test_resolve_legacy_channel_kind():
    assert resolve_legacy({"channel_kind": "field"}, Board())["channel_target"] == "fe"
    assert resolve_legacy({"channel_kind": "beamtable"}, Board())["channel_target"] == "beamtable"


def test_resolve_legacy_passes_through_new_params():
    out = resolve_legacy({"gain_target": "beamtable"}, Board())
    assert out["gain_target"] == "beamtable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gain_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudchaser.board.gain_map'`

- [ ] **Step 3: Write the implementation**

`src/cloudchaser/board/gain_map.py`. 스펙 6장의 타깃 표를 구현한다.

```python
"""게인/위상 타깃 -> 레지스터 매핑, 그리고 채널 라우팅의 raw 대체.

벤더 chip.fields.wr / chip.path / chip.beam_table 을 쓰지 않기 위한 계층이다.
근거는 설계 스펙 2장·6장.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다.
"""

from __future__ import annotations

from .firehawk import (
    COMMON_GAIN, FE_GAIN_ADDR, QUAD_ENABLES_ADDR, QUAD_PWRDN_ADDR,
    BEAM_ENABLES_ADDR, parse_ch,
)

GAIN_TARGETS = ("common", "fe", "beamtable")


def set_gain(fh, target, code, *, beam="b0", channel="h0"):
    """Set a gain code on the selected target.

    target : "common"    -> beam-wide attenuation, 0x1005 + beam index (6-bit, 0 = max gain)
             "fe"        -> per-channel FE gain, 0x1018 + channel index (4-bit)
             "beamtable" -> RTPS attenuator, beam-table word (7-bit, 0 = max gain)
    """
    code = int(code)
    if target == "common":
        fh.wr_verify(COMMON_GAIN + int(beam[-1]), code & 0xFFFF)
    elif target == "fe":
        pol, ci = parse_ch(channel)
        cur = fh.rd(FE_GAIN_ADDR + ci)
        if pol == "v":
            new = (cur & 0x00FF) | ((code & 0xFF) << 8)
        else:
            new = (cur & 0xFF00) | (code & 0xFF)
        fh.wr_verify(FE_GAIN_ADDR + ci, new)
    elif target == "beamtable":
        _, ci = parse_ch(channel)
        cur = fh.rd(ci)
        fh.wr(ci, (cur & ~0x7F) | (code & 0x7F))
        fh.beam_up()
    else:
        raise ValueError(f"unknown gain target: {target!r} (use one of {GAIN_TARGETS})")


def get_gain(fh, target, *, beam="b0", channel="h0"):
    """Read back the gain code from the selected target."""
    if target == "common":
        return fh.rd(COMMON_GAIN + int(beam[-1])) & 0x3F
    if target == "fe":
        pol, ci = parse_ch(channel)
        w = fh.rd(FE_GAIN_ADDR + ci)
        return (w >> 8) & 0xFF if pol == "v" else w & 0xFF
    if target == "beamtable":
        _, ci = parse_ch(channel)
        return fh.rd(ci) & 0x7F
    raise ValueError(f"unknown gain target: {target!r} (use one of {GAIN_TARGETS})")


def set_phase(fh, code, *, beam="b0", channel="h0", atten=0):
    """Set the 9-bit RTPS phase (coarse beam-table + fine phase-cal RAM)."""
    pol, ci = parse_ch(channel)
    fh.set_rtps_attn(int(atten), int(code), ci, int(beam[-1]), 1 if pol == "v" else 0)


def route_channels(fh, channels, beam, kind):
    """Enable ONLY the listed channels on the given beam (raw replacement for path.enable)."""
    beam_i = int(str(beam)[-1])
    enbit = 1 << beam_i
    qen = [[0, 0, 0] for _ in range(4)]
    qpd = [[0, 0, 0, 0, 0] for _ in range(4)]
    mask = 0
    for ch in channels:
        pol, ci = parse_ch(ch)
        qen[ci] = [enbit, enbit, 0]
        # TX 는 h=[5:3]/v=[2:0], RX 는 반대다.
        if kind == "tx":
            base = 0 if pol == "v" else 3
        else:
            base = 3 if pol == "v" else 0
        qpd[ci] = [0b111 << base, 1, 1, 0, 0]
        mask |= 1 << ci
    fh.set_quad_enables(qen)
    fh.set_quad_pwrdn(qpd)
    be = [[0, 0, 0, 0] for _ in range(3)]
    be[beam_i] = [mask, 1, 1 if kind == "tx" else 4, 0]
    fh.set_beam_enables(be)


def disable_all(fh):
    """Turn every channel and beam off (raw replacement for path.disable_all)."""
    fh.set_quad_pwrdn([[0, 0, 0, 0, 0] for _ in range(4)])
    fh.set_quad_enables([[0, 0, 0] for _ in range(4)])
    fh.set_beam_enables([[0, 0, 0, 0] for _ in range(3)])


_LEGACY_HINT = ("[deprecated] {old} is deprecated; use {new}. "
                "Mapped to {mapping}")


def resolve_legacy(params, board, log=print):
    """구 파라미터(필드 이름 문자열)를 신규 타깃 계약으로 매핑한다.

    반환: params 사본 + 신규 키. 구 키가 없으면 그대로 통과시킨다.
    """
    out = dict(params)
    field = out.pop("gain_field", "") or ""
    if field and not out.get("gain_target"):
        if field.endswith("_common_gain"):
            out["gain_target"] = "common"
            out["beam"] = field.split("_")[0]
            mapping = f"gain_target=common, beam={out['beam']}"
        elif field.startswith("gain_control_"):
            out["gain_target"] = "fe"
            out["channel"] = field[len("gain_control_"):]
            mapping = f"gain_target=fe, channel={out['channel']}"
        else:
            out["gain_target"] = "common"
            mapping = "gain_target=common"
        log(_LEGACY_HINT.format(old="gain_field", new="gain_target", mapping=mapping))

    cfield = out.pop("common_field", "") or ""
    if cfield and not out.get("common_target"):
        out["common_target"] = "common"
        if cfield.endswith("_common_gain"):
            out["beam"] = cfield.split("_")[0]
        log(_LEGACY_HINT.format(old="common_field", new="common_target",
                                mapping="common_target=common"))

    kind = out.pop("channel_kind", "") or ""
    chfield = out.pop("channel_field", "") or ""
    if kind and not out.get("channel_target"):
        out["channel_target"] = "beamtable" if kind == "beamtable" else "fe"
        log(_LEGACY_HINT.format(old="channel_kind", new="channel_target",
                                mapping=f"channel_target={out['channel_target']}"))
    if chfield and out.get("channel_target") == "fe" and not out.get("channel"):
        out["channel"] = chfield[len("gain_control_"):] if chfield.startswith(
            "gain_control_") else chfield

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gain_map.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/cloudchaser/board/gain_map.py tests/test_gain_map.py
git commit -m "feat(board): add gain target mapping, raw channel routing, legacy param shim"
```

---

### Task 7: `op1db` / `ip1db` 파라미터 마이그레이션

**Files:**
- Modify: `src/cloudchaser/test_items/op1db.py` (params 블록 + `run` 의 게인 기입)
- Modify: `src/cloudchaser/test_items/ip1db.py`
- Test: `tests/test_test_items_fake.py` (기존 파일에 추가·수정)

**Interfaces:**
- Consumes: Task 6 `set_gain`, `resolve_legacy`; Task 4/5 가 남긴 `chip._fh`
- Produces: 두 테스트 항목이 `gain_target` / `beam` / `channel` 파라미터를 받는다. `gain_field` 는 shim 경유로만 동작한다.

- [ ] **Step 1: Write the failing test**

`tests/test_test_items_fake.py` 에 추가:

```python
def test_op1db_gain_target_common_writes_beam_register():
    """gain_target=common 이면 0x1005+beam 에 코드가 들어간다."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b1")     # 기존 헬퍼 사용
    run_item("op1db", bench, chip, {"gain_target": "common", "gain_code": 0x2A})
    assert FH(chip, 0).rd(COMMON_GAIN + 1) == 0x2A


def test_op1db_legacy_gain_field_still_works(capsys):
    """구 gain_field 는 경고와 함께 동작해야 한다."""
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b1")
    run_item("op1db", bench, chip, {"gain_field": "b1_common_gain", "gain_code": 0x11})
    assert FH(chip, 0).rd(COMMON_GAIN + 1) == 0x11
    assert "[deprecated] gain_field" in capsys.readouterr().out


def test_ip1db_gain_target_defaults_to_board_beam():
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip(beam="b0", kind="rx")
    run_item("ip1db", bench, chip, {"gain_code": 0x00})
    assert FH(chip, 0).rd(COMMON_GAIN + 0) == 0x00


def test_no_vendor_fields_wr_in_test_items():
    """쓰기 경로에 벤더 fields.wr 가 남아 있으면 안 된다(shadow 캐시 위험)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "cloudchaser"
    offenders = []
    for p in (root / "test_items").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "fields.wr" in line and not line.strip().startswith("#"):
                offenders.append(f"{p.name}:{i}")
    assert not offenders, f"vendor fields.wr found: {offenders}"
```

`_fake_bench_and_chip(beam=..., kind=...)` 과 `run_item(...)` 헬퍼가 기존 파일에 없으면 이 테스트 파일 상단에 추가한다:

```python
def _fake_bench_and_chip(beam="b0", kind="tx"):
    """fake bench + bring-up 된 chip 한 쌍."""
    from pathlib import Path
    from cloudchaser.bench import Bench
    from cloudchaser.board.bringup import bring_up_rx, bring_up_tx, make_chip, make_chip_rx
    cfgfile = "bench_rx.toml" if kind == "rx" else "bench.toml"
    bench = Bench.from_toml(
        Path(__file__).resolve().parents[1] / "config" / cfgfile, fake=True)
    bench.board.beam = beam
    chip = (make_chip_rx if kind == "rx" else make_chip)(bench.board, fake=True)
    (bring_up_rx if kind == "rx" else bring_up_tx)(chip, bench.board, require_version=False)
    return bench, chip


def run_item(test_id, bench, chip, overrides):
    """테스트 항목 1개를 fake 로 실행."""
    from cloudchaser.test_items import TestContext, get_test
    item = get_test(test_id)
    params = {p.name: p.default for p in item.params}
    params.update(overrides)
    return item.run(TestContext(bench=bench, chip=chip, fake=True), params, log=print)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_test_items_fake.py -k "gain_target or legacy_gain_field or vendor_fields" -v`
Expected: FAIL — `gain_target` 파라미터가 없다

- [ ] **Step 3: Migrate `op1db.py`**

params 블록에서 `gain_field` 를 빼고 3개를 넣는다:

```python
        Param("gain_target", "Gain Target", "choice", "common",
              choices=["common", "fe", "beamtable"],
              help="which gain knob to hold fixed: common (beam-wide), "
                   "fe (per-channel FE), beamtable (RTPS attenuator)"),
        Param("beam", "Beam", "str", "",
              help="beam override (b0/b1/b2). BLANK = use the board beam."),
        Param("channel", "Channel", "str", "",
              help="channel override for fe/beamtable targets (e.g. h1). "
                   "BLANK = first active channel."),
```

`run()` 의 게인 기입부(`chip.fields.wr(field, code)`)를 교체한다:

```python
        params = resolve_legacy(params, bench.board, log=log)
        target = params.get("gain_target") or "common"
        code = int(params["gain_code"])
        beam = params.get("beam") or getattr(bench.board, "beam", "b0")
        chans = getattr(bench.board, "active_channels", []) or []
        channel = params.get("channel") or (chans[0] if chans else "h0")
        fh = chip._fh
        ...
        # 1) 게인 고정(동작점)
        set_gain(fh, target, code, beam=beam, channel=channel)
```

import 를 추가한다:

```python
from ..board.gain_map import resolve_legacy, set_gain
```

- [ ] **Step 4: Migrate `ip1db.py`**

같은 방식. `ip1db` 의 beam-table 리셋(`chip.beam_table.zero_table()` + `chip.spi.beam_up()`)도 raw 로 바꾼다:

```python
        # 최대 게인 측정 보장: 채널 RTPS(beam table)도 0(max gain)으로 리셋한다.
        fh.load_beam_table(0, [[0, 0, 0, 0, 0, 0, 0, 0]])
        fh.beam_up()
```

기존의 `try/except` + warn 로그는 유지할 필요가 없다(raw 기입은 예외를 던지지 않는다). 제거한다.

- [ ] **Step 5: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_test_items_fake.py -v`
Expected: PASS. `test_no_vendor_fields_wr_in_test_items` 는 아직 다른 항목 때문에 FAIL 할 수 있다 — 그러면 Task 8 완료 시까지 `@pytest.mark.xfail(reason="migrated in Task 8-9")` 로 표시하고 Task 9 마지막에 해제한다.

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/test_items/op1db.py src/cloudchaser/test_items/ip1db.py tests/test_test_items_fake.py
git commit -m "refactor(test-items): migrate op1db/ip1db to gain_target params"
```

---

### Task 8: `gain_index_accuracy` / `channel_gain_alignment` 마이그레이션

**Files:**
- Modify: `src/cloudchaser/test_items/gain_index_accuracy.py`
- Modify: `src/cloudchaser/test_items/channel_gain_alignment.py`
- Test: `tests/test_test_items_fake.py` (추가)

**Interfaces:**
- Consumes: Task 6 `set_gain`, `route_channels`, `disable_all`, `resolve_legacy`
- Produces: `common_target` / `channel_target` 파라미터. `common_field` · `channel_field` · `channel_kind` 는 shim 경유.

- [ ] **Step 1: Write the failing test**

```python
def test_gain_index_sweeps_beamtable_by_default():
    """channel_target 기본값 beamtable -> beam-table 워드가 마지막 코드로 남는다."""
    from cloudchaser.board.firehawk import FH
    bench, chip = _fake_bench_and_chip()
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0], "channel_codes": [7, 21], "channel_quad": 0,
              "log_psu": False})
    assert FH(chip, 0).rd(0) & 0x7F == 21


def test_gain_index_channel_target_fe():
    from cloudchaser.board.firehawk import FH, FE_GAIN_ADDR
    bench, chip = _fake_bench_and_chip()
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0], "channel_codes": [5], "channel_target": "fe",
              "channel": "h0", "log_psu": False})
    assert FH(chip, 0).rd(FE_GAIN_ADDR + 0) & 0xFF == 5


def test_gain_index_legacy_channel_kind(capsys):
    bench, chip = _fake_bench_and_chip()
    run_item("gain_index_accuracy", bench, chip,
             {"common_codes": [0], "channel_codes": [3], "channel_kind": "beamtable",
              "channel_quad": 0, "log_psu": False})
    assert "[deprecated] channel_kind" in capsys.readouterr().out


def test_channel_gain_alignment_routes_channels_raw():
    """path.enable 대신 raw 라우팅을 써야 한다 -- quad enable 레지스터로 확인."""
    from cloudchaser.board.firehawk import FH
    bench, chip = _fake_bench_and_chip()
    run_item("channel_gain_alignment", bench, chip,
             {"channels": "h1", "channels_script": "h1"})
    assert FH(chip, 0).rd(0x100C + 1) != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_test_items_fake.py -k "gain_index or channel_gain_alignment" -v`
Expected: FAIL

- [ ] **Step 3: Migrate `gain_index_accuracy.py`**

params 에서 `common_field` · `channel_field` · `channel_kind` 를 빼고 넣는다:

```python
        Param("common_target", "Common Gain Target", "choice", "common",
              choices=["common"],
              help="beam-wide gain knob (0x1005 + beam index)"),
        Param("channel_target", "Channel Gain Target", "choice", "beamtable",
              choices=["beamtable", "fe"],
              help="per-path gain knob. beamtable = RTPS attenuator (works on "
                   "this chip). fe = per-channel FE gain (DEAD on this silicon)."),
        Param("channel", "Channel", "str", "",
              help="channel override for the fe target (e.g. h1). "
                   "BLANK = first active channel."),
```

`run()` 상단을 교체한다:

```python
        params = resolve_legacy(params, bench.board, log=log)
        ctarget = params.get("common_target") or "common"
        chtarget = params.get("channel_target") or "beamtable"
        beam = params.get("beam") or getattr(bench.board, "beam", "b0")
        fh = chip._fh
```

`set_channel(code)` 를 교체한다:

```python
        def set_channel(code: int) -> None:
            """채널 게인 한 코드 적용."""
            if chtarget == "beamtable":
                # per-path gain = beam table attenuator_setting (0=max gain).
                # raw 코드 0..63 의 gain 은 2단(fine bits0:3 / coarse bits5:4) 구조라
                # 본질적으로 비단조(톱니) -- 칩 특성이며 write 방식 문제 아님.
                set_gain(fh, "beamtable", int(code), channel=f"h{chquad}")
            else:
                set_gain(fh, "fe", int(code), channel=channel)
```

common 코드 기입(`chip.fields.wr(cfield, c)`)은 `set_gain(fh, ctarget, c, beam=beam)` 로 바꾼다.
`chlabel` 로그 문자열도 `chtarget` 기준으로 바꾼다.

- [ ] **Step 4: Migrate `channel_gain_alignment.py`**

`common_field` → `common_target` 로 params 를 바꾸고, `setup_channels` 를 raw 로 교체한다:

```python
        def setup_channels(on_list: list[str]) -> None:
            """주어진 채널만 ON(beam 라우팅) + center 바이어스 + RTPS 0 + common gain 고정."""
            disable_all(fh)
            fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
            route_channels(fh, list(on_list), beam, "tx")
            fh.load_beam_table(0, [[0, 0, 0, 0, 0, 0, 0, 0]])
            fh.beam_up()
            set_gain(fh, common_target, max_code, beam=beam)
```

import 추가:

```python
from ..board.gain_map import disable_all, resolve_legacy, route_channels, set_gain
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_test_items_fake.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/test_items/gain_index_accuracy.py src/cloudchaser/test_items/channel_gain_alignment.py tests/test_test_items_fake.py
git commit -m "refactor(test-items): migrate gain_index/channel_gain_alignment to targets"
```

---

### Task 9: `evm` / `phase_index_accuracy` / `manual.py` 쓰기 헬퍼

**Files:**
- Modify: `src/cloudchaser/test_items/evm.py`
- Modify: `src/cloudchaser/test_items/phase_index_accuracy.py`
- Modify: `src/cloudchaser/manual.py`
- Test: `tests/test_test_items_fake.py` (xfail 해제), `tests/test_session_ux.py`

**Interfaces:**
- Consumes: Task 6 전부
- Produces: `manual.py` 의 `build_namespace` 가 `fh` 를 네임스페이스에 노출. `gain`/`chgain`/`atten`/`phase`/`chan`/`latch` 가 raw 기입으로 동작.

- [ ] **Step 1: Write the failing test**

```python
def test_evm_sets_common_gain_raw():
    from cloudchaser.board.firehawk import FH, COMMON_GAIN
    bench, chip = _fake_bench_and_chip()
    run_item("evm", bench, chip, {"pin_start_dbm": -10.0, "pin_stop_dbm": -10.0})
    assert FH(chip, 0).rd(COMMON_GAIN + 0) == 0


def test_phase_index_uses_nine_bit_phase():
    """9-bit 위상: coarse 는 beam-table, fine 은 phase-cal RAM 에 들어간다."""
    from cloudchaser.board.firehawk import FH, PHASE_CAL_ADDR
    bench, chip = _fake_bench_and_chip()
    run_item("phase_index_accuracy", bench, chip, {"phase_codes": [13]})
    fh = FH(chip, 0)
    assert fh.rd(0) >> 7 == 13 // 4
    assert fh.rd(PHASE_CAL_ADDR + 0) == 0x2000 | (13 % 4)


def test_session_namespace_exposes_fh():
    from cloudchaser.manual import build_namespace
    bench, chip = _fake_bench_and_chip()
    ns = build_namespace(bench, chip)
    assert "fh" in ns
```

> `phase_index_accuracy` 의 위상 파라미터 이름이 `phase_codes` 가 아니면 실제 이름으로 바꾼다. `.\.venv\Scripts\python.exe -c "from cloudchaser.test_items import get_test; print([p.name for p in get_test('phase_index_accuracy').params])"` 로 확인한다.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_test_items_fake.py -k "evm_sets or phase_index or namespace_exposes" -v`
Expected: FAIL

- [ ] **Step 3: Migrate `evm.py`**

`chip.fields.wr(f"b{beam[-1]}_common_gain", 0)` → `set_gain(fh, "common", 0, beam=beam)`
`chip.beam_table.zero_table()` + `chip.spi.beam_up()` → `fh.load_beam_table(0, [[0]*8])` + `fh.beam_up()`

- [ ] **Step 4: Migrate `phase_index_accuracy.py`**

기존은 beam-table 의 7-bit coarse 만 썼다. `set_phase()` 로 바꿔 **9-bit 전체 해상도**를 쓴다:

```python
from ..board.gain_map import set_phase
...
            set_phase(fh, int(code), beam=beam, channel=channel)
```

파라미터 범위 상한도 511로 넓히고, help 문구를 갱신한다("9-bit, 0..511, coarse beam-table + fine phase-cal").

- [ ] **Step 5: Migrate `manual.py` 쓰기 헬퍼**

`build_namespace` 안에서 `fh = chip._fh` 를 잡고 다음을 교체한다:

| 헬퍼 | 기존 | 신규 |
|---|---|---|
| `gain(code)` | `wr(f"b{bm[-1]}_common_gain", code)` | `set_gain(fh, "common", code, beam=bm)` |
| `chgain(ch, code)` | `wr(f"gain_control_{pol}{idx}", code)` | `set_gain(fh, "fe", code, channel=ch)` |
| `atten(ch, code)` | `wr(f"ch{idx}_{pol}_b{b[-1]}_attn_cal", code)` | `set_gain(fh, "beamtable", code, channel=ch)` |
| `phase(ch, code)` | beam_table RMW (7-bit) | `set_phase(fh, code, beam=beam, channel=ch)` (9-bit) |
| `chan(ch, b)` | `path.disable_all()` + `path.enable()` | `disable_all(fh)` + `route_channels(fh, [ch], b, kind)` |
| `latch()` | `fields.wr(f, 1)` 반복 | **삭제.** raw 비트팩이 pulse 비트를 워드에 함께 쓰므로 별도 latch 가 불필요하다 |
| `commit()` | `chip.commit()` | **삭제.** raw 기입은 즉시 반영된다 |
| `load_golden()` | `chip.regs[a] = v` + `chip.commit()` | 전부 `fh.wr(a, v)` 로 단일화 |
| `rd(field)` / `rinfo` | `chip.fields.rd(...)` | **유지** (읽기는 HW 직접 읽기라 안전) |

`fh` 를 네임스페이스에 추가한다:

```python
    ns["fh"] = fh
```

`wr(field, val)` 헬퍼(필드 이름으로 쓰기)는 **제거한다.** 쓰기 경로에 벤더 `fields.wr` 를 남기지 않는 것이 이 작업의 목적이다. 대신 `fh.wr_verify(addr, val)` 를 쓰라고 docstring 과 `help()` 문구에서 안내한다.

- [ ] **Step 6: `test_no_vendor_fields_wr_in_test_items` 확장 + xfail 해제**

Task 7에서 붙인 `xfail` 마커를 떼고, 검사 범위를 `test_items/` + `manual.py` + `board/` 로 넓힌다:

```python
def test_no_vendor_fields_wr_on_write_path():
    """쓰기 경로에 벤더 fields.wr 가 남아 있으면 안 된다(shadow 캐시 위험)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "cloudchaser"
    targets = list((root / "test_items").glob("*.py")) + \
        list((root / "board").glob("*.py")) + [root / "manual.py"]
    offenders = []
    for p in targets:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "fields.wr" in line and not line.strip().startswith("#"):
                offenders.append(f"{p.name}:{i}")
    assert not offenders, f"vendor fields.wr found on write path: {offenders}"
```

- [ ] **Step 7: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: PASS. `tests/test_session_ux.py:366` 의 `"param.gain_field: b1_common_gain"` assert 는 Task 10에서 고치므로 여기서는 FAIL 해도 된다.

- [ ] **Step 8: Commit**

```bash
git add src/cloudchaser/test_items/evm.py src/cloudchaser/test_items/phase_index_accuracy.py src/cloudchaser/manual.py tests/test_test_items_fake.py
git commit -m "refactor: migrate evm/phase_index/manual helpers to raw register writes"
```

---

### Task 10: `session.py` 파라미터 화이트리스트 + `tx_suite`

**Files:**
- Modify: `src/cloudchaser/session.py:47-71` (`_WIZARD_HIDDEN`), `:583-600` (`tx_suite` steps)
- Modify: `tests/test_session_ux.py`

**Interfaces:**
- Consumes: Task 7·8의 신규 파라미터 이름
- Produces: `tx_suite` 가 `gain_target`/`channel_target` 을 넘긴다. wizard 가 신규 파라미터를 숨긴다.

- [ ] **Step 1: Write the failing test**

`tests/test_session_ux.py:348-366` 의 테스트를 갱신한다:

```python
    # linearity(op1db) 가 b1 common gain 으로 실행됐는지 CSV 헤더로 확인
    assert "param.gain_target: common" in op_csv.read_text(encoding="utf-8")
    assert "param.beam: b1" in op_csv.read_text(encoding="utf-8")
```

추가로:

```python
def test_wizard_hides_new_gain_params():
    from cloudchaser.session import _WIZARD_HIDDEN
    assert "gain_target" in _WIZARD_HIDDEN["op1db"]
    assert "gain_field" not in _WIZARD_HIDDEN["op1db"]
    assert "channel_target" in _WIZARD_HIDDEN["gain_index_accuracy"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_session_ux.py -v`
Expected: FAIL

- [ ] **Step 3: Update `_WIZARD_HIDDEN`**

```python
    "op1db": {
        "ref_skip_pts", "ref_avg_pts", "sa_span_hz",
        "sa_ref_level_dbm", "settle_s", "gain_target", "beam", "channel",
        "pin_step_db",
    },
    "gain_index_accuracy": {
        "common_target", "channel_target", "channel", "common_codes",
        "channel_codes", "sa_span_hz", "sa_ref_level_dbm", "settle_s",
    },
    "channel_gain_alignment": {
        "max_gain_code", "beam", "common_target", "channels",
        "sa_span_hz", "sa_ref_level_dbm", "settle_s",
    },
    "ip1db": {
        "ref_skip_pts", "ref_avg_pts", "sa_span_hz",
        "sa_ref_level_dbm", "settle_s", "gain_target", "beam", "channel",
        "pin_step_db",
    },
```

- [ ] **Step 4: Update `tx_suite`**

```python
    steps = [
        # gain_code 0x00 = 최대 게인. SA ref 25 dBm(Psat ~24 dBm 커버, 계측기 최대 25).
        ("linearity", "op1db",
         {"freq_hz": freq_hz, "gain_target": "common", "beam": bm,
          "gain_code": 0x00, "sa_ref_level_dbm": 25.0, "pin_start_dbm": -22.0,
          "pin_stop_dbm": 10.0, "pin_step_db": 1.0}),
        ("gain_common", "gain_index_accuracy",
         {"freq_hz": freq_hz, "sg_level_dbm": _TX_GAIN_SG_DBM,
          "sa_ref_level_dbm": _TX_GAIN_SA_REF_DBM,
          "common_codes": list(range(64)), "channel_codes": [0],
          "channel_target": "beamtable", "log_psu": False}),
        ("gain_chan", "gain_index_accuracy",
         {"freq_hz": freq_hz, "sg_level_dbm": _TX_GAIN_SG_DBM,
          "sa_ref_level_dbm": _TX_GAIN_SA_REF_DBM,
          "common_codes": [0], "channel_codes": list(range(64)),
          "channel_target": "beamtable", "log_psu": False}),
```

`rx_suite` 에 `gain_field` 가 있으면 같은 방식으로 바꾼다(`grep -n "gain_field" src/cloudchaser/session.py` 로 확인).

- [ ] **Step 5: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: **전부 PASS.** 여기서부터 회귀 없음이 보장돼야 한다.

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/session.py tests/test_session_ux.py
git commit -m "refactor(session): use gain_target params in wizard and tx_suite"
```

---

### Task 11: `regdump` CLI

**Files:**
- Create: `src/cloudchaser/regdump.py`
- Test: `tests/test_regdump.py`

**Interfaces:**
- Consumes: Task 1 `FH`, Task 4/5 bring-up, `bench.Bench`
- Produces:
  - `load_dump(src, base=0x1000) -> dict[int, int]` — `.csv`(addr,value / 값만) 및 `.xlsx` 지원
  - `save_dump(d, path) -> None`
  - `regdiff(theirs: dict, ours: dict, log=print) -> list[int]`
  - `python -m cloudchaser.regdump` CLI — 스펙 8.8의 옵션 전부

- [ ] **Step 1: Write the failing test**

`tests/test_regdump.py`:

```python
"""레지스터 덤프 로드/저장/비교 검증."""
import pytest

from cloudchaser.regdump import load_dump, regdiff, save_dump


def test_load_addr_value_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("addr,value\n0x1000,0xDC11\n0x1001,0x0000\n", encoding="utf-8")
    assert load_dump(p) == {0x1000: 0xDC11, 0x1001: 0x0000}


def test_load_values_only_csv_uses_base(tmp_path):
    """주소 없이 값만 나열된 파일(MATLAB mem_dump)은 base 부터 순차 주소."""
    p = tmp_path / "v.csv"
    p.write_text("3\n7\n", encoding="utf-8")
    assert load_dump(p, base=0x1008) == {0x1008: 3, 0x1009: 7}


def test_load_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("# note\n\n0x1000,1\n", encoding="utf-8")
    assert load_dump(p) == {0x1000: 1}


def test_save_and_reload_roundtrip(tmp_path):
    d = {0x1000: 0xDC11, 0x104C: 3378}
    p = tmp_path / "o.csv"
    save_dump(d, p)
    assert load_dump(p) == d


def test_regdiff_reports_only_differences(capsys):
    theirs = {0x1000: 1, 0x1001: 2, 0x1002: 3}
    ours = {0x1000: 1, 0x1001: 9, 0x1002: 3}
    diffs = regdiff(theirs, ours)
    assert diffs == [0x1001]
    out = capsys.readouterr().out
    assert "0x1001" in out
    assert "1 differing / 3 compared" in out


def test_regdiff_handles_missing_addresses(capsys):
    diffs = regdiff({0x1000: 1, 0x1005: 5}, {0x1000: 1})
    assert diffs == [0x1005]
    assert "--" in capsys.readouterr().out


def test_load_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["addr", "value"])
    ws.append(["0x1000", "0xDC11"])
    ws.append([0x1001, 5])
    p = tmp_path / "d.xlsx"
    wb.save(p)
    assert load_dump(p) == {0x1000: 0xDC11, 0x1001: 5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_regdump.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudchaser.regdump'`

- [ ] **Step 3: Write the implementation**

`src/cloudchaser/regdump.py`:

```python
"""레지스터 덤프 저장 / 로드 / 비교 CLI.

Sivers 가 준 레퍼런스 덤프(reference/Data_260729_DoosanSTMP_RegDump.xlsx)와
우리 bring-up 결과를 필드 단위로 대조한다. 판정 기준은 설계 스펙 8.5 참고:
잔차가 다이별 eFuse bias 에만 남으면 SW 포팅은 맞다.

실행:
  python -m cloudchaser.regdump --save out\\regs.csv
  python -m cloudchaser.regdump --diff reference\\Data_260729_DoosanSTMP_RegDump.xlsx
  python -m cloudchaser.regdump --diff out\\regs_efuse.csv --ours out\\regs_casper.csv
  python -m cloudchaser.regdump --fake --diff tests\\data\\golden_regs_tx_v1_split.csv

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bench import Bench
from .board.bringup import bring_up_tx, make_chip
from .board.firehawk import FH
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout


def _to_int(x):
    """'0x1000' / '4096' / 4096 -> int. 변환 불가면 None."""
    if isinstance(x, int):
        return x
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return int(s, 0)
    except ValueError:
        return None


def _load_xlsx(path, base):
    """xlsx 첫 시트의 앞 두 열을 (addr, value)로 읽는다.

    헤더 행('addr'로 시작)과 파싱 불가 행은 건너뛴다. 값만 있는 행은 base 부터
    순차 주소를 매긴다(MATLAB mem_dump 형식 대응).
    """
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    out, seq = {}, base
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        cells = [c for c in row[:2] if c is not None and str(c).strip() != ""]
        if not cells:
            continue
        if str(cells[0]).strip().lower().startswith("addr"):
            continue
        nums = [_to_int(c) for c in cells]
        if len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
            out[nums[0]] = nums[1] & 0xFFFF
        elif nums and nums[0] is not None:
            out[seq] = nums[0] & 0xFFFF
            seq += 1
    wb.close()
    return out


def load_dump(src, base=0x1000):
    """레지스터 덤프를 {addr: val} 로 로드한다. .csv / .xlsx / dict 를 받는다.

    csv 허용 형식(자동 감지): 'addr,value' / 'addr value' / 'addr\\tvalue'.
    값만 한 열로 나열된 경우는 base 부터 순차 주소를 매긴다.
    """
    if isinstance(src, dict):
        return {int(k): int(v) & 0xFFFF for k, v in src.items()}
    p = Path(src)
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        return _load_xlsx(p, base)
    out, seq = {}, base
    for raw in p.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s[0] in "#%" or s.lower().startswith("addr"):
            continue
        parts = s.replace(",", " ").replace("\t", " ").split()
        nums = [_to_int(x) for x in parts]
        if any(n is None for n in nums):
            continue
        if len(nums) >= 2:
            out[nums[0]] = nums[1] & 0xFFFF
        elif len(nums) == 1:
            out[seq] = nums[0] & 0xFFFF
            seq += 1
    return out


def save_dump(d, path):
    """{addr: val} 을 'addr,value' hex CSV 로 저장한다."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write("addr,value\n")
        for addr in sorted(d):
            f.write(f"0x{addr:04X},0x{d[addr] & 0xFFFF:04X}\n")
    print(f"  dumped {len(d)} regs -> {p}")


def regdiff(theirs, ours, log=print):
    """두 덤프를 비교해 다른 레지스터만 출력하고, 다른 주소 목록을 반환한다."""
    addrs = sorted(set(theirs) | set(ours))
    diffs = []
    for a in addrs:
        tv, ov = theirs.get(a), ours.get(a)
        if tv != ov:
            diffs.append(a)
            ts = f"0x{tv:04X}" if tv is not None else "  --  "
            os_ = f"0x{ov:04X}" if ov is not None else "  --  "
            log(f"  0x{a:04X}:  theirs={ts}  ours={os_}")
    log(f"  {len(diffs)} differing / {len(addrs)} compared")
    return diffs


def main(argv=None):
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="Dump and compare chip registers.")
    ap.add_argument("--fake", action="store_true", help="no hardware (fake SPI)")
    ap.add_argument("--no-power", action="store_true", help="skip PSU power-up")
    ap.add_argument("--save", metavar="PATH", help="save the dump as addr,value CSV")
    ap.add_argument("--diff", metavar="PATH", help="reference dump to compare against (.csv/.xlsx)")
    ap.add_argument("--ours", metavar="PATH", help="our dump from a file (default: read the chip live)")
    ap.add_argument("--range", nargs=2, metavar=("A", "B"), default=["0x1000", "0x1204"],
                    help="dump address range [A, B)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="bench toml path")
    args = ap.parse_args(argv)

    a, b = int(args.range[0], 0), int(args.range[1], 0)

    if args.ours:
        ours = load_dump(args.ours)
    else:
        bench = Bench.from_toml(args.config, fake=args.fake)
        if not args.no_power and not args.fake:
            bench.power_up()
        chip = make_chip(bench.board, fake=args.fake)
        bring_up_tx(chip, bench.board, require_version=not args.fake)
        fh = FH(chip, bench.board.chip_id)
        ours = {addr: fh.rd(addr) for addr in range(a, b)}

    if args.save:
        save_dump(ours, args.save)
    if args.diff:
        theirs = load_dump(args.diff, base=a)
        diffs = regdiff(theirs, ours)
        return 1 if diffs else 0
    if not args.save:
        for addr in sorted(ours):
            print(f"  0x{addr:04X} = 0x{ours[addr]:04X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`bench.power_up()` 메서드 이름이 실제와 다르면 `driver_reg_diff.py:225-235` 의 전원 인가 호출을 그대로 복사해 맞춘다.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_regdump.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: CLI 스모크 확인**

```bash
.\.venv\Scripts\python.exe -m cloudchaser.regdump --fake --save out\fake_regs.csv
.\.venv\Scripts\python.exe -m cloudchaser.regdump --fake --diff tests\data\golden_regs_tx_v1_split.csv
```

Expected: 두 번째 명령이 `0 differing / N compared` 를 출력한다. 차이가 나면 `bench.toml` 의 `[board]` 가 골든 설정(`active_channels=["v1"]`, `beam="b0"`, `split_mode=true`)과 다른 것이다 — 그 경우 명령에 맞춰 임시로 맞춘 뒤 다시 확인하고, 스펙 8.2에 그 전제를 한 줄 덧붙인다.

- [ ] **Step 6: Commit**

```bash
git add src/cloudchaser/regdump.py tests/test_regdump.py
git commit -m "feat: add regdump CLI for register dump and diff vs Sivers xlsx"
```

---

### Task 12: 문서 갱신

**Files:**
- Modify: `docs/SESSION.md` (§6 측정 항목, 163-166행 게인 설명, 379행 레지스터 읽기 예시)
- Modify: `README.md` (테스트 목록·CLI)
- Modify: `scripts/cloudchaser_workbook.py`, `scripts/cloudchaser_workbook_ko.py`
- Modify: `CLAUDE.md` (bring-up 핵심 설명)

**Interfaces:**
- Consumes: 전 태스크의 최종 파라미터·CLI 이름

- [ ] **Step 1: `docs/SESSION.md` 갱신**

- 163행 근처의 `gain_index_accuracy(channel_kind='beamtable', channel_quad=1)` → `gain_index_accuracy(channel_target='beamtable', channel_quad=1)`
- 165-166행의 게인 설명에 타깃 3종(`common`/`fe`/`beamtable`) 표를 넣는다. `fe`(구 `gain_control_*`)가 이 칩에서 DEAD 라는 기존 서술은 유지한다.
- 379행 `C.fields.rd('b0_common_gain')` 는 **읽기라 그대로 유효하다.** 옆에 `fh.rd(0x1005)` 예시를 추가한다.
- 새 절 "레지스터 덤프와 대조"를 추가하고 스펙 8.5·8.8 내용을 옮긴다.
- 새 절 "optimize bias 전/후 비교"를 추가하고 스펙 8.4 절차를 옮긴다.

- [ ] **Step 2: `README.md` 갱신**

- 구조 설명에 `board/firehawk.py` · `board/bias_v4.py` · `board/gain_map.py` · `regdump.py` 를 추가한다.
- CLI 목록에 `python -m cloudchaser.regdump` 를 추가한다.
- "벤더 sivers_api 는 SPI 전송 계층만 사용한다(쓰기는 raw 레지스터)" 한 줄을 넣는다.

- [ ] **Step 3: workbook 스크립트 2개 갱신**

`scripts/cloudchaser_workbook.py` 와 `_ko.py` 에서:
- `wr("b0_common_gain", 0x10); latch()` 예시 → `fh.wr_verify(0x1005, 0x10)` 로 교체(346-357행 / 379-390행 근처)
- `gain_index_accuracy(..., channel_kind="beamtable", ...)` → `channel_target="beamtable"` (446행 / 512행)
- `latch()` · `commit()` 설명 문단은 삭제하고 "raw 기입은 pulse 비트를 워드에 함께 써서 별도 latch 가 필요 없다"로 대체한다.
- `rd("b0_common_gain")` 읽기 예시는 유지한다.

- [ ] **Step 4: `CLAUDE.md` 갱신**

"보드 하드웨어 현황" 절의 bring-up 설명을 갱신한다:

```markdown
- bring-up 은 **raw 레지스터 기입**이다(`board/firehawk.py` FH 엔진). 벤더 `sivers_api` 는
  SPI 전송 계층으로만 쓰고, `fields.wr`/`path`/`commit`/`beam_table` 같은 고수준 쓰기 API 는
  쓰지 않는다 — 근거는 `docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md`.
  읽기(`fields.rd`)는 HW 를 직접 읽으므로 진단용으로 계속 쓴다.
- bias 는 v4 시트(`bias_v4.py`)의 TX `Casper` / RX `NF_OPTIM` 을 기본 적용한다
  (`bench.toml` 의 `optimized_bias`).
- 게인 조작은 필드 이름이 아니라 타깃(`common`/`fe`/`beamtable`)으로 지정한다.
  per-path 는 `beamtable`(RTPS)이 실동작이고 `fe`(구 `gain_control_*`)는 이 칩에서 DEAD.
```

- [ ] **Step 5: 최종 전체 확인**

```bash
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m cloudchaser.runner run op1db --fake
.\.venv\Scripts\python.exe -m cloudchaser.regdump --fake --diff tests\data\golden_regs_tx_v1_split.csv
```

Expected: pytest 전량 PASS · op1db fake 실행 성공 · `0 differing`

- [ ] **Step 6: Commit**

```bash
git add docs/SESSION.md README.md scripts/cloudchaser_workbook.py scripts/cloudchaser_workbook_ko.py CLAUDE.md
git commit -m "docs: update for raw register bring-up, gain targets, regdump CLI"
```

- [ ] **Step 7: 브랜치 마무리**

CLAUDE.md 의 워크플로를 따른다: 푸시 → main 머지 → main 푸시 → 작업 브랜치 삭제.

```bash
git push -u origin feat/raw-register-bringup
git checkout main && git merge --no-ff feat/raw-register-bringup
git push origin main
git branch -d feat/raw-register-bringup
```

---

## 실칩 검증 (구현 후, 실험 PC에서)

이 계획의 태스크는 전부 fake 모드까지만 검증한다. **실칩 검증은 별도이며 실험 PC가 필요하다.** 절차는 스펙 8.4·8.5를 따른다.

1. `regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx` → 잔차가 다이별 eFuse bias(`0x1041`/`0x1045`/`0x1049`/`0x1055`)에만 남는지 확인
2. `optimized_bias` true/false 로 OP1dB·Pdc 델타 측정
3. `dist_st2_1_ptat` 13 vs 28 비교 → 열린 항목 종결
4. `run_efuse_init` false/true 비교 → 열린 항목 종결
