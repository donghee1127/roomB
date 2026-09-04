# 실제 Script 구동

import subprocess, time, pathlib, pyautogui, pyperclip
import win32gui, win32con, win32process

chip_id = 0
channel = "Tx_H0"  # 원하는 채널명으로 바꾸세요
trx_mode = "tx"  # "tx" 또는 "rx"
attn_mode = 1 # 0이면 실행, 1이면 skip

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

# 4) T/Rx mode 설정
pyautogui.write(mode)
pyautogui.press("enter")

# 5) Channel enable
#pyautogui.write(f"set_channel_enables {chip_id} 2 0 0 0 2")
pyautogui.write(f"set_channel_enables {chip_id} {' '.join(map(str, ch[channel]))}")
pyautogui.press("enter")
pyautogui.write(f"get_channel_enables {chip_id}")
pyautogui.press("enter")

# 6) Atten 설정 (Gain index 설정)

# 예) set_common_atten 0 HTX VTX HRX VRX
# 지정한 Path를 0~63으로 1초 간격 sweep, 나머지는 고정값
# This command sets the four 6-bit values for the common path attenuators. (1당 0.5dB씩 감소. 0이 최대)
if attn_mode == 0:
    for htx in range(0, 10):  # 0..63
        cmd = f"set_common_atten {chip_id} {htx} 0 0 0"
        pyautogui.write(cmd)     # 한 글자씩 타이핑
        pyautogui.press("enter") # 실행
        print("sent:", cmd)
        time.sleep(0.2)          # Sweep timing 간격 설정
        
else:
    #pyautogui.write(f"set_common_atten {chip_id} 63 63 63 63")
    pyautogui.write(f"get_common_atten {chip_id}")
    pyautogui.press("enter")

# 7) Element Atten 설정 

pyautogui.write(f"set_beam_set {chip_id} 0 0 0 20 0.0 20 0.0 20 0.0 20 0.0") # 0(Chip ID) 0(Index) 0(Tx/Rx) 0(H/V) 10(CH0 Gain) 0.0(CH0 Phase) ...
pyautogui.press("enter")
pyautogui.write(f"set_beam_pointers {chip_id} 0 0 0 0") #<chip_id> <HTX> <VTX> <HRX> <VRX>
pyautogui.press("enter")
pyautogui.write("spi_beam_upd")
pyautogui.press("enter")


print("완료! 이제 같은 CLI 창에서 계속 원하는 명령을 수동으로 입력하면 됩니다.")

## 빔북 로드
#load_beam_table 0
#C:\Users\sejin1.yang\beam_table_2048.csv #경로 입력하라고 나오면 잘쳐야함 로딩하는데 꽤걸림




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

