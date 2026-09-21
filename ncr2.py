import RPi.GPIO as GPIO
import time
import re
import shutil
from datetime import datetime
import os

# =========================================================
# 0. 로그 설정
# =========================================================
SCRIPT_PATH = os.path.abspath(__file__)
LOG_FILENAME = os.path.abspath(f"ncr_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
log_lines = []

def log_print(message):
    print(message)
    log_lines.append(message)

def save_log():
    try:
        with open(LOG_FILENAME, "w") as f:
            for line in log_lines:
                f.write(line + "\n")
    except Exception as e:
        print(f"[ERROR] Failed to save log: {e}")

# =========================================================
# 1. GPIO 및 SPI 핀 설정
# =========================================================
SCLK_PIN = 11
MOSI_PIN = 10
MISO_PIN = 9

ALL_CS_PINS = [8, 2, 5, 6]
ALL_CHANNELS = [1, 2, 3, 4]
CURRENT_TARGET_CS = []
CURRENT_TARGET_CHANNELS = []

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(SCLK_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MOSI_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MISO_PIN, GPIO.IN)

for pin in ALL_CS_PINS:
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)

# =========================================================
# 2. 레지스터 정의
# =========================================================
REG_GAIN = [0x01C, 0x01D, 0x01E, 0x01F]
REG_PHASE_I = [0x020, 0x022, 0x024, 0x026]
REG_PHASE_Q = [0x021, 0x023, 0x025, 0x027]

# =========================================================
# 2-1. ADAR1000 위상 룩업 테이블 (Rev. B, Table 10 ~ Table 13)
#
#  - 128 스텝, 스텝당 2.8125도 (index * 2.8125 = 위상[도])
#  - 각 엔트리는 (I Reg, Q Reg), Bit5 = 극성(polarity), Bit[4:0] = VM VGA gain
#  - index 0 = (0x3F, 0x20) = 0도 기준점 (= 빔 캘리브레이션의 측정 조건)
# =========================================================
PHASE_STEP_DEG = 360.0 / 128.0   # 2.8125

PHASE_TABLE = [
    (0x3F, 0x20), (0x3F, 0x21), (0x3F, 0x23), (0x3F, 0x24),   # idx   0 ..   3  (  0.0000 deg ..)
    (0x3F, 0x26), (0x3E, 0x27), (0x3E, 0x28), (0x3D, 0x2A),   # idx   4 ..   7  ( 11.2500 deg ..)
    (0x3D, 0x2B), (0x3C, 0x2D), (0x3C, 0x2E), (0x3B, 0x2F),   # idx   8 ..  11  ( 22.5000 deg ..)
    (0x3A, 0x30), (0x39, 0x31), (0x38, 0x33), (0x37, 0x34),   # idx  12 ..  15  ( 33.7500 deg ..)
    (0x36, 0x35), (0x35, 0x36), (0x34, 0x37), (0x33, 0x38),   # idx  16 ..  19  ( 45.0000 deg ..)
    (0x32, 0x38), (0x30, 0x39), (0x2F, 0x3A), (0x2E, 0x3A),   # idx  20 ..  23  ( 56.2500 deg ..)
    (0x2C, 0x3B), (0x2B, 0x3C), (0x2A, 0x3C), (0x28, 0x3C),   # idx  24 ..  27  ( 67.5000 deg ..)
    (0x27, 0x3D), (0x25, 0x3D), (0x24, 0x3D), (0x22, 0x3D),   # idx  28 ..  31  ( 78.7500 deg ..)
    (0x21, 0x3D), (0x01, 0x3D), (0x03, 0x3D), (0x04, 0x3D),   # idx  32 ..  35  ( 90.0000 deg ..)
    (0x06, 0x3D), (0x07, 0x3C), (0x08, 0x3C), (0x0A, 0x3C),   # idx  36 ..  39  (101.2500 deg ..)
    (0x0B, 0x3B), (0x0D, 0x3A), (0x0E, 0x3A), (0x0F, 0x39),   # idx  40 ..  43  (112.5000 deg ..)
    (0x11, 0x38), (0x12, 0x38), (0x13, 0x37), (0x14, 0x36),   # idx  44 ..  47  (123.7500 deg ..)
    (0x16, 0x35), (0x17, 0x34), (0x18, 0x33), (0x19, 0x31),   # idx  48 ..  51  (135.0000 deg ..)
    (0x19, 0x30), (0x1A, 0x2F), (0x1B, 0x2E), (0x1C, 0x2D),   # idx  52 ..  55  (146.2500 deg ..)
    (0x1C, 0x2B), (0x1D, 0x2A), (0x1E, 0x28), (0x1E, 0x27),   # idx  56 ..  59  (157.5000 deg ..)
    (0x1E, 0x26), (0x1F, 0x24), (0x1F, 0x23), (0x1F, 0x21),   # idx  60 ..  63  (168.7500 deg ..)
    (0x1F, 0x20), (0x1F, 0x01), (0x1F, 0x03), (0x1F, 0x04),   # idx  64 ..  67  (180.0000 deg ..)
    (0x1F, 0x06), (0x1E, 0x07), (0x1E, 0x08), (0x1D, 0x0A),   # idx  68 ..  71  (191.2500 deg ..)
    (0x1D, 0x0B), (0x1C, 0x0D), (0x1C, 0x0E), (0x1B, 0x0F),   # idx  72 ..  75  (202.5000 deg ..)
    (0x1A, 0x10), (0x19, 0x11), (0x18, 0x13), (0x17, 0x14),   # idx  76 ..  79  (213.7500 deg ..)
    (0x16, 0x15), (0x15, 0x16), (0x14, 0x17), (0x13, 0x18),   # idx  80 ..  83  (225.0000 deg ..)
    (0x12, 0x18), (0x10, 0x19), (0x0F, 0x1A), (0x0E, 0x1A),   # idx  84 ..  87  (236.2500 deg ..)
    (0x0C, 0x1B), (0x0B, 0x1C), (0x0A, 0x1C), (0x08, 0x1C),   # idx  88 ..  91  (247.5000 deg ..)
    (0x07, 0x1D), (0x05, 0x1D), (0x04, 0x1D), (0x02, 0x1D),   # idx  92 ..  95  (258.7500 deg ..)
    (0x01, 0x1D), (0x21, 0x1D), (0x23, 0x1D), (0x24, 0x1D),   # idx  96 ..  99  (270.0000 deg ..)
    (0x26, 0x1D), (0x27, 0x1C), (0x28, 0x1C), (0x2A, 0x1C),   # idx 100 .. 103  (281.2500 deg ..)
    (0x2B, 0x1B), (0x2D, 0x1A), (0x2E, 0x1A), (0x2F, 0x19),   # idx 104 .. 107  (292.5000 deg ..)
    (0x31, 0x18), (0x32, 0x18), (0x33, 0x17), (0x34, 0x16),   # idx 108 .. 111  (303.7500 deg ..)
    (0x36, 0x15), (0x37, 0x14), (0x38, 0x13), (0x39, 0x11),   # idx 112 .. 115  (315.0000 deg ..)
    (0x39, 0x10), (0x3A, 0x0F), (0x3B, 0x0E), (0x3C, 0x0D),   # idx 116 .. 119  (326.2500 deg ..)
    (0x3C, 0x0B), (0x3D, 0x0A), (0x3E, 0x08), (0x3E, 0x07),   # idx 120 .. 123  (337.5000 deg ..)
    (0x3E, 0x06), (0x3F, 0x04), (0x3F, 0x03), (0x3F, 0x01),   # idx 124 .. 127  (348.7500 deg ..)
]

# 빔 캘리브레이션 측정 조건 (데이터시트상 0도 지점)
CAL_REF_I = 0x3F
CAL_REF_Q = 0x20
CAL_GAIN_INDEX = 0xA5     # 캘리브레이션 중 모든 CS/CH 공통 gain index
CAL_REF_CS = 8            # 기준 칩
CAL_REF_CH = 1            # 기준 채널

def phase_to_iq(phase_deg):
    """원하는 위상(도)에 가장 가까운 ADAR1000 (I, Q) 레지스터 값을 반환.

    반환값: (i_reg, q_reg, index, quantized_phase_deg)
    """
    idx = int(round((phase_deg % 360.0) / PHASE_STEP_DEG)) % 128
    i_reg, q_reg = PHASE_TABLE[idx]
    return i_reg, q_reg, idx, idx * PHASE_STEP_DEG

def iq_to_phase(i_reg, q_reg):
    """(I, Q) 레지스터 값이 테이블에 있으면 해당 위상(도)을 반환, 없으면 None."""
    try:
        idx = PHASE_TABLE.index((i_reg, q_reg))
    except ValueError:
        return None
    return idx * PHASE_STEP_DEG

def wrap180(deg):
    """각도를 -180 ~ +180 범위로 정규화."""
    return (deg + 180.0) % 360.0 - 180.0

# =========================================================
# 3. 샘플별 빔 캘리브레이션 데이터
#
#  'phase_cal' 명령을 실행하면 아래 블록이 자동으로 갱신되어 저장된다.
#  (BEGIN/END 마커 사이만 교체되므로 마커 줄은 지우지 말 것)
#
#  구조: BOARD_CALIBRATIONS[샘플번호][CS][CH] = {'i':.., 'q':.., 'meas':..}
#    i, q  : CS8/CH1 과 위상이 같아지도록 보정된 phase index
#    meas  : 캘리브레이션 당시 (0x3F, 0x20) 조건에서 계측기로 읽은 위상(도)
# =========================================================
# --- BEGIN BOARD_CALIBRATIONS ---
BOARD_CALIBRATIONS = {
    1: {
        8: {
            1: {'i': 0x3F, 'q': 0x20},
            2: {'i': 0x3C, 'q': 0x0D},
            3: {'i': 0x3C, 'q': 0x0D},
            4: {'i': 0x3B, 'q': 0x0E},
        },
        2: {
            1: {'i': 0x3C, 'q': 0x0D},
            2: {'i': 0x3A, 'q': 0x0F},
            3: {'i': 0x3F, 'q': 0x04},
            4: {'i': 0x3F, 'q': 0x23},
        },
        5: {
            1: {'i': 0x3F, 'q': 0x03},
            2: {'i': 0x3E, 'q': 0x06},
            3: {'i': 0x3D, 'q': 0x0A},
            4: {'i': 0x3F, 'q': 0x03},
        },
        6: {
            1: {'i': 0x3E, 'q': 0x07},
            2: {'i': 0x3E, 'q': 0x07},
            3: {'i': 0x3B, 'q': 0x0E},
            4: {'i': 0x3F, 'q': 0x20},
        },
    },
}
# --- END BOARD_CALIBRATIONS ---

# 현재 선택된 conduction 보드 샘플 번호 (tx_on 이 이 샘플의 캘리브레이션을 사용)
CURRENT_SAMPLE = 1

def get_calibration(sample=None):
    """선택된 샘플의 캘리브레이션 딕셔너리를 반환. 없으면 무보정(0x3F, 0x20)."""
    if sample is None:
        sample = CURRENT_SAMPLE
    if sample in BOARD_CALIBRATIONS:
        return BOARD_CALIBRATIONS[sample]
    log_print(f"[WARN] Sample #{sample} has no calibration data. Using uncalibrated (0x3F, 0x20).")
    return {cs: {ch: {'i': CAL_REF_I, 'q': CAL_REF_Q} for ch in ALL_CHANNELS} for cs in ALL_CS_PINS}

# =========================================================
# 4. SPI 함수
# =========================================================
def spi_transfer(cs, data_bytes):
    GPIO.output(cs, GPIO.LOW)
    read_bytes = []
    try:
        for byte in data_bytes:
            read_byte = 0
            for bit in range(7, -1, -1):
                if (byte >> bit) & 1:
                    GPIO.output(MOSI_PIN, GPIO.HIGH)
                else:
                    GPIO.output(MOSI_PIN, GPIO.LOW)

                GPIO.output(SCLK_PIN, GPIO.HIGH)
                if GPIO.input(MISO_PIN):
                    read_byte |= (1 << bit)
                GPIO.output(SCLK_PIN, GPIO.LOW)

            read_bytes.append(read_byte)
    finally:
        GPIO.output(cs, GPIO.HIGH)
        time.sleep(0.001)

    return read_bytes

def send_command(cs, reg_addr, data):
    page = (reg_addr >> 8) & 0xFF
    addr = reg_addr & 0xFF
    return spi_transfer(cs, [page, addr, data])

# =========================================================
# 5. 전원 제어 핀
# =========================================================
PIN_22 = 22  # +5V
PIN_23 = 23  # +3.3V
PIN_24 = 24  # -5V
PIN_25 = 25  # -3.3V

GPIO.setup(PIN_22, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_23, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_24, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_25, GPIO.OUT, initial=GPIO.LOW)

# =========================================================
# 6. 공통 시퀀스
# =========================================================
SAFE_STANDBY_SEQUENCE = [
    (0x029, 0x85, 'Set CH1 PA_BIAS to min (≈ -2.5V)'),
    (0x02A, 0x85, 'Set CH2 PA_BIAS to min (≈ -2.5V)'),
    (0x02B, 0x85, 'Set CH3 PA_BIAS to min (≈ -2.5V)'),
    (0x02C, 0x85, 'Set CH4 PA_BIAS to min (≈ -2.5V)'),
    (0x031, 0x90, 'Disable Tx/Rx mode (TR control)')
]

DISABLE_SEQUENCE = [
    (0x01C, 0x00, 'Set channel 1 Tx to min gain'),
    (0x01D, 0x00, 'Set channel 2 Tx to min gain'),
    (0x01E, 0x00, 'Set channel 3 Tx to min gain'),
    (0x01F, 0x00, 'Set channel 4 Tx to min gain'),
    (0x010, 0x00, 'Set channel 1 Rx to min gain'),
    (0x011, 0x00, 'Set channel 2 Rx to min gain'),
    (0x012, 0x00, 'Set channel 3 Rx to min gain'),
    (0x013, 0x00, 'Set channel 4 Rx to min gain'),
    (0x028, 0x02, 'Load Tx vector data'),
    (0x028, 0x01, 'Load Rx vector data'),
    (0x029, 0x85, 'Set CH1 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02A, 0x85, 'Set CH2 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02B, 0x85, 'Set CH3 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02C, 0x85, 'Set CH4 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02D, 0x68, 'Set LNA_BIAS_ON to minimal power (≈ -2.0V)'),
    (0x030, 0x50, 'Enable the LNA bias DAC output'),
    (0x031, 0x90, 'Put ADAR1000 into SPI-controlled TR state and disable TX_EN/RX_EN bits')
]

# =========================================================
# 7. 유틸리티
# =========================================================
def parse_int_list(user_text, valid_set=None):
    user_text = user_text.strip().lower()
    if user_text in ["all", "*"]:
        return "all"
    if user_text in ["cancel", "q", "quit"]:
        return None

    items = []
    for part in user_text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
            items.append(v)
        except ValueError:
            pass

    items = sorted(list(set(items)))

    if valid_set is not None:
        items = [x for x in items if x in valid_set]

    return items if items else []

def ask_hex_byte(prompt, default=None):
    while True:
        text = input(prompt).strip()

        if text.lower() in ["cancel", "q", "quit"]:
            return None

        if text == "":
            return default

        try:
            val = int(text, 0)
            if not (0 <= val <= 0xFF):
                print("Value must be between 0x00 and 0xFF.")
                continue
            return val
        except ValueError:
            print("Invalid value. Enter hex like 0xA0 or decimal like 160, or press Enter for default.")

def ask_gain_index():
    while True:
        text = input("Enter gain index (default: 0xF0) or 'cancel': ").strip()
        if text.lower() in ["cancel", "q", "quit"]:
            return None
        if text == "":
            return 0xF0
        try:
            val = int(text, 0)
            if not (0 <= val <= 0xFF):
                print("Value must be between 0x00 and 0xFF.")
                continue
            return val
        except ValueError:
            print("Invalid value. Enter hex like 0xF0 or decimal like 240.")

def ask_cs_selection():
    while True:
        text = input("Enter target CS pins (8,2,5,6) or 'all' (or 'cancel'): ").strip()
        if text.lower() in ["cancel", "q", "quit"]:
            return None
        if text.lower() in ["all", "*"]:
            return ALL_CS_PINS[:]
        values = parse_int_list(text, valid_set=ALL_CS_PINS)
        if values:
            return values
        print("Invalid CS selection. Try again.")

def ask_channel_selection_for_cs(cs):
    while True:
        text = input(f"Enter target channels for CS{cs} (1,2,3,4) or 'all' (or 'cancel'): ").strip()
        if text.lower() in ["cancel", "q", "quit"]:
            return None
        if text.lower() in ["all", "*"]:
            return [1, 2, 3, 4]
        values = parse_int_list(text, valid_set=[1, 2, 3, 4])
        if values:
            return values
        print(f"Invalid channel selection for CS{cs}. Try again.")

def ask_sample_number(prompt="Enter conduction board sample number (e.g. 2) or 'cancel': "):
    """conduction 보드 샘플 번호를 입력받는다."""
    while True:
        text = input(prompt).strip()
        if text.lower() in ["cancel", "q", "quit"]:
            return None
        if text == "":
            print("Sample number is required.")
            continue
        try:
            val = int(text, 0)
        except ValueError:
            print("Invalid sample number. Enter an integer like 1, 2, 3 ...")
            continue
        if val < 0:
            print("Sample number must be 0 or greater.")
            continue
        return val

def ask_phase_deg(prompt):
    """계측기에서 읽은 위상(도)을 입력받는다. 'skip' 이면 'skip' 문자열 반환."""
    while True:
        text = input(prompt).strip()
        if text.lower() in ["cancel", "q", "quit"]:
            return None
        if text.lower() in ["skip", "s"]:
            return "skip"
        try:
            return float(text)
        except ValueError:
            print("Invalid phase. Enter a number in degrees (e.g. -37.4), or 'skip' / 'cancel'.")

def ask_yes_no(prompt, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        text = input(prompt + suffix).strip().lower()
        if text == "":
            return default
        if text in ["y", "yes"]:
            return True
        if text in ["n", "no"]:
            return False
        print("Please answer y or n.")

def write_sequence_to_all_cs(sequence, cs_list):
    for cs in cs_list:
        log_print(f"=== Operating on CS{cs} ===")
        for reg, val, desc in sequence:
            resp = send_command(cs, reg, val)
            log_print(f"CS{cs}: {desc} - Reg 0x{reg:03X}, Data 0x{val:02X}, Resp {resp}")

# =========================================================
# 8. 기능 함수들
# =========================================================
def bias_on():
    log_print("=== bias_on start ===")
    GPIO.output(PIN_22, GPIO.LOW)
    log_print("+5V off")
    time.sleep(5)

    GPIO.output(PIN_24, GPIO.LOW)
    log_print("-5V off")
    time.sleep(2)

    GPIO.output(PIN_25, GPIO.LOW)
    log_print("-3.3V off")
    time.sleep(2)

    GPIO.output(PIN_23, GPIO.LOW)
    log_print("+3.3V off")
    time.sleep(2)

    log_print("All Bias Setting low")

    GPIO.output(PIN_23, GPIO.HIGH)
    log_print("+3.3V ON")
    time.sleep(2)

    GPIO.output(PIN_25, GPIO.HIGH)
    log_print("-3.3V ON")
    time.sleep(2)

    GPIO.output(PIN_24, GPIO.HIGH)
    log_print("-5V ON")
    time.sleep(2)

    log_print("=== SPI initialization ===")
    for cs in ALL_CS_PINS:
        log_print(f"--- Initializing CS{cs} ---")
        init_sequence = [
            (0x000, 0x81, 'Reset'),
            (0x401, 0x02, 'Allow LDO adjustments from user settings'),
            (0x400, 0x55, 'Adjust LDO Settings'),
            (0x038, 0x60, 'Bypass the beam and bias RAM (enable SPI)'),
            (0x02E, 0x7F, 'Enable all Rx channels, LNA, VGA, Vector Mod'),
            (0x02F, 0x7F, 'Enable all Tx channels, PA, VGA, Vector Mod'),
            (0x034, 0x08, 'Set LNA preamplifier to nominal bias'),
            (0x035, 0x55, 'Set Rx VGA and Vector Mod to nominal bias'),
            (0x036, 0x2D, 'Set Tx VGA and Vector Mod to nominal bias'),
            (0x037, 0x06, 'Set Tx PA preamplifier to nominal bias'),
            (0x029, 0x85, 'Set PA1_BIAS_ON value (≈ -2.5V)'),
            (0x02A, 0x85, 'Set PA2_BIAS_ON value (≈ -2.5V)'),
            (0x02B, 0x85, 'Set PA3_BIAS_ON value (≈ -2.5V)'),
            (0x02C, 0x85, 'Set PA4_BIAS_ON value (≈ -2.5V)'),
            (0x046, 0x85, 'Set PA1_BIAS_OFF value (≈ -2.5V)'),
            (0x047, 0x85, 'Set PA2_BIAS_OFF value (≈ -2.5V)'),
            (0x048, 0x85, 'Set PA3_BIAS_OFF value (≈ -2.5V)'),
            (0x049, 0x85, 'Set PA4_BIAS_OFF value (≈ -2.5V)'),
            (0x02D, 0x68, 'Set LNA_BIAS_ON value (≈ -2.0V)'),
            (0x04A, 0x68, 'Set LNA_BIAS_OFF value (≈ -2.0V)'),
            (0x031, 0x90, 'Disable Tx/Rx using SPI TR control'),
            (0x030, 0x50, 'Enable the PA and LNA output DACs'),
        ]
        for reg, val, desc in init_sequence:
            resp = send_command(cs, reg, val)
            log_print(f"CS{cs}: {desc} - Reg 0x{reg:03X}, Data 0x{val:02X}, Resp {resp}")

    time.sleep(2)
    GPIO.output(PIN_22, GPIO.HIGH)
    log_print("+5V ON")
    log_print("=== bias_on done ===")

def tx_on():
    log_print("=== tx_on start ===")
    log_print(f"Using calibration of conduction board sample #{CURRENT_SAMPLE}")

    calibration = get_calibration()

    target_cs_list = ask_cs_selection()
    if target_cs_list is None:
        log_print("tx_on cancelled at CS selection.")
        return

    gain_idx = ask_gain_index()
    if gain_idx is None:
        log_print("tx_on cancelled at gain index input.")
        return

    common_bias_value = ask_hex_byte(
        "Enter common PA bias value for selected CS/channels (default: 0x20) or 'cancel': ",
        default=0x20
    )
    if common_bias_value is None:
        log_print("tx_on cancelled at bias input.")
        return

    global CURRENT_TARGET_CS, CURRENT_TARGET_CHANNELS
    CURRENT_TARGET_CS = target_cs_list[:]
    CURRENT_TARGET_CHANNELS = []

    user_config = {}
    for cs in target_cs_list:
        print(f"--- CS{cs} setup ---")
        ch_list = ask_channel_selection_for_cs(cs)
        if ch_list is None:
            log_print("tx_on cancelled at channel selection.")
            return

        user_config[cs] = {}
        for ch in ch_list:
            if cs in calibration and ch in calibration[cs]:
                ch_cfg = calibration[cs][ch]
            else:
                log_print(f"Missing calibration for sample #{CURRENT_SAMPLE} CS{cs} CH{ch}. Skipping.")
                continue

            user_config[cs][ch] = {
                "gain": gain_idx,
                "i": ch_cfg["i"],
                "q": ch_cfg["q"],
                "bias": common_bias_value
            }
            CURRENT_TARGET_CHANNELS.append(ch)

    CURRENT_TARGET_CHANNELS = sorted(list(set(CURRENT_TARGET_CHANNELS)))
    log_print(f"Target CS: {CURRENT_TARGET_CS}")
    log_print(f"Target Channels: {CURRENT_TARGET_CHANNELS}")
    log_print(f"Common gain index: 0x{gain_idx:02X}")
    log_print(f"Common bias value: 0x{common_bias_value:02X}")

    log_print("=== Auto-Reset: Forcing all chips to Safe Standby ===")
    write_sequence_to_all_cs(SAFE_STANDBY_SEQUENCE, ALL_CS_PINS)
    log_print("All chips are now locked in Pinch-off state.")
    time.sleep(0.1)

    for cs in target_cs_list:
        log_print(f"=== Common Tx Setup for CS{cs} ===")

        for ch, vals in user_config[cs].items():
            bias_val = vals["bias"]
            reg_addr = 0x029 + (ch - 1)
            resp = send_command(cs, reg_addr, bias_val)
            log_print(f"CS{cs} CH{ch} PA_BIAS - Reg 0x{reg_addr:03X}, Data 0x{bias_val:02X}, Resp {resp}")

        resp = send_command(cs, 0x031, 0xD2)
        log_print(f"CS{cs}: Put ADAR1000 into SPI-controlled Tx mode - Reg 0x031, Data 0xD2, Resp {resp}")

    log_print("=== Applying Individual Gain & Phase Settings ===")
    for cs in target_cs_list:
        if cs not in user_config:
            continue

        log_print(f"-> Configuring Chip CS{cs}")
        for ch, vals in user_config[cs].items():
            idx = ch - 1

            resp = send_command(cs, REG_GAIN[idx], vals["gain"])
            log_print(f"CS{cs} CH{ch} GAIN - Reg 0x{REG_GAIN[idx]:03X}, Data 0x{vals['gain']:02X}, Resp {resp}")

            resp = send_command(cs, REG_PHASE_I[idx], vals["i"])
            log_print(f"CS{cs} CH{ch} PHASE_I - Reg 0x{REG_PHASE_I[idx]:03X}, Data 0x{vals['i']:02X}, Resp {resp}")

            resp = send_command(cs, REG_PHASE_Q[idx], vals["q"])
            log_print(f"CS{cs} CH{ch} PHASE_Q - Reg 0x{REG_PHASE_Q[idx]:03X}, Data 0x{vals['q']:02X}, Resp {resp}")

        resp = send_command(cs, 0x028, 0x02)
        log_print(f"CS{cs}: LOAD - Reg 0x028, Data 0x02, Resp {resp}")
        log_print(f"[CS{cs}] Gain & Phase applied & Loaded.")

    log_print("=== tx_on done ===")

def bias_off():
    log_print("=== bias_off start ===")
    write_sequence_to_all_cs(DISABLE_SEQUENCE, ALL_CS_PINS)
    time.sleep(2)

    GPIO.output(PIN_22, GPIO.LOW)
    log_print("GPIO22 OFF (+5V OFF)")
    time.sleep(15)

    GPIO.output(PIN_24, GPIO.LOW)
    log_print("GPIO24 OFF (-5V OFF)")
    time.sleep(2)

    GPIO.output(PIN_25, GPIO.LOW)
    log_print("GPIO25 OFF (-3.3V OFF)")
    time.sleep(2)

    GPIO.output(PIN_23, GPIO.LOW)
    log_print("GPIO23 OFF (+3.3V OFF)")
    time.sleep(2)

    log_print("System successfully powered down.")
    log_print("=== bias_off done ===")

# =========================================================
# 8-1. 빔 캘리브레이션 (phase_cal)
# =========================================================
def _cal_measure_single(cs, ch, i_reg, q_reg, bias_val, prompt):
    """빔 캘리브레이션용 단일 채널 측정.

    bias_on 으로 보드 전체를 완전히 새로 켠 뒤, 지정한 CS/CH 하나에만
    gain/phase 를 걸어 계측기로 위상을 읽게 하고, 측정이 끝나면 bias_off 로
    보드를 완전히 끈다. (다른 CS/CH 는 bias_on 직후의 초기 상태 그대로이므로
    별도의 뮤트 없이도 꺼져 있다.)

    반환값: 측정값(float), 'skip', 또는 None(취소).
    사용자가 취소하거나 중간에 예외가 나도 finally 에서 반드시 bias_off 를
    호출해 보드를 안전 상태로 되돌린다.
    """
    log_print(f"--- Power-cycling for CS{cs} CH{ch} measurement ---")
    bias_on()
    try:
        idx = ch - 1
        reg_addr = 0x029 + idx
        resp = send_command(cs, reg_addr, bias_val)
        log_print(f"CS{cs} CH{ch} PA_BIAS - Reg 0x{reg_addr:03X}, Data 0x{bias_val:02X}, Resp {resp}")

        resp = send_command(cs, 0x031, 0xD2)
        log_print(f"CS{cs}: SPI-controlled Tx mode - Reg 0x031, Data 0xD2, Resp {resp}")

        resp = send_command(cs, REG_GAIN[idx], CAL_GAIN_INDEX)
        log_print(f"CS{cs} CH{ch} GAIN - Reg 0x{REG_GAIN[idx]:03X}, Data 0x{CAL_GAIN_INDEX:02X}, Resp {resp}")

        resp = send_command(cs, REG_PHASE_I[idx], i_reg)
        log_print(f"CS{cs} CH{ch} PHASE_I - Reg 0x{REG_PHASE_I[idx]:03X}, Data 0x{i_reg:02X}, Resp {resp}")

        resp = send_command(cs, REG_PHASE_Q[idx], q_reg)
        log_print(f"CS{cs} CH{ch} PHASE_Q - Reg 0x{REG_PHASE_Q[idx]:03X}, Data 0x{q_reg:02X}, Resp {resp}")

        resp = send_command(cs, 0x028, 0x02)
        log_print(f"CS{cs}: LOAD - Reg 0x028, Data 0x02, Resp {resp}")
        log_print(f"CS{cs} CH{ch}: gain 0x{CAL_GAIN_INDEX:02X}, I 0x{i_reg:02X}, Q 0x{q_reg:02X} applied & loaded.")

        return ask_phase_deg(prompt)
    finally:
        bias_off()

def phase_cal():
    """빔 캘리브레이션.

    절차 (채널마다 완전한 bias_on / bias_off 전원 사이클을 반복한다):
      1) conduction 보드 샘플 번호를 입력받는다.
      2) 채널 하나마다: bias_on -> 그 채널만 gain 0xA5, phase index
         (0x3F, 0x20) 로 켜고 네트웍 아날라이저 위상을 입력받음 -> bias_off.
         이 사이클을 CS8/CH1(기준) 부터 시작해 나머지 15개 채널까지 반복한다.
      3) 각 채널의 위상 오차 = (측정값 - 기준값) 이므로,
         보정 위상 = -(측정값 - 기준값) 을 ADAR1000 Table 10~13 으로 양자화해
         가장 가까운 (I, Q) 레지스터 값을 구한다.
      4) 결과를 ncr2.py 의 BOARD_CALIBRATIONS 블록에 기록한다.

    * 채널마다 보드 전원을 완전히 껐다 켜므로 시간이 오래 걸린다
      (bias_on/bias_off 각각의 sleep 시간 참고).
    """
    global CURRENT_SAMPLE

    log_print("=== phase_cal start ===")

    sample = ask_sample_number()
    if sample is None:
        log_print("phase_cal cancelled at sample number input.")
        return

    if sample in BOARD_CALIBRATIONS:
        if not ask_yes_no(f"Sample #{sample} already has calibration data. Overwrite?", default=False):
            log_print("phase_cal cancelled (existing data kept).")
            return

    bias_val = ask_hex_byte(
        "Enter common PA bias value for calibration (default: 0x20) or 'cancel': ",
        default=0x20
    )
    if bias_val is None:
        log_print("phase_cal cancelled at bias input.")
        return

    print("")
    print("=========================================================")
    print(f" Beam (phase) calibration - conduction board sample #{sample}")
    print("=========================================================")
    print(f" - Reference channel : CS{CAL_REF_CS} CH{CAL_REF_CH}")
    print(f" - Phase index       : I=0x{CAL_REF_I:02X}, Q=0x{CAL_REF_Q:02X} (= 0 deg in ADAR1000 Table 10)")
    print(f" - Gain index        : 0x{CAL_GAIN_INDEX:02X} (all channels)")
    print(" - Each channel is measured with its own full bias_on -> measure -> bias_off cycle.")
    print(" - Enter the phase read on the network analyzer, in degrees.")
    print(" - 'skip' leaves a channel uncalibrated (0x3F, 0x20); 'cancel' aborts.")
    print("")

    # --- 1단계: 기준 채널 CS8/CH1 측정 ---
    print(f"--- Step 1: reference channel CS{CAL_REF_CS} CH{CAL_REF_CH} ---")
    ref_phase = _cal_measure_single(
        CAL_REF_CS, CAL_REF_CH, CAL_REF_I, CAL_REF_Q, bias_val,
        f"Measured phase of CS{CAL_REF_CS} CH{CAL_REF_CH} at (0x{CAL_REF_I:02X}, 0x{CAL_REF_Q:02X}) [deg]: "
    )
    if ref_phase is None or ref_phase == "skip":
        log_print("phase_cal cancelled: the reference channel must be measured.")
        return
    log_print(f"Reference phase (CS{CAL_REF_CS} CH{CAL_REF_CH}) = {ref_phase:.3f} deg")

    # --- 2단계: 나머지 채널 측정 ---
    results = {CAL_REF_CS: {CAL_REF_CH: {'i': CAL_REF_I, 'q': CAL_REF_Q, 'meas': ref_phase}}}

    print("")
    print("--- Step 2: remaining channels ---")
    for cs in ALL_CS_PINS:
        results.setdefault(cs, {})
        for ch in ALL_CHANNELS:
            if cs == CAL_REF_CS and ch == CAL_REF_CH:
                continue

            meas = _cal_measure_single(
                cs, ch, CAL_REF_I, CAL_REF_Q, bias_val,
                f"Measured phase of CS{cs} CH{ch} at (0x{CAL_REF_I:02X}, 0x{CAL_REF_Q:02X}) [deg]: "
            )
            if meas is None:
                log_print("phase_cal cancelled by user during measurement.")
                return
            if meas == "skip":
                log_print(f"CS{cs} CH{ch}: skipped, left uncalibrated (0x{CAL_REF_I:02X}, 0x{CAL_REF_Q:02X}).")
                results[cs][ch] = {'i': CAL_REF_I, 'q': CAL_REF_Q, 'meas': None}
                continue

            # 이 채널은 0도 지령에서 meas 를 출력한다 -> 오차 = meas - ref
            # 보정 위상 = -오차 = ref - meas (mod 360)
            error = wrap180(meas - ref_phase)
            correction = (-error) % 360.0
            i_reg, q_reg, idx, quantized = phase_to_iq(correction)
            residual = wrap180(quantized - correction)

            results[cs][ch] = {'i': i_reg, 'q': q_reg, 'meas': meas}
            log_print(
                f"CS{cs} CH{ch}: meas {meas:8.3f} deg, error {error:+8.3f} deg, "
                f"correction {correction:8.3f} deg -> idx {idx:3d} ({quantized:8.4f} deg) "
                f"I 0x{i_reg:02X}, Q 0x{q_reg:02X}, residual {residual:+6.3f} deg"
            )

    # --- 3단계: 결과 저장 ---
    BOARD_CALIBRATIONS[sample] = results
    CURRENT_SAMPLE = sample

    print("")
    log_print(f"=== Calibration result for sample #{sample} ===")
    print(render_calibrations())

    if persist_calibrations():
        log_print(f"BOARD_CALIBRATIONS in {SCRIPT_PATH} updated (backup: ncr2.py.bak).")
    else:
        log_print("[WARN] Could not update the source file. Copy the block above into ncr2.py manually.")

    log_print(f"Current sample set to #{sample}.")

    # --- 4단계: 선택적 검증 ---
    if ask_yes_no("Verify the calibration now (re-measure each channel with the corrected phase)?", default=False):
        phase_cal_verify(sample, ref_phase)

    log_print("=== phase_cal done ===")

def phase_cal_verify(sample=None, ref_phase=None):
    """보정된 i/q 를 적용한 상태에서 각 채널을 다시 측정해 잔차를 확인한다.

    phase_cal 과 동일하게 채널마다 bias_on -> 측정 -> bias_off 사이클을 반복한다.
    """
    if sample is None:
        sample = CURRENT_SAMPLE
    if sample not in BOARD_CALIBRATIONS:
        log_print(f"[ERROR] Sample #{sample} has no calibration data to verify.")
        return

    calibration = BOARD_CALIBRATIONS[sample]
    log_print(f"=== phase_cal verification for sample #{sample} ===")

    bias_val = ask_hex_byte(
        "Enter common PA bias value for verification (default: 0x20) or 'cancel': ",
        default=0x20
    )
    if bias_val is None:
        log_print("Verification cancelled at bias input.")
        return

    for cs in ALL_CS_PINS:
        for ch in ALL_CHANNELS:
            cfg = calibration.get(cs, {}).get(ch)
            if cfg is None:
                continue

            meas = _cal_measure_single(
                cs, ch, cfg['i'], cfg['q'], bias_val,
                f"[verify] Measured phase of CS{cs} CH{ch} "
                f"at (0x{cfg['i']:02X}, 0x{cfg['q']:02X}) [deg]: "
            )
            if meas is None:
                log_print("Verification cancelled by user.")
                return
            if meas == "skip":
                continue

            if cs == CAL_REF_CS and ch == CAL_REF_CH and ref_phase is None:
                ref_phase = meas

            if ref_phase is None:
                log_print(f"[verify] CS{cs} CH{ch}: {meas:8.3f} deg")
            else:
                log_print(f"[verify] CS{cs} CH{ch}: {meas:8.3f} deg, "
                          f"residual vs reference {wrap180(meas - ref_phase):+7.3f} deg")

    log_print("=== verification done ===")
# =========================================================
# 8-2. 캘리브레이션 데이터 직렬화 / 소스 파일 갱신
# =========================================================
CAL_BEGIN_MARKER = "# --- BEGIN BOARD_CALIBRATIONS ---"
CAL_END_MARKER = "# --- END BOARD_CALIBRATIONS ---"

def render_calibrations():
    """BOARD_CALIBRATIONS 를 소스에 그대로 붙여넣을 수 있는 문자열로 만든다."""
    lines = ["BOARD_CALIBRATIONS = {"]
    for sample in sorted(BOARD_CALIBRATIONS):
        lines.append(f"    {sample}: {{")
        cal = BOARD_CALIBRATIONS[sample]
        for cs in ALL_CS_PINS:
            if cs not in cal:
                continue
            lines.append(f"        {cs}: {{")
            for ch in ALL_CHANNELS:
                if ch not in cal[cs]:
                    continue
                cfg = cal[cs][ch]
                entry = f"'i': 0x{cfg['i']:02X}, 'q': 0x{cfg['q']:02X}"
                meas = cfg.get('meas')
                if meas is not None:
                    entry += f", 'meas': {meas:.3f}"
                lines.append(f"            {ch}: {{{entry}}},")
            lines.append("        },")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines)

def persist_calibrations():
    """ncr2.py 의 BEGIN/END 마커 사이를 현재 BOARD_CALIBRATIONS 로 교체한다."""
    try:
        with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
            source = f.read()

        # 마커는 '줄 전체'로만 인식한다. 이렇게 해야 아래 CAL_BEGIN_MARKER =
        # "..." 같은 문자열 리터럴 줄이 마커로 잘못 잡히지 않는다.
        pattern = re.compile(
            r"^" + re.escape(CAL_BEGIN_MARKER) + r"$.*?^" + re.escape(CAL_END_MARKER) + r"$",
            re.DOTALL | re.MULTILINE,
        )
        if not pattern.search(source):
            log_print(f"[ERROR] Markers not found in {SCRIPT_PATH}.")
            return False

        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        replacement = (
            f"{CAL_BEGIN_MARKER}\n"
            f"# last updated by phase_cal: {stamp}\n"
            f"{render_calibrations()}\n"
            f"{CAL_END_MARKER}"
        )
        # 치환 문자열의 \g, \1 등이 역참조로 해석되지 않도록 람다로 치환한다.
        updated = pattern.sub(lambda m: replacement, source, count=1)

        shutil.copyfile(SCRIPT_PATH, SCRIPT_PATH + ".bak")
        with open(SCRIPT_PATH, "w", encoding="utf-8") as f:
            f.write(updated)
        return True

    except Exception as e:
        log_print(f"[ERROR] Failed to persist calibration data: {e}")
        return False

# =========================================================
# 8-3. 샘플 선택 / 조회
# =========================================================
def select_sample():
    """tx_on 이 사용할 conduction 보드 샘플 번호를 바꾼다."""
    global CURRENT_SAMPLE
    print(f"Known samples: {sorted(BOARD_CALIBRATIONS)} (current: #{CURRENT_SAMPLE})")
    sample = ask_sample_number("Enter sample number to use or 'cancel': ")
    if sample is None:
        return
    if sample not in BOARD_CALIBRATIONS:
        print(f"[WARN] Sample #{sample} has no calibration data yet. Run 'phase_cal' first.")
        if not ask_yes_no("Select it anyway?", default=False):
            return
    CURRENT_SAMPLE = sample
    log_print(f"Current sample set to #{CURRENT_SAMPLE}.")

def show_calibration():
    """현재 샘플의 캘리브레이션 값을 위상과 함께 보여준다."""
    if CURRENT_SAMPLE not in BOARD_CALIBRATIONS:
        print(f"Sample #{CURRENT_SAMPLE} has no calibration data.")
        return

    cal = BOARD_CALIBRATIONS[CURRENT_SAMPLE]
    print(f"=== Calibration of conduction board sample #{CURRENT_SAMPLE} ===")
    print(f"{'CS':>4} {'CH':>3} {'I':>5} {'Q':>5} {'applied phase':>16} {'measured':>10}")
    for cs in ALL_CS_PINS:
        if cs not in cal:
            continue
        for ch in ALL_CHANNELS:
            if ch not in cal[cs]:
                continue
            cfg = cal[cs][ch]
            phase = iq_to_phase(cfg['i'], cfg['q'])
            phase_s = f"{phase:10.4f} deg" if phase is not None else "(custom)"
            meas = cfg.get('meas')
            meas_s = f"{meas:10.3f}" if meas is not None else "-"
            print(f"{cs:>4} {ch:>3}  0x{cfg['i']:02X}  0x{cfg['q']:02X} {phase_s:>16} {meas_s:>10}")

def show_status():
    print("=== STATUS ===")
    print(f"Current conduction board sample: #{CURRENT_SAMPLE}")
    print(f"Samples with calibration data: {sorted(BOARD_CALIBRATIONS)}")
    print(f"Current target CS: {CURRENT_TARGET_CS}")
    print(f"Current target channels: {CURRENT_TARGET_CHANNELS}")
    print(f"Log file: {LOG_FILENAME}")

# =========================================================
# 9. 메인 명령 루프
# =========================================================
COMMANDS = "bias_on, phase_cal, tx_on, bias_off, sample, cal, status, exit"

def main():
    log_print(f"Log path: {LOG_FILENAME}")
    log_print("ncr2.py interactive control started.")
    log_print(f"Commands: {COMMANDS}")
    log_print(f"Current conduction board sample: #{CURRENT_SAMPLE}")
    log_print("New board flow: bias_on -> phase_cal -> tx_on")

    try:
        while True:
            cmd = input("ncr2> ").strip().lower()

            if cmd == "bias_on":
                bias_on()
            elif cmd == "phase_cal":
                phase_cal()
            elif cmd == "tx_on":
                tx_on()
            elif cmd == "bias_off":
                bias_off()
            elif cmd == "sample":
                select_sample()
            elif cmd == "cal":
                show_calibration()
            elif cmd == "status":
                show_status()
            elif cmd in ["exit", "quit"]:
                log_print("Exiting...")
                break
            elif cmd == "":
                continue
            else:
                print(f"Unknown command. Use: {COMMANDS}")

    except KeyboardInterrupt:
        print("Interrupted by user.")
    except Exception as e:
        print(f"[ERROR] {e}")
        log_print(f"[ERROR] {e}")
    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass
        save_log()
        print(f"Log saved to: {LOG_FILENAME}")

# =========================================================
# 10. 실행
# =========================================================
if __name__ == "__main__":
    main()
