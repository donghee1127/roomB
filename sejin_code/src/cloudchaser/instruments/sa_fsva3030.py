"""Rohde & Schwarz FSVA3030 스펙트럼 분석기(SA) 드라이버.

CloudChaser TX 출력을 측정할 때 쓰는 장비다. 1차 마일스톤에서는 '측정 직전'
상태(center/span/RBW/ref-level/입력감쇠)만 설정한다. 실제 sweep/marker 읽기는
다음(측정) 단계에서 한다.

FSVA 특이점: 다른 measurement application(IQ Analyzer 등) 상태에 있으면
SENS:FREQ:SPAN 같은 명령을 -200 "function not available" 로 거부한다. 그래서
설정 전에 스펙트럼 분석 모드(INST:SEL SAN)로 먼저 진입시킨다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import math
import re

from .scpi import ScpiError, ScpiSocket


class FSVA3030(ScpiSocket):
    """FSVA3030 한 대를 제어하는 드라이버."""

    def __init__(self, host: str, *, port: int = 5025, fake: bool = False,
                 name: str | None = None) -> None:
        super().__init__(host, port, fake=fake, name=name or "FSVA3030")

    def set_center(self, hz: float) -> None:
        """중심 주파수[Hz] 설정."""
        self.write(f"SENS:FREQ:CENT {hz:.0f}")

    def set_span(self, hz: float) -> None:
        """주파수 span[Hz] 설정."""
        self.write(f"SENS:FREQ:SPAN {hz:.0f}")

    def set_rbw(self, hz: float) -> None:
        """분해능 대역폭 RBW[Hz] 설정."""
        self.write(f"SENS:BAND:RES {hz:.0f}")

    def set_ref_level(self, dbm: float) -> None:
        """기준 레벨(reference level)[dBm] 설정."""
        self.write(f"DISP:WIND:TRAC:Y:SCAL:RLEV {dbm:.2f}")

    def set_ref_level_offset(self, db: float) -> None:
        """기준 레벨 오프셋[dB](DISP:...:RLEV:OFFS) — 출력 경로 손실 보상용.

        모든 레벨 읽기에 db 가 더해진다. db = out_loss 로 두면 마커/피크/채널전력
        읽기가 '실제측정 + out_loss = DUT(칩 빔포트) 출력 전력' 이 된다.
        """
        self.write(f"DISP:WIND:TRAC:Y:SCAL:RLEV:OFFS {db:.2f}")

    def set_input_atten(self, db: float) -> None:
        """입력 감쇠[dB] 설정."""
        self.write(f"INP:ATT {db:.0f}")

    def _switch_app(self, sel: str, expect: str, *, log=None,
                    max_wait_s: float = 30.0, tries: int = 3) -> bool:
        """measurement application 전환(INST:SEL) 하나로 통일한 안전 경로.

        예전에는 전환마다 이렇게 했는데, 스펙트럼<->NR5G 를 오갈 때 자주 깨졌다:
          write_try("INST:SEL ...")  -> wait_opc()  -> resync()
        문제 세 가지를 여기서 한꺼번에 없앤다.

        1) ``write_try`` 는 write 직후 SYST:ERR? 를 곧장 질의한다. 앱 전환은 오래
           걸리는 overlapped 동작이라 계측기가 바쁘면 응답을 못 주고, 그때 나는
           OSError 를 write_try 가 잡지 않아 **측정 전체가 죽었다**. (같은 함정을
           _auto_adjust 는 이미 피하고 있었는데 INST:SEL 에는 적용이 안 돼 있었다.)
           -> 여기서는 맨 write 로 보내고, 에러 큐는 전환이 끝난 뒤에 읽는다.
        2) ``wait_opc`` 는 단발 *OPC? 라 self.timeout(기본 5s)을 넘기면 OSError 다.
           그걸 삼키고 진행하면 앱이 아직 로딩 중인데 측정을 시작하게 되고, 뒤늦게
           도착한 '1' 이 **다음 query 의 응답으로 밀려** off-by-one desync 가 났다.
           -> wait_opc_poll 로 짧은 소켓 timeout 을 걸고 폴링한다(자기 응답을 스스로
              정리하므로 늦게 오는 '1' 이 남지 않는다).
        3) 전환이 실제로 됐는지 아무도 확인하지 않아, 실패가 조용히 지나가고 나중에
           'function not available' 이나 EVM fetch 실패로 터졌다.
           -> INST:SEL? 로 확인하고, 아니면 재시도한다.

        확인이 관대한 이유: FSVA 의 INST:SEL? 응답 문자열을 벤더 매뉴얼로 확정하지
        못했다(추정: 'SAN' / 'NR5G'). 그래서 부분일치/대소문자 무시로 보고, 응답이
        예상 밖이면 **경고만 남기고 진행**한다 -- 추정이 틀려도 예전 동작보다
        나빠지지 않고, 맞으면 실패를 잡는다. 실기에서 응답이 확인되면 엄격하게 바꾼다.

        반환: 전환이 확인됐으면 True(확인 불가/실패는 False, 예외는 던지지 않음).
        """
        want = expect.strip().upper().strip("'\"")
        for attempt in range(1, max(1, tries) + 1):
            self.write(f"INST:SEL {sel}")          # ★ 여기서 SYST:ERR? 를 읽지 않는다
            self.wait_opc_poll(max_wait_s=max_wait_s)
            self.resync()
            try:
                got = self.query("INST:SEL?").strip().upper().strip("'\"")
            except OSError as e:
                if log is not None:
                    log(f"[warn  ] {self.name} INST:SEL? did not answer after "
                        f"switching to {want} ({e}) -- continuing")
                self.resync()
                return False
            if want in got or got in want:
                if attempt > 1 and log is not None:
                    log(f"[sa    ] {self.name} switched to {want} "
                        f"on attempt {attempt}")
                break
            if attempt >= tries:
                if log is not None:
                    log(f"[warn  ] {self.name} still reports '{got}' after "
                        f"{tries} attempts to select {want} -- continuing anyway "
                        f"(measurements in the wrong app usually fail next)")
                return False
            if log is not None:
                log(f"[warn  ] {self.name} reports '{got}', expected {want} "
                    f"-- retrying app switch ({attempt}/{tries})")
        # 전환이 끝난 뒤에 에러 큐를 비운다(전환 중 쌓인 -200 등을 다음 명령이
        # 자기 에러로 오해하지 않게).
        for e in self.drain_errors():
            if log is not None:
                log(f"[warn  ] {self.name} error queued during app switch "
                    f"(ignored): {e}")
        return True

    def enter_spectrum_mode(self, log=None) -> bool:
        """스펙트럼 분석 모드(SAN)로 전환한다.

        FSVA 가 다른 measurement application 상태면 SPAN/RBW 등이 'function not
        available' 로 막힌다. 전환 절차와 그 이유는 _switch_app 참조.
        """
        return self._switch_app("SAN", "SAN", log=log)

    def configure(self, *, center_hz: float, span_hz: float, rbw_hz: float,
                  ref_level_dbm: float, input_atten_db: float,
                  spectrum_mode: bool = True, log=None) -> bool:
        """측정 직전 설정. 명령별로 견디며 진행(거부돼도 경고만), 전체 성공 여부 반환.

        spectrum_mode=True 면 설정 전에 스펙트럼 모드로 먼저 진입시킨다.
        """
        if spectrum_mode:
            self.enter_spectrum_mode(log)
        ok = True
        ok &= self.write_try(f"SENS:FREQ:CENT {center_hz:.0f}", log)
        ok &= self.write_try(f"SENS:FREQ:SPAN {span_hz:.0f}", log)
        ok &= self.write_try(f"SENS:BAND:RES {rbw_hz:.0f}", log)
        ok &= self.write_try(f"DISP:WIND:TRAC:Y:SCAL:RLEV {ref_level_dbm:.2f}", log)
        ok &= self.write_try(f"INP:ATT {input_atten_db:.0f}", log)
        return ok

    # -- 측정(단일 sweep + 피크 마커) -----------------------------------
    def measure_peak_dbm(self, *, max_wait_s: float = 30.0) -> float:
        """단일 sweep 를 1회 실행하고, 마커 피크 전력[dBm]을 읽어 반환한다.

        CW 톤 측정에 사용: 보드 출력의 가장 큰 신호(=인가한 CW)를 마커로 잡는다.
        절차: 진행 중 sweep 중단(ABOR) → 연속 sweep 끄기 → 1회 sweep 실행 →
        *OPC? 폴링으로 완료 대기 → 마커 ON → 피크 탐색 → Y값 읽기.

        완료 대기는 ``*WAI`` 블로킹 대신 ``wait_opc_poll`` 을 쓴다 — narrow RBW +
        wide span 으로 1회 sweep 이 소켓 timeout(기본 5s)을 넘겨도 측정이 죽지
        않게 한다(reference Summit2629 패턴). max_wait_s 는 1회 sweep 최대 허용시간.
        """
        self.write("ABOR")                 # 진행 중이던 sweep 을 깨끗이 중단
        self.write("INIT:CONT OFF")        # 연속 sweep 끄고 단일 sweep 모드로
        self.write("INIT:IMM")             # sweep 1회 실행(논블로킹)
        self.wait_opc_poll(max_wait_s=max_wait_s)  # 완료까지 폴링 대기(timeout 안전)
        self.write("CALC:MARK1:STAT ON")   # 마커1 켜기
        self.write("CALC:MARK1:MAX")       # 트레이스 최댓값으로 마커 이동
        return self.query_float("CALC:MARK1:Y?")  # 마커 Y(전력) 읽기

    # -- 5G NR 변조분석(EVM) --------------------------------------------
    def select_nr5g(self, log=None) -> bool:
        """5G NR 측정 채널로 '전환만' 한다(설정은 그대로 둠).

        FSVA 가 spectrum(SAN) 등 다른 application 에 있으면 EVM fetch 가 막힌다.
        CW 테스트(ip1db/gain) 직후엔 SA 가 SAN 모드라, manual EVM 측정 전에 이 함수로
        NR 앱만 선택하면 사용자가 손으로 만든 NR 설정이 복원돼 측정이 된다(재설정 X).
        """
        return self._switch_app("'NR5G'", "NR5G", log=log)

    def setup_nr5g_analyzer(self, *, center_hz: float, bw_mhz: int = 100,
                            log=None) -> bool:
        """FSVA 를 5G NR 변조분석 모드로 설정한다(K144 옵션 필요, EVM 측정용).

        ★주의: R&S NR5G 분석 SCPI 는 펌웨어/옵션에 따라 다를 수 있다. GUI 에서 NR
          측정 설정 후 SCPI Recorder 로 정확한 시퀀스를 뽑아 검증/교체 권장.
        """
        self.select_nr5g(log)   # NR 앱 선택(+ OPC 대기 + resync)
        ok = True
        ok &= self.write_try(f"SENS:FREQ:CENT {center_hz:.0f}", log)
        ok &= self.write_try(f"CONF:NR5G:DL:CC1:BW BW{int(bw_mhz)}", log)
        ok &= self.write_try("CONF:NR5G:MEAS EVM", log)
        return ok

    def _auto_adjust(self, cmd: str, what: str, log=None,
                     max_wait_s: float = 30.0) -> None:
        """Auto 조정(EVM/Level) 공통: 긴 동작이라 폴링 대기, 실패해도 경고만.

        ``SENS:ADJ:*`` 는 시간이 오래 걸리는 overlapped 명령이라, 직후 SYST:ERR?
        를 곧장 읽으면(write_try) 계측기가 바빠 응답을 못 줘 socket timeout 으로
        전체 측정이 죽는다. write 로 보낸 뒤 wait_opc_poll 로 완료를 폴링하고,
        타임아웃/거부가 나도 resync 후 경고만 남기고 진행한다(best-effort).
        """
        try:
            self.write(cmd)
            self.wait_opc_poll(max_wait_s=max_wait_s)
        except (OSError, ScpiError) as e:
            self.resync()
            if log is not None:
                log(f"[warn  ] {self.name} auto-{what} skipped -> "
                    f"{type(e).__name__}: {e}")

    def auto_evm(self, log=None) -> None:
        """Auto EVM(레벨/동기 자동 최적화). 시간이 걸리므로 폴링 대기."""
        self._auto_adjust("SENS:ADJ:EVM", "EVM", log)

    def auto_level(self, log=None) -> None:
        """Auto Level(입력 레벨 자동)."""
        self._auto_adjust("SENS:ADJ:LEV", "Level", log)

    def measure_once(self, *, max_wait_s: float = 30.0) -> None:
        """현재 설정으로 단발 측정 1회(완료 대기). fetch 전에 호출.

        블로킹 ``*WAI`` 대신 wait_opc_poll 로 폴링 — NR 프레임 측정이 소켓
        timeout(기본 5s)을 넘겨도 죽지 않게 한다(measure_peak_dbm 과 같은 패턴).
        """
        self.write("ABOR")
        self.write("INIT:CONT OFF")
        self.write("INIT:IMM")
        self.wait_opc_poll(max_wait_s=max_wait_s)

    def read_evm_db(self) -> float:
        """프레임 요약 EVM[dB] 읽기('EVM All' 평균, component carrier 1). 미동기면 nan.

        FSVA 가 EVM 을 %로 주면(>0) dB 로 변환하고, 이미 dB(<=0)면 그대로 쓴다 —
        UNIT:EVM 설정과 무관하게 항상 일관된 dB 값을 돌려준다.
        (EVM:DSSF 등 변조별 하위결과는 해당 변조가 없으면 NaN/상수라 :ALL 을 쓴다.)
        """
        v = self.query_float_or_nan("FETC:CC1:ISRC:FRAM:SUMM:EVM:ALL:AVER?")
        if math.isnan(v) or v <= 0.0:
            return v
        return 20.0 * math.log10(v / 100.0)

    def read_nr_power_dbm(self) -> float:
        """프레임 요약 총 전력[dBm] 읽기. 락 미동기면 nan."""
        return self.query_float_or_nan("FETC:CC1:ISRC:FRAM:SUMM:POW:AVER?")

    # -- 인접채널전력(ACP) ----------------------------------------------
    def setup_acp(self, *, center_hz: float, chan_bw_hz: float = 99.0e6,
                  spacing_hz: float = 100.0e6, n_adj: int = 1, log=None) -> bool:
        """스펙트럼 모드에서 ACP 측정을 설정한다(채널BW/인접채널 간격/쌍 수)."""
        self.enter_spectrum_mode(log)
        ok = True
        ok &= self.write_try(f"SENS:FREQ:CENT {center_hz:.0f}", log)
        ok &= self.write_try("CALC:MARK:FUNC:POW:SEL ACP", log)
        ok &= self.write_try(f"POW:ACH:ACP {int(n_adj)}", log)
        ok &= self.write_try(f"POW:ACH:BWID:CHAN1 {chan_bw_hz:.0f}", log)
        ok &= self.write_try(f"POW:ACH:SPAC {spacing_hz:.0f}", log)
        return ok

    def read_channel_power_dbm(self) -> float:
        """현재 ACP 측정의 채널 전력[dBm] 읽기."""
        return self.query_float("CALC:MARK:FUNC:POW:RES? CPOW")

    def read_acp_dbc(self) -> tuple[float, float]:
        """상대 ACP[dBc] (lower, upper) 읽기.

        응답 형식: <channel_power>,<lower_rel>,<upper_rel> → 마지막 두 값 사용.
        """
        resp = self.query("CALC:MARK:FUNC:POW:RES? ACP")
        nums = [float(x) for x in re.findall(
            r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", resp)]
        if len(nums) >= 3:
            return nums[-2], nums[-1]
        raise ValueError(f"cannot parse ACP from: {resp!r}")

    def write(self, cmd: str) -> None:
        """fake 모드에서 현재 application 을 추적하기 위해 write 를 가로챈다.

        실기에서는 부모 구현 그대로다(추적만 추가). 이게 있어야 _switch_app 의
        확인 경로를 하드웨어 없이 테스트할 수 있다.
        """
        c = cmd.strip().upper()
        if c.startswith("INST:SEL") and "?" not in c:
            self._fake_app = c.split(None, 1)[1].strip().strip("'\"") if " " in c else ""
        super().write(cmd)

    def _fake_query(self, cmd: str) -> str:
        """가짜 모드 응답(하드웨어 없이 dry-run 용)."""
        c = cmd.strip().upper()
        if c.startswith("INST:SEL?") or c.startswith("INST?"):
            return getattr(self, "_fake_app", "SAN")
        if "CENT" in c:
            return "28000000000"
        if "SPAN" in c:
            return "100000000"
        if "EVM" in c:
            return "-32.5"                    # 가짜 EVM[dB]
        if "FRAM:SUMM:POW" in c:
            return "-10.0"                    # 가짜 NR 총전력
        if "POW:RES? ACP" in c:
            return "-10.0,-33.2,-34.1"        # ch_pwr, lower, upper
        if "POW:RES? CPOW" in c:
            return "-10.0"
        if "MARK" in c and ("Y?" in c or ":Y" in c):
            return "-10.0"   # 가짜 피크 전력(dry-run 에서 테스트가 끝까지 돌게)
        return super()._fake_query(cmd)
