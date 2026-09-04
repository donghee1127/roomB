# -*- coding: utf-8 -*-
# Summit 2629e control + Temp read (pipe-only; no GUI console)
# 실행 환경: Windows, Python 3.10+, IPython 콘솔
# 사용법:
#   1) 이 파일 전체를 IPython에 붙여넣기/실행
#   2) 필요하면 아래 설정값(chip_id/channel/trx_mode/attn_mode)만 바꿔서 다시 실행
#   3) 측정 도중 임의 시점에:  cur_temp = temp_read(chip_id)

import subprocess, time, pathlib, threading, re
from collections import deque

# -------------------- 사용자 설정 --------------------
chip_id = 0
channel = "Tx_H0"      # 원하는 채널명
trx_mode = "tx"        # "tx" 또는 "rx"
attn_mode = 1          # 0이면 HTX sweep 예시 실행, 1이면 skip
spi_clk = 20_000_000   # CLI의 spi_init에 넘길 값 (20 MHz)

cli_path = pathlib.Path(r"C:\Program Files\Sivers Semiconductors\MIX2429E_CLI\MIXC2429E_CLI.exe")

# 채널 매핑(네 코드 그대로)
ch = {
    "Tx_H0": (2,0,0,0,2), "Tx_H1": (0,2,0,0,2), "Tx_H2": (0,0,2,0,2), "Tx_H3": (0,0,0,2,2),
    "Tx_V0": (8,0,0,0,8), "Tx_V1": (0,8,0,0,8), "Tx_V2": (0,0,8,0,8), "Tx_V3": (0,0,0,8,8),
    "Rx_H0": (1,0,0,0,1), "Rx_H1": (0,1,0,0,1), "Rx_H2": (0,0,1,0,1), "Rx_H3": (0,0,0,1,1),
    "Rx_V0": (4,0,0,0,4), "Rx_V1": (0,4,0,0,4), "Rx_V2": (0,0,4,0,4), "Rx_V3": (0,0,0,4,4),
    "Tx_H": (2,2,2,2,2), "Tx_V": (2,2,2,2,2), "Rx_H": (2,2,2,2,2), "Rx_V": (2,2,2,2,2),
}
m = {"tx": "set_tx_mode 0", "rx": "set_rx_mode 0"}
mode_cmd = m[trx_mode.lower()]  # 잘못된 값이면 KeyError

# -------------------- 파이프 기반 CLI I/O --------------------
PROC = None
_LOG = []                 # 전체 출력 라인 누적
_LOG_LOCK = threading.Lock()
_READER_STOP = threading.Event()

def _reader_thread(proc):
    # CLI stdout을 계속 읽어 _LOG에 라인 단위로 누적
    while not _READER_STOP.is_set():
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.01)
            continue
        with _LOG_LOCK:
            _LOG.append(line.rstrip())

def start_cli():
    """CLI를 새 콘솔 없이 파이프 모드로 실행하고 출력 리더 스레드를 시작."""
    global PROC, _READER_STOP, _LOG
    _LOG.clear()
    _READER_STOP.clear()
    PROC = subprocess.Popen(
        [str(cli_path)],
        cwd=str(cli_path.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,          # str 입출력
        bufsize=1           # 라인 버퍼링
        # 새 콘솔 생성 금지 (기본값이면 OK)
    )
    t = threading.Thread(target=_reader_thread, args=(PROC,), daemon=True)
    t.start()
    return PROC

def _snap_idx():
    with _LOG_LOCK:
        return len(_LOG)

def _get_since(idx):
    with _LOG_LOCK:
        return _LOG[idx:]

def send(cmd: str):
    """CLI에 한 줄 전송(+개행)."""
    if PROC is None or PROC.poll() is not None:
        raise RuntimeError("CLI 프로세스가 실행 중이 아닙니다.")
    PROC.stdin.write(cmd.rstrip() + "\n")
    PROC.stdin.flush()

def send_and_capture(cmd: str, quiet=0.12, timeout=1.5):
    """
    cmd를 보내고, 그 시점 이후 새로 생긴 출력 라인을 모아 반환.
    'quiet' 동안 신규 라인이 없으면 수집 종료.
    """
    idx0 = _snap_idx()
    send(cmd)
    t0 = time.time()
    last_len = 0
    while True:
        time.sleep(0.03)
        lines = _get_since(idx0)
        cur_len = len(lines)
        if cur_len != last_len:
            last_len = cur_len
            t0 = time.time()  # 출력이 갱신되면 quiet 타이머 초기화
        if time.time() - t0 >= quiet:
            return "\n".join(lines)
        if time.time() - (t0 - quiet) > timeout:
            # 전체 타임아웃 초과 시에도 종료
            return "\n".join(lines)

def last_hex(text: str):
    """문자열에서 가장 마지막 0x???? 형태의 헥사 값을 정수로 반환."""
    m = re.findall(r"0x([0-9A-Fa-f]{1,8})", text)
    return int(m[-1], 16) if m else None

# -------------------- 초기화/설정 (네 코드와 동일 동작) --------------------
def cli_init_sequence(chip_id: int, channel: str, mode_cmd: str, attn_mode: int, spi_clk: int):
    # 3) Initialize
    cmds = [
        f"spi_init 0 {spi_clk}",
        "spi_reset",
        f"init_device {chip_id}",
        f"get_short_ID {chip_id}",
        f"get_unique_ID {chip_id}",
    ]
    for c in cmds:
        _ = send_and_capture(c)

    # 4) T/Rx mode
    _ = send_and_capture(mode_cmd)

    # 5) Channel enable
    ce = ' '.join(map(str, ch[channel]))
    _ = send_and_capture(f"set_channel_enables {chip_id} {ce}")
    _ = send_and_capture(f"get_channel_enables {chip_id}")

    # 6) Atten 설정
    if attn_mode == 0:
        for htx in range(0, 10):
            out = send_and_capture(f"set_common_atten {chip_id} {htx} 0 0 0", quiet=0.05, timeout=1.0)
            print("sent:", f"set_common_atten {chip_id} {htx} 0 0 0")
            time.sleep(0.2)
    else:
        _ = send_and_capture(f"get_common_atten {chip_id}")

    # 7) Element Atten/Beam
    _ = send_and_capture(f"set_beam_set {chip_id} 0 0 0 20 0.0 20 0.0 20 0.0 20 0.0")
    _ = send_and_capture(f"set_beam_pointers {chip_id} 0 0 0 0")
    _ = send_and_capture("spi_beam_upd")

# -------------------- 온도 읽기 전용 유틸 --------------------
_TEMP_ENABLED = False

def _ensure_temp_enabled(chip_id: int):
    """
    0x202F 읽어 [9],[8] 비트가 꺼져있으면 OR 0x0300으로 enable.
    SPI UG 초기화 예시에도 같은 절차가 제시됨.  :contentReference[oaicite:4]{index=4} :contentReference[oaicite:5]{index=5}
    """
    global _TEMP_ENABLED
    if _TEMP_ENABLED:
        return

    _ = send_and_capture("load_address 0x202F")              # LOAD_POINTER 0x202F  :contentReference[oaicite:6]{index=6}
    out = send_and_capture(f"read_register {chip_id}")       # READ_REGISTER       :contentReference[oaicite:7]{index=7}
    cur = last_hex(out)
    if cur is None:
        print("[Temp] 0x202F read 실패: CLI 출력 형식 확인 필요")
        return
    if (cur & 0x0300) != 0x0300:
        newv = cur | 0x0300
        _ = send_and_capture("load_address 0x202F")
        _ = send_and_capture(f"write_register {chip_id} 0x{newv:04X}")  # WRITE_REGISTER  :contentReference[oaicite:8]{index=8}
        print(f"[Temp] enable: 0x202F {cur:04X} -> {newv:04X}")
    else:
        # 이미 enable
        pass
    _TEMP_ENABLED = True

def temp_read(chip_id: int) -> int | None:
    """
    Temp ADC 원시 코드(0..255) 반환. 절대 °C 환산은 보정에 의존.
    절차: ensure enable → adc_capture → load_address 0x2037 → read_register
    근거: ADC 업데이트는 ADC_CAPTURE(0x08), Temp_ADC=0x2037(8-bit).  :contentReference[oaicite:9]{index=9} :contentReference[oaicite:10]{index=10}
    """
    _ensure_temp_enabled(chip_id)

    # 트리거
    _ = send_and_capture("adc_capture")                      # command 0x08  :contentReference[oaicite:11]{index=11}
    # 변환 시간은 25*2^DIV 클럭(기본 DIV=1). μs급이므로 소폭 대기.  :contentReference[oaicite:12]{index=12}
    time.sleep(0.002)

    # 읽기
    _ = send_and_capture("load_address 0x2037")             # Temp_ADC addr  :contentReference[oaicite:13]{index=13}
    out = send_and_capture(f"read_register {chip_id}")
    val16 = last_hex(out)
    if val16 is None:
        print("[Temp] read_register 결과 파싱 실패")
        return None
    return val16 & 0xFF

def run_cli(cmd: str, quiet=0.12, timeout=1.5) -> str:
    """원하는 CLI 명령을 임의로 실행하고 출력 텍스트를 바로 가져온다(디버그/검증용)."""
    return send_and_capture(cmd, quiet=quiet, timeout=timeout)

# -------------------- 시작 시 자동 초기화 --------------------
try:
    if PROC is None or PROC.poll() is not None:
        start_cli()
    cli_init_sequence(chip_id, channel, mode_cmd, attn_mode, spi_clk)
    print("[CLI] init 완료. 이제 temp_read(chip_id) 호출로 온도 읽기 가능.")
except Exception as e:
    print("초기화 중 오류:", e)
