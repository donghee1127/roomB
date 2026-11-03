"""
beam_sync_main.py - 빔포밍 DUT + 포지셔너(TC-5594A) 동기 제어 (노트북에서 실행)

구조
  노트북 ──(Wi-Fi, SSH)──> 라즈베리파이: beam_sync_agent.py (+ module.py) 자동 업로드/실행
        └─(LAN 또는 시리얼)─> 포지셔너 TC-5594A

동기화 방식 (lock-step handshake)
  매 스텝마다
    1) DUT 에 BEAM <idx> 전송 -> 적용 완료 응답(@@ OK) 수신
    2) 포지셔너 이동 명령 -> 현재각을 폴링해서 목표각 도착 확인
    3) 도착 시점부터 DWELL_S 초 대기
  다음 스텝은 앞 단계가 '완료 확인'된 뒤에만 시작하므로 두 장비가 타이머로
  따로 돌 때 생기는 누적 시간 오차(drift)가 원리적으로 생기지 않는다.

사용법
  pip install paramiko pyserial
  python beam_sync_main.py                 # 기본 설정으로 무한 반복 (Ctrl+C로 정지)
  python beam_sync_main.py --cycles 3      # 3회 반복 후 종료
  python beam_sync_main.py --no-pos        # DUT만 (포지셔너 없이 테스트)
  python beam_sync_main.py --no-dut        # 포지셔너만 (DUT 없이 테스트)
  python beam_sync_main.py --com COM5      # 포지셔너 시리얼 포트 지정
"""
import argparse
import csv
import getpass
import os
import socket
import sys
import threading
import time
from datetime import datetime

# ==========================================================================
# 사용자 설정
# ==========================================================================
# --- 시퀀스: (빔 틸트 각도, 포지셔너 각도) 를 순서대로 반복 ---
STEPS = [
    (-30, -30),
    (-10, -10),
    (0, 0),
    (10, 10),
    (30, 30),
]
DWELL_S = 5.0          # 포지셔너 도착 후 대기 시간 (초)

# --- DUT (라즈베리파이) ---
DUT_HOST = "10.94.24.10"
DUT_USER = "nsg"
DUT_PASSWORD = None    # None 이면 실행 시 입력받음 (SSH 키가 설정돼 있으면 키 우선 사용)
DUT_REMOTE_DIR = "beam_sync"   # 파이 홈 디렉토리 기준 업로드 폴더
BIAS_VAL = 0x02        # PA_BIAS 레지스터 (0x029~0x02C) 값 - beam_tilt_demo.py 와 동일
GAIN_VAL = 0xA5        # 전 칩/채널 공통 gain index
AGENT_WATCHDOG_S = 60  # 이 시간 동안 노트북 명령이 없으면 DUT가 스스로 전원 차단

# 실측 보정: 공칭 빔 각도 -> 실제로 phase 계산에 쓸 각도
# (beam_tilt_demo.py 에서는 +-20도가 반대로 나와서 {20: -20, -20: 20} 을 사용했었음.
#  +-10/+-30 도 측정해보고 반대로 나오면 여기에 추가)
HW_ANGLE_OVERRIDE = {}

# --- 포지셔너 TC-5594A ---
POS_TRANSPORT = "serial"   # "tcp" 또는 "serial"
POS_HOST = "192.168.5.20"  # tcp 일 때 (이전 포지셔너 설정값, 실제 값 확인 필요)
POS_PORT = 1001
POS_COM = "COM3"           # serial 일 때 (장치관리자 > 포트(COM & LPT)에서 확인, --com 으로도 지정 가능)
POS_BAUD = 9600
POS_EOL = "\r"             # 명령 종단 문자 (안 되면 "\r\n" 시도)
POS_AXIS = "AZI"           # 틸트할 축: "AZI" 또는 "ELV"
POS_SPEED = 5              # 1~10
POS_TOL_DEG = 0.3          # 도착 판정 허용 오차
POS_MOVE_TIMEOUT_S = 90    # 이동 타임아웃
POS_RETURN_ZERO = True     # 종료 시 0도로 복귀

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
HERE = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}", flush=True)


# ==========================================================================
# 포지셔너
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

    def wait_arrival(self, axis, target, tol, timeout, idle=None):
        """현재각을 폴링해서 목표각 +-tol 안에 연속 2회 들어오면 도착으로 판정."""
        deadline = time.monotonic() + timeout
        hits = 0
        cur = None
        while time.monotonic() < deadline:
            cur = self.angle(axis)
            hits = hits + 1 if abs(cur - target) <= tol else 0
            if hits >= 2:
                return cur
            if idle:
                idle()
            time.sleep(0.2)
        raise PositionerError(f"move timeout: target {target:g}, last {cur}")


class NullPositioner:
    """--no-pos 용 더미."""
    def open(self): pass
    def close(self): pass
    def query(self, cmd, timeout=3.0): return "(no positioner)"
    def command(self, cmd, timeout=3.0): pass
    def move(self, axis, deg): pass
    def wait_arrival(self, axis, target, tol, timeout, idle=None): return float("nan")


# ==========================================================================
# DUT (SSH 로 라즈베리파이의 beam_sync_agent.py 와 통신)
# ==========================================================================
class DutError(Exception):
    pass


class DutLink:
    PING_INTERVAL_S = 15

    def __init__(self, host, user, password, remote_dir, watchdog):
        self.host, self.user, self.password = host, user, password
        self.remote_dir = remote_dir
        self.watchdog = watchdog
        self.client = None
        self.chan = None
        self.last_tx = 0.0
        self.lock = threading.Lock()

    def connect(self):
        import paramiko
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            try:
                self.client.connect(self.host, username=self.user, password=self.password, timeout=10)
            except paramiko.SSHException:
                # SSH 키가 없으면 AuthenticationException 이 아니라
                # "No authentication methods available"(SSHException) 이 난다 -> 비밀번호 입력
                if self.password is not None:
                    raise
                self.password = getpass.getpass(f"{self.user}@{self.host} password: ")
                self.client.connect(self.host, username=self.user, password=self.password,
                                    timeout=10, look_for_keys=False, allow_agent=False)
        except paramiko.AuthenticationException:
            raise DutError("SSH 로그인 실패 (비밀번호 확인)")
        except (paramiko.SSHException, OSError) as e:
            raise DutError(f"SSH 연결 실패: {e} (파이 전원/Wi-Fi keti_mcu 연결/IP 확인)")
        self.client.get_transport().set_keepalive(5)

    def upload(self):
        sftp = self.client.open_sftp()
        try:
            try:
                sftp.mkdir(self.remote_dir)
            except IOError:
                pass  # 이미 있음
            for name in ("beam_sync_agent.py", "module.py"):
                sftp.put(os.path.join(HERE, name), f"{self.remote_dir}/{name}")
                log(f"[DUT] uploaded {name} -> ~/{self.remote_dir}/")
        finally:
            sftp.close()

    def start(self):
        self.chan = self.client.get_transport().open_session()
        self.chan.exec_command(
            f"cd ~/{self.remote_dir} && exec python3 -u beam_sync_agent.py --watchdog {self.watchdog:g}")
        self.stdin = self.chan.makefile_stdin("wb")
        self.stdout = self.chan.makefile("r")
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        self.last_tx = time.monotonic()
        self._read_reply(timeout=30, expect="READY")

    def _pump_stderr(self):
        for line in self.chan.makefile_stderr("r"):
            line = line.rstrip()
            if line:
                log(f"[DUT] {line}")

    def _read_reply(self, timeout, expect=None):
        self.chan.settimeout(timeout)
        while True:
            try:
                line = self.stdout.readline()
            except socket.timeout:
                raise DutError(f"no reply within {timeout}s")
            if not line:
                raise DutError("SSH channel closed (agent exited)")
            line = line.strip()
            if not line.startswith("@@ "):
                log(f"[DUT] {line}")
                continue
            reply = line[3:]
            if reply.startswith("ERR"):
                raise DutError(reply)
            if expect and not reply.startswith(expect):
                raise DutError(f"unexpected reply: {reply}")
            return reply

    def request(self, cmd, timeout=10):
        with self.lock:
            self.stdin.write((cmd + "\n").encode())
            self.stdin.flush()
            self.last_tx = time.monotonic()
            return self._read_reply(timeout, expect="OK")

    def keepalive(self):
        """긴 대기 중에 호출. 에이전트 watchdog 이 만료되지 않도록 주기적으로 PING."""
        if time.monotonic() - self.last_tx > self.PING_INTERVAL_S:
            self.request("PING")

    def close(self):
        if self.chan is not None:
            self.chan.close()
        if self.client is not None:
            self.client.close()


class NullDut:
    """--no-dut 용 더미."""
    def connect(self): pass
    def upload(self): pass
    def start(self): pass
    def request(self, cmd, timeout=10): return f"OK (no dut) {cmd}"
    def keepalive(self): pass
    def close(self): pass


# ==========================================================================
# 메인 시퀀스
# ==========================================================================
def parse_args():
    p = argparse.ArgumentParser(description="Beamforming DUT + positioner synchronized control")
    p.add_argument("--cycles", type=int, default=0, help="반복 횟수 (0 = Ctrl+C 까지 무한)")
    p.add_argument("--dwell", type=float, default=DWELL_S, help="도착 후 대기 시간(초)")
    p.add_argument("--no-dut", action="store_true", help="DUT 없이 포지셔너만")
    p.add_argument("--no-pos", action="store_true", help="포지셔너 없이 DUT만")
    p.add_argument("--com", default=POS_COM, help="포지셔너 시리얼 포트 (default: %(default)s)")
    return p.parse_args()


def sleep_with_keepalive(seconds, dut):
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))
        dut.keepalive()


def main():
    args = parse_args()

    beam_angles = []
    for beam_deg, _ in STEPS:
        if beam_deg not in beam_angles:
            beam_angles.append(beam_deg)
    beam_idx = {deg: i for i, deg in enumerate(beam_angles)}
    hw_angles = [HW_ANGLE_OVERRIDE.get(a, a) for a in beam_angles]

    os.makedirs(LOG_DIR, exist_ok=True)
    csv_path = os.path.join(LOG_DIR, f"beam_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    pos = NullPositioner() if args.no_pos else Positioner(
        POS_TRANSPORT, POS_HOST, POS_PORT, args.com, POS_BAUD, POS_EOL)
    dut = NullDut() if args.no_dut else DutLink(
        DUT_HOST, DUT_USER, DUT_PASSWORD, DUT_REMOTE_DIR, AGENT_WATCHDOG_S)

    dut_started = False
    pos_opened = False
    try:
        # --- 포지셔너 연결 ---
        pos.open()
        pos_opened = True
        log(f"[POS] connected: {pos.query('MODEL?')}")
        pos.command(f"{POS_AXIS}:SPD {POS_SPEED}")
        pos.command(f"{POS_AXIS}:TORQ ON")

        # --- DUT 연결 / 에이전트 기동 / 전원 ON ---
        log(f"[DUT] connecting {DUT_USER}@{DUT_HOST} ...")
        dut.connect()
        dut.upload()
        dut.start()
        dut_started = True
        log(f"[DUT] agent ready. power on & init (bias=0x{BIAS_VAL:02X}, gain=0x{GAIN_VAL:02X}) ...")
        dut.request(f"INIT 0x{BIAS_VAL:02X} 0x{GAIN_VAL:02X} {','.join(f'{a:g}' for a in hw_angles)}",
                    timeout=120)
        log(f"[DUT] init done. beam table: "
            + ", ".join(f"#{i}={a:+g}" for i, a in enumerate(beam_angles)))

        log(f"시퀀스 {STEPS} / dwell {args.dwell:g}s / "
            + (f"{args.cycles}회 반복" if args.cycles else "무한 반복 (Ctrl+C 정지)"))

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["cycle", "step", "beam_deg", "beam_idx", "pos_target_deg",
                             "pos_actual_deg", "t_beam_ack", "t_pos_arrived", "t_dwell_end"])
            cycle = 0
            while args.cycles == 0 or cycle < args.cycles:
                cycle += 1
                for step, (beam_deg, pos_deg) in enumerate(STEPS):
                    idx = beam_idx[beam_deg]

                    # 1) 빔 인가 -> 응답 확인
                    dut.request(f"BEAM {idx}")
                    t_beam = datetime.now()
                    log(f"[{cycle}-{step}] beam #{idx} ({beam_deg:+g} deg) applied")

                    # 2) 포지셔너 이동 -> 도착 확인
                    pos.move(POS_AXIS, pos_deg)
                    actual = pos.wait_arrival(POS_AXIS, pos_deg, POS_TOL_DEG,
                                              POS_MOVE_TIMEOUT_S, idle=dut.keepalive)
                    t_pos = datetime.now()
                    log(f"[{cycle}-{step}] positioner {POS_AXIS} {pos_deg:+g} deg arrived "
                        f"(actual {actual:+.2f}), dwell {args.dwell:g}s")

                    # 3) 대기
                    sleep_with_keepalive(args.dwell, dut)
                    t_end = datetime.now()

                    writer.writerow([cycle, step, beam_deg, idx, pos_deg, f"{actual:.2f}",
                                     t_beam.isoformat(timespec="milliseconds"),
                                     t_pos.isoformat(timespec="milliseconds"),
                                     t_end.isoformat(timespec="milliseconds")])
                    f.flush()
        log("설정된 반복 완료.")

    except KeyboardInterrupt:
        log("Ctrl+C 감지 -> 안전 종료")
    except (PositionerError, DutError, OSError) as e:
        log(f"[ERROR] {type(e).__name__}: {e} -> 안전 종료")
    finally:
        if dut_started:
            try:
                log("[DUT] power off (약 25초) ...")
                dut.request("OFF", timeout=120)
                dut.request("QUIT")
            except Exception as e:
                log(f"[DUT][warn] 정상 종료 실패 ({e}). 에이전트가 연결 끊김을 감지해 스스로 전원을 차단합니다.")
        dut.close()

        if pos_opened:
            if POS_RETURN_ZERO and not args.no_pos:
                try:
                    pos.move(POS_AXIS, 0)
                    pos.wait_arrival(POS_AXIS, 0, POS_TOL_DEG, POS_MOVE_TIMEOUT_S)
                    log("[POS] 0도 복귀 완료")
                except Exception as e:
                    log(f"[POS][warn] 0도 복귀 실패: {e}")
            pos.close()

        if os.path.exists(csv_path):
            log(f"로그: {csv_path}")


if __name__ == "__main__":
    main()
