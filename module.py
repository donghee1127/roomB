import RPi.GPIO as GPIO
import time
import math
import csv
import os
from datetime import datetime

# ==========================================================================
# 사용자 설정 구역 (고정값) - 배선 안 바뀌면 건드릴 필요 없음
# ==========================================================================

# 이번 실행에서 실제로 송신(Tx)을 켤 칩 CS 번호
TARGET_CS_PINS = [8, 2, 5, 6]

# 소자 간격 / 파장 비율 (수평 방향)
D_OVER_LAMBDA = 0.58

# "0828 rapa tuning" phase-calibrated boresight(0도, 정면) 기준 I/Q 값
# 여기의 gain은 참고용 원본값이고, 실제 gain은 실행 시 입력받는 값으로 전부 덮어씀
BORESIGHT_CONFIG = {
    8: {
        1: {'gain': 0xA5, 'i': 0x3F, 'q': 0x20},
        2: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D},
        3: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D},
        4: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E},
    },
    2: {
        1: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D},
        2: {'gain': 0xA5, 'i': 0x3A, 'q': 0x0F},
        3: {'gain': 0xA5, 'i': 0x3F, 'q': 0x04},
        4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x23},
    },
    5: {
        1: {'gain': 0xA5, 'i': 0x3F, 'q': 0x03},
        2: {'gain': 0xA5, 'i': 0x3E, 'q': 0x06},
        3: {'gain': 0xA5, 'i': 0x3D, 'q': 0x0A},
        4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x03},
    },
    6: {
        1: {'gain': 0xA5, 'i': 0x3E, 'q': 0x07},
        2: {'gain': 0xA5, 'i': 0x3E, 'q': 0x07},
        3: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E},
        4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x20},
    },
}

# 4x4 물리 배치 (좌->우: col0~col3). Horizontal tilt 진행위상은 col 인덱스 기준으로 부여
GRID = [
    [(2, 1), (2, 4), (5, 1), (5, 4)],
    [(2, 2), (2, 3), (5, 2), (5, 3)],
    [(8, 3), (8, 2), (6, 3), (6, 2)],
    [(8, 4), (8, 1), (6, 4), (6, 1)],
]
COL_OF = {(cs, ch): c for row in GRID for c, (cs, ch) in enumerate(row)}

# 아래 두 값은 실행 시 사용자 입력을 받아 채워짐 (main 참고)
beamforming_config = {}
PA_BIAS_ON = [0x00, 0x00, 0x00, 0x00]


# ==========================================================================
# 0. 위상 계산 - 데이터시트 Table 10~13 (I/Q <-> Phase 매핑, 2.8125deg 분해능)
# ==========================================================================
PHASE_TABLE = [
    (0, 0x3F, 0x20), (2.8125, 0x3F, 0x21), (5.625, 0x3F, 0x23), (8.4375, 0x3F, 0x24),
    (11.25, 0x3F, 0x26), (14.0625, 0x3E, 0x27), (16.875, 0x3E, 0x28), (19.6875, 0x3D, 0x2A),
    (22.5, 0x3D, 0x2B), (25.3125, 0x3C, 0x2D), (28.125, 0x3C, 0x2E), (30.9375, 0x3B, 0x2F),
    (33.75, 0x3A, 0x30), (36.5625, 0x39, 0x31), (39.375, 0x38, 0x33), (42.1875, 0x37, 0x34),
    (45, 0x36, 0x35), (47.8125, 0x35, 0x36), (50.625, 0x34, 0x37), (53.4375, 0x33, 0x38),
    (56.25, 0x32, 0x38), (59.0625, 0x30, 0x39), (61.875, 0x2F, 0x3A), (64.6875, 0x2E, 0x3A),
    (67.5, 0x2C, 0x3B), (70.3125, 0x2B, 0x3C), (73.125, 0x2A, 0x3C), (75.9375, 0x28, 0x3C),
    (78.75, 0x27, 0x3D), (81.5625, 0x25, 0x3D), (84.375, 0x24, 0x3D), (87.1875, 0x22, 0x3D),
    (90, 0x21, 0x3D), (92.8125, 0x01, 0x3D), (95.625, 0x03, 0x3D), (98.4375, 0x04, 0x3D),
    (101.25, 0x06, 0x3D), (104.0625, 0x07, 0x3C), (106.875, 0x08, 0x3C), (109.6875, 0x0A, 0x3C),
    (112.5, 0x0B, 0x3B), (115.3125, 0x0D, 0x3A), (118.125, 0x0E, 0x3A), (120.9375, 0x0F, 0x39),
    (123.75, 0x11, 0x38), (126.5625, 0x12, 0x38), (129.375, 0x13, 0x37), (132.1875, 0x14, 0x36),
    (135, 0x16, 0x35), (137.8125, 0x17, 0x34), (140.625, 0x18, 0x33), (143.4375, 0x19, 0x31),
    (146.25, 0x19, 0x30), (149.0625, 0x1A, 0x2F), (151.875, 0x1B, 0x2E), (154.6875, 0x1C, 0x2D),
    (157.5, 0x1C, 0x2B), (160.3125, 0x1D, 0x2A), (163.125, 0x1E, 0x28), (165.9375, 0x1E, 0x27),
    (168.75, 0x1E, 0x26), (171.5625, 0x1F, 0x24), (174.375, 0x1F, 0x23), (177.1875, 0x1F, 0x21),
    (180, 0x1F, 0x20), (182.8125, 0x1F, 0x01), (185.625, 0x1F, 0x03), (188.4375, 0x1F, 0x04),
    (191.25, 0x1F, 0x06), (194.0625, 0x1E, 0x07), (196.875, 0x1E, 0x08), (199.6875, 0x1D, 0x0A),
    (202.5, 0x1D, 0x0B), (205.3125, 0x1C, 0x0D), (208.125, 0x1C, 0x0E), (210.9375, 0x1B, 0x0F),
    (213.75, 0x1A, 0x10), (216.5625, 0x19, 0x11), (219.375, 0x18, 0x13), (222.1875, 0x17, 0x14),
    (225, 0x16, 0x15), (227.8125, 0x15, 0x16), (230.625, 0x14, 0x17), (233.4375, 0x13, 0x18),
    (236.25, 0x12, 0x18), (239.0625, 0x10, 0x19), (241.875, 0x0F, 0x1A), (244.6875, 0x0E, 0x1A),
    (247.5, 0x0C, 0x1B), (250.3125, 0x0B, 0x1C), (253.125, 0x0A, 0x1C), (255.9375, 0x08, 0x1C),
    (258.75, 0x07, 0x1D), (261.5625, 0x05, 0x1D), (264.375, 0x04, 0x1D), (267.1875, 0x02, 0x1D),
    (270, 0x01, 0x1D), (272.8125, 0x21, 0x1D), (275.625, 0x23, 0x1D), (278.4375, 0x24, 0x1D),
    (281.25, 0x26, 0x1D), (284.0625, 0x27, 0x1C), (286.875, 0x28, 0x1C), (289.6875, 0x2A, 0x1C),
    (292.5, 0x2B, 0x1B), (295.3125, 0x2D, 0x1A), (298.125, 0x2E, 0x1A), (300.9375, 0x2F, 0x19),
    (303.75, 0x31, 0x18), (306.5625, 0x32, 0x18), (309.375, 0x33, 0x17), (312.1875, 0x34, 0x16),
    (315, 0x36, 0x15), (317.8125, 0x37, 0x14), (320.625, 0x38, 0x13), (323.4375, 0x39, 0x11),
    (326.25, 0x39, 0x10), (329.0625, 0x3A, 0x0F), (331.875, 0x3B, 0x0E), (334.6875, 0x3C, 0x0D),
    (337.5, 0x3C, 0x0B), (340.3125, 0x3D, 0x0A), (343.125, 0x3E, 0x08), (345.9375, 0x3E, 0x07),
    (348.75, 0x3E, 0x06), (351.5625, 0x3F, 0x04), (354.375, 0x3F, 0x03), (357.1875, 0x3F, 0x01),
]
_IQ_TO_PHASE = {(i, q): p for p, i, q in PHASE_TABLE}


def phase_of(i, q):
    return _IQ_TO_PHASE[(i, q)]


def nearest_iq(target_deg):
    t = target_deg % 360
    return min(PHASE_TABLE, key=lambda row: min(abs(row[0] - t), 360 - abs(row[0] - t)))


def compute_beamforming_config(tilt_deg, gain_value):
    """boresight I/Q + 열(column)별 진행위상(datasheet 이론식, d/lambda 기반)으로 새 config 계산"""
    step = 360.0 * D_OVER_LAMBDA * math.sin(math.radians(tilt_deg))
    cfg = {}
    for cs, channels in BORESIGHT_CONFIG.items():
        cfg[cs] = {}
        for ch, data in channels.items():
            base_phase = phase_of(data['i'], data['q'])
            col = COL_OF[(cs, ch)]
            target = base_phase + col * step
            _, ni, nq = nearest_iq(target)
            cfg[cs][ch] = {'gain': gain_value, 'i': ni, 'q': nq}
    return cfg


# ==========================================================================
# 0.5 실행 시 입력 받기 / 로그 저장
# ==========================================================================
def prompt_float(msg):
    while True:
        try:
            return float(input(msg))
        except ValueError:
            print("숫자로 입력해주세요.")


def prompt_hex_byte(msg):
    while True:
        try:
            v = int(input(msg), 0)
            if 0 <= v <= 0xFF:
                return v
            print("0~255 (0x00~0xFF) 범위로 입력해주세요.")
        except ValueError:
            print("올바른 형식이 아닙니다 (예: 0x20 또는 32).")


def prompt_settings():
    tilt_deg = prompt_float("Beam tilt 각도 (deg, 수평, +/- 가능, 0=정면): ")
    bias_val = prompt_hex_byte("PA_BIAS 레지스터(0x029~0x02C) 값 (예: 0x20 또는 32): ")
    gain_val = prompt_hex_byte("Gain index 값, 전 칩/채널 공통 (예: 0xA5 또는 165): ")
    return tilt_deg, bias_val, gain_val


def write_log_csv(tilt_deg, bias_val, gain_val, cfg):
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(log_dir, f"module_log_{ts}.csv")

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Beam Tilt (deg)", tilt_deg])
        writer.writerow(["d/lambda", D_OVER_LAMBDA])
        writer.writerow(["PA_BIAS reg value (0x029~0x02C)", f"0x{bias_val:02X}"])
        writer.writerow(["Gain index (all chips/channels)", f"0x{gain_val:02X}"])
        writer.writerow([])
        writer.writerow(["CS", "CH", "Gain", "Phase_I", "Phase_Q", "Phase(deg)", "PA_BIAS(0x029~0x02C)"])
        for cs in sorted(cfg.keys()):
            for ch in sorted(cfg[cs].keys()):
                d = cfg[cs][ch]
                deg = phase_of(d['i'], d['q'])
                writer.writerow([
                    cs, ch,
                    f"0x{d['gain']:02X}",
                    f"0x{d['i']:02X}",
                    f"0x{d['q']:02X}",
                    f"{deg:.4f}",
                    f"0x{bias_val:02X}",
                ])

    print(f"\n[log] 로그 저장 완료: {path}")
    return path


# ==========================================================================
# 1. GPIO 및 소프트웨어 SPI 핀 설정 (고정값, 배선 안 바뀌면 건드릴 필요 없음)
# ==========================================================================
SCLK_PIN = 11
MOSI_PIN = 10
MISO_PIN = 9

ALL_CS_PINS = [8, 2, 5, 6]

PIN_22 = 22  # +5V
PIN_23 = 23  # +3.3V
PIN_24 = 24  # -5V
PIN_25 = 25  # -3.3V

REG_GAIN = [0x01C, 0x01D, 0x01E, 0x01F]
REG_PHASE_I = [0x020, 0x022, 0x024, 0x026]
REG_PHASE_Q = [0x021, 0x023, 0x025, 0x027]


def gpio_setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(SCLK_PIN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(MOSI_PIN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(MISO_PIN, GPIO.IN)

    for pin in ALL_CS_PINS:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)

    GPIO.setup(PIN_22, GPIO.OUT)
    GPIO.setup(PIN_23, GPIO.OUT)
    GPIO.setup(PIN_24, GPIO.OUT)
    GPIO.setup(PIN_25, GPIO.OUT)


# ==========================================================================
# 2. 소프트웨어 SPI 통신 함수
# ==========================================================================
def spi_transfer(cs, data_bytes):
    GPIO.output(cs, GPIO.LOW)
    read_bytes = []
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
    GPIO.output(cs, GPIO.HIGH)
    time.sleep(0.001)
    return read_bytes


def send_command(cs, reg_addr, data):
    page = (reg_addr >> 8) & 0xFF
    addr = reg_addr & 0xFF
    return spi_transfer(cs, [page, addr, data])


def send_sequence(cs, sequence, label=False):
    for reg, val, desc in sequence:
        if label:
            print(f"CS{cs}: {desc} - Reg 0x{reg:03X}, Data 0x{val:02X}")
        send_command(cs, reg, val)


# ==========================================================================
# 3. bias_on_debug.py 로직 - 전원 인가 + 칩 초기화
# ==========================================================================
INIT_SEQUENCE = [
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


def power_on_and_init():
    print("\n========== [1/3] POWER ON & INIT ==========")

    GPIO.output(PIN_22, GPIO.LOW)
    print("+5V off")
    time.sleep(5)
    GPIO.output(PIN_24, GPIO.LOW)
    print("-5V off")
    time.sleep(2)
    GPIO.output(PIN_25, GPIO.LOW)
    print("-3.3V off")
    time.sleep(2)
    GPIO.output(PIN_23, GPIO.LOW)
    print("+3.3V off")
    time.sleep(2)
    print("All Bias Setting low")

    GPIO.output(PIN_23, GPIO.HIGH)
    print("GPIO23  ON (+3.3V ON)")
    time.sleep(2)
    GPIO.output(PIN_25, GPIO.HIGH)
    print("GPIO25  ON (-3.3V ON)")
    time.sleep(2)
    GPIO.output(PIN_24, GPIO.HIGH)
    print("GPIO24  ON (-5V ON)")
    time.sleep(2)

    for cs in ALL_CS_PINS:
        print(f"\n=== Initializing CS{cs} ===")
        send_sequence(cs, INIT_SEQUENCE, label=True)

    time.sleep(2)
    GPIO.output(PIN_22, GPIO.HIGH)
    print("GPIO22  ON (+5V ON)")


# ==========================================================================
# 4. tx_on_debug.py 로직 - 송신 모드 활성화 + Gain/Phase 적용
# ==========================================================================
SAFE_STANDBY_SEQUENCE = [
    (0x029, 0x85, 'Set CH1 PA_BIAS to min (≈ -2.5V)'),
    (0x02A, 0x85, 'Set CH2 PA_BIAS to min (≈ -2.5V)'),
    (0x02B, 0x85, 'Set CH3 PA_BIAS to min (≈ -2.5V)'),
    (0x02C, 0x85, 'Set CH4 PA_BIAS to min (≈ -2.5V)'),
    (0x031, 0x90, 'Disable Tx/Rx mode (TR control)'),
]


def build_common_tx_sequence():
    return [
        (0x029, PA_BIAS_ON[0], 'CH1 PA_BIAS_ON'),
        (0x02A, PA_BIAS_ON[1], 'CH2 PA_BIAS_ON'),
        (0x02B, PA_BIAS_ON[2], 'CH3 PA_BIAS_ON'),
        (0x02C, PA_BIAS_ON[3], 'CH4 PA_BIAS_ON'),
        (0x031, 0xD2, 'Put ADAR1000 into SPI-controlled Tx mode'),
    ]


def tx_on():
    print("\n========== [2/3] TX ON ==========")

    print("\n=== Auto-Reset: Forcing all chips to Safe Standby ===")
    for cs in ALL_CS_PINS:
        send_sequence(cs, SAFE_STANDBY_SEQUENCE)
    print("All chips are now locked in Pinch-off state.")
    time.sleep(0.1)

    common_tx_sequence = build_common_tx_sequence()
    for cs in TARGET_CS_PINS:
        print(f"\n=== Common Tx Setup for CS{cs} ===")
        send_sequence(cs, common_tx_sequence)

    print("\n=== Applying Individual Gain & Phase Settings ===")
    for cs in TARGET_CS_PINS:
        if cs in beamforming_config:
            print(f"-> Configuring Chip CS{cs}")
            for ch in range(1, 5):
                ch_data = beamforming_config[cs][ch]
                idx = ch - 1
                send_command(cs, REG_GAIN[idx], ch_data['gain'])
                send_command(cs, REG_PHASE_I[idx], ch_data['i'])
                send_command(cs, REG_PHASE_Q[idx], ch_data['q'])

            send_command(cs, 0x028, 0x02)
            print(f"   [CS{cs}] Gain & Phase applied & Loaded.")

    print(f"\nTarget {TARGET_CS_PINS} successfully activated for measurement.")


# ==========================================================================
# 5. bias_off_debug.py 로직 - 안전하게 끄기 + 전원 차단
# ==========================================================================
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
    (0x031, 0x90, 'Put ADAR1000 into SPI-controlled TR state and disable TX_EN/RX_EN bits'),
]


def power_off():
    print("\n========== [3/3] POWER OFF ==========")

    for cs in ALL_CS_PINS:
        print(f"\n=== Multichip Disabling CS{cs} ===")
        send_sequence(cs, DISABLE_SEQUENCE)

    time.sleep(2)

    GPIO.output(PIN_22, GPIO.LOW)
    print("GPIO22  OFF (+5V OFF)")
    time.sleep(15)

    GPIO.output(PIN_24, GPIO.LOW)
    print("GPIO24  OFF (-5V OFF)")
    time.sleep(2)

    GPIO.output(PIN_25, GPIO.LOW)
    print("GPIO25  OFF (-3.3V OFF)")
    time.sleep(2)

    GPIO.output(PIN_23, GPIO.LOW)
    print("GPIO23  OFF (+3.3V OFF)")
    time.sleep(2)

    print("\nSystem successfully powered down.")


# ==========================================================================
# 6. 메인 실행 흐름
#    입력받기 -> 위상계산 -> 로그저장 -> bias_on -> tx_on -> (측정 대기) -> bias_off
# ==========================================================================
if __name__ == "__main__":
    tilt_deg, bias_val, gain_val = prompt_settings()

    beamforming_config = compute_beamforming_config(tilt_deg, gain_val)
    PA_BIAS_ON = [bias_val, bias_val, bias_val, bias_val]

    print(f"\n[config] tilt={tilt_deg} deg, PA_BIAS(0x029~0x02C)=0x{bias_val:02X}, gain=0x{gain_val:02X}")
    for cs in sorted(beamforming_config.keys()):
        for ch in sorted(beamforming_config[cs].keys()):
            d = beamforming_config[cs][ch]
            print(f"  CS{cs} CH{ch}: gain=0x{d['gain']:02X} i=0x{d['i']:02X} q=0x{d['q']:02X} "
                  f"({phase_of(d['i'], d['q']):.2f} deg)")

    write_log_csv(tilt_deg, bias_val, gain_val, beamforming_config)

    gpio_setup()

    power_on_and_init()
    tx_on()

    input("\n측정을 진행하세요. 끝나면 Enter를 눌러 전원을 끕니다...")

    power_off()
    # 전압 유지가 필요 없는 시점이므로 여기서 종료해도 무방 (GPIO.cleanup() 미사용, 원본 스크립트들과 동일)
