###################Beam Book 생성 ###########################

import subprocess, time, pathlib, pyautogui, pyperclip
import win32gui, win32con, win32process

channel = "Tx_H0"  # 원하는 채널명으로 바꾸세요
trx_mode = "tx"  # "tx" 또는 "rx"
attn_mode = 0 # 0이면 실행, 1이면 skip

ch = {
    "Tx_H0": (2,0,0,0,2), "Tx_H1": (0,2,0,0,2), "Tx_H2": (0,0,2,0,2), "Tx_H3": (0,0,0,2,2),
    "Tx_V0": (8,0,0,0,8), "Tx_V1": (0,8,0,0,8), "Tx_V2": (0,0,8,0,8), "Tx_V3": (0,0,0,8,8),
    "Rx_H0": (1,0,0,0,1), "Rx_H1": (0,1,0,0,1), "Rx_H2": (0,0,1,0,1), "Rx_H3": (0,0,0,1,1),
    "Rx_V0": (4,0,0,0,4), "Rx_V1": (0,4,0,0,4), "Rx_V2": (0,0,4,0,4), "Rx_V3": (0,0,0,4,4),
    "Tx_H": (2,2,2,2,2), "Tx_V": (2,2,2,2,2), "Rx_H": (2,2,2,2,2), "Rx_V": (2,2,2,2,2),
}

m = {"tx": "set_tx_mode 0", "rx": "set_rx_mode 0"}
mode = m[trx_mode.lower()]  # 잘못된 값이면 KeyError

# 1) 새 콘솔로 CLI 실행
cli_path = pathlib.Path(r"C:\Program Files\Sivers Semiconductors\MIX2429E_CLI\MIXC2429E_CLI.exe")
proc = subprocess.Popen([str(cli_path)],
                        cwd=str(cli_path.parent),
                        creationflags=subprocess.CREATE_NEW_CONSOLE)                 

# 2) 방금 띄운 프로세스의 콘솔 창을 찾아 전면으로 가져오기
def bring_to_front_by_pid(pid, retry=20, delay=0.1):
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
            return True
        time.sleep(delay)
    return False

bring_to_front_by_pid(proc.pid)  # 실패하더라도 보통 기본 포커스로 붙음.

# 안전: 키보드 동작 사이 디폴트 지연(초). 너무 빠르면 0.0~0.02로 낮춰도 됨.
pyautogui.PAUSE = 0.02

# 3) Initialize Step / init_devcie 0 에서 약 11초 걸림
cmds = """\
spi_init 0 20000000
spi_reset
init_device 0
get_short_ID 0
get_unique_ID 0
"""
pyperclip.copy(cmds)
pyautogui.hotkey('ctrl', 'v')
time.sleep(0.1)
pyautogui.press("enter")

# ===== Beam Table full build (2048 entries) & CSV store =====
chip_id = 0

def type_and_enter(cmd: str, sleep=0.2):
    pyautogui.write(cmd)
    pyautogui.press("enter")
    time.sleep(sleep)

# (1) TX / H-pol : index 0..511
# Gains: 20 -> 5 (16 steps), Phases: 0.0 .. 348.75 (32 steps, 11.25 step)
time.sleep(2)
index = 0
for gain in range(20, 4, -1):                 # 20..5
    for k in range(32):                        # 0..31
        ph = 11.25 * k                         # 0.0 .. 348.75
        cmd = f"set_beam_set {chip_id} {index} 0 0 {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f}"
        type_and_enter(cmd)
        index += 1
time.sleep(2)
index = 512
# (2) TX / V-pol : index 512..1023
for gain in range(20, 4, -1):
    for k in range(32):
        ph = 11.25 * k
        cmd = f"set_beam_set {chip_id} {index} 0 1 {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f}"
        type_and_enter(cmd)
        index += 1
time.sleep(2)
index = 1024
# (3) RX / H-pol : index 1024..1535
for gain in range(32, 16, -1):                 # 32..17
    for k in range(32):
        ph = 11.25 * k
        cmd = f"set_beam_set {chip_id} {index} 1 0 {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f}"
        type_and_enter(cmd)
        index += 1
time.sleep(2)
index = 1536
# (4) RX / V-pol : index 1536..2047
for gain in range(32, 16, -1):
    for k in range(32):
        ph = 11.25 * k
        cmd = f"set_beam_set {chip_id} {index} 1 1 {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f} {gain} {ph:.1f}"
        type_and_enter(cmd)
        index += 1

# 안전 체크: 마지막 인덱스는 2048이어야 함
assert index == 2048, f"Indexed {index} entries, expected 2048"

# (저장) 전체 0~2047 범위를 CSV로 백업
# store_beam_table <chip_id> <start_index> <num>
# => 0부터 2048개 엔트리를 저장해야 0..2047 전체가 저장됨
type_and_enter(f"store_beam_table {chip_id} 0 2048", sleep=0.1)


store_beam_table 0 0 2048

C:\Users\sejin1.yang\Documents\beambook.csv
