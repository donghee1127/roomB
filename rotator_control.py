"""
rotator_control.py - 로테이터(포지셔너 TC-5594A) 단독 제어 (노트북에서 실행)

azimuth / elevation 각도를 입력하면 바로 해당 각도로 돌리고, 도착할 때까지
현재각을 폴링해서 확인한다. 통신 방식/명령은 beam_sync_main.py 와 동일.
    <AXIS>:MOVE <deg>   이동 (응답 'OK')
    <AXIS>:MOVE?        현재각 조회
    <AXIS>:SPD <1~10>   속도
    <AXIS>:TORQ ON      토크 ON
    MODEL?              모델명
    (AXIS = AZI / ELV)

사용법
  pip install pyserial
  python rotator_control.py                    # 대화형 모드
  python rotator_control.py 30 10              # AZ 30, EL 10 으로 이동 후 종료
  python rotator_control.py --com COM5         # 시리얼 포트 지정
  python rotator_control.py --tcp 192.168.5.20 # TCP 로 연결 (포트는 --port)

대화형 모드 입력
  30 10        AZ 30, EL 10 으로 동시에 이동
  az 30        AZ 만 이동 (EL 유지)
  el -5        EL 만 이동 (AZ 유지)
  0 / home     AZ 0, EL 0 으로 이동
  pos          현재 각도 조회
  speed 5      속도 변경 (1~10, 두 축 모두)
  q            종료
"""
import argparse
import socket
import sys
import time
from datetime import datetime

# ==========================================================================
# 사용자 설정 (beam_sync_main.py 와 동일한 기본값)
# ==========================================================================
POS_TRANSPORT = "serial"   # "tcp" 또는 "serial"
POS_HOST = "192.168.5.20"  # tcp 일 때
POS_PORT = 1001
POS_COM = "COM3"           # serial 일 때 (장치관리자 > 포트(COM & LPT)에서 확인)
POS_BAUD = 9600
POS_EOL = "\r"             # 명령 종단 문자 (안 되면 "\r\n" 시도)
POS_SPEED = 5              # 1~10
POS_TOL_DEG = 0.3          # 도착 판정 허용 오차
POS_MOVE_TIMEOUT_S = 90    # 이동 타임아웃

AZ_AXIS = "AZI"
EL_AXIS = "ELV"

# 소프트웨어 각도 제한 (장비/케이블 사양에 맞게 조정)
AZ_LIMIT = (-180.0, 180.0)
EL_LIMIT = (-90.0, 90.0)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}", flush=True)


# ==========================================================================
# 포지셔너 (beam_sync_main.py 의 Positioner 와 동일한 프로토콜)
# ==========================================================================
class PositionerError(Exception):
    pass


class Positioner:
    def __init__(self, transport, host, port, com, baud, eol):
        self.transport = transport
        self.host, self.port = host, port
        self.com, self.baud = com, baud
        self.eol = eol
        self.dev = None
        self.buf = b""

    def open(self):
        if self.transport == "tcp":
            self.dev = socket.create_connection((self.host, self.port), timeout=5)
        elif self.transport == "serial":
            import serial
            self.dev = serial.Serial(self.com, self.baud, timeout=0.1)
        else:
            raise ValueError(f"unknown transport: {self.transport}")

    def close(self):
        if self.dev is not None:
            self.dev.close()
            self.dev = None

    def _write(self, text):
        data = (text + self.eol).encode("ascii")
        if self.transport == "tcp":
            self.dev.sendall(data)
        else:
            self.dev.write(data)

    def _read_chunk(self):
        if self.transport == "tcp":
            self.dev.settimeout(0.1)
            try:
                chunk = self.dev.recv(1024)
            except socket.timeout:
                return b""
            if not chunk:
                raise PositionerError("connection closed by positioner")
            return chunk
        return self.dev.read(1024)

    def _readline(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            for sep in (b"\r", b"\n"):
                if sep in self.buf:
                    line, self.buf = self.buf.split(sep, 1)
                    line = line.strip()
                    if line:
                        return line.decode("ascii", "replace")
            if time.monotonic() > deadline:
                raise PositionerError(f"response timeout (buffer={self.buf!r})")
            self.buf += self._read_chunk()

    def query(self, cmd, timeout=3.0):
        self.buf = b""
        self._write(cmd)
        return self._readline(timeout)

    def command(self, cmd, timeout=3.0):
        resp = self.query(cmd, timeout)
        if resp.upper() != "OK":
            raise PositionerError(f"'{cmd}' -> '{resp}'")

    def angle(self, axis):
        resp = self.query(f"{axis}:MOVE?")
        try:
            return float(resp)
        except ValueError:
            raise PositionerError(f"'{axis}:MOVE?' -> '{resp}'")

    def move(self, axis, deg):
        self.command(f"{axis}:MOVE {deg:g}")

    def wait_arrival_multi(self, targets, tol, timeout):
        """여러 축을 동시에 폴링. 모든 축이 목표각 +-tol 안에 연속 2회 들어오면 도착.

        targets: {axis: target_deg}.  반환: {axis: actual_deg}
        """
        deadline = time.monotonic() + timeout
        hits = {ax: 0 for ax in targets}
        cur = {}
        last_print = 0.0
        while time.monotonic() < deadline:
            for ax, tgt in targets.items():
                cur[ax] = self.angle(ax)
                hits[ax] = hits[ax] + 1 if abs(cur[ax] - tgt) <= tol else 0
            if all(h >= 2 for h in hits.values()):
                return cur
            now = time.monotonic()
            if now - last_print >= 1.0:
                last_print = now
                print("    moving... " + ", ".join(
                    f"{ax} {cur[ax]:+8.2f} -> {targets[ax]:+g}" for ax in targets), flush=True)
            time.sleep(0.2)
        raise PositionerError(
            "move timeout: " + ", ".join(f"{ax} target {targets[ax]:g}, last {cur.get(ax)}" for ax in targets))


# ==========================================================================
# 로테이터 제어
# ==========================================================================
def check_limit(name, deg, limit):
    lo, hi = limit
    if not (lo <= deg <= hi):
        raise ValueError(f"{name} {deg:g} deg is outside limit [{lo:g}, {hi:g}]")


def move_to(pos, az=None, el=None):
    """AZ/EL 중 지정한 축을 동시에 이동시키고 도착을 확인한다."""
    targets = {}
    if az is not None:
        check_limit("AZ", az, AZ_LIMIT)
        targets[AZ_AXIS] = az
    if el is not None:
        check_limit("EL", el, EL_LIMIT)
        targets[EL_AXIS] = el
    if not targets:
        return

    log("move: " + ", ".join(f"{ax} {deg:+g} deg" for ax, deg in targets.items()))
    for ax, deg in targets.items():
        pos.move(ax, deg)
    t0 = time.monotonic()
    actual = pos.wait_arrival_multi(targets, POS_TOL_DEG, POS_MOVE_TIMEOUT_S)
    log(f"arrived ({time.monotonic() - t0:.1f}s): "
        + ", ".join(f"{ax} {actual[ax]:+.2f} deg" for ax in targets))


def show_position(pos):
    az = pos.angle(AZ_AXIS)
    el = pos.angle(EL_AXIS)
    log(f"current: AZ {az:+.2f} deg, EL {el:+.2f} deg")
    return az, el


def set_speed(pos, speed):
    if not (1 <= speed <= 10):
        raise ValueError("speed must be 1 ~ 10")
    for ax in (AZ_AXIS, EL_AXIS):
        pos.command(f"{ax}:SPD {speed}")
    log(f"speed set to {speed} (AZ, EL)")


def parse_move(parts):
    """입력 토큰 -> (az, el). None 은 해당 축 유지. 해석 실패 시 ValueError."""
    if len(parts) == 1 and parts[0] in ("0", "home", "zero"):
        return 0.0, 0.0
    if len(parts) == 2 and parts[0] in ("az", "azi", "azimuth"):
        return float(parts[1]), None
    if len(parts) == 2 and parts[0] in ("el", "elv", "elevation"):
        return None, float(parts[1])
    if len(parts) == 2:
        return float(parts[0]), float(parts[1])
    raise ValueError("invalid input")


HELP = """\
  <AZ> <EL>  : move both, e.g. '30 10'
  az <deg>   : move azimuth only,   e.g. 'az -45'
  el <deg>   : move elevation only, e.g. 'el 15'
  0 / home   : move to AZ 0, EL 0
  pos        : read current angles
  speed <n>  : set speed 1~10
  help       : show this help
  q          : quit"""


def interactive(pos):
    print("")
    print("=== Rotator control ===")
    print(HELP)
    print(f"  (limits: AZ {AZ_LIMIT[0]:g}~{AZ_LIMIT[1]:g}, EL {EL_LIMIT[0]:g}~{EL_LIMIT[1]:g} deg)")
    show_position(pos)

    while True:
        try:
            text = input("rotator> ").strip().lower()
        except EOFError:
            break
        if not text:
            continue
        parts = text.replace(",", " ").split()

        try:
            if parts[0] in ("q", "quit", "exit"):
                break
            if parts[0] == "help":
                print(HELP)
            elif parts[0] in ("pos", "?", "where"):
                show_position(pos)
            elif parts[0] == "speed" and len(parts) == 2:
                set_speed(pos, int(parts[1]))
            else:
                try:
                    az, el = parse_move(parts)
                except ValueError:
                    print("Invalid input. Type 'help' for usage.")
                    continue
                move_to(pos, az, el)
        except ValueError as e:
            print(f"[ERROR] {e}")
        except PositionerError as e:
            log(f"[ERROR] {e}")
        except KeyboardInterrupt:
            # 도착 대기만 중단한다. 로테이터는 이미 받은 명령대로 계속 움직일 수 있음.
            print("")
            log("wait interrupted (rotator may still be moving). Use 'pos' to check.")


def parse_args():
    p = argparse.ArgumentParser(description="Rotator (TC-5594A) AZ/EL control")
    p.add_argument("az", nargs="?", type=float, help="target azimuth (deg) - one-shot mode")
    p.add_argument("el", nargs="?", type=float, help="target elevation (deg) - one-shot mode")
    p.add_argument("--com", default=POS_COM, help="serial port (default: %(default)s)")
    p.add_argument("--baud", type=int, default=POS_BAUD, help="serial baud (default: %(default)s)")
    p.add_argument("--tcp", metavar="HOST", help="use TCP to HOST instead of serial")
    p.add_argument("--port", type=int, default=POS_PORT, help="TCP port (default: %(default)s)")
    p.add_argument("--speed", type=int, default=POS_SPEED, help="speed 1~10 (default: %(default)s)")
    return p.parse_args()


def main():
    args = parse_args()
    if (args.az is None) != (args.el is None):
        print("One-shot mode needs both AZ and EL, e.g. 'python rotator_control.py 30 10'")
        return 1

    transport = "tcp" if args.tcp else POS_TRANSPORT
    host = args.tcp or POS_HOST
    pos = Positioner(transport, host, args.port, args.com, args.baud, POS_EOL)

    try:
        pos.open()
    except Exception as e:
        where = f"{host}:{args.port}" if transport == "tcp" else args.com
        log(f"[ERROR] cannot open positioner ({transport} {where}): {e}")
        return 1

    try:
        log(f"connected: {pos.query('MODEL?')}")
        for ax in (AZ_AXIS, EL_AXIS):
            pos.command(f"{ax}:TORQ ON")
        set_speed(pos, args.speed)

        if args.az is not None:
            move_to(pos, args.az, args.el)
        else:
            interactive(pos)
        return 0

    except KeyboardInterrupt:
        print("")
        log("interrupted by user")
        return 1
    except (PositionerError, ValueError, OSError) as e:
        log(f"[ERROR] {type(e).__name__}: {e}")
        return 1
    finally:
        pos.close()
        log("disconnected")


if __name__ == "__main__":
    sys.exit(main())
