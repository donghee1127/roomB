#!/usr/bin/env python3
"""
beam_sync_agent.py - DUT(라즈베리파이)에서 실행되는 빔 제어 에이전트

직접 실행할 필요 없음. 노트북의 beam_sync_main.py 가 SSH로
module.py 와 함께 ~/beam_sync/ 에 업로드한 뒤 자동으로 실행한다.

프로토콜 (한 줄 = 한 명령, 응답은 반드시 '@@ ' 로 시작하는 한 줄)
    CAL <cs:ch:i:q,...>                   boresight(0도) 캘리브레이션 I/Q 지정 (INIT 전에)
                                          -> @@ OK CAL <채널 수>
    INIT <bias> <gain> <deg0,deg1,...>   전원 ON + 칩 초기화 + 빔 테이블 미리 계산
                                          -> @@ OK INIT <빔 개수>
    BEAM <idx>                            미리 계산된 빔 idx 적용 (첫 BEAM 때 TX ON)
                                          -> @@ OK BEAM <idx> <deg>
    PING                                  -> @@ OK PONG
    OFF                                   안전 전원 차단 -> @@ OK OFF
    QUIT                                  종료 (전원이 켜져 있으면 차단 후 종료)
    실패 시                               -> @@ ERR <메시지>

module.py 의 print 출력은 stderr 로 돌려서 프로토콜 응답(stdout)과 섞이지 않게 한다.

안전장치
  - stdin EOF(SSH 끊김) 또는 WATCHDOG 초 동안 명령이 없으면 power_off 후 종료.
"""
import argparse
import contextlib
import os
import select
import sys
import traceback

import module as m


def reply(msg):
    sys.stdout.write("@@ " + msg + "\n")
    sys.stdout.flush()


def info(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def hw(fn, *args, **kwargs):
    """module.py 함수 호출. 그 안의 print 는 stderr 로 보낸다."""
    with contextlib.redirect_stdout(sys.stderr):
        return fn(*args, **kwargs)


class LineReader:
    """select + os.read 기반 줄 단위 읽기 (watchdog 타임아웃 지원)."""

    def __init__(self, fd):
        self.fd = fd
        self.buf = b""

    def readline(self, timeout):
        while b"\n" not in self.buf:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                raise TimeoutError
            chunk = os.read(self.fd, 4096)
            if not chunk:
                return None  # EOF
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", "replace").strip()


class Agent:
    def __init__(self):
        self.beams = []        # [(deg, beamforming_config), ...]
        self.powered = False
        self.tx = False

    def cmd_cal(self, args):
        """module.BORESIGHT_CONFIG 를 전달받은 캘리브레이션 값으로 교체한다.
        compute_beamforming_config() 가 이 값을 0도 기준으로 틸트 위상을 더한다."""
        if self.powered:
            raise RuntimeError("CAL must be sent before INIT")
        new = {}
        for item in args[0].split(","):
            cs, ch, i, q = item.split(":")
            cs, ch, i, q = int(cs), int(ch), int(i, 0), int(q, 0)
            m.phase_of(i, q)  # ADAR1000 위상 테이블에 없는 값이면 KeyError
            new.setdefault(cs, {})[ch] = {'gain': 0, 'i': i, 'q': q}
        expected = {(cs, ch) for cs, chs in m.BORESIGHT_CONFIG.items() for ch in chs}
        got = {(cs, ch) for cs, chs in new.items() for ch in chs}
        if got != expected:
            raise ValueError(f"channel set mismatch: missing {sorted(expected - got)}")
        m.BORESIGHT_CONFIG = new
        for cs in sorted(new):
            info(f"[agent] CAL CS{cs}: " + " ".join(
                f"CH{ch}=({d['i']:#04x},{d['q']:#04x}) {m.phase_of(d['i'], d['q']):.2f}deg"
                for ch, d in sorted(new[cs].items())))
        return f"CAL {len(got)}"

    def cmd_init(self, args):
        bias = int(args[0], 0)
        gain = int(args[1], 0)
        angles = [float(a) for a in args[2].split(",")]

        m.gpio_setup()
        m.PA_BIAS_ON = [bias, bias, bias, bias]
        self.beams = [(a, m.compute_beamforming_config(a, gain)) for a in angles]
        for idx, (deg, cfg) in enumerate(self.beams):
            info(f"[agent] beam {idx}: {deg:+g} deg -> "
                 + " ".join(f"CS{cs}CH{ch}={m.phase_of(d['i'], d['q']):.1f}"
                            for cs in sorted(cfg) for ch, d in sorted(cfg[cs].items())))

        hw(m.power_on_and_init)
        self.powered = True
        self.tx = False
        return f"INIT {len(self.beams)}"

    def cmd_beam(self, args):
        if not self.powered:
            raise RuntimeError("not powered (INIT first)")
        idx = int(args[0])
        deg, cfg = self.beams[idx]
        m.beamforming_config = cfg
        if not self.tx:
            hw(m.tx_on, verbose=False)
            self.tx = True
        else:
            # TX_EN을 다시 토글하지 않고 gain/phase만 갱신 -> 끊김 없이 빔만 이동
            hw(m.apply_beamforming, verbose=False)
        return f"BEAM {idx} {deg:+g}"

    def cmd_off(self, args):
        if self.powered:
            hw(m.power_off)
        self.powered = False
        self.tx = False
        return "OFF"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchdog", type=float, default=60.0,
                        help="이 시간(초) 동안 명령이 없으면 전원 차단 후 종료")
    args = parser.parse_args()

    agent = Agent()
    handlers = {"CAL": agent.cmd_cal, "INIT": agent.cmd_init, "BEAM": agent.cmd_beam, "OFF": agent.cmd_off}
    reader = LineReader(sys.stdin.fileno())

    reply("READY")
    try:
        while True:
            try:
                line = reader.readline(args.watchdog)
            except TimeoutError:
                info(f"[agent] watchdog: {args.watchdog:g}s 동안 명령 없음 -> 종료")
                break
            if line is None:
                info("[agent] stdin EOF (연결 끊김) -> 종료")
                break
            if not line:
                continue

            parts = line.split()
            name = parts[0].upper()
            if name == "PING":
                reply("OK PONG")
                continue
            if name == "QUIT":
                reply("OK QUIT")
                break
            if name not in handlers:
                reply(f"ERR unknown command: {name}")
                continue
            try:
                reply("OK " + handlers[name](parts[1:]))
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                reply(f"ERR {name}: {e}")
    finally:
        if agent.powered:
            info("[agent] 안전 전원 차단 중...")
            try:
                hw(m.power_off)
            except Exception:
                traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
