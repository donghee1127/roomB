"""Anritsu MS4644B VectorStar VNA 드라이버 (raw socket SCPI).

phase_index_accuracy 측정에서 DUT 의 S21 gain/phase 를 읽는 장비다.

★ 캘리브레이션 정책 (중요):
  VNA 캘리브레이션은 사용자가 측정 전에 '수동으로' 해 둔다. 이 드라이버는
  절대 *RST / preset 을 보내지 않으며, 트레이스 정의(S21)도 현재 설정을
  쿼리해 이미 맞으면 건드리지 않는다. 주파수 설정(configure_sweep)은
  cal 보간/무효 위험이 있으므로 호출 측(test item)이 opt-in 일 때만 부른다.

통신: 표준 socket SCPI. Anritsu VectorStar 의 raw-socket SCPI 포트는 관례상
5001 이다(R&S/Keysight 의 5025 와 다름 — bench.toml [vna].port 로 변경 가능).

데이터 읽기: phase code 하나당 단일 sweep 후 complex S-data(:CALC1:DATA:SDAT?,
real/imag 쌍)를 1회 쿼리하고 파이썬에서 dB/deg 로 변환한다. 화면 트레이스
포맷(MLOG/PHAS)을 전환하지 않으므로 사용자 화면 설정을 건드리지 않는다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import cmath
import math
import re

from .scpi import ScpiError, ScpiSocket

# 구분자: 콤마 그리고/또는 공백·줄바꿈. VectorStar 는 ASCII 트레이스를
# 'real, imag' 쌍 여러 줄(\n 구분)로 보낸다(실측) — 콤마만으로 split 하면
# '...E-004\n 4.005...' 처럼 줄 경계의 두 숫자가 한 토큰으로 붙는다.
_SEP_RE = re.compile(r"[,\s]+")


def _parse_block_ascii(resp: str) -> list[float]:
    """ASCII 응답(콤마/공백/줄바꿈 구분 실수 나열)을 float 리스트로 파싱한다.

    IEEE-488.2 definite-length 블록 헤더(``#<n><len>...``)가 붙어 있으면 벗겨내고,
    헤더 없는 평문도 그대로 받는다. 빈 응답이면 빈 리스트.
    """
    s = resp.strip()
    if s.startswith("#"):
        # '#' + 자릿수 1글자 + 길이 n글자 + 페이로드
        if len(s) < 2 or not s[1].isdigit():
            raise ScpiError(f"malformed block header in response: {s[:20]!r}")
        ndigits = int(s[1])
        s = s[2 + ndigits:]
    s = s.strip()
    if not s:
        return []
    try:
        return [float(tok) for tok in _SEP_RE.split(s) if tok]
    except ValueError as e:
        raise ScpiError(f"non-numeric token in trace data: {e}") from None


class MS4644B(ScpiSocket):
    """Anritsu MS4644B VectorStar 한 대를 제어하는 드라이버 (ch1/tr1 고정)."""

    def __init__(self, host: str, *, port: int = 5001, timeout: float = 10.0,
                 fake: bool = False, name: str | None = None) -> None:
        super().__init__(host, port, timeout, fake=fake, name=name or "VNA")
        self._freqs: list[float] | None = None   # 주파수축 캐시(설정 바뀌면 invalidate)
        self._fake_sweep_count = 0               # fake: sweep 마다 phase 를 돌리는 카운터

    # -- 셋업 (전부 비파괴 — *RST/preset 금지) ---------------------------
    def setup_s21(self, log=None) -> bool:
        """S21 측정 준비를 '비파괴로' 한다. 전체 성공 여부 반환.

        ASCII 전송 포맷 + ch1/trace1 을 S21 로(이미 S21 이면 안 건드림) + 선택.
        마지막에 에러 큐를 비워, 계측기가 SCPI 호환 모드가 아니거나 명령을
        거부하면 여기서 바로 경고가 드러나게 한다.
        """
        ok = True
        ok &= self.write_try(":FORM:DATA ASCII", log)
        cur = self.query(":CALC1:PAR1:DEF?").strip().upper()
        if "S21" not in cur:
            ok &= self.write_try(":CALC1:PAR1:DEF S21", log)
            self._freqs = None
        ok &= self.write_try(":CALC1:PAR1:SEL", log)
        stale = self.drain_errors()
        for e in stale:
            ok = False
            if log is not None:
                log(f"[warn  ] {self.name} error during S21 setup: {e}")
        return ok

    def configure_sweep(self, start_hz: float, stop_hz: float, points: int,
                        log=None) -> bool:
        """sweep 주파수 범위/포인트 수를 설정한다. 전체 성공 여부 반환.

        ★ 사용자 cal 의 주파수 그리드와 다르면 cal 이 보간되거나 무효가 될 수
        있다. 호출 측이 configure_freq=True 로 명시했을 때만 불러야 한다.
        """
        ok = True
        ok &= self.write_try(f":SENS1:FREQ:STAR {start_hz:.0f}", log)
        ok &= self.write_try(f":SENS1:FREQ:STOP {stop_hz:.0f}", log)
        ok &= self.write_try(f":SENS1:SWE:POIN {int(points)}", log)
        self._freqs = None   # 주파수축이 바뀌었으므로 캐시 무효화
        return ok

    def hold(self, log=None) -> bool:
        """sweep 을 hold(단일 트리거 대기) 모드로 전환한다."""
        return self.write_try(":SENS1:HOLD:FUNC HOLD", log)

    def continuous(self, log=None) -> bool:
        """sweep 을 연속 모드로 되돌린다(측정 종료 시 사용자에게 반환)."""
        return self.write_try(":SENS1:HOLD:FUNC CONT", log)

    # -- 측정 -------------------------------------------------------------
    def single_sweep(self, *, max_wait_s: float = 60.0) -> None:
        """단일 sweep 을 1회 트리거하고 완료까지 폴링 대기한다."""
        self.write(":TRIG:SING")
        self.wait_opc_poll(max_wait_s=max_wait_s)

    # sanity 상한: MS4644B 최대 sweep 포인트(25,000)보다 넉넉히 큰 값.
    # fallback POIN? 응답이 이걸 넘으면 desync 로 주파수 값 등을 읽은 것이다.
    _MAX_SWEEP_POINTS = 100_001

    def read_freqs(self) -> list[float]:
        """트레이스 주파수축[Hz]을 읽는다(1회 캐시).

        :SENS1:FREQ:DATA? 가 거부되거나 파싱이 안 되면 START/STOP/POINTS 쿼리로
        linspace 를 만들어 fallback 한다.

        ★ desync 방어(실측 사고): 블록 쿼리 응답이 timeout 보다 늦게 도착하면
        버퍼에 남아 이후 쿼리가 밀린 응답을 받는다 -> POIN? 이 주파수 값(예:
        2.15e10)을 돌려받아 수십억 포인트 linspace 를 만들다 MemoryError.
        그래서 (1) 블록 쿼리는 timeout 을 올려 읽고, (2) 실패 시 resync 로
        잔여 응답을 버린 뒤 fallback 하고, (3) 포인트 수를 sanity check 한다.
        """
        if self._freqs is not None:
            return self._freqs
        # 대용량 ASCII 트레이스 전송이 기본 timeout 을 넘길 수 있다(read_sdata 동일).
        old_to = self.timeout
        self.set_timeout(max(old_to, 30.0))
        try:
            freqs = _parse_block_ascii(self.query_block(":SENS1:FREQ:DATA?"))
        except (ScpiError, OSError):
            freqs = []
        finally:
            self.set_timeout(old_to)
        if not freqs:
            self.resync()   # 늦게 도착한 블록 응답이 있으면 버려 동기 복구
            start = self.query_float(":SENS1:FREQ:STAR?")
            stop = self.query_float(":SENS1:FREQ:STOP?")
            n = int(self.query_float(":SENS1:SWE:POIN?"))
            if not (1 <= n <= self._MAX_SWEEP_POINTS):
                raise ScpiError(
                    f"{self.name}: implausible sweep point count {n} from "
                    f":SENS1:SWE:POIN? -- likely a desynced/garbled response; "
                    f"retry or power-cycle the VNA remote session")
            if n < 2:
                freqs = [start]
            else:
                step = (stop - start) / (n - 1)
                freqs = [start + i * step for i in range(n)]
        self._freqs = freqs
        return freqs

    def read_sdata(self) -> list[complex]:
        """선택된 트레이스의 complex S-data(real/imag 쌍)를 읽는다.

        큰 ASCII 트레이스 전송이 기본 timeout 을 넘길 수 있어, 읽는 동안만
        소켓 timeout 을 올렸다가 복원한다.
        """
        old_to = self.timeout
        self.set_timeout(max(old_to, 30.0))
        try:
            vals = _parse_block_ascii(self.query_block(":CALC1:DATA:SDAT?"))
        finally:
            self.set_timeout(old_to)
        if len(vals) % 2 != 0:
            raise ScpiError(f"{self.name}: SDAT returned odd count ({len(vals)})")
        return [complex(vals[i], vals[i + 1]) for i in range(0, len(vals), 2)]

    def read_s21(self, *, max_wait_s: float = 60.0
                 ) -> tuple[list[float], list[float], list[float]]:
        """단일 sweep 1회 실행 후 (freqs_hz, gain_db, phase_deg) 를 반환한다.

        gain = 20*log10(|S21|) [dB], phase = angle(S21) [deg, -180..180].
        주파수축과 S-data 포인트 수가 다르면 예외(트레이스/채널 불일치 신호).
        """
        self.single_sweep(max_wait_s=max_wait_s)
        freqs = self.read_freqs()
        sdata = self.read_sdata()
        if len(freqs) != len(sdata):
            raise ScpiError(
                f"{self.name}: freq axis ({len(freqs)} pts) != S-data "
                f"({len(sdata)} pts) -- check trace/channel selection")
        floor = 1e-12   # |S|=0 에서 log10 폭발 방지
        gain_db = [20.0 * math.log10(max(abs(s), floor)) for s in sdata]
        phase_deg = [math.degrees(cmath.phase(s)) for s in sdata]
        return freqs, gain_db, phase_deg

    def marker_read(self, freq_hz: float) -> float:
        """마커1 을 지정 주파수로 옮기고 Y 값을 읽는다(인터랙티브 디버깅용).

        phase_index_accuracy 는 트레이스 기반으로 읽으므로 이 함수에 의존하지
        않는다. 반환값의 의미(dB/deg)는 계기의 현재 트레이스 포맷을 따른다.
        """
        self.write_try(":CALC1:MKR1:ACT")
        self.write(f":CALC1:MKR1:X {freq_hz:.0f}")
        return self.query_float(":CALC1:MKR1:Y?")

    # -- fake 모드 응답 -------------------------------------------------
    _FAKE_POINTS = 11
    _FAKE_START = 27.5e9
    _FAKE_STOP = 28.5e9
    _FAKE_STEP_DEG = 2.8125   # sweep 마다 phase 가 이만큼 돌게 함(= 이상 LSB)

    def _fake_query(self, cmd: str) -> str:
        """가짜 모드 응답: 11포인트 트레이스, SDAT 호출마다 phase +2.8125도.

        |S| = 0.1 (-20 dB) 고정. 연속 phase code sweep 을 흉내내 요약 통계
        (mean step 등) 경로까지 결정적으로 검증할 수 있게 한다.
        """
        c = cmd.strip().upper()
        n = self._FAKE_POINTS
        if "PAR1:DEF?" in c:
            return "S21"
        if "SWE:POIN?" in c:
            return str(n)
        if "FREQ:STAR?" in c:
            return f"{self._FAKE_START:.0f}"
        if "FREQ:STOP?" in c:
            return f"{self._FAKE_STOP:.0f}"
        if "FREQ:DATA?" in c:
            step = (self._FAKE_STOP - self._FAKE_START) / (n - 1)
            return ",".join(f"{self._FAKE_START + i * step:.0f}" for i in range(n))
        if "DATA:SDAT?" in c:
            self._fake_sweep_count += 1
            ph = math.radians(self._fake_sweep_count * self._FAKE_STEP_DEG)
            re_v, im_v = 0.1 * math.cos(ph), 0.1 * math.sin(ph)
            return ",".join(f"{re_v:.6e},{im_v:.6e}" for _ in range(n))
        if "MKR1:Y?" in c:
            return "-20.0"
        return super()._fake_query(cmd)
