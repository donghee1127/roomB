import RPi.GPIO as GPIO
import time

'''
Turn off sequence
+5V off
-5V off
-3.3V off
+3.3V off 
'''

# ==========================================
# 1. GPIO 및 소프트웨어 SPI 핀 설정
# ==========================================
SCLK_PIN = 11
MOSI_PIN = 10
MISO_PIN = 9

CS_PINS = [8, 2, 5, 6]

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

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
# 2. 소프트웨어 SPI 통신 함수
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
# 3. 칩 비활성화 (전원 오프 전처리) 시퀀스
# ==========================================
DISABLE = [
    # minimum gain setting
    (0x01C, 0x00, 'Set channel 1 Tx to min gain'),
    (0x01D, 0x00, 'Set channel 2 Tx to min gain'),
    (0x01E, 0x00, 'Set channel 3 Tx to min gain'),
    (0x01F, 0x00, 'Set channel 4 Tx to min gain'),
    (0x010, 0x00, 'Set channel 1 Rx to min gain'),
    (0x011, 0x00, 'Set channel 2 Rx to min gain'),
    (0x012, 0x00, 'Set channel 3 Rx to min gain'),
    (0x013, 0x00, 'Set channel 4 Rx to min gain'),
    
    # Gain 변경사항 Load
    (0x028, 0x02, 'Load Tx vector data'),
    (0x028, 0x01, 'Load Rx vector data'),

    # Bias 최소 전압 및 TR 모드 비활성화
    (0x029, 0x85, 'Set CH1 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02A, 0x85, 'Set CH2 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02B, 0x85, 'Set CH3 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02C, 0x85, 'Set CH4 PA_BIAS_ON to minimal power (≈ -2.5V)'),
    (0x02D, 0x68, 'Set LNA_BIAS_ON to minimal power (≈ -2.0V)'),
    (0x030, 0x50, 'Enable the LNA bias DAC output'),
    (0x031, 0x90, 'Put ADAR1000 into SPI-controlled TR state and disable TX_EN/RX_EN bits')
]

for cs in CS_PINS:
    print(f"\n=== Multichip Disabling CS{cs} ===")
    for reg, val, desc in DISABLE:
        print(f"CS{cs}: {desc} - Reg 0x{reg:03X}, Data 0x{val:02X}")
        resp = send_command(cs, reg, val)

time.sleep(2)

# ==========================================
# 4. 전원 오프 시퀀스 (양전압 먼저)
# ==========================================
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