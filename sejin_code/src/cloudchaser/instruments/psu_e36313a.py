"""Keysight E36313A 3채널 전원공급기(PSU) 드라이버.

이 드라이버의 가장 중요한 목표는 **보드를 안전하게 켜는 것**이다. 그래서:
  1) 먼저 보호 설정(채널별 전류제한 + 과전압보호 OVP)을 건 뒤
  2) 전압을 0V 에서 목표값까지 '한 번에' 가 아니라 **여러 스텝으로 천천히** 올린다.
  3) 각 스텝마다 보호가 트립(차단)됐는지 확인하고, 트립되면 즉시 멈춘다.
이 패턴은 Matlab ``Pdown_PowSup_*`` 스크립트의 "스텝 인가 + 트립체크 + V/I 읽기"를
그대로 옮긴 것이다.

SCPI 채널 리스트 문법: 여러 채널을 한 번에 지정할 때 ``(@1,2,3)`` 또는 ``(@1:3)`` 사용.

E36313A 하드웨어 특이점(실측으로 확인됨):
- ch1 = 6V 레인지(최대 ~10A), ch2/ch3 = 25V 레인지(최대 ~2A).
- 25V 채널(ch2/ch3)은 OVP 가능 범위를 0.5~27.5V 로 '보고' 하지만, 실제로는 낮은
  값(예: 1.3V)을 -222 "Data out of range" 로 거부한다. 그래서 OVP 는 받아들여지는
  값을 찾을 때까지 조금씩 올려가며 설정한다(_set_ovp_resilient 참고).

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .scpi import ScpiError, ScpiSocket


@dataclass
class Rail:
    """전원 레일 한 개 = PSU 채널 1개의 설정 묶음.

    ch       : 물리 채널 번호(1~3)
    name     : 레일 이름(예: "CORE_1V0"). 로그/식별용.
    v_target : 목표 출력 전압[V]
    i_limit  : 전류 제한[A] (보드 보호의 1차 수단)
    ovp      : 과전압 보호 레벨[V] (0 이하면 OVP 설정 생략)
    detect_v : chip auto-detect 1단계에서만 쓰는 중간 전압[V] (None 이면 v_target)
    """

    ch: int
    name: str
    v_target: float
    i_limit: float
    ovp: float
    detect: bool = False    # True 면 chip auto-detect 1단계에서 먼저 켜는 SPI 레일
    # 보드 종류가 확정되기 전에는 TX/RX 양쪽에 안전한 전압만 걸어야 한다. TX 의
    # VDD_IO 처럼 보드마다 목표 전압이 다른 레일은 detect_v(공용 안전값)까지만 올리고,
    # 종류가 확정된 뒤 v_target 으로 승압한다.
    detect_v: float | None = None


class TripError(ScpiError):
    """전원 보호(OVP/OCP)가 트립됨 — 보드 보호를 위해 즉시 중단해야 함을 알리는 예외."""


class E36313A(ScpiSocket):
    """E36313A 한 대(채널 3개)를 제어하는 드라이버."""

    def __init__(self, host: str, rails: list[Rail], *, port: int = 5025,
                 fake: bool = False, name: str | None = None,
                 trip_poll: bool = True) -> None:
        super().__init__(host, port, fake=fake, name=name or "E36313A")
        # 이름으로 레일을 찾는 딕셔너리 {"CORE_1V0": Rail, ...}
        self.rails: dict[str, Rail] = {r.name: r for r in rails}
        # 채널 번호로 레일을 찾는 딕셔너리 {2: Rail, ...}
        self._by_ch: dict[int, Rail] = {r.ch: r for r in rails}
        # fake 모드에서 MEAS? 가 돌려줄 '현재 설정 전압'을 채널별로 기억해 둔다.
        self._set_v: dict[int, float] = {r.ch: 0.0 for r in rails}
        # 트립 상태 조회 지원 여부. 계측기가 조회 명령을 안 받으면 첫 실패 후 False 로
        # 바꿔서, 이후엔 트립 폴링을 건너뛴다(타임아웃 반복 방지).
        # trip_poll=False(bench.toml) 면 처음부터 끈다 -- STAT:QUES:COND? 를 아예
        # 지원하지 않는 장비에서 매 세션 소켓 타임아웃(기본 5s)을 기다리지 않도록.
        self._trip_poll_cfg = trip_poll
        self._trip_supported = trip_poll
        self._trip_off_logged = False

    def has_rail(self, name: str) -> bool:
        """이 PSU 가 해당 이름의 레일을 가지고 있는지 여부."""
        return name in self.rails

    # -- 보호 설정 ------------------------------------------------------
    def _ovp_range(self, ch: int) -> tuple[float, float] | None:
        """채널이 보고하는 OVP 설정 가능 범위 (MIN, MAX) 를 질의해서 반환.

        질의가 실패하면(파싱 불가/타임아웃) None 을 돌려준다.
        주의: 위 모듈 설명대로, 이 범위는 실제 허용값과 다를 수 있다(참고용).
        """
        try:
            lo = float(self.query(f"VOLT:PROT? MIN,(@{ch})"))
            hi = float(self.query(f"VOLT:PROT? MAX,(@{ch})"))
            return lo, hi
        except (ValueError, OSError):
            return None

    def _set_ovp_resilient(self, r: "Rail", log) -> None:
        """OVP 를 '계측기가 실제로 받아주는' 값으로 끈질기게 설정한다.

        동작: 요청값(r.ovp)부터 시작해 거부되면 0.5V 씩 올려가며 시도하고,
        처음으로 거부되지 않는 값을 채택한다. (그 값이 요청값과 다르면 경고 출력.)
        끝까지(상한까지) 실패하면 OVP 설정은 포기하고 전류제한만으로 보호하며
        진행한다 — OVP 하나 때문에 전체 bring-up 을 막지 않기 위함.
        """
        rng = self._ovp_range(r.ch)
        # 탐색 상한: 범위를 알면 그 최대값, 모르면 요청값 +6V 정도까지만 시도.
        hi = rng[1] if rng else r.ovp + 6.0
        # 시작값: 요청값과 보고된 최소값 중 큰 값(보고 최소보다 낮으면 의미 없으니).
        v = max(r.ovp, rng[0]) if rng else r.ovp
        for _ in range(20):  # 최대 20회 시도(무한 루프 방지)
            if v > hi + 1e-6:
                break
            self.write(f"VOLT:PROT {round(v, 3)},(@{r.ch})")
            if not self.drain_errors():  # 에러가 없으면 = 받아들여짐
                if abs(v - r.ovp) > 1e-6:  # 요청값과 다른 값으로 안착했으면 정보로 알림
                    # 25V 레인지 채널(ch2/ch3)은 OVP 하한이 ~1.65V 라 낮은 값을 거부한다.
                    # 정상 동작(받아들여지는 값으로 자동 안착)이므로 warn 이 아니라 info 로.
                    log(f"[ovp   ] {self.name} ch{r.ch}({r.name}) OVP {r.ovp}V below "
                        f"channel floor -> applied {round(v, 3)}V (current limit is "
                        f"primary protection)")
                return
            v += 0.5  # 거부됨 → 0.5V 올려 재시도
        log(f"[warn  ] {self.name} ch{r.ch}({r.name}) OVP could not be set -> "
            f"continuing with current limit ({r.i_limit}A) only")

    def apply_protection(self, log=print, only: set[str] | None = None) -> None:
        """채널별 전류제한 + OVP 를 설정한다 (출력 OFF, 0V 상태에서 호출할 것).

        - VOLT 0 / CURR : 명령마다 즉시 에러를 확인(write_checked) → 잘못된 값이면
          어느 명령이 문제인지 바로 예외로 알림.
        - OVP : 위 _set_ovp_resilient 로 '받아들여지는 값'을 찾아 설정하고, 실패해도
          진행을 막지 않는다. ovp <= 0 이면 OVP 설정 자체를 건너뛴다.
        - only : 주어지면 그 이름의 레일에만 보호를 건다(2단계 전원에서 FE 레일만).

        보호 설정 전에 큐에 남은 stale 에러를 비운다. 전 단계의 ramp/측정에서 남은
        에러(예: -113)가 write_checked 의 다음 명령에 잘못 귀속되어 bring-up 을 통째로
        abort 시키던 문제를 막는다 — connect_all 의 startup drain 과 같은 취지.
        """
        for e in self.drain_errors():
            log(f"[warn  ] {self.name} stale error before protection (ignored): {e}")
        # 설정으로 껐어도 조용히 넘어가지 않는다 -- 운영자가 트립 보호가 도는 줄 알면 안 된다.
        if not self._trip_poll_cfg and not self._trip_off_logged:
            log(f"[power ] {self.name} trip polling off by config (trip_poll=false); "
                f"the current limit remains the primary protection")
            self._trip_off_logged = True
        for r in self.rails.values():
            if only is not None and r.name not in only:
                continue
            self.write_checked(f"VOLT 0,(@{r.ch})")          # 안전: 전압 0 으로
            self.write_checked(f"CURR {r.i_limit},(@{r.ch})")  # 전류 제한
            if r.ovp > 0:
                self._set_ovp_resilient(r, log)               # 과전압 보호
            self._set_v[r.ch] = 0.0  # 내부 추적 전압도 0 으로 초기화

    # -- 출력/전압 ------------------------------------------------------
    def output(self, on: bool, channels: list[int] | None = None) -> None:
        """지정 채널들의 출력을 켜거나 끈다. channels 미지정 시 모든 레일."""
        chans = channels or [r.ch for r in self.rails.values()]
        clist = ",".join(str(c) for c in chans)
        self.write(f"OUTP {'ON' if on else 'OFF'},(@{clist})")

    def set_voltage(self, ch: int, v: float) -> None:
        """한 채널의 출력 전압을 설정하고, 내부 추적값(_set_v)도 갱신한다."""
        self.write(f"VOLT {v:.4f},(@{ch})")
        self._set_v[ch] = v

    # -- 보호 트립 ------------------------------------------------------
    def tripped(self, ch: int | None = None) -> bool:
        """OVP/OCP 트립 여부를 확인한다.

        STAT:QUES:COND? 응답의 비트로 판단한다(bit0=과전압 OV, bit1=과전류 OC).
        만약 계측기가 이 조회를 지원하지 않아 타임아웃/에러가 나면, 트립 폴링을
        비활성화하고 이후 항상 False 를 반환한다. 전류제한이 1차 보호이므로
        트립 폴링 없이도 안전하다.
        """
        if not self._trip_supported:
            return False
        chans = [ch] if ch is not None else [r.ch for r in self.rails.values()]
        clist = ",".join(str(c) for c in chans)
        try:
            resp = self.query(f"STAT:QUES:COND? (@{clist})")
        except OSError:  # socket timeout 도 OSError 의 하위 → 여기서 잡힘
            # 늦게 도착할 응답을 버려 다음 query 가 한 칸 밀리는 desync 를 막는다.
            self.resync()
            self._trip_supported = False
            # 조용히 끄면 운영자는 트립 보호가 계속 도는 줄 안다 -- 반드시 알린다.
            print(f"[warn  ] {self.name} trip polling disabled "
                  f"(STAT:QUES:COND? did not answer); the current limit "
                  f"remains the primary protection")
            return False
        for x in resp.split(","):
            x = x.strip()
            if not x:
                continue
            try:
                if int(float(x)) & 0b11:  # bit0(OV) 또는 bit1(OC) 가 켜져 있으면 트립
                    return True
            except ValueError:
                pass
        return False

    def clear_protection(self, ch: int | None = None) -> None:
        """트립된 보호를 해제(클리어)한다."""
        chans = [ch] if ch is not None else [r.ch for r in self.rails.values()]
        clist = ",".join(str(c) for c in chans)
        self.write(f"OUTP:PROT:CLE (@{clist})")

    # -- 측정 -----------------------------------------------------------
    # MEAS? 측정 읽기에 한해 쓰는 소켓 timeout[s]. 쿼리 **하나**에 걸리는 값이고,
    # read_all_vi 한 번은 PSU 당 2개(VOLT?/CURR?)를 보낸다.
    #
    # 2026-09-04 실측(TX 벤치, psu_probe --vi 100 을 15/5/3s 로 세 번):
    #   15s -> 실패 10%, 실패 1회 15.5s, 전체 403s
    #    5s -> 실패  2%, 실패 1회  5.6s, 전체 270s
    #    3s -> 실패  2%, 실패 1회  3.6s, 전체 266s
    # 정상 read_all_vi 는 2.45~2.65s(쿼리 4개, 가장 느린 단일 쿼리 약 1.0s)라
    # 3s 는 3배 여유다. 짧게 잡을수록 나아진다는 것 자체가 원인을 말해준다 --
    # 15s 를 기다려도 못 받은 응답이 3s 로 줄이자 더 적게 실패했다면, 느린 응답이
    # 아니라 **오지 않는 응답**이다. 기다림은 아무것도 사주지 않는다.
    #
    # 옛 15.0 은 autorange 를 의심해 넉넉히 잡은 값이었는데, autorange 가 원인이
    # 아님은 2026-06-25 에 이미 확인됐다(DIAG:DISL 도 이 펌웨어가 거부).
    MEAS_TIMEOUT_S = 3.0

    def read_vi(self) -> dict[str, dict[str, float]]:
        """모든 채널의 실제 전압/전류를 측정해 레일별로 반환한다.

        반환 형식: {"CORE_1V0": {"v": 1.001, "i": 0.004}, ...}
        (Matlab Record_PS_VI 패턴: MEAS:VOLT? / MEAS:CURR? 를 채널 리스트로 한 번에)

        측정 동안만 socket timeout 을 MEAS_TIMEOUT_S 로 바꾼다. timeout 이 나면
        resync() 로 출력 큐를 비워 '다음' 읽기가 off-by-one 으로 어긋나지 않게 한 뒤
        예외를 그대로 올린다(호출측이 재시도하거나 NaN 으로 처리).

        예전엔 max(self.timeout, MEAS_TIMEOUT_S) 로 '올리기만' 했는데, 그러면
        MEAS_TIMEOUT_S 를 기본 소켓 timeout(5s)보다 낮게 잡아도 조용히 무시된다 --
        2026-09-04 에 psu_probe --meas-timeout 3 이 실제로는 5s 로 돌아 측정을
        오독하게 만들었다. 이제는 준 값을 그대로 쓴다.
        """
        chans = sorted(self._by_ch)
        clist = ",".join(str(c) for c in chans)
        old_to = self.timeout
        self.set_timeout(self.MEAS_TIMEOUT_S)
        try:
            v = [float(x) for x in self.query(f"MEAS:VOLT? (@{clist})").split(",")]
            i = [float(x) for x in self.query(f"MEAS:CURR? (@{clist})").split(",")]
        except OSError:
            self.resync()  # 늦게 오는 응답을 버려 다음 query 동기를 지킨다
            raise
        finally:
            self.set_timeout(old_to)
        out: dict[str, dict[str, float]] = {}
        for idx, c in enumerate(chans):
            out[self._by_ch[c].name] = {"v": v[idx], "i": i[idx]}
        return out

    # -- 램프(전압을 천천히 올리고 내리기) ------------------------------
    def ramp_rail(self, name: str, *, step_v: float, settle_s: float) -> None:
        """한 레일을 0V 에서 목표 전압까지 step_v 간격으로 천천히 올린다.

        각 스텝 후 settle_s 만큼 기다렸다가 트립 여부를 확인하고, 트립되면
        TripError 를 던져 즉시 중단한다(보드 보호).
        """
        r = self.rails[name]
        self.output(True, [r.ch])  # 먼저 출력 ON (전압은 아직 0 부근)
        # 스텝 수는 ceil 로 계산해야 목표 전압에 정확히 도달한다.
        # 예: 목표 1.3V, step 0.2V → 1.3/0.2=6.5 → ceil=7 스텝(마지막에 1.3V 도달).
        steps = max(1, math.ceil(r.v_target / step_v))
        for k in range(1, steps + 1):
            v = min(r.v_target, step_v * k)  # 목표를 넘지 않게 클램프
            self.set_voltage(r.ch, v)
            time.sleep(settle_s)
            if self.tripped(r.ch):
                raise TripError(f"{self.name} ch{r.ch}({name}) protection tripped "
                                f"during ramp-up @ {v:.2f}V")

    def ramp_rail_down(self, name: str, *, step_v: float, settle_s: float) -> None:
        """한 레일을 현재 전압에서 0V 까지 step_v 간격으로 천천히 내리고 출력 OFF."""
        r = self.rails[name]
        v = self._set_v.get(r.ch, r.v_target)  # 현재 설정 전압에서 시작
        while v > 0:
            v = max(0.0, v - step_v)
            self.set_voltage(r.ch, v)
            time.sleep(settle_s)
        self.output(False, [r.ch])  # 0V 도달 후 출력 끔

    # -- fake 모드 응답 -------------------------------------------------
    def _fake_query(self, cmd: str) -> str:
        """가짜 모드 전용: 하드웨어 없이도 그럴듯한 응답을 만들어 dry-run 가능하게 함."""
        c = cmd.strip().upper()
        # 트립/상태 조회 → 항상 정상(0)
        if "OUTP:PROT:TRIP" in c or "STAT:QUES" in c:
            n = len(self._chanlist(cmd))
            return ",".join(["0"] * max(1, n))
        # 전압 측정 → 마지막으로 설정한 전압을 그대로 돌려줌
        if c.startswith("MEAS:VOLT"):
            chans = self._chanlist(cmd) or sorted(self._by_ch)
            return ",".join(f"{self._set_v.get(c, 0.0):.4f}" for c in chans)
        # 전류 측정 → 전압이 인가됐으면 소량의 가짜 전류, 0V 면 0
        if c.startswith("MEAS:CURR"):
            chans = self._chanlist(cmd) or sorted(self._by_ch)
            return ",".join(f"{0.05 if self._set_v.get(c, 0.0) > 0 else 0.0:.4f}"
                            for c in chans)
        # OVP 범위 질의 → MIN 0, MAX 32 (clamp 가 요청값을 그대로 통과시키게)
        if c.startswith("VOLT:PROT?"):
            return "0" if "MIN" in c else "32"
        return super()._fake_query(cmd)

    @staticmethod
    def _chanlist(cmd: str) -> list[int]:
        """명령 문자열에서 채널 리스트를 파싱한다. '(@1,2,3)'/'(@1:3)' → [1,2,3]."""
        if "(@" not in cmd:
            return []
        inside = cmd.split("(@", 1)[1].split(")", 1)[0]  # @ 와 ) 사이만 추출
        chans: list[int] = []
        for part in inside.split(","):
            part = part.strip()
            if ":" in part:                  # "1:3" 같은 범위 표기 처리
                a, b = part.split(":")
                chans.extend(range(int(a), int(b) + 1))
            elif part:
                chans.append(int(part))
        return chans
