# -*- coding: utf-8 -*-
"""
Summit 2629e 제어 스크립트 (가독성·안정성 주석 강화판)

아키텍처
1) 고수준 제어(채널, 모드, 빔 등)는 'MIXC2429E_CLI.exe'를 "새 콘솔"로 띄워
   키보드 자동화(pyautogui)로 명령을 보내고, 콘솔 화면을 안전하게 복사해 tail만 캡처(run_cli)한다.
   - 이유: 이 CLI는 stdout 파이프 대신 콘솔 API(WriteConsole)로 출력하므로 PIPE 모드로는 텍스트를 못 읽는 경우가 많음.
   - 해결: 콘솔 버퍼 전체를 복사(Windows Terminal: Ctrl+Shift+A/C, 고전 콘솔: Alt+Space→E→A→Enter),
           "명령 전/후" 버퍼 차이만 잘라 tail로 반환.

2) 온도 읽기만은 FTDI MPSSE(ftd2xx)로 "직접 SPI"에 접근한다.
   - CLI에 'load_address/read_register/adc_capture' 같은 저수준 명령이 없는 빌드가 있어 CLI로는 직접 레지스터 접근 불가.
   - 절차: CLI가 잡고 있던 FTDI 핸들을 'spi_close'로 잠깐 릴리즈 → Python이 MPSSE로 읽기 →
           곧바로 CLI에 'spi_init'으로 핸들 복귀.
   - SPI 프로토콜 규약(요점):
       * 32-bit 트랜잭션, LSB-first. (바이트마다 bit reverse 필요)
       * 상위 16bit: [0]=IDTYPE(1), [1..8]=CHIP_ID, [9..15]=CMD(7bit)
         하위 16bit: Payload(레지스터 주소/데이터)
       * READ_REGISTER는 MOSI로 상위 16비트만 내보내고, 이후 16클럭 동안 MISO에서 페이로드가 나옴.
       * Temp 센서 값: ADC_CAPTURE 후 Temp_ADC(0x2037)에 8-bit로 갱신. Core/Bandgap enable 비트는 0x202F의 [8],[9].

사용법
- 이 파일(셀)을 IPython에 "통째로" 붙여 실행하면 CLI가 자동 초기화되고, 채널/빔까지 설정됨.
- 이후 아무 때나:
    print(run_cli("get_channel_enables 0"))
    t = temp_read_via_spi(chip_id)   # 0..255 (RAW)
    print("Temp ADC =", t)
"""

# -------------------- 필수 라이브러리 --------------------
import subprocess, time, pathlib, re
import pyautogui, pyperclip
import win32gui, win32con, win32process   # 콘솔 창 포커스/복원
import ftd2xx as ftd                      # FTDI MPSSE (SPI 저수준)
import os, csv

# -------------------- 사용자 설정 --------------------
chip_id   = 0
channel   = "Tx_H0"            # 아래 ch 사전 중에서 선택
trx_mode  = "tx"               # "tx" 또는 "rx"
attn_mode = 1                  # 0: 공통 Atten HTX sweep 예시 실행, 1: sweep 생략
spi_clk   = 20_000_000         # SPI 클럭(Hz) – CLI와 Python(MPSSE) 모두 동일 속도로 사용
cli_path  = pathlib.Path(r"C:\Program Files\Sivers Semiconductors\MIX2429E_CLI\MIXC2429E_CLI.exe")

# 채널 → (HTX, VTX, HRX, VRX, Common) 매핑
ch = {
    "Tx_H0": (2,0,0,0,2), "Tx_H1": (0,2,0,0,2), "Tx_H2": (0,0,2,0,2), "Tx_H3": (0,0,0,2,2),
    "Tx_V0": (8,0,0,0,8), "Tx_V1": (0,8,0,0,8), "Tx_V2": (0,0,8,0,8), "Tx_V3": (0,0,0,8,8),
    "Rx_H0": (1,0,0,0,1), "Rx_H1": (0,1,0,0,1), "Rx_H2": (0,0,1,0,1), "Rx_H3": (0,0,0,1,1),
    "Rx_V0": (4,0,0,0,4), "Rx_V1": (0,4,0,0,4), "Rx_V2": (0,0,4,0,4), "Rx_V3": (0,0,0,4,4),
    "Tx_H": (2,2,2,2,2), "Tx_V": (2,2,2,2,2), "Rx_H": (2,2,2,2,2), "Rx_V": (2,2,2,2,2),
}

# TR 모드 명령어
mode_cmd = {"tx": "set_tx_mode 0", "rx": "set_rx_mode 0"}[trx_mode.lower()]

# pyautogui 기본 지연(키 입력 간 텀). 너무 빠르면 누락되므로 20~40ms 권장
pyautogui.PAUSE = 0.03


# =====================================================================
# 0) 콘솔 창 핸들 찾기/전면으로 가져오기
# =====================================================================
def bring_to_front_by_pid(pid: int, retry: int = 30, delay: float = 0.1):
    """
    주어진 PID의 최상위(visible) 윈도우를 찾아 전면 포커스로 올린다.
    - pyautogui로 키 입력/복사를 시도하기 전 반드시 호출(포커스 보장)
    """
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
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)  # 최소화 상태 복원
            try:
                win32gui.SetForegroundWindow(hwnd)          # 전면 포커스
            except Exception:
                pass
            return hwnd
        time.sleep(delay)
    return None


# =====================================================================
# 1) 콘솔 전체 복사 & tail 추출 (출력 캡처의 핵심)
# =====================================================================
def _copy_console_all_text(proc_pid: int, pause: float = 0.09, max_retry: int = 3) -> str:
    """
    현재 콘솔 버퍼 전체를 '텍스트'로 복사해 반환.
    - Windows Terminal: Ctrl+Shift+A(전체선택) → Ctrl+Shift+C(복사)
    - 고전 콘솔(conhost): Alt+Space(시스템메뉴) → 'E'(Edit) → 'A'(Select All) → Enter(복사)
    - 일부 영문 콘솔 호환: Alt+Space → 'E' → 'S' → Enter
    * 복사 성공을 센티넬 문자열로 검증하여, 실패 시 다른 루트로 폴백
    """
    bring_to_front_by_pid(proc_pid)

    sentinel = "__CLIP_SENTINEL__"
    for _ in range(max_retry):
        # 0) 클립보드를 센티넬로 초기화(복사 성공 여부 판별용)
        try:
            pyperclip.copy(sentinel)
        except Exception:
            pass

        # (A) Windows Terminal 경로
        pyautogui.hotkey('ctrl', 'shift', 'a')   # Select All
        time.sleep(0.05)
        pyautogui.hotkey('ctrl', 'shift', 'c')   # Copy
        time.sleep(pause)
        txt = pyperclip.paste() or ""
        if txt and txt != sentinel:
            return txt

        # (B) 고전 콘솔 경로 (로캘-내성: 'A'=모두선택)
        pyautogui.keyDown('alt'); pyautogui.press('space'); pyautogui.keyUp('alt'); time.sleep(0.06)
        pyautogui.press('e'); time.sleep(0.04)   # Edit
        pyautogui.press('a'); time.sleep(0.06)   # Select All
        pyautogui.press('enter'); time.sleep(pause)  # Copy
        txt = pyperclip.paste() or ""
        if txt and txt != sentinel:
            return txt

        # (C) 일부 영문 콘솔(단축키가 'S'인 경우) 폴백
        pyautogui.keyDown('alt'); pyautogui.press('space'); pyautogui.keyUp('alt'); time.sleep(0.06)
        pyautogui.press('e'); time.sleep(0.04)
        pyautogui.press('s'); time.sleep(0.06)
        pyautogui.press('enter'); time.sleep(pause)
        txt = pyperclip.paste() or ""
        if txt and txt != sentinel:
            return txt

    return ""  # 끝까지 실패해도 빈 문자열 반환(상위에서 폴백 처리)


def _send_and_capture_tail(proc_pid: int, cmd: str, settle: float = 0.28, tail_win: int = 8000) -> str:
    """
    콘솔에 'cmd'를 입력하고(Enter), 출력이 다 찍힐 때까지 약간 기다린 뒤,
    "명령 전후 콘솔 버퍼의 차이"만 잘라 tail로 반환.
    - settle: CLI가 느린 PC/USB 환경이면 0.30~0.35로 늘려주세요.
    - tail_win: 스크롤/롤링으로 앞부분이 사라진 경우를 대비해 뒤쪽 일부를 기준으로 diff 계산.
    """
    bring_to_front_by_pid(proc_pid)
    before = _copy_console_all_text(proc_pid)
    pyautogui.write(cmd); pyautogui.press("enter")
    time.sleep(settle)
    after = _copy_console_all_text(proc_pid)

    if after.startswith(before):
        return after[len(before):]

    # 롤링 등으로 앞부분이 일치하지 않으면 뒤쪽 구간으로 diff 시도
    pivot = before[-tail_win:]
    idx = after.rfind(pivot)
    if idx >= 0:
        return after[idx + len(pivot):]

    # 최후에는 after의 맨 뒤 일부만이라도 반환
    return after[-tail_win:]


def run_cli(cmd: str, settle: float = 0.28) -> str:
    """
    (외부 호출용) CLI에 한 줄 명령을 보내고 해당 명령으로 새로 출력된 텍스트를 반환.
    - 내부적으로 콘솔 전체 복사 + tail 추출을 사용.
    - 반환 텍스트에는 에코 줄/마지막 '>' 프롬프트를 포함할 수 있으므로,
      필요하면 호출부에서 strip() 또는 후처리.
    """
    out = _send_and_capture_tail(proc.pid, cmd, settle=settle)
    # 기본 정리: 첫 줄이 에코된 명령이면 제거, 끝의 '>' 프롬프트 제거
    out = out.replace("\r", "")
    lines = [ln for ln in out.split("\n")]
    if lines and lines[0].strip() == cmd.strip():
        lines = lines[1:]
    while lines and lines[-1].strip() in ("", ">"):
        lines.pop()
    return "\n".join(lines)



# =====================================================================
# 2) FTDI MPSSE: SPI 직통(온도 전용) – 안정 오픈/클럭/트랜잭션 유틸
# =====================================================================
_SPI_CLK_HZ = spi_clk  # CLI와 동일 속도로 사용(원하면 독립적으로 바꿔도 됨)

def _rev8(x: int) -> int:
    """바이트 단위 비트 순서 뒤집기(LSB-first <-> MSB-first 변환). MPSSE 명령은 MSB-first이므로 데이터 바이트는 반전해서 보냄."""
    x = ((x & 0xF0) >> 4) | ((x & 0x0F) << 4)
    x = ((x & 0xCC) >> 2) | ((x & 0x33) << 2)
    x = ((x & 0xAA) >> 1) | ((x & 0x55) << 1)
    return x & 0xFF

def _mpsse_open(clock_hz: int, max_wait_s: float = 3.0):
    """
    FTDI 핸들을 튼튼하게 오픈:
    - CLI에서 'spi_close' 직후 드라이버가 핸들을 반납하는 데 소요되는 지연을 재시도로 흡수.
    - listDevices()로 장치를 열거, description 우선 openEx → 실패 시 index=0 폴백.
    - 네가 쓰던 MPSSE 초기화(3-phase, /5 disable, 클럭 설정) 그대로 적용.
    - GPIO LowByte를 읽어 현재 라인 상태를 유지하고, CS(ADBUS3)만 토글(다른 라인 건드리지 않음).
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

    OPEN_BY_DESC = getattr(ftd, "OPEN_BY_DESCRIPTION", 2)

    while True:
        try:
            # 1) 장치 목록에서 유의미한 description 선택
            dev_names = _list_all()
            cand_desc = None
            for pref in ("C232HM", "FT232H", "USB", "SPI"):
                cand_desc = next((n for n in dev_names if pref.lower() in n.lower()), None)
                if cand_desc:
                    break

            # 2) description 우선, 없으면 index=0 폴백
            d = ftd.openEx(cand_desc, OPEN_BY_DESC) if cand_desc else ftd.open(0)

            # 3) 타임아웃/레이트/모드 설정
            d.setTimeouts(100, 100)
            try:
                d.setLatencyTimer(2)
            except Exception:
                pass
            d.setBitMode(0x00, 0x00); time.sleep(0.02)  # Reset
            d.setBitMode(0x00, 0x02)                    # MPSSE
            d.write(bytes([0x8A]))                      # Disable divide-by-5
            d.write(bytes([0x97]))                      # Enable 3-phase clocking
            div = int(60_000_000/(2*clock_hz)) - 1
            d.write(bytes([0x86, div & 0xFF, (div >> 8) & 0xFF]))

            # 4) 현재 GPIO LowByte 확보 → CS만 제어
            d.write(bytes([0x81])); time.sleep(0.01)
            n = d.getQueueStatus()
            gpio_low = d.read(n)[0] if n else 0xFF
            d._gpio_low = gpio_low | 0x08             # CS=High 기본
            d.write(bytes([0x80, d._gpio_low & 0xFF, 0xFF]))  # value, direction(모두 출력)
            return d

        except ftd.DeviceError:
            if time.time() > t_end:
                print("[FTDI] open 실패. listDevices() =", _list_all())
                raise
            time.sleep(0.1)

def _cs_low(d):  # CS 활성(0)
    d._gpio_low &= ~0x08
    d.write(bytes([0x80, d._gpio_low & 0xFF, 0xFF]))

def _cs_high(d): # CS 비활성(1)
    d._gpio_low |= 0x08
    d.write(bytes([0x80, d._gpio_low & 0xFF, 0xFF]))

def _mpsse_write_bytes(d, data: bytes):
    """
    MOSI로 data를 보냄(클럭 생성). 명령 0x11은 "MSB-first, -ve edge"라서
    LSB-first 데이터인 칩 규격에 맞추기 위해 바이트는 사전에 _rev8() 처리해서 준다.
    """
    if not data: return
    n = len(data)
    d.write(bytes([0x11, (n-1) & 0xFF, ((n-1) >> 8) & 0xFF]) + data)

def _mpsse_read_bytes(d, n: int) -> bytes:
    """MISO에서 n바이트를 읽음(클럭 생성). 명령 0x20: 'MSB-first, +ve edge'."""
    if n <= 0: return b""
    d.write(bytes([0x20, (n-1) & 0xFF, ((n-1) >> 8) & 0xFF]))
    return d.read(n)

def _clock_dummy(d, num_bits: int):
    """CS 상태와 무관하게 '클럭만' 더 주고 싶을 때 사용(ADC_CAPTURE 후 여유 클럭)."""
    if num_bits <= 0: return
    num_bytes = (num_bits + 7) // 8
    _mpsse_write_bytes(d, b"\x00"*num_bytes)

def _first16(chip_id: int, cmd7: int) -> bytes:
    """
    트랜잭션 상위 16비트(LSB-first):
      bit0 = IDTYPE(1로 고정), bit1..8 = CHIP_ID, bit9..15 = CMD[6:0]
    MPSSE는 MSB-first이므로, 각 바이트는 _rev8() 한 값을 보낸다.
    """
    v  = (1) | ((chip_id & 0xFF) << 1) | ((cmd7 & 0x7F) << 9)
    b0 = _rev8(v & 0xFF)
    b1 = _rev8((v >> 8) & 0xFF)
    return bytes([b0, b1])

def _payload16_bytes(val16: int) -> bytes:
    """하위 16비트 Payload(레지스터 주소/데이터). 바이트는 LSB-first → _rev8() 후 송출."""
    lo, hi = (val16 & 0xFF), ((val16 >> 8) & 0xFF)
    return bytes([_rev8(lo), _rev8(hi)])

# SPI 명령(칩 규격): LOAD_POINTER=0x00, READ=0x01, WRITE=0x02, ADC_CAPTURE=0x08
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
    """
    READ_REGISTER: MOSI로 상위 16비트(ID/CHIP/CMD)만 내보내고,
    이어지는 16클럭 동안 MISO에 데이터가 출력됨(=여기서 2바이트 읽기).
    """
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x01))
    raw = _mpsse_read_bytes(d, 2)   # 페이로드 16비트
    _cs_high(d)
    if len(raw) != 2:
        raise RuntimeError("MPSSE read underrun")
    lo = _rev8(raw[0]); hi = _rev8(raw[1])
    return (hi << 8) | lo

def _adc_capture(d, chip: int = 0xFF):
    """
    ADC_CAPTURE 트리거: 16번째 SCLK에서 시작하고 25*2^DIV 클럭 후 레지스터에 갱신됨.
    - 상위 16비트만 전송하고 나머지 16클럭은 읽기 명령으로 소모(무시).
    - 이후 안전을 위해 여유 클럭 더 제공(예: 32비트). CS가 High여도 SCLK만 있으면 OK.
    """
    _cs_low(d)
    _mpsse_write_bytes(d, _first16(chip, 0x08))
    _mpsse_read_bytes(d, 2)   # 잔여 16클럭 생성(무시)
    _cs_high(d)
    _clock_dummy(d, 32)


def temp_read_via_spi(chip_id: int = 0, restore_clk: int = _SPI_CLK_HZ) -> int | None:
    """
    [외부용] "온도만" SPI로 직접 읽기(8-bit RAW).
    흐름: CLI의 FTDI 핸들을 잠깐 풀고(spi_close) → Python이 MPSSE로 읽기 → CLI에 즉시 spi_init 복귀.
    반환: 0..255 (RAW) / 실패 시 None
    """
    try:
        # 1) CLI가 잡고 있는 FTDI 핸들을 릴리즈 (CLI 창은 그대로 유지됨)
        _ = run_cli("spi_close", settle=0.25)
        time.sleep(0.20)  # 드라이버가 핸들을 완전히 반납하도록 약간 대기

        # 2) Python이 FTDI를 오픈(MPSSE 진입)
        d = _mpsse_open(restore_clk)
        try:
            # 3) (필요 시) Temp 센서 enable 보장: 0x202F의 [8]=core, [9]=bandgap ON
            _load_pointer(d, 0x202F, 0xFF)        # 브로드캐스트로 포인터 지정
            cur_202F = _read_reg16(d, chip_id)
            if (cur_202F & 0x0300) != 0x0300:
                _load_pointer(d, 0x202F, 0xFF)
                _write_reg16(d, chip_id, cur_202F | 0x0300)

            # 4) ADC 캡처 트리거 후 여유 클럭 제공
            _adc_capture(d, 0xFF)

            # 5) Temp_ADC(0x2037) 읽기(8-bit 유효)
            _load_pointer(d, 0x2037, 0xFF)
            val16 = _read_reg16(d, chip_id)
            return val16 & 0xFF

        finally:
            try:
                d.close()
            except Exception:
                pass

    finally:
        # 6) CLI가 다시 케이블을 잡도록 복구
        _ = run_cli(f"spi_init 0 {restore_clk}", settle=0.35)


# =====================================================================
# 3) CLI 실행(새 콘솔) + 초기화/모드/채널/빔 설정
# =====================================================================
# (1) CLI 실행
proc = subprocess.Popen([str(cli_path)],
                        cwd=str(cli_path.parent),
                        creationflags=subprocess.CREATE_NEW_CONSOLE)
assert bring_to_front_by_pid(proc.pid), "CLI 창을 찾을 수 없습니다."

# (2) 초기화 시퀀스: paste로 한번에 주입
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
time.sleep(0.3)  # init_device가 길 수 있어 약간 여유

# (3) TR 모드 설정
pyautogui.write(mode_cmd); pyautogui.press("enter")

# (4) 채널 enable / 확인
pyautogui.write(f"set_channel_enables {chip_id} {' '.join(map(str, ch[channel]))}"); pyautogui.press("enter")
pyautogui.write(f"get_channel_enables {chip_id}"); pyautogui.press("enter")

# (6) 공통 Atten Max 설정
pyautogui.write(f"set_common_atten {chip_id} 0 0 0 0"); pyautogui.press("enter")

# (6) 공통 Atten: sweep 예시 또는 현 상태 확인
if attn_mode == 0:
    for htx in range(0, 10):   # 0..63 sweep 예시
        cmd = f"set_common_atten {chip_id} {htx} 0 0 0"
        pyautogui.write(cmd); pyautogui.press("enter")
        print("sent:", cmd)
        time.sleep(0.2)
else:
    pyautogui.write(f"get_common_atten {chip_id}"); pyautogui.press("enter")

# (6) 빔 셋업(인덱스 0 예시) → 포인터 0 → 적용
pyautogui.write(f"set_beam_set {chip_id} 0 0 0 20 0.0 20 0.0 20 0.0 20 0.0"); pyautogui.press("enter")
pyautogui.write(f"set_beam_pointers {chip_id} 0 0 0 0"); pyautogui.press("enter")
pyautogui.write("spi_beam_upd"); pyautogui.press("enter")

print("[CLI] 기본 초기화/설정 전송 완료. 이제 run_cli('...') 또는 temp_read_via_spi()로 제어하세요.")


##############test

print(run_cli("spi_query"))        # 케이블 보임 확인
t = temp_read_via_spi(chip_id)     # 온도 RAW(0..255)
print("Temp ADC =", t)
print(run_cli("get_channel_enables 0"))  # 다시 CLI로 잘 복귀했는지
print(run_cli("set_common_atten 0 63 0 0 0"))

print(run_cli("set_channel_enables 0 2 0 0 0 2"))
print(run_cli("set_common_atten 0 0 0 0 0"))

print(run_cli("set_beam_set 0 0 0 0 20 0.0 20 0.0 20 0.0 20 0.0"))



print(run_cli("set_common_atten 0 2 0 0 0"))
print(run_cli("set_common_atten 0 4 0 0 0"))


############ 명령어 Archive###############
#spi_init 0 20000000
#spi_reset
#init_device 0
#get_short_ID 0
#get_unique_ID 0
#set_tx_mode 0
#set_channel_enables 0 2 0 0 0 2 #Tx_H0
#set_channel_enables 0 0 2 0 0 2 #Tx_H1
#set_channel_enables 0 0 0 2 0 2 #Tx_H2
#set_channel_enables 0 0 0 0 2 2 #Tx_H3
#
#set_channel_enables 0 8 0 0 0 8 #Tx_V0
#set_channel_enables 0 0 8 0 0 8 #Tx_V1
#set_channel_enables 0 0 0 8 0 8 #Tx_V2
#set_channel_enables 0 0 0 0 8 8 #Tx_V3
#
#set_channel_enables 0 1 0 0 0 1 #Rx_H0
#set_channel_enables 0 0 1 0 0 1 #Rx_H1
#set_channel_enables 0 0 0 1 0 1 #Rx_H2
#set_channel_enables 0 0 0 0 1 1 #Rx_H3
#
#set_channel_enables 0 4 0 0 0 4 #Rx_V0
#set_channel_enables 0 0 4 0 0 4 #Rx_V1
#set_channel_enables 0 0 0 4 0 4 #Rx_V2
#set_channel_enables 0 0 0 0 4 4 #Rx_V3
#
#get_channel_enables 0 # 0x00:off 0x03:H 0x0c:V (e,g, Tx_H0/ Enable Bits: CH0 0x03, CH1 0x00, CH2 0x00, CH3 0x00, Common 0x03)
####### Common Gain Index 조절
##set_common_atten <chip_id> <HTX> <VTX> <HRX> <VRX>
##get_common_atten <chip_id>
#set_common_atten 0 63 63 0 0
#get_common_atten 0
#
#
#spi_close
#
#
#set_beam_set 0 0 0 0 20 0.0 20 0.0 20 0.0 20 0.0 #<chip id> <index> <RXTX> <pol> <CH0 GAIN> <CH0 PH> ... <CH3 GAIN> <CH3 PH>
#이 명령은 빔 테이블의 위치<index>를 Command Line의 게인(Gain) 및 위상(Phase) 매개변수와 함께 저장합니다.
#<RXTX> RX = 1, TX = 0 / <pol> H-pol = 0, V-pol = 1 --> rxtx 및 pol 값은 특정 채널에 대한 최적의 보정을 선택합니다.
#나머지 숫자는 4개 채널(element)의 게인(Gain) 설정 및 위상(Phase) 설정을 나타냅니다.
#게인은 TX의 경우 5~20dB, RX의 경우 17~32dB 사이에서 1dB 단위로 설정되며 정수 값으로 입력해야 합니다.
#위상 값은 0.0~360.0도 사이이며 11.25도 step으로 설정 가능하며 소수점을 포함해야 합니다.
#
#set_beam_pointers 0 0 0 0 0 #<chip_id> <HTX> <VTX> <HRX> <VRX>
#이 명령은 H-pol 및 V-pol TX와 RX에 대한 현재 빔 테이블 포인터를 각각 설정합니다. 
#이 명령은 빔 포머 제어 상태를 업데이트하지 않으며, spi_beam_upd를 실행해야 적용됩니다. 
#이 명령은 H-pol 및 V-pol TX와 RX에 대한 현재 빔 테이블 포인터를 각각 설정합니다. 
#이 명령은 빔 포머 제어 상태를 업데이트하지 않으며, spi_beam_upd를 실행해야 적용됩니다.
#
#spi_beam_upd
#set_beam_pointers 실행 후 실행해야 실제로 테이블이 적용됨