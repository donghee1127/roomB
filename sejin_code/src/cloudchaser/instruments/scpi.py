"""raw-socket SCPI 전송 베이스 클래스.

이 모듈은 LAN(TCP 5025 포트)으로 연결되는 SCPI 계측기와 통신하는 가장 기본적인
계층이다. Matlab Instrument Control 의 ``tcpip(ip, 5025)`` / ``fopen`` / ``query``
패턴을 그대로 파이썬으로 옮긴 것이며, NI-VISA 같은 추가 드라이버 설치가 전혀
필요 없다 (표준 라이브러리 ``socket`` 만 사용).

핵심 개념:
- 계측기와의 통신은 "ASCII 텍스트 + 줄바꿈(\\n) 종단" 방식의 SCPI 명령이다.
- ``write()``  : 응답이 없는 명령 전송 (예: "VOLT 1.0,(@1)")
- ``query()`` : 끝에 '?' 가 붙은 질의를 보내고 응답 한 줄을 받음 (예: "*IDN?")

``fake=True`` (가짜 모드):
  실제 소켓을 열지 않고, 보낸 명령을 ``history`` 리스트에 기록만 한다. 질의에는
  ``_fake_query()`` 가 돌려주는 가짜 응답을 반환한다. 덕분에 하드웨어가 없는 PC
  에서도 전체 시퀀스를 끝까지 실행(dry-run)하며 코드를 검증할 수 있다.

주의: 사용자에게 보이는 모든 출력/예외 메시지는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import re
import socket
import time

# 응답 문자열에서 첫 번째 실수(부호/소수점/지수 포함)를 뽑는 정규식.
_FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


class ScpiError(RuntimeError):
    """계측기가 SCPI 에러(SYST:ERR?)를 보고했거나 통신이 불가능할 때 던지는 예외."""


class ScpiSocket:
    """SCPI-over-TCP(:5025) 계측기 한 대를 표현하는 클래스.

    하나의 인스턴스가 하나의 계측기(=하나의 TCP 연결)를 담당한다.
    PSU/SG/SA 드라이버는 모두 이 클래스를 상속받아 만든다.
    """

    def __init__(
        self,
        host: str,
        port: int = 5025,
        timeout: float = 5.0,
        *,
        fake: bool = False,
        name: str | None = None,
    ) -> None:
        # host/port : 계측기 IP 와 SCPI 포트(보통 5025)
        self.host = host
        self.port = port
        # timeout : 소켓 읽기/연결 제한 시간(초). 응답 없는 계측기에서 무한 대기 방지.
        self.timeout = timeout
        # fake : True 면 실제 통신 없이 동작(개발 PC 용)
        self.fake = fake
        # name : 로그에 표시할 계측기 이름(예: "PSU1"). 미지정 시 클래스명.
        self.name = name or type(self).__name__
        # _sock : 실제 TCP 소켓 객체. 연결 전/후로 None ↔ socket 가 바뀐다.
        self._sock: socket.socket | None = None
        # history : 지금까지 보낸 모든 명령 문자열(실제/가짜 모드 공통). 디버깅·테스트용.
        self.history: list[str] = []

    # -- 연결 / 해제 ----------------------------------------------------
    def connect(self) -> "ScpiSocket":
        """계측기에 TCP 연결한다. fake 모드면 아무것도 안 하고 self 반환."""
        if self.fake:
            return self
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self._sock = s
        return self  # 체이닝(예: E36313A(...).connect())을 위해 self 반환

    def close(self) -> None:
        """소켓을 닫는다. (주의: 전원 출력을 끄지는 않음 — 그건 PSU 쪽 책임)"""
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    # with 문(컨텍스트 매니저)으로 쓰면 블록 종료 시 자동으로 close() 된다.
    def __enter__(self) -> "ScpiSocket":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- 저수준 송수신 --------------------------------------------------
    def write(self, cmd: str) -> None:
        """명령 한 줄을 전송한다(응답 없음). 끝에 \\n 을 붙여 보낸다."""
        self.history.append(cmd)
        if self.fake:
            return  # 가짜 모드: 기록만 하고 끝
        if self._sock is None:
            raise ScpiError(f"{self.name}: not connected (call connect() first)")
        self._sock.sendall((cmd + "\n").encode("ascii"))

    def _read(self) -> str:
        """소켓에서 \\n 이 나올 때까지 읽어 한 줄(응답)을 반환하는 내부 함수."""
        assert self._sock is not None
        buf = bytearray()
        while not buf.endswith(b"\n"):
            chunk = self._sock.recv(4096)
            if not chunk:  # 연결이 끊기면 빈 바이트 → 루프 탈출
                break
            buf.extend(chunk)
        return buf.decode("ascii").strip()

    def query(self, cmd: str) -> str:
        """질의를 보내고 응답 한 줄을 받아 문자열로 반환한다."""
        self.history.append(cmd)
        if self.fake:
            return self._fake_query(cmd)
        if self._sock is None:
            raise ScpiError(f"{self.name}: not connected (call connect() first)")
        self._sock.sendall((cmd + "\n").encode("ascii"))
        return self._read()

    def query_block(self, cmd: str, *, idle_s: float = 0.3) -> str:
        """블록(여러 줄일 수 있는 대용량) 응답 질의. 트레이스 읽기는 반드시 이걸 쓴다.

        ``_read()`` 는 '\\n 으로 끝나면 응답 완료'로 보는 한 줄용 리더라,
        Anritsu VectorStar 처럼 ASCII 트레이스를 'real, imag' 쌍 여러 줄로
        보내는 계측기에선 chunk 경계가 줄 끝에 걸리는 순간 응답이 잘린다
        (비결정적 truncation — 실측). 이 메서드는:
          - IEEE-488.2 definite-length 헤더(``#<n><len>``)가 있으면 그 길이만큼
            정확히 읽고, 뒤따르는 종단문자까지 소비한다(다음 query desync 방지).
          - 헤더가 없으면 데이터 유입이 idle_s 동안 끊길 때까지 읽는다.
        첫 응답 대기는 self.timeout 을 따른다(무응답 시 OSError).
        """
        self.history.append(cmd)
        if self.fake:
            return self._fake_query(cmd)
        if self._sock is None:
            raise ScpiError(f"{self.name}: not connected (call connect() first)")
        self._sock.sendall((cmd + "\n").encode("ascii"))
        buf = bytearray()
        chunk = self._sock.recv(4096)   # 첫 chunk 는 self.timeout 만큼 대기
        if chunk:
            buf.extend(chunk)
        # -- definite-length 블록: 헤더가 알려주는 길이만큼 정확히 읽는다 --
        if (len(buf) >= 2 and buf[:1] == b"#"
                and chr(buf[1]).isdigit() and chr(buf[1]) != "0"):
            nd = int(chr(buf[1]))
            while len(buf) < 2 + nd:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
            try:
                payload_len = int(buf[2:2 + nd].decode("ascii"))
            except ValueError:
                raise ScpiError(f"{self.name}: malformed block header in "
                                f"response to {cmd!r}") from None
            total = 2 + nd + payload_len
            while len(buf) < total:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
            if len(buf) == total:   # 종단문자(\n)가 아직 안 왔으면 잠깐 기다려 소비
                old_to = self.timeout
                self.set_timeout(idle_s)
                try:
                    buf.extend(self._sock.recv(16))
                except OSError:
                    pass
                finally:
                    self.set_timeout(old_to)
            return buf.decode("ascii", errors="replace").strip()
        # -- 헤더 없음(또는 #0 indefinite): idle_s 동안 조용해질 때까지 읽는다 --
        old_to = self.timeout
        self.set_timeout(idle_s)
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
        except OSError:   # idle timeout = 응답 끝
            pass
        finally:
            self.set_timeout(old_to)
        return buf.decode("ascii", errors="replace").strip()

    # -- 공통 SCPI 헬퍼 -------------------------------------------------
    def idn(self) -> str:
        """계측기 식별 문자열(*IDN?) 반환. 예: 'Keysight,E36313A,...'"""
        return self.query("*IDN?")

    def reset(self) -> None:
        """계측기를 기본 상태로 리셋(*RST). (주의: 사용자 설정이 날아감)"""
        self.write("*RST")

    def clear_status(self) -> None:
        """상태/에러 큐를 비운다(*CLS). 연결 직후 옛 에러를 지우는 데 사용."""
        self.write("*CLS")

    def wait_opc(self) -> None:
        """직전 동작이 끝날 때까지 대기(*OPC? 가 '1' 을 돌려줄 때까지)."""
        self.query("*OPC?")

    def wait_opc_poll(self, *, max_wait_s: float = 30.0, poll_s: float = 0.2,
                      poll_timeout: float = 0.5) -> None:
        """긴 동작(느린 sweep 등)이 끝날 때까지 *OPC? 를 폴링하며 기다린다.

        ``wait_opc`` 는 한 번의 *OPC? 질의를 self.timeout(기본 5s) 안에 받아야 하므로,
        narrow RBW + wide span 처럼 1회 sweep 이 5s 를 넘기면 socket timeout 으로
        측정이 통째로 실패한다. 이 메서드는 소켓 timeout 을 짧게(poll_timeout) 잡고
        *OPC? 가 '1' 을 줄 때까지(또는 max_wait_s 초과까지) 반복 질의한다 — 폴링 중
        나는 socket timeout 은 '아직 안 끝남'으로 보고 넘긴다.

        (reference Summit2629 'wait_opc_poll' 패턴 이식. fake 모드는 즉시 반환.)
        """
        if self.fake:
            return
        old_to = self.timeout
        self.set_timeout(poll_timeout)
        t0 = time.monotonic()
        polled = False  # 한 번이라도 timeout 나며 *OPC? 를 재전송했는지
        try:
            while True:
                try:
                    if self.query("*OPC?").strip().startswith("1"):
                        # 폴링 중 보낸(응답을 못 읽은) *OPC? 들은 동작이 끝나면 한꺼번에
                        # '1' 로 응답돼 버퍼에 쌓인다 → 이후 query 가 한 칸씩 밀리는
                        # desync 발생. 완료 직후 남은 응답을 비워 동기를 지킨다.
                        if polled:
                            self.resync()
                        return
                except OSError:  # socket timeout(=아직 sweep 중) → 계속 폴링
                    polled = True
                if time.monotonic() - t0 > max_wait_s:
                    raise ScpiError(
                        f"{self.name}: *OPC? polling timeout after {max_wait_s}s")
                time.sleep(poll_s)
        finally:
            self.set_timeout(old_to)

    def set_timeout(self, timeout: float) -> None:
        """소켓 읽기/연결 제한 시간[s]을 바꾼다(연결돼 있으면 소켓에도 반영)."""
        self.timeout = timeout
        if self._sock is not None:
            self._sock.settimeout(timeout)

    def resync(self, *, drain_timeout: float = 0.3) -> int:
        """출력 버퍼에 남은(안 읽힌) 응답을 모두 버려 query 동기를 맞춘다.

        타임아웃으로 응답을 못 읽었거나 측정 application 전환(INST:SEL) 직후엔
        계측기 출력 큐에 응답이 남아, 이후 모든 query 가 '직전 query 의 응답'을
        받는 off-by-one desync 가 생긴다(-410 Query interrupted 등). 이 메서드는
        소켓 timeout 을 짧게 잡고 남은 바이트를 다 읽어 버려 동기를 복구한다.
        버린 바이트 수를 반환한다(fake/미연결은 0).
        """
        if self.fake or self._sock is None:
            return 0
        old_to = self.timeout
        self.set_timeout(drain_timeout)
        dropped = 0
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                dropped += len(chunk)
        except OSError:  # socket timeout = 더 읽을 게 없음 → 동기 복구 완료
            pass
        finally:
            self.set_timeout(old_to)
        return dropped

    def query_float(self, cmd: str) -> float:
        """질의 응답에서 첫 번째 실수를 뽑아 반환한다(단위/공백/잡문자에 견고).

        ``float(query(...))`` 직접 호출은 응답에 단위나 여분 토큰이 섞이면 깨진다.
        측정값 읽기(마커 Y, EVM, 채널전력 등)는 모두 이 헬퍼를 거치게 한다.
        """
        resp = self.query(cmd)
        m = _FLOAT_RE.search(resp)
        if not m:
            raise ScpiError(f"{self.name}: no float in response to {cmd!r}: {resp!r}")
        return float(m.group(0))

    def query_float_or_nan(self, cmd: str) -> float:
        """query_float 와 같되, 계측기가 결과없음을 뜻하는 'NAN'/9.91E37 을 주면
        예외 대신 float('nan') 을 반환한다.

        NR 변조분석 FETCh 등은 '아직 동기/락이 안 됨'을 NAN 으로 돌려준다. 이걸
        에러로 띄우면 스윕 전체가 죽으므로, 호출 측이 nan 을 '값 없음'으로 다루게 한다.
        """
        resp = self.query(cmd)
        if "NAN" in resp.upper():
            return float("nan")
        m = _FLOAT_RE.search(resp)
        if not m:
            return float("nan")
        v = float(m.group(0))
        return float("nan") if abs(v) >= 9.9e37 else v  # R&S NaN 예약값

    def drain_errors(self, limit: int = 32) -> list[str]:
        """계측기 에러 큐(SYST:ERR?)를 끝까지 읽어 비우고, 0 이 아닌 에러 목록 반환.

        SCPI 계측기는 에러를 큐에 쌓아두므로, '0,"No error"' 가 나올 때까지
        반복해서 꺼내야 큐가 깨끗해진다. limit 은 무한 루프 방지용 상한.
        """
        errors: list[str] = []
        for _ in range(limit):
            resp = self.query("SYST:ERR?")
            code = resp.split(",", 1)[0].strip()  # "예: -222" 또는 "0"
            try:
                if int(float(code)) == 0:  # 코드 0 = 더 이상 에러 없음 → 종료
                    break
            except ValueError:
                break  # 숫자 파싱 불가(fake 등) → 중단
            errors.append(resp)
        return errors

    def check_error(self) -> None:
        """에러 큐를 모두 비우고, 남아있던 에러가 있으면 예외를 던진다."""
        errs = self.drain_errors()
        if errs:
            raise ScpiError(f"{self.name}: SCPI error {' ; '.join(errs)}")

    def write_checked(self, cmd: str) -> None:
        """명령 전송 직후 에러를 확인 — 실패하면 '어느 명령이' 문제인지 예외에 담는다.

        여러 명령을 보낸 뒤 한 번에 확인하면 어느 명령이 범인인지 알 수 없으므로,
        값 검증이 중요한 설정(전압/전류/OVP 등)에 이 메서드를 쓴다.
        """
        self.write(cmd)
        errs = self.drain_errors()
        if errs:
            raise ScpiError(f"{self.name}: command '{cmd}' rejected -> "
                            f"{' ; '.join(errs)}")

    def write_try(self, cmd: str, log=None) -> bool:
        """명령을 보내되, 거부돼도 예외를 던지지 않고 경고만 남긴다. 성공 여부 반환.

        계측기가 특정 명령을 거부해도 전체 절차를 멈추면 안 되는 'best-effort'
        설정(SG/SA 파라미터 등)에 사용한다.
        """
        self.write(cmd)
        errs = self.drain_errors()
        if errs:
            if log is not None:
                log(f"[warn  ] {self.name} command '{cmd}' rejected -> "
                    f"{' ; '.join(errs)}")
            return False
        return True

    # -- fake 모드 응답 -------------------------------------------------
    def _fake_query(self, cmd: str) -> str:
        """가짜 모드에서 질의에 대한 응답을 만든다.

        기본은 공통 질의(*IDN?, *OPC?, SYST:ERR?)만 처리하고 나머지는 "0".
        각 계측기 서브클래스가 이 메서드를 오버라이드해 의미 있는 값을 돌려준다.
        """
        c = cmd.strip().upper()
        if c == "*IDN?":
            return f"FAKE,{self.name},0,0.0"
        if c == "*OPC?":
            return "1"
        if c.startswith("SYST:ERR"):
            return '0,"No error"'
        return "0"
