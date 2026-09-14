import RPi.GPIO as GPIO
import time
from datetime import datetime
import os

# =========================================================
# 0. 로그 설정
# =========================================================
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
# 3. beamforming_config
# =========================================================
beamforming_config = {
   8: {
       1: {'gain': 0xF0, 'i': 0x3F, 'q': 0x20},
       2: {'gain': 0xF0, 'i': 0x3C, 'q': 0x0D},
       3: {'gain': 0xF0, 'i': 0x3C, 'q': 0x0D},
       4: {'gain': 0xF0, 'i': 0x3B, 'q': 0x0E}
   },
   2: {
       1: {'gain': 0xF0, 'i': 0x3C, 'q': 0x0D},
       2: {'gain': 0xF0, 'i': 0x3A, 'q': 0x0F},
       3: {'gain': 0xF0, 'i': 0x3F, 'q': 0x04},
       4: {'gain': 0xF0, 'i': 0x3F, 'q': 0x23}
   },
   5: {
       1: {'gain': 0xF0, 'i': 0x3F, 'q': 0x03},
       2: {'gain': 0xF0, 'i': 0x3E, 'q': 0x06},
       3: {'gain': 0xF0, 'i': 0x3D, 'q': 0x0A},
       4: {'gain': 0xF0, 'i': 0x3F, 'q': 0x03}
   },
   6: {
       1: {'gain': 0xF0, 'i': 0x3E, 'q': 0x07},
       2: {'gain': 0xF0, 'i': 0x3E, 'q': 0x07},
       3: {'gain': 0xF0, 'i': 0x3B, 'q': 0x0E},
       4: {'gain': 0xF0, 'i': 0x3F, 'q': 0x20}
   }
}

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
            if cs in beamforming_config and ch in beamforming_config[cs]:
                ch_cfg = beamforming_config[cs][ch]
            else:
                log_print(f"Missing beamforming_config for CS{cs} CH{ch}. Skipping.")
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

def show_status():
    print("=== STATUS ===")
    print(f"Current target CS: {CURRENT_TARGET_CS}")
    print(f"Current target channels: {CURRENT_TARGET_CHANNELS}")
    print(f"Log file: {LOG_FILENAME}")

# =========================================================
# 9. 메인 명령 루프
# =========================================================
def main():
    log_print(f"Log path: {LOG_FILENAME}")
    log_print("ncr.py interactive control started.")
    log_print("Commands: bias_on, tx_on, bias_off, status, exit")

    try:
        while True:
            cmd = input("ncr> ").strip().lower()

            if cmd == "bias_on":
                bias_on()
            elif cmd == "tx_on":
                tx_on()
            elif cmd == "bias_off":
                bias_off()
            elif cmd == "status":
                show_status()
            elif cmd in ["exit", "quit"]:
                log_print("Exiting...")
                break
            elif cmd == "":
                continue
            else:
                print("Unknown command. Use: bias_on, tx_on, bias_off, status, exit")

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
