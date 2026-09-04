# -*- coding: utf-8 -*-
# Summit 2629e: 콘솔 기반 제어 + 출력 tail 캡처 + Temp 읽기
# 사용법은 맨 아래 “실행 방법” 참고

import subprocess, time, pathlib, pyautogui, pyperclip, re
import win32gui, win32con, win32process
import ftd2xx as ftd

# -------------------- 사용자 설정 --------------------
chip_id   = 0
channel   = "Tx_H0"    # 아래 ch 사전 중 선택
trx_mode  = "tx"       # "tx" 또는 "rx"
attn_mode = 1          # 0이면 HTX sweep 예시 수행, 1이면 skip
spi_clk   = 20_000_000 # spi_init에 넘길 SPI 클럭(Hz)

cli_path = pathlib.Path(r"C:\Program Files\Sivers Semiconductors\MIX2429E_CLI\MIXC2429E_CLI.exe")

ch = {
    "Tx_H0": (2,0,0,0,2), "Tx_H1": (0,2,0,0,2), "Tx_H2": (0,0,2,0,2), "Tx_H3": (0,0,0,2,2),
    "Tx_V0": (8,0,0,0,8), "Tx_V1": (0,8,0,0,8), "Tx_V2": (0,0,8,0,8), "Tx_V3": (0,0,0,8,8),
    "Rx_H0": (1,0,0,0,1), "Rx_H1": (0,1,0,0,1), "Rx_H2": (0,0,1,0,1), "Rx_H3": (0,0,0,1,1),
    "Rx_V0": (4,0,0,0,4), "Rx_V1": (0,4,0,0,4), "Rx_V2": (0,0,4,0,4), "Rx_V3": (0,0,0,4,4),
    "Tx_H": (2,2,2,2,2), "Tx_V": (2,2,2,2,2), "Rx_H": (2,2,2,2,2), "Rx_V": (2,2,2,2,2),
}
m = {"tx": "set_tx_mode 0", "rx": "set_rx_mode 0"}
mode_cmd = m[trx_mode.lower()]

# -------------------- 콘솔 창 핸들/포커스 --------------------
def bring_to_front_by_pid(pid, retry=30, delay=0.1):
    for _ in range(retry):
        targets = []
        def _enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                if wpid == pid:
                    targets.append(hwnd)
        win32gui.EnumWindows(_enum_cb, None)
        if targets:
            hwnd = targets[0]
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return hwnd
        time.sleep(delay)
    return None

# -------------------- 안전한 콘솔 전체 복사 & tail 추출 --------------------
def _copy_console_all_text(proc_pid, pause: float = 0.08, max_retry: int = 3) -> str:
    """
    콘솔 전체를 안전하게 복사해서 문자열 반환.
    - 1순위: Windows Terminal 키( Ctrl+Shift+A → Ctrl+Shift+C )
    - 2순위: 시스템 메뉴( Alt+Space → 'E' → 'A' → Enter )  # 'A'=모두 선택(Select All)
    - 3순위: 시스템 메뉴( Alt+Space → 'E' → 'S' → Enter )  # 일부 영문 콘솔 호환
    ※ 어떤 시퀀스도 실패하면 마지막으로 얻은 버퍼(또는 빈 문자열) 반환
    """
    sentinel = "__CLIP_SENTINEL__"
    text = ""
    for _ in range(max_retry):
        # 포커스 보장
        bring_to_front_by_pid(proc.pid)

        # 0) 센티넬로 클립보드 초기화
        try:
            pyperclip.copy(sentinel)
        except Exception:
            pass

        # --- (A) Windows Terminal 경로 ---
        pyautogui.hotkey('ctrl', 'shift', 'a')  # Select All
        time.sleep(0.04)
        pyautogui.hotkey('ctrl', 'shift', 'c')  # Copy
        time.sleep(pause)
        text = pyperclip.paste() or ""
        if text and text != sentinel:
            return text

        # --- (B) 시스템 메뉴: Edit(E) -> Select All(A) ---
        pyautogui.keyDown('alt'); pyautogui.press('space'); pyautogui.keyUp('alt')
        time.sleep(0.06)
        pyautogui.press('e')   # Edit
        time.sleep(0.04)
        pyautogui.press('a')   # Select All   ← 여기서 'A' 사용!
        time.sleep(0.06)
        pyautogui.press('enter')   # Copy
        time.sleep(pause)
        text = pyperclip.paste() or ""
        if text and text != sentinel:
            return text

        # --- (C) 시스템 메뉴: Edit(E) -> Select All(S) (영문 일부 호환) ---
        pyautogui.keyDown('alt'); pyautogui.press('space'); pyautogui.keyUp('alt')
        time.sleep(0.06)
        pyautogui.press('e')   # Edit
        time.sleep(0.04)
        pyautogui.press('s')   # Select All (영문 콘솔 대비)
        time.sleep(0.06)
        pyautogui.press('enter')
        time.sleep(pause)
        text = pyperclip.paste() or ""
        if text and text != sentinel:
            return text

    return text  # 실패 시 마지막 버퍼(또는 빈 문자열)

def _send_and_capture_tail(proc_pid, cmd: str, settle: float = 0.25, tail_fallback: int = 6000) -> str:
    """
    콘솔 명령 실행 전/후 버퍼를 비교해, 새로 생긴 tail만 반환.
    - settle: 출력이 다 찍힐 때까지 소폭 대기 (환경 따라 0.20~0.35 조정)
    """
    bring_to_front_by_pid(proc_pid)
    before = _copy_console_all_text(proc_pid)
    pyautogui.write(cmd); pyautogui.press("enter")
    time.sleep(settle)
    after = _copy_console_all_text(proc_pid)

    if after.startswith(before):
        return after[len(before):]
    # 롤링 등으로 앞부분이 누락됐으면 뒤쪽 일부만 기준으로 tail 추출
    pivot = before[-tail_fallback:]
    idx = after.rfind(pivot)
    if idx >= 0:
        return after[idx+len(pivot):]
    return after[-tail_fallback:]  # 최후의 수단

_HEX_RE = re.compile(r"0[xX]([0-9A-Fa-f]{1,8})")
def _parse_last_hex(s: str) -> int | None:
    m = _HEX_RE.findall(s)
    return int(m[-1], 16) if m else None
    
######################SPI 직접 통신 위한 셋팅###########################    
_SPI_CLK_HZ = spi_clk  # 네가 위쪽에서 정한 값(예: 20_000_000)을 그대로 사용

# --- MPSSE 바이트 단위 비트 리버스(LSB-first <-> MSB-first 보정) ---
def _rev8(x: int) -> int:
    x = ((x & 0xF0) >> 4) | ((x & 0x0F) << 4)
    x = ((x & 0xCC) >> 2) | ((x & 0x33) << 2)
    x = ((x & 0xAA) >> 1) | ((x & 0x55) << 1)
    return x & 0xFF

def _mpsse_open(clock_hz: int, max_wait_s: float = 3.0):
    """
    FTDI 핸들을 튼튼하게 오픈:
    - spi_close 직후 드라이버 반납 지연 흡수(재시도)
    - 장치 목록 열거 후 description으로 openEx 시도 → 실패 시 index=0 폴백
    - 네가 쓰던 MPSSE 초기화 그대로 적용
    """
    t_end = time.time() + max_wait_s

    def _list_all():
        names = []
        try:
            lst = ftd.listDevices()
            if lst:
                for e in lst:
                    s = e.decode() if isinstance(e, (bytes, bytearray)) else str(e)
                    names.append(s)
        except Exception:
            pass
        return names

    OPEN_BY_SN   = getattr(ftd, "OPEN_BY_SERIAL_NUMBER", 1)
    OPEN_BY_DESC = getattr(ftd, "OPEN_BY_DESCRIPTION", 2)

    last_err = None
    while True:
        try:
            dev_names = _list_all()

            # description 후보 선택
            cand_desc = None
            for pref in ("C232HM", "FT232H", "USB", "SPI"):
                cand_desc = next((n for n in dev_names if pref.lower() in n.lower()), None)
                if cand_desc:
                    break

            d = ftd.openEx(cand_desc, OPEN_BY_DESCRIPTION) if cand_desc else ftd.open(0)

            # ---- 네가 쓰던 초기화 그대로 ----
            d.setTimeouts(100, 100)
            try:
                d.setLatencyTimer(2)
            except Exception:
                pass

            d.setBitMode(0x00, 0x00); time.sleep(0.02)
            d.setBitMode(0x00, 0x02)
            d.write(bytes([0x8A]))  # disable divide-by-5
            d.write(bytes([0x97]))  # enable 3-phase clocking

            div = int(60_000_000/(2*clock_hz)) - 1
            d.write(bytes([0x86, div & 0xFF, (div >> 8) & 0xFF]))

            # 현재 GPIO LowByte 확보 후 CS만 토글
            d.write(bytes([0x81])); time.sleep(0.01)
            n = d.getQueueStatus()
            gpio_low = d.read(n)[0] if n else 0xFF
            d._gpio_low = gpio_low | 0x08
            d.write(bytes([0x80, d._gpio_low & 0xFF, 0xFF]))
            return d

        except ftd.DeviceError as e:
            last_err = e
            if time.time() > t_end:
                print("[FTDI] open 실패. listDevices() =", _list_all())
                raise
            time.sleep(0.1)

def _cs_low(d):
    d._gpio_low &= ~0x08  # CS=0
    d.write(bytes([0x80, d._gpio_low & 0xFF, 0xFF]))

def _cs_high(d):
    d._gpio_low |= 0x08   # CS=1
    d.write(bytes([0x80, d._gpio_low & 0xFF, 0xFF]))

# --- MPSSE 전송 유틸: 쓰기/읽기(클럭 발생) ---
def _mpsse_write_bytes(d, data: bytes):
    # 0x11: Clock Data Bytes Out (MSB-first, -ve edge) → 바이트는 _rev8() 해서 넣음
    n = len(data)
    if n == 0: return
    d.write(bytes([0x11, (n-1) & 0xFF, ((n-1)>>8) & 0xFF]) + data)

def _mpsse_read_bytes(d, n: int) -> bytes:
    # 0x20: Clock Data Bytes In (MSB-first, +ve edge) → 장치가 내보내는 걸 읽음
    if n <= 0: return b""
    d.write(bytes([0x20, (n-1) & 0xFF, ((n-1)>>8) & 0xFF]))
    return d.read(n)

def _clock_dummy(d, num_bits: int):
    """CS 상태와 무관하게 SPI_CLK만 추가로 토글. (ADC_CAPTURE 후 여유 클럭 제공 용)
       여기선 바이트 단위로 0x00을 내보내면 자연스럽게 클럭 생성됨."""
    if num_bits <= 0: return
    num_bytes = (num_bits + 7) // 8
    _mpsse_write_bytes(d, b"\x00"*num_bytes)

# --- 32비트 트랜잭션의 상위 16비트(IDTYPE+CHIP_ID+CMD) 패킹(LSB-first 규약 반영) ---
def _first16(chip_id: int, cmd7: int) -> bytes:
    # bit0=IDTYPE=1, bit1..8=CHIP_ID(LSB→MSB), bit9..15=CMD[0..6](LSB→MSB)
    v = (1) | ((chip_id & 0xFF) << 1) | ((cmd7 & 0x7F) << 9)
    b0 = _rev8(v & 0xFF)         # MPSSE가 MSB-first라서 바이트 리버스
    b1 = _rev8((v >> 8) & 0xFF)
    return bytes([b0, b1])

def _payload16_bytes(val16: int) -> bytes:
    # 페이로드도 LSB-first 규약 반영해서 바이트 리버스 후 송출
    lo, hi = val16 & 0xFF, (val16 >> 8) & 0xFF
    return bytes([_rev8(lo), _rev8(hi)])

# --- SPI 명령 구현: LOAD_POINTER / WRITE_REGISTER / READ_REGISTER / ADC_CAPTURE ---
def _load_pointer(d, addr14: int, chip: int = 0xFF):
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x00))             # LOAD_POINTER
    _mpsse_write_bytes(d, _payload16_bytes(addr14 & 0x3FFF))
    _cs_high(d)

def _write_reg16(d, chip: int, val16: int):
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x02))             # WRITE_REGISTER
    _mpsse_write_bytes(d, _payload16_bytes(val16 & 0xFFFF))
    _cs_high(d)

def _read_reg16(d, chip: int) -> int:
    # READ: 상위 16비트(ID/CHIP/CMD)만 MOSI로 내보낸 뒤, 나머지 16클럭은 '읽기 전용'으로 돌려 페이로드 수신
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x01))             # READ_REGISTER
    raw = _mpsse_read_bytes(d, 2)                           # 페이로드 16비트
    _cs_high(d)
    if len(raw) != 2:
        raise RuntimeError("MPSSE read underrun")
    lo = _rev8(raw[0]); hi = _rev8(raw[1])
    return (hi << 8) | lo

def _adc_capture(d, chip: int = 0xFF):
    # ADC_CAPTURE는 16번째 클럭에서 시작 → 추가 클럭이 필요(25*2^DIV)
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x08))   # 상위 16비트만 전송(페이로드는 의미 없음)
    _mpsse_read_bytes(d, 2)                       # 남은 16클럭 생성(읽긴 하지만 무시)
    _cs_high(d)
    # 여유 클럭 더 제공(예: 32비트) - CS는 높아도 SPI_CLK만 있으면 OK
    _clock_dummy(d, 32)

def temp_read_via_spi(chip_id: int = 0, restore_clk: int = _SPI_CLK_HZ) -> int | None:
    """
    CLI는 그대로 유지. 케이블만 잠깐 Python이 가져와 Temp ADC(0x2037)를 읽고, 즉시 CLI에 반환.
    반환: 0..255 RAW
    """
    try:
        _ = run_cli("spi_close", settle=0.25)
        time.sleep(0.2)  # 드라이버 반납 여유

        d = _mpsse_open(restore_clk)
        try:
            # (필요 시) 온도 센서 enable (0x202F [9:8])
            _load_pointer(d, 0x202F, 0xFF)
            cur_202F = _read_reg16(d, chip_id)
            if (cur_202F & 0x0300) != 0x0300:
                _load_pointer(d, 0x202F, 0xFF)
                _write_reg16(d, chip_id, cur_202F | 0x0300)

            # ADC 캡처 → 추가 클럭
            _adc_capture(d, 0xFF)

            # Temp_ADC(0x2037) 읽기
            _load_pointer(d, 0x2037, 0xFF)
            val16 = _read_reg16(d, chip_id)
            return val16 & 0xFF

        finally:
            try:
                d.close()
            except Exception:
                pass

    finally:
        _ = run_cli(f"spi_init 0 {restore_clk}", settle=0.35)
    return None

# -------------------- CLI 실행 (새 콘솔) & 기본 환경 --------------------
pyautogui.PAUSE = 0.03  # 키 입력 사이 지연
proc = subprocess.Popen([str(cli_path)],
                        cwd=str(cli_path.parent),
                        creationflags=subprocess.CREATE_NEW_CONSOLE)
hwnd = bring_to_front_by_pid(proc.pid)
assert hwnd, "CLI 창을 찾을 수 없습니다."

# -------------------- 네가 하던 초기화/설정 그대로 --------------------
# 3) Initialize
cmds = f"""\
spi_init 0 {spi_clk}
spi_reset
init_device {chip_id}
get_short_ID {chip_id}
get_unique_ID {chip_id}
"""
pyperclip.copy(cmds)
pyautogui.hotkey('ctrl', 'v')
time.sleep(0.1)
pyautogui.press("enter")
time.sleep(0.3)  # init_device가 길 수 있음 → tail 추출은 run_cli로 재확인

# 4) T/Rx mode
pyautogui.write(mode_cmd); pyautogui.press("enter")

# 5) Channel enable
pyautogui.write(f"set_channel_enables {chip_id} {' '.join(map(str, ch[channel]))}"); pyautogui.press("enter")
pyautogui.write(f"get_channel_enables {chip_id}"); pyautogui.press("enter")

# 6) Atten 설정
if attn_mode == 0:
    for htx in range(0, 10):  # 0..63 sweep 예시
        cmd = f"set_common_atten {chip_id} {htx} 0 0 0"
        pyautogui.write(cmd); pyautogui.press("enter")
        print("sent:", cmd)
        time.sleep(0.2)
else:
    pyautogui.write(f"get_common_atten {chip_id}"); pyautogui.press("enter")

# 7) Element Atten/Beam
pyautogui.write(f"set_beam_set {chip_id} 0 0 0 20 0.0 20 0.0 20 0.0 20 0.0"); pyautogui.press("enter")
pyautogui.write(f"set_beam_pointers {chip_id} 0 0 0 0"); pyautogui.press("enter")
pyautogui.write("spi_beam_upd"); pyautogui.press("enter")

print("[CLI] 기본 초기화/설정 전송 완료.")

# -------------------- run_cli: 콘솔 tail을 돌려주는 안전 래퍼 --------------------
def run_cli(cmd: str, settle: float = 0.25) -> str:
    """
    CLI에 명령을 한 줄 보내고, 해당 명령으로 새로 찍힌 콘솔 tail 텍스트를 반환.
    예) print(run_cli("get_channel_enables 0"))
    """
    return _send_and_capture_tail(proc.pid, cmd, settle=settle)

# -------------------- 온도 읽기 유틸 --------------------
__temp_enabled_once = False

def _ensure_temp_sensor_enabled(chip_id: int = 0):
    """
    0x202F Temp Sensor Cal/Control: [8]=core, [9]=bandgap을 1로 (RMW OR 0x0300).
    - LOAD_ADDRESS 0x202F → READ_REGISTER <chip_id> → (값|0x0300) → LOAD_ADDRESS 0x202F → WRITE_REGISTER <chip_id> 0x????.
    문서: enable 필드/초기화 예시 참고. :contentReference[oaicite:4]{index=4} :contentReference[oaicite:5]{index=5}
    """
    global __temp_enabled_once
    if __temp_enabled_once:
        return
    _ = run_cli("load_address 0x202F", settle=0.20)
    out = run_cli(f"read_register {chip_id}", settle=0.25)
    cur = _parse_last_hex(out)
    if cur is None:
        print("[Temp] 0x202F read 실패: 출력 형식 확인 필요\n--- tail ---\n", out)
        return
    if (cur & 0x0300) != 0x0300:
        newv = cur | 0x0300
        _ = run_cli("load_address 0x202F", settle=0.20)
        _ = run_cli(f"write_register {chip_id} 0x{newv:04X}", settle=0.25)
        print(f"[Temp] Enable TempSensor @0x202F: 0x{cur:04X} -> 0x{newv:04X}")
    __temp_enabled_once = True

def temp_read(chip_id: int = 0) -> int | None:
    """
    Temp_ADC(0x2037) 8-bit RAW 코드(0~255) 반환.
    시퀀스: (1) temp enable 보장 → (2) adc_capture → (3) load_address 0x2037 → (4) read_register <chip_id>
    - ADC는 ADC_CAPTURE(0x08) 때만 샘플/갱신, Temp_ADC=0x2037(8-bit)  :contentReference[oaicite:6]{index=6} :contentReference[oaicite:7]{index=7}
    """
    _ensure_temp_sensor_enabled(chip_id)
    _ = run_cli("adc_capture", settle=0.25)      # 25*2^DIV 클럭 후 업데이트 (μs급, 약간 대기) :contentReference[oaicite:8]{index=8}
    _ = run_cli("load_address 0x2037", settle=0.20)
    out = run_cli(f"read_register {chip_id}", settle=0.25)
    val16 = _parse_last_hex(out)
    if val16 is None:
        print("[Temp] read_register 파싱 실패\n--- tail ---\n", out)
        return None
    return val16 & 0xFF

print("[TIP] 이제 run_cli('get_channel_enables 0')나 temp_read(chip_id)를 바로 호출하세요.")


##############test

print(run_cli("spi_query"))        # 케이블 보임 확인
t = temp_read_via_spi(chip_id)     # 온도 RAW(0..255)
print("Temp ADC =", t)
print(run_cli("get_channel_enables 0"))  # 다시 CLI로 잘 복귀했는지
print(run_cli("set_common_atten 0 63 0 0 0"))