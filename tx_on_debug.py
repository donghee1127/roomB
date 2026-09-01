import RPi.GPIO as GPIO
import time

# ==========================================
# 1. GPIO 및 소프트웨어 SPI 핀 설정
# ==========================================
SCLK_PIN = 11
MOSI_PIN = 10
MISO_PIN = 9

# 시스템에 장착된 모든 칩 (초기화 및 안전 리셋용)
ALL_CS_PINS = [8,2,5,6]

# ★ [측정 타겟 변경] 실제로 송신(Tx)을 켤 칩 번호만 입력하세요!
# 변경 예시: [8] -> [2] -> [8, 2] 등으로 자유롭게 변경 후 즉시 실행
TARGET_CS_PINS = [8,2,5,6]

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(SCLK_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MOSI_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MISO_PIN, GPIO.IN)

# 모든 칩의 CS 핀을 기본적으로 HIGH로 막아둡니다.
for pin in ALL_CS_PINS:
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)

# ==========================================
# 2. 개별 빔포밍 설정 (Gain & Phase Dictionary)
# ==========================================
# TARGET이 아닌 칩의 데이터는 자동으로 무시되므로 그대로 두셔도 됩니다.
# beamforming_config = {
#     8: { 
#         1: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         2: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         3: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         4: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}  
#     },
#     2: { 
#         1: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         2: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         3: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         4: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}  
#     },
#     5: { 
#         1: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         2: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         3: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         4: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}  
#     },
#     6: { 
#         1: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         2: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         3: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         4: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}  
#     }
# }

#middle gain
# beamforming_config = {
#     8: { 
#         1: {'gain': 0xA5, 'i': 0x3F, 'q': 0x20}, 
#         2: {'gain': 0xA5, 'i': 0x3F, 'q': 0x21}, 
#         3: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E}, 
#         4: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E}  
#     },
#     2: { 
#         1: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D}, 
#         2: {'gain': 0xA5, 'i': 0x3A, 'q': 0x0F}, 
#         3: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E}, 
#         4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x23}  
#     },
#     5: { 
#         1: {'gain': 0xA5, 'i': 0x3F, 'q': 0x01}, 
#         2: {'gain': 0xA5, 'i': 0x3F, 'q': 0x01}, 
#         3: {'gain': 0xA5, 'i': 0x3F, 'q': 0x01}, 
#         4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x01}  
#     },
#     6: { 
#         1: {'gain': 0xA5, 'i': 0x3E, 'q': 0x07}, 
#         2: {'gain': 0xA5, 'i': 0x3F, 'q': 0x23}, 
#         3: {'gain': 0xA5, 'i': 0x3F, 'q': 0x03}, 
#         4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x20}  
#     }
# }

## Max gain
# beamforming_config = {
#     8: { 
#         1: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}, 
#         2: {'gain': 0xFF, 'i': 0x3F, 'q': 0x21}, 
#         3: {'gain': 0xFF, 'i': 0x3B, 'q': 0x0E}, 
#         4: {'gain': 0xFF, 'i': 0x3B, 'q': 0x0E}  
#     },
#     2: { 
#         1: {'gain': 0xFF, 'i': 0x3C, 'q': 0x0D}, 
#         2: {'gain': 0xFF, 'i': 0x3A, 'q': 0x0F}, 
#         3: {'gain': 0xFF, 'i': 0x3B, 'q': 0x0E}, 
#         4: {'gain': 0xFF, 'i': 0x3F, 'q': 0x23}  
#     },
#     5: { 
#         1: {'gain': 0xFF, 'i': 0x3F, 'q': 0x01}, 
#         2: {'gain': 0xFF, 'i': 0x3F, 'q': 0x01}, 
#         3: {'gain': 0xFF, 'i': 0x3F, 'q': 0x01}, 
#         4: {'gain': 0xFF, 'i': 0x3F, 'q': 0x01}  
#     },
#     6: { 
#         1: {'gain': 0xFF, 'i': 0x3E, 'q': 0x07}, 
#         2: {'gain': 0xFF, 'i': 0x3F, 'q': 0x23}, 
#         3: {'gain': 0xFF, 'i': 0x3F, 'q': 0x03}, 
#         4: {'gain': 0xFF, 'i': 0x3F, 'q': 0x20}  
#     }
# }



# beamforming_config = {
#     8: { 
#         1: {'gain': 0x8F, 'i': 0x3F, 'q': 0x20}, 
#         2: {'gain': 0x8F, 'i': 0x3F, 'q': 0x21}, 
#         3: {'gain': 0x8F, 'i': 0x3B, 'q': 0x0E}, 
#         4: {'gain': 0x8F, 'i': 0x3B, 'q': 0x0E}  
#     },
#     2: { 
#         1: {'gain': 0x8F, 'i': 0x3C, 'q': 0x0D}, 
#         2: {'gain': 0x8F, 'i': 0x3A, 'q': 0x0F}, 
#         3: {'gain': 0x8F, 'i': 0x3B, 'q': 0x0E}, 
#         4: {'gain': 0x8F, 'i': 0x3F, 'q': 0x23}  
#     },
#     5: { 
#         1: {'gain': 0x8F, 'i': 0x3F, 'q': 0x01}, 
#         2: {'gain': 0x8F, 'i': 0x3F, 'q': 0x01}, 
#         3: {'gain': 0x8F, 'i': 0x3F, 'q': 0x01}, 
#         4: {'gain': 0x8F, 'i': 0x3F, 'q': 0x01}  
#     },
#     6: { 
#         1: {'gain': 0x8F, 'i': 0x3E, 'q': 0x07}, 
#         2: {'gain': 0x8F, 'i': 0x3F, 'q': 0x23}, 
#         3: {'gain': 0x8F, 'i': 0x3F, 'q': 0x03}, 
#         4: {'gain': 0x8F, 'i': 0x3F, 'q': 0x20}  
#     }
# }

# 0828 rapa tuning --> rapa 측정 (bias=0x02)
# beamforming_config = {
#    8: { 
#        1: {'gain': 0xA5, 'i': 0x3F, 'q': 0x20}, 
#        2: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D}, 
#        3: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D}, 
#        4: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E}  
#    },
#    2: { 
#        1: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D}, 
#        2: {'gain': 0xA5, 'i': 0x3A, 'q': 0x0F}, 
#        3: {'gain': 0xA5, 'i': 0x3F, 'q': 0x04}, 
#        4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x23}  
#    },
#    5: { 
#        1: {'gain': 0xA5, 'i': 0x3F, 'q': 0x03}, 
#        2: {'gain': 0xA5, 'i': 0x3E, 'q': 0x06}, 
#        3: {'gain': 0xA5, 'i': 0x3D, 'q': 0x0A}, 
#        4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x03}  
#    },
#     6: { 
#         1: {'gain': 0xA5, 'i': 0x3E, 'q': 0x07}, 
#         2: {'gain': 0xA5, 'i': 0x3E, 'q': 0x07}, 
#         3: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E}, 
#         4: {'gain': 0xA5, 'i': 0x3F, 'q': 0x20}  
#     }
# }


# 0828 rapa tuning tilt 30 deg --> needed phase diff 36 deg
# beamforming_config = {
#      8: { 
#          1: {'gain': 0xA5, 'i': 0x38, 'q': 0x33},
#          2: {'gain': 0xA5, 'i': 0x3E, 'q': 0x27},
#          3: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D}, 
#          4: {'gain': 0xA5, 'i': 0x3B, 'q': 0x0E}  
#     },
#      2: { 
#         1: {'gain': 0xA5, 'i': 0x3C, 'q': 0x0D}, 
#         2: {'gain': 0xA5, 'i': 0x3A, 'q': 0x0F}, 
#         3: {'gain': 0xA5, 'i': 0x3B, 'q': 0x2F},
#         4: {'gain': 0xA5, 'i': 0x36, 'q': 0x35}
#     },
#     5: { 
#         1: {'gain': 0xA5, 'i': 0x2B, 'q': 0x3C},
#         2: {'gain': 0xA5, 'i': 0x2E, 'q': 0x3A},
#         3: {'gain': 0xA5, 'i': 0x21, 'q': 0x3D},
#         4: {'gain': 0xA5, 'i': 0x08, 'q': 0x3C}
#     },
#      6: { 
#          1: {'gain': 0xA5, 'i': 0x03, 'q': 0x3D},
#          2: {'gain': 0xA5, 'i': 0x03, 'q': 0x3D},
#          3: {'gain': 0xA5, 'i': 0x36, 'q': 0x35},
#          4: {'gain': 0xA5, 'i': 0x28, 'q': 0x3C}
#      }
#  }

## additional tuning try
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



REG_GAIN = [0x01C, 0x01D, 0x01E, 0x01F]
REG_PHASE_I = [0x020, 0x022, 0x024, 0x026]
REG_PHASE_Q = [0x021, 0x023, 0x025, 0x027]

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
# 4. [NEW] 전체 칩 자동 리셋 (안전 대기 모드)
# ==========================================
# 타겟 칩을 켜기 전에, 무조건 전체 칩을 한 번 끄고 시작합니다.
safe_standby_sequence = [
    (0x029, 0x85, 'Set CH1 PA_BIAS to min (≈ -2.5V)'),
    (0x02A, 0x85, 'Set CH2 PA_BIAS to min (≈ -2.5V)'),
    (0x02B, 0x85, 'Set CH3 PA_BIAS to min (≈ -2.5V)'),
    (0x02C, 0x85, 'Set CH4 PA_BIAS to min (≈ -2.5V)'),
    (0x031, 0x90, 'Disable Tx/Rx mode (TR control)')
]

print("\n=== Auto-Reset: Forcing all chips to Safe Standby ===")
for cs in ALL_CS_PINS:
    for reg, val, desc in safe_standby_sequence:
        send_command(cs, reg, val)
print("All chips are now locked in Pinch-off state.")
time.sleep(0.1) # 리셋 후 잠깐 대기

# ==========================================
# 5. 타겟 칩 송신(Tx) 모드 활성화 및 Bias 인가
# ==========================================
common_tx_sequence = [
    (0x029, 0x20, 'CH1 PA_BIAS_ON to reduced power (≈ -1.25V)'),
    (0x02A, 0x20, 'CH2 PA_BIAS_ON to reduced power (≈ -1.25V)'),
    (0x02B, 0x20, 'CH3 PA_BIAS_ON to reduced power (≈ -1.25V)'),
    (0x02C, 0x20, 'CH4 PA_BIAS_ON to reduced power (≈ -1.25V)'),
    (0x031, 0xD2, 'Put ADAR1000 into SPI-controlled Tx mode')
]

for cs in TARGET_CS_PINS:
    print(f"\n=== Common Tx Setup for CS{cs} ===")
    for reg, val, desc in common_tx_sequence:
        send_command(cs, reg, val)

# ==========================================
# 6. 타겟 칩 개별 Gain & Phase 적용 시퀀스
# ==========================================
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
            
        # 모든 채널의 세팅이 끝난 후 한 번만 Load 하여 동시 적용
        send_command(cs, 0x028, 0x02)
        print(f"   [CS{cs}] Gain & Phase applied & Loaded.")

print(f"\nTarget {TARGET_CS_PINS} successfully activated for measurement.")