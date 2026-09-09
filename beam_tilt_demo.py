import time
from datetime import datetime

import module as m

# ==========================================================================
# 데모용 설정값 - 여기만 고치면 됨
# ==========================================================================
INTERVAL = 10          # 틸트 전환 간격 (초)
BIAS_VAL = 0x02        # PA_BIAS 레지스터 (0x029~0x02C) 값
GAIN_VAL = 0xA5        # 전 칩/채널 공통 gain index

# 0 -> 10 -> 20 -> 10 -> 0 -> -10 -> -20 -> -10 -> (반복)
TILT_SEQUENCE = [0, 10, 20, 10, 0, -10, -20, -10]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def set_tilt(tilt_deg):
    m.beamforming_config = m.compute_beamforming_config(tilt_deg, GAIN_VAL)
    m.PA_BIAS_ON = [BIAS_VAL, BIAS_VAL, BIAS_VAL, BIAS_VAL]
    log(f"Beam tilt -> {tilt_deg:+d} deg")


def main():
    m.gpio_setup()

    log(f"POWER ON & INIT (bias=0x{BIAS_VAL:02X}, gain=0x{GAIN_VAL:02X})")
    m.power_on_and_init()

    # 최초 진입 시 0도로 TX ON (여기서 TX_EN이 처음 켜짐)
    set_tilt(0)
    m.tx_on()

    log(f"시연 시작. {INTERVAL}초 간격으로 {TILT_SEQUENCE} 순서를 반복합니다. (Ctrl+C로 정지)")

    try:
        step = 1
        while True:
            time.sleep(INTERVAL)
            tilt = TILT_SEQUENCE[step % len(TILT_SEQUENCE)]
            set_tilt(tilt)
            # TX_EN을 다시 껐다 켜지 않고 gain/phase만 갱신 -> 끊김 없이 빔만 이동
            m.apply_beamforming()
            step += 1
    except KeyboardInterrupt:
        log("Ctrl+C 감지, 안전하게 전원을 끕니다...")
    finally:
        m.power_off()


if __name__ == "__main__":
    main()
