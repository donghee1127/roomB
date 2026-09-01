import RPi.GPIO as GPIO
import time

'''
GPIO22가 +5V
GPIO23이 +3.3V
GPIO24이 -5V
GPIO25이 -3.3V

Turn on sequence
+3.3V
-3.3V
-5V
(SPI initialize PA -2.5V LNA -2.0V)
+5V
'''

# ==========================================
# 1. GPIO 및 소프트웨어 SPI 핀 설정
# ==========================================
SCLK_PIN = 11  # SPI0_SCLK
MOSI_PIN = 10  # SPI0_MOSI
MISO_PIN = 9   # SPI0_MISO 

# 모든 칩(8, 2, 5, 6)을 리스트에 넣어도 이제 충돌하지 않습니다.
CS_PINS = [8,2,5,6] 

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False) # 불필요한 GPIO 경고 메시지 숨김

# SPI 통신 핀 초기화
GPIO.setup(SCLK_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MOSI_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MISO_PIN, GPIO.IN)

for pin in CS_PINS:
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)

# 전원 제어 핀 설정
PIN_22 = 22
PIN_23 = 23
PIN_24 = 24
PIN_25 = 25

GPIO.setup(PIN_22, GPIO.OUT) 
GPIO.setup(PIN_23, GPIO.OUT) 
GPIO.setup(PIN_24, GPIO.OUT) 
GPIO.setup(PIN_25, GPIO.OUT) 

# ==========================================
# 2. 전원 인가 시퀀스 (음전압 먼저)
# ==========================================
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

# ==========================================
# 3. 소프트웨어 SPI 통신 함수
# ==========================================
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

# ==========================================
# 4. 초기화 시퀀스 (SPI)
# ==========================================
init_sequence = [
    # HOUSEKEEPING
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
 
    # PA BIAS VALUES (최소 전류 대기 상태)
    (0x029, 0x85, 'Set PA1_BIAS_ON value (≈ -2.5V)'),
    (0x02A, 0x85, 'Set PA2_BIAS_ON value (≈ -2.5V)'),
    (0x02B, 0x85, 'Set PA3_BIAS_ON value (≈ -2.5V)'),
    (0x02C, 0x85, 'Set PA4_BIAS_ON value (≈ -2.5V)'),
    (0x046, 0x85, 'Set PA1_BIAS_OFF value (≈ -2.5V)'),
    (0x047, 0x85, 'Set PA2_BIAS_OFF value (≈ -2.5V)'),
    (0x048, 0x85, 'Set PA3_BIAS_OFF value (≈ -2.5V)'),
    (0x049, 0x85, 'Set PA4_BIAS_OFF value (≈ -2.5V)'),
 
    # LNA BIAS VALUES
    (0x02D, 0x68, 'Set LNA_BIAS_ON value (≈ -2.0V)'),
    (0x04A, 0x68, 'Set LNA_BIAS_OFF value (≈ -2.0V)'),
 
    # TR CONTROL STATE
    (0x031, 0x90, 'Disable Tx/Rx using SPI TR control'),
 
    # Enable PA/LNA DACs
    (0x030, 0x50, 'Enable the PA and LNA output DACs'),
]

for cs in CS_PINS:
    print(f"\n=== Initializing CS{cs} ===")
    for reg, val, desc in init_sequence:
        print(f"CS{cs}: {desc} - Reg 0x{reg:03X}, Data 0x{val:02X}")
        resp = send_command(cs, reg, val)
        
time.sleep(2)
GPIO.output(PIN_22, GPIO.HIGH)
print("GPIO22  ON (+5V ON)")

# 전압 유지를 위해 GPIO.cleanup() 및 SPI.close()는 사용하지 않습니다.