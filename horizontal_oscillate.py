import argparse
import sys
import time

from instrument.positioner import positioner

HOST = "192.168.5.20"
PORT = 1001
ELEVATION_H = 90          # mvcontrol.py의 Horizontal(H-plane) 측정 기준 Elevation 고정값
SWEEP_SPEED = 100

# 0 -> 10 -> 20 -> 10 -> 0 -> -10 -> -20 -> -10 (이후 반복)
ANGLE_SEQUENCE = [0, 10, 20, 10, 0, -10, -20, -10]


def parse_args():
    parser = argparse.ArgumentParser(description="Positioner horizontal oscillation control")
    parser.add_argument("-i", "--interval", type=float, default=5.0,
                         help="각 각도로 이동 후 대기 시간(초). 기본값 5초")
    parser.add_argument("--host", default=HOST, help="Positioner IP (default: %(default)s)")
    parser.add_argument("--port", type=int, default=PORT, help="Positioner Port (default: %(default)s)")
    parser.add_argument("--speed", type=int, default=SWEEP_SPEED, help="이동 속도 (default: %(default)s)")
    parser.add_argument("--elevation", type=float, default=ELEVATION_H,
                         help="고정 Elevation 각도 (default: %(default)s)")
    parser.add_argument("--cycles", type=int, default=0,
                         help="반복 횟수 (0이면 Ctrl+C로 멈출 때까지 무한 반복, 기본값 0)")
    return parser.parse_args()


def main():
    args = parse_args()

    pos = positioner()
    print(f"[connect] {args.host}::{args.port}")
    pos.connect(args.host, args.port)
    print(f"[status] {pos.get_status()}")

    pos.query("CONF:FXT:SPD %d\r" % args.speed)

    print(f"[start] interval={args.interval}s, elevation fixed at {args.elevation} deg")
    print(f"[sequence] {ANGLE_SEQUENCE} (repeat" + (f" x{args.cycles})" if args.cycles else ", 무한)"))

    try:
        step = 0
        cycle = 0
        while args.cycles == 0 or cycle < args.cycles:
            azi = ANGLE_SEQUENCE[step % len(ANGLE_SEQUENCE)]
            print(f"[move] azimuth = {azi:+d} deg")
            pos.move_to(args.elevation, azi)
            time.sleep(args.interval)

            step += 1
            if step % len(ANGLE_SEQUENCE) == 0:
                cycle += 1
    except KeyboardInterrupt:
        print("\n[stop] Ctrl+C 입력 감지, 0도로 복귀 후 종료합니다")
    finally:
        try:
            pos.move_to(args.elevation, 0)
        except Exception as e:
            print(f"[warn] 0도 복귀 실패: {e}")
        pos.disconnect()
        print("[disconnect] done")


if __name__ == "__main__":
    main()
