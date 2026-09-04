"""Rohde & Schwarz SMW200A 신호발생기(SG) 드라이버.

CloudChaser TX 측정에서 보드에 인가할 RF 신호를 만드는 장비다.
1차 마일스톤에서는 '측정 직전'까지만 준비하므로, 주파수/전력만 설정하고
**RF 출력은 OFF** 로 둔다. 실제 RF 인가는 다음(측정) 단계에서 켠다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

from .scpi import ScpiSocket


class SMW200A(ScpiSocket):
    """SMW200A 한 대를 제어하는 드라이버."""

    def __init__(self, host: str, *, port: int = 5025, fake: bool = False,
                 name: str | None = None) -> None:
        super().__init__(host, port, fake=fake, name=name or "SMW200A")

    def set_frequency(self, hz: float) -> None:
        """출력 주파수[Hz] 설정."""
        self.write(f"SOUR:FREQ {hz:.0f}")

    def set_level(self, dbm: float) -> None:
        """출력 전력 레벨[dBm] 설정."""
        self.write(f"SOUR:POW:LEV:IMM:AMPL {dbm:.2f}")

    def set_level_offset(self, db: float) -> None:
        """레벨 오프셋[dB] 설정(SOUR:POW:OFFS) — 입력 경로 손실 보상용.

        R&S 규약: POW 으로 입력/표시되는 레벨 = '다운스트림 네트워크 출력단(=DUT)'
        의 레벨이고, 실제 RF 출력 = 입력레벨 - 오프셋. 따라서 오프셋을 -(in_loss) 로
        두면 set_level(P) 가 'DUT 입력 P' 를 의미하고 실제 출력은 P + in_loss 로
        부스트되어 케이블/trace 손실을 보상한다(칩에 P 가 실제로 들어감).
        호출 측(Bench.apply_path_loss)이 부호를 정해 넘긴다.
        """
        self.write(f"SOUR:POW:OFFS {db:.2f}")

    def rf_output(self, on: bool) -> None:
        """RF 출력 ON/OFF."""
        self.write(f"OUTP:STAT {'ON' if on else 'OFF'}")

    def configure(self, freq_hz: float, level_dbm: float, rf_output: bool = False,
                  log=None) -> bool:
        """측정 직전 셋업: 주파수/전력 설정 + RF 출력 상태(기본 OFF).

        명령별로 견디며 진행한다(거부돼도 예외 없이 경고만). 전체 성공 여부 반환.
        write_try 가 실패한 명령을 영어 경고로 log 에 남긴다.
        """
        ok = True
        ok &= self.write_try(f"SOUR:FREQ {freq_hz:.0f}", log)
        ok &= self.write_try(f"SOUR:POW:LEV:IMM:AMPL {level_dbm:.2f}", log)
        ok &= self.write_try(f"OUTP:STAT {'ON' if rf_output else 'OFF'}", log)
        return ok

    # -- 변조신호(5G NR / ARB) -----------------------------------------
    def setup_nr5g(self, *, bw_mhz: int = 100, link: str = "DOWN",
                   scs_khz: int = 120, log=None) -> bool:
        """5G NR 변조 baseband 를 생성한다(R&S SMW, K144 옵션 필요).

        위성 Ka 대역과 유사하게 FR2(120kHz SCS), 100MHz 대역폭이 기본.
        ★주의: R&S NR5G SCPI 는 펌웨어/옵션에 따라 키워드가 다를 수 있다. 아래는
          표준 기반이며, SMW GUI 에서 NR 설정 후 'SCPI Recorder' 로 실제 시퀀스를
          뽑아 검증/교체하길 권장. 안 맞으면 측정 쪽에서 modulation='manual' 로
          두고 SMW 를 손으로 설정한 뒤 측정만 해도 된다. (명령별 best-effort)
        """
        ok = True
        ok &= self.write_try("SOUR:BB:NR5G:PRESet", log)
        ok &= self.write_try(f"SOUR:BB:NR5G:LINK {link}", log)
        ok &= self.write_try(f"SOUR:BB:NR5G:NODE:CELL0:CBW BW{int(bw_mhz)}", log)
        ok &= self.write_try(f"SOUR:BB:NR5G:NODE:CELL0:TXBW:SCSP SCS{int(scs_khz)}", log)
        ok &= self.write_try("SOUR:BB:NR5G:STAT ON", log)
        return ok

    def load_waveform(self, path: str, log=None) -> bool:
        """ARB 파형 파일을 불러와 baseband 로 재생한다(미리 만든 waveform 사용)."""
        ok = self.write_try(f"SOUR:BB:ARB:WAV:SEL '{path}'", log)
        ok &= self.write_try("SOUR:BB:ARB:STAT ON", log)
        return ok

    def modulation_off(self, log=None) -> bool:
        """baseband 변조를 끈다(CW 로 복귀)."""
        ok = self.write_try("SOUR:BB:NR5G:STAT OFF", log)
        ok &= self.write_try("SOUR:BB:ARB:STAT OFF", log)
        return ok

    def modulation_on(self, log=None) -> bool:
        """이미 선택된 ARB 파형 baseband 를 다시 켠다(modulation_off 의 짝).

        CW 테스트가 baseband 를 꺼두므로, 그 뒤 manual EVM 측정 전에 이걸로 파형을
        다시 재생한다(파형 파일은 이미 WAV:SEL 로 선택돼 있다고 가정)."""
        return self.write_try("SOUR:BB:ARB:STAT ON", log)

    def _fake_query(self, cmd: str) -> str:
        """가짜 모드 응답(하드웨어 없이 dry-run 용)."""
        c = cmd.strip().upper()
        if c.startswith("SOUR:FREQ"):
            return "28000000000"
        if "POW" in c:
            return "-30.0"
        if c.startswith("OUTP"):
            return "0"
        return super()._fake_query(cmd)
