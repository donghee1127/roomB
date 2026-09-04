import ftd2xx as ftd
import time

# FTDI SPI 설정 변수
SPI_CLOCK = 10000000  # SPI 클럭 속도 (10 MHz)
SPI_MODE = 0          # SPI 모드 (Mode 0: CPOL=0, CPHA=0)
CS_PIN = 3            # CS 핀: TMS (Pin 7, ADBUS3)

# GPIO 핀 매핑
RESET_N = 4  # GPIOL0 (Pin 8, ADBUS4)
BEAM_UPD = 5  # GPIOL1 (Pin 9, ADBUS5)
TR_SWITCH = 6  # GPIOL2 (Pin 10, ADBUS6)

# 현재 GPIO 상태를 저장하는 변수 (초기값: 모든 핀 Low)
global_gpio_state = 0x00

# FTDI 장치 초기화 함수
def initialize_ftdi():
    try:
        # FTDI 장치 열기
        device = ftd.open(0)  # 첫 번째 FTDI 장치 열기
        print("FTDI 장치가 정상적으로 열렸습니다.")

        # MPSSE 모드 활성화
        device.setBitMode(0xFF, 0x02)
        print("MPSSE 모드 활성화 완료.")

        # SPI 클럭 설정
        clock_divisor = int(60000000 / (2 * SPI_CLOCK)) - 1
        device.write(bytes([0x86, clock_divisor & 0xFF, (clock_divisor >> 8) & 0xFF]))
        print(f"SPI 클럭이 {SPI_CLOCK} Hz로 설정되었습니다.")

        # SPI 모드 설정
        if SPI_MODE == 0:
            device.write(bytes([0x8A]))  # Disable clock divide by 5
            device.write(bytes([0x97]))  # Enable 3-phase clocking
        else:
            raise ValueError("현재 SPI_MODE 0만 지원됩니다.")

        return device

    except Exception as e:
        print(f"FTDI 초기화 중 오류 발생: {str(e)}")
        return None

# GPIO 상태 설정 함수
def set_gpio(device, pin, value):
    """
    특정 GPIO 핀의 상태를 설정합니다.
    :param device: FTDI 디바이스 객체
    :param pin: 설정할 GPIO 핀 (ADBUS 핀 번호)
    :param value: 설정 값 (1: High, 0: Low)
    """
    global global_gpio_state  # 현재 GPIO 상태를 추적하는 전역 변수

    try:
        # 핀 상태 변경
        if value == 1:
            global_gpio_state |= (1 << pin)  # 핀을 High로 설정
        else:
            global_gpio_state &= ~(1 << pin)  # 핀을 Low로 설정

        # 현재 상태를 FTDI로 쓰기
        device.write(bytes([0x80, global_gpio_state, 0xFF]))
        print(f"GPIO{pin} 상태 설정: {'HIGH' if value else 'LOW'}")

    except Exception as e:
        print(f"GPIO 상태 설정 중 오류 발생: {str(e)}")

# SPI 데이터 쓰기 함수
def spi_write(device, data):
    try:
        # CS 핀 활성화 (Low)
        set_gpio(device, CS_PIN, 0)

        # 데이터 전송
        for byte in data:
            device.write(bytes([0x11, 0x00, 0x00, byte]))  # 1 byte 전송

        # CS 핀 비활성화 (High)
        set_gpio(device, CS_PIN, 1)

        print(f"SPI Write 완료: {data}")

    except Exception as e:
        print(f"SPI Write 중 오류 발생: {str(e)}")

# SPI 데이터 읽기 함수
def spi_read(device, length):
    try:
        # CS 핀 활성화 (Low)
        set_gpio(device, CS_PIN, 0)

        # 데이터 읽기 명령어
        device.write(bytes([0x20, length & 0xFF, (length >> 8) & 0xFF]))

        # 응답 데이터 읽기
        response = device.read(length)

        # CS 핀 비활성화 (High)
        set_gpio(device, CS_PIN, 1)

        print(f"SPI Read 완료: {list(response)}")
        return list(response)

    except Exception as e:
        print(f"SPI Read 중 오류 발생: {str(e)}")
        return None

# 메인 실행 함수
def main():
    # FTDI 장치 초기화
    device = initialize_ftdi()
    if not device:
        return

    RESET_N = 4
    set_gpio(device, RESET_N, 0)  # RESET_N 핀 LOW
    time.sleep(1)
    # GPIO 테스트 (RESET_N, BEAM_UPD, TR_SWITCH 핀 제어)
    set_gpio(device, RESET_N, 1)  # RESET_N 핀 HIGH
    time.sleep(3)
    set_gpio(device, RESET_N, 0)  # RESET_N 핀 LOW
    time.sleep(1)

    BEAM_UPD = 5
    set_gpio(device, BEAM_UPD, 0)  # BEAM_UPD 핀 LOW
    time.sleep(1)
    set_gpio(device, BEAM_UPD, 1)  # BEAM_UPD 핀 HIGH
    time.sleep(3)
    set_gpio(device, BEAM_UPD, 0)  # BEAM_UPD 핀 LOW
    time.sleep(1)

    TR_SWITCH = 6
    set_gpio(device, TR_SWITCH, 0)  # TR_SWITCH 핀 LOW
    time.sleep(1)
    set_gpio(device, TR_SWITCH, 1)  # TR_SWITCH 핀 HIGH
    time.sleep(3)
    set_gpio(device, TR_SWITCH, 0)  # TR_SWITCH 핀 LOW
    time.sleep(1)

    # SPI Write 테스트
    write_data = [0xFF, 0xAA, 0xFF]
    spi_write(device, write_data)

    # SPI Read 테스트
    read_data = spi_read(device, 3)

    # 장치 닫기
    device.close()
    print("FTDI 장치 닫힘.")

if __name__ == "__main__":
    main()
