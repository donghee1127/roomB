import argparse
import os
import time

from instrument.positioner import positioner

HOST = "192.168.5.20"
PORT = 1001
ROLLING_INIT = 0          # rolling 축 초기값 (고정할 값). mvcontrol.py의 init_Positioner_Azimuth_h 기본값
SWEEP_SPEED = 100

# 포지셔너 본축: 0 -> 10 -> 20 -> 10 -> 0 -> -10 -> -20 -> -10 (이후 반복)
ANGLE_SEQUENCE = [0, 10, 20, 10, 0, -10, -20, -10]

STOP_FLAG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oscillate_stop.flag")


def parse_args():
    parser = argparse.ArgumentParser(description="Positioner horizontal oscillation control")
    parser.add_argument("-i", "--interval", type=float, default=5.0,
                         help="각 각도로 이동 후 대기 시간(초). 기본값 5초")
    parser.add_argument("--host", default=HOST, help="Positioner IP (default: %(default)s)")
    parser.add_argument("--port", type=int, default=PORT, help="Positioner Port (default: %(default)s)")
    parser.add_argument("--speed", type=int, default=SWEEP_SPEED, help="이동 속도 (default: %(default)s)")
    parser.add_argument("--rolling", type=float, default=ROLLING_INIT,
                         help="고정할 rolling 축 각도 (default: %(default)s)")
    parser.add_argument("--cycles", type=int, default=0,
                         help="반복 횟수 (0이면 정지 명령이 올 때까지 무한 반복, 기본값 0)")
    return parser.parse_args()


def stop_requested():
    return os.path.exists(STOP_FLAG_PATH)


def interruptible_sleep(seconds):
    """seconds 동안 자되, 0.2초 간격으로 정지 신호를 확인해서 빠르게 반응한다."""
    remaining = seconds
    tick = 0.2
    while remaining > 0:
        if stop_requested():
            return True
        time.sleep(min(tick, remaining))
        remaining -= tick
    return stop_requested()


def main():
    args = parse_args()

    # 이전 실행에서 남은 정지 플래그가 있으면 정리하고 시작
    if os.path.exists(STOP_FLAG_PATH):
        os.remove(STOP_FLAG_PATH)

    pos = positioner()
    print(f"[connect] {args.host}::{args.port}")
    pos.connect(args.host, args.port)
    print(f"[status] {pos.get_status()}")

    pos.query("CONF:FXT:SPD %d\r" % args.speed)

    print(f"[start] interval={args.interval}s, rolling axis fixed at {args.rolling} deg")
    print(f"[sequence] {ANGLE_SEQUENCE} (repeat" + (f" x{args.cycles})" if args.cycles else ", 무한)"))
    print(f"[stop] 중간에 멈추려면 'Stop Horizontal Oscillate.bat'를 실행하세요 (또는 Ctrl+C)")

    stopped = False
    try:
        step = 0
        cycle = 0
        while args.cycles == 0 or cycle < args.cycles:
            if stop_requested():
                stopped = True
                break

            pos_angle = ANGLE_SEQUENCE[step % len(ANGLE_SEQUENCE)]
            print(f"[move] positioner = {pos_angle:+d} deg (rolling = {args.rolling} deg)")
            pos.move_to(pos_angle, args.rolling)

            if interruptible_sleep(args.interval):
                stopped = True
                break

            step += 1
            if step % len(ANGLE_SEQUENCE) == 0:
                cycle += 1
    except KeyboardInterrupt:
        stopped = True

    if stopped:
        print("\n[stop] 정지 신호 감지, 0도로 복귀 후 종료합니다")
    else:
        print("\n[done] 설정된 반복 횟수 완료, 0도로 복귀 후 종료합니다")

    try:
        pos.move_to(0, args.rolling)
    except Exception as e:
        print(f"[warn] 0도 복귀 실패: {e}")

    pos.disconnect()
    print("[disconnect] done")

    if os.path.exists(STOP_FLAG_PATH):
        os.remove(STOP_FLAG_PATH)


if __name__ == "__main__":
    main()
