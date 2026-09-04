import os, csv

# =====================================================================
# 2) FTDI MPSSE: SPI 직통(온도 전용) – 안정 오픈/클럭/트랜잭션 유틸 (교체본)
# =====================================================================
_SPI_CLK_HZ = spi_clk  # CLI와 동일 속도로 사용(원하면 독립적으로 바꿔도 됨)

# ---- FTDI 핀 비트 ----
BIT_SK, BIT_DO, BIT_DI, BIT_CS = 0, 1, 2, 3
BIT_RESETN, BIT_BEAMUP, BIT_TRSW = 4, 5, 6

# 방향: SK/DO/CS/RESETN/BEAMUP/TRSW = 출력(1), DI(MISO)=입력(0), ADBUS7=입력(0)
DIR_MASK = (1<<BIT_SK)|(1<<BIT_DO)|(1<<BIT_CS)|(1<<BIT_RESETN)|(1<<BIT_BEAMUP)|(1<<BIT_TRSW)  # 0x7B
INIT_VAL = (1<<BIT_CS)|(1<<BIT_RESETN)  # CS=High, RESET_N=High

TEMP_LUT_CSV_PATH = r"C:\Users\sejin1.yang\Temperature_Sensor_LUT.csv"  # 경로 필요시 수정
_TEMP_LUT_DICT = None

def _rev8(x: int) -> int:
    x = ((x & 0xF0) >> 4) | ((x & 0x0F) << 4)
    x = ((x & 0xCC) >> 2) | ((x & 0x33) << 2)
    x = ((x & 0xAA) >> 1) | ((x & 0x55) << 1)
    return x & 0xFF

def _mpsse_open(clock_hz: int, max_wait_s: float = 3.0):
    """
    FTDI 핸들을 튼튼하게 오픈:
      - run_cli('spi_close') 직후 드라이버 반납 지연을 재시도로 흡수
      - description 우선 openEx → 실패 시 index=0 폴백
      - SPI에 적합하게: /5 비활성(0x8A), 3-phase 비활성(0x8D), loopback off(0x85)
      - 방향 마스크는 ADBUS2(MISO)=입력(핵심!)
    """
    t_end = time.time() + max_wait_s
    OPEN_BY_DESC = getattr(ftd, "OPEN_BY_DESCRIPTION", 2)

    def _list_desc():
        try:
            lst = ftd.listDevices() or []
            return [e.decode() if isinstance(e,(bytes,bytearray)) else str(e) for e in lst]
        except Exception:
            return []

    while True:
        try:
            descs = _list_desc()
            pref = next((d for p in ("C232HM","FT232H","USB","SPI") for d in descs if p.lower() in d.lower()), None)
            d = ftd.openEx(pref, OPEN_BY_DESC) if pref else ftd.open(0)

            # 타임아웃/지연
            d.setTimeouts(100, 100)
            try: d.setLatencyTimer(2)
            except Exception: pass

            # MPSSE 초기화
            d.setBitMode(0x00, 0x00); time.sleep(0.02)  # reset
            d.setBitMode(0x00, 0x02)                    # MPSSE
            d.write(bytes([0x8A]))                      # disable divide-by-5
            d.write(bytes([0x8D]))                      # disable 3-phase clocking (SPI)
            d.write(bytes([0x85]))                      # disable loopback

            # SCK = 60MHz/(2*(1+div))
            div = max(0, int(60_000_000/(2*clock_hz) - 1))
            d.write(bytes([0x86, div & 0xFF, (div >> 8) & 0xFF]))

            # Low GPIO: 값/방향 설정 (CS=High, RESETN=High, MISO는 입력)
            d._gpio_val, d._gpio_dir = INIT_VAL, DIR_MASK
            d.write(bytes([0x80, d._gpio_val & 0xFF, d._gpio_dir & 0xFF]))
            return d
        except ftd.DeviceError:
            if time.time() > t_end:
                print("[FTDI] open 실패. devices =", _list_desc())
                raise
            time.sleep(0.1)

def _cs_low(d):
    d._gpio_val &= ~(1<<BIT_CS)
    d.write(bytes([0x80, d._gpio_val & 0xFF, d._gpio_dir & 0xFF]))

def _cs_high(d):
    d._gpio_val |=  (1<<BIT_CS)
    d.write(bytes([0x80, d._gpio_val & 0xFF, d._gpio_dir & 0xFF]))

def _mpsse_write_bytes(d, data: bytes):
    # MPSSE 0x11: (MSB-first, -ve edge). 바이트를 bit-reverse해서 LSB-first로 맞춤.
    if not data: return
    n = len(data)
    rb = bytes(_rev8(b) for b in data)
    d.write(bytes([0x11, (n-1) & 0xFF, ((n-1) >> 8) & 0xFF]) + rb)

def _mpsse_read_bytes(d, n: int) -> bytes:
    # MPSSE 0x20: (MSB-first, +ve edge). 수신 바이트를 bit-reverse.
    if n <= 0: return b""
    d.write(bytes([0x20, (n-1) & 0xFF, ((n-1) >> 8) & 0xFF]))
    raw = d.read(n)
    return bytes(_rev8(b) for b in raw)

def _clock_dummy(d, num_bits: int):
    if num_bits <= 0: return
    num_bytes = (num_bits + 7) // 8
    _mpsse_write_bytes(d, b"\x00" * num_bytes)

# ---- 2629e 트랜잭션 도우미 (LSB-first 32비트) ----
def _first16(chip_id: int, cmd7: int) -> bytes:
    v  = (1) | ((chip_id & 0xFF) << 1) | ((cmd7 & 0x7F) << 9)
    return bytes([v & 0xFF, (v >> 8) & 0xFF])  # LSB 바이트가 먼저

def _payload16_bytes(val16: int) -> bytes:
    lo, hi = (val16 & 0xFF), ((val16 >> 8) & 0xFF)
    return bytes([lo, hi])  # 나중에 _mpsse_write_bytes 쪽에서 bit-reverse됨

def _load_pointer(d, addr14: int, chip: int = 0xFF):
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x00))
    _mpsse_write_bytes(d, _payload16_bytes(addr14 & 0x3FFF))
    _cs_high(d)

def _write_reg16(d, chip: int, val16: int):
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x02))
    _mpsse_write_bytes(d, _payload16_bytes(val16 & 0xFFFF))
    _cs_high(d)

def _read_reg16(d, chip: int) -> int:
    # 헤더 16클럭 후 payload 16클럭에서만 MISO 유효(READ-register 규약)
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x01))
    raw = _mpsse_read_bytes(d, 2)  # little-endian로 조립
    _cs_high(d)
    if len(raw) != 2:
        raise RuntimeError("MPSSE read underrun")
    return raw[0] | (raw[1] << 8)

def _adc_capture(d, chip: int = 0xFF, div_pow2: int = 1):
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x08))  # payload 안 씀
    _mpsse_read_bytes(d, 2)                      # 잔여 16클럭 소모
    _cs_high(d)
    _clock_dummy(d, 25 * (1 << div_pow2) + 16)   # ADC 완료까지 SPI_CLK 유지

def temp_read_via_spi(chip_id: int = 0, restore_clk: int = _SPI_CLK_HZ) -> int | None:
    """
    [외부용] 온도 RAW(0..255) 읽기.
      흐름: spi_close → Python(MPSSE) → (필요 설정) → ADC_CAPTURE → Temp_ADC → close → spi_init 복귀
    """
    try:
        # 1) CLI가 잡은 핸들 릴리즈
        _ = run_cli("spi_close", settle=0.25)
        time.sleep(0.20)

        # 2) Python이 FTDI 오픈(MPSSE)
        d = _mpsse_open(restore_clk)
        try:
            # 3) Temp enable (0x202F bit[9:8])
            _load_pointer(d, 0x202F, 0xFF)
            cur = _read_reg16(d, chip_id)
            if (cur & 0x0300) != 0x0300:
                _load_pointer(d, 0x202F, 0xFF)
                _write_reg16(d, chip_id, cur | 0x0300)

            # 4) ADC divider/mask (안전 기본값: DIV=1, MASK=0x03FF)
            _load_pointer(d, 0x2035, 0xFF)   # ADC_DIV
            _write_reg16(d, 0xFF, 0x0001)    # 2^1 (reset 기본값과 동일)  :contentReference[oaicite:7]{index=7}
            _write_reg16(d, 0xFF, 0x03FF)    # 다음 주소=0x2036, MASK/폴라리티 설정  :contentReference[oaicite:8]{index=8}

            # 5) ADC_CAPTURE + SCK 유지
            _adc_capture(d, 0xFF, div_pow2=1) # 25·2^DIV 클럭 필요  :contentReference[oaicite:9]{index=9}

            # 6) Temp_ADC(0x2037) 읽기 (8-bit)
            _load_pointer(d, 0x2037, 0xFF)
            val16 = _read_reg16(d, chip_id)  # 8비트 유효  :contentReference[oaicite:10]{index=10}
            return val16 & 0xFF
        finally:
            try: d.close()
            except Exception: pass
    finally:
        # 7) CLI에 핸들 복귀
        _ = run_cli(f"spi_init 0 {restore_clk}", settle=0.35)


def load_temp_lut_csv(path: str = TEMP_LUT_CSV_PATH) -> dict[int, float]:
    """
    CSV에서 {ADC(int): Celsius(float)} 사전을 만들어 전역 캐시에 저장.
    - UTF-8 with BOM(엑셀 저장)도 처리됨.
    - 비어있는 줄/헤더는 자동 건너뜀.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"LUT CSV not found: {path}")
    lut: dict[int, float] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        rdr = csv.reader(f)
        for row in rdr:
            if not row or all((c or "").strip() == "" for c in row):
                continue
            try:
                adc = int(float(row[0]))
                tC  = float(row[1])
            except Exception:
                # 헤더/형식 다른 줄은 스킵
                continue
            lut[adc] = tC
    if not lut:
        raise ValueError("Empty LUT after parsing. Check CSV format.")
    global _TEMP_LUT_DICT
    _TEMP_LUT_DICT = lut
    return lut

def adc_to_celsius_exact_from_csv(adc_code: int,
                                  path: str = TEMP_LUT_CSV_PATH) -> float | None:
    """
    ADC 코드가 CSV LUT에 '정확히' 존재할 때만 해당 °C 반환.
    없으면 None.
    """
    global _TEMP_LUT_DICT
    if _TEMP_LUT_DICT is None:
        load_temp_lut_csv(path)
    return _TEMP_LUT_DICT.get(int(adc_code))

def read_temp_celsius_exact_from_csv(chip_id: int = 0,
                                     path: str = TEMP_LUT_CSV_PATH) -> float | None:
    """
    temp_read_via_spi()로 RAW 읽고 CSV LUT로 °C 매핑(정확 매칭만).
    매칭 실패 시 영어 메시지 출력.
    """
    raw = temp_read_via_spi(chip_id)
    tC  = adc_to_celsius_exact_from_csv(raw, path)
    if tC is None:
        print("No matching temperature value found.")
        return None
    print(f"{tC:.2f} °C (ADC={raw})")
    return tC
# ============================================================================



###### Test
print(run_cli("spi_query"))
t = temp_read_via_spi(chip_id)     # 온도 RAW(0..255)
print("Temp ADC =", t)
read_temp_celsius_exact_from_csv(chip_id)
print(run_cli("get_channel_enables 0"))
