# -*- coding: utf-8 -*-
"""
R&S 자동화 (ACP 읽기 전용: 화면 값 그대로 Fetch)
- SG 파워 스윕
- FSVA는 '설정 변경 없음' (측정/표시된 값만 읽음)
- 저장 항목: Channel Power(dBm), Lower/Upper ACP(dBc)
- PSU 3채널 V/I 로깅
"""

import time
import csv
import re
from typing import Tuple, Optional, List

# =========================
# 사용자 설정
# =========================
SMW_IP   = "192.168.10.2"
FSVA_IP  = "192.168.10.3"
NGP_IP   = "192.168.10.4"
PORT     = 5025
LINK_MODE = "SOCKET"

# 스윕 파라미터
POWER_START_DBM = -70
POWER_STOP_DBM  = -20
POWER_STEP_DBM  = 1
SETTLE_TIME_S   = 2                 # SG 레벨 변경 후 안정화
CSV_PATH        = "acp_sweep_log.csv"

# ⚠️ FSVA 측정 트리거 사용 여부 (기본: False)
# - False: 정말 '화면에 있는 값'만 읽음 (FSVA 설정/상태 절대 변경 X)
# - True : 현재 설정은 유지하되, ABOR; INIT:IMM 한번 돌려 '최신 프레임'을 확보
USE_TRIGGER_ON_FETCH = True

# PSU 채널
PSU_CHANNELS = [1, 2, 3]

# =========================
# 유틸
# =========================
def build_resource(ip: str, port: int, mode: str) -> str:
    mode = mode.upper().strip()
    if mode == "SOCKET":
        return f"TCPIP::{ip}::{port}::SOCKET"
    elif mode == "INSTR":
        return f"TCPIP0::{ip}::inst0::INSTR"
    else:
        raise ValueError("LINK_MODE must be 'SOCKET' or 'INSTR'")

def parse_first_float(s: str) -> float:
    m = re.search(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", s.strip())
    if not m:
        raise ValueError(f"Float not found in response: {s!r}")
    return float(m.group(0))

def parse_all_floats(s: str) -> List[float]:
    return [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", s)]

def frange_inclusive(start: float, stop: float, step: float):
    x = start
    if step == 0:
        yield x; return
    if step > 0:
        while x <= stop + 1e-12:
            yield round(x, 10); x += step
    else:
        while x >= stop - 1e-12:
            yield round(x, 10); x += step

# =========================
# VISA 래퍼
# =========================
try:
    import pyvisa
    from pyvisa import constants
except Exception as e:
    raise SystemExit(
        "pyvisa가 설치되어 있지 않습니다. 설치:\n"
        "  pip install pyvisa pyvisa-py\n"
        f"(원인: {e})"
    )

class VisaDevice:
    def __init__(self, resource: str, timeout_ms: int = 5000):
        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(resource)
        self.inst.timeout = timeout_ms
        self.inst.write_termination = "\n"
        self.inst.read_termination  = "\n"
    def write(self, cmd: str):  return self.inst.write(cmd)
    def query(self, cmd: str) -> str:  return self.inst.query(cmd)
    def read(self) -> str:  return self.inst.read()
    def close(self):
        try: self.inst.close()
        finally:
            try: self.rm.close()
            except Exception: pass
    def idn(self) -> str:
        try: return self.query("*IDN?")
        except Exception: return "Unknown"

# (선택) 트리거 폴링 유틸 — 설정은 건드리지 않지만, 단발 측정만 수행
def wait_opc_poll(dev: VisaDevice, cmd: str,
                  max_wait_s: float = 30, poll_s: float = 0.2, query_timeout_ms: int = 500):
    dev.write(cmd)
    old_to = dev.inst.timeout
    dev.inst.timeout = query_timeout_ms
    t0 = time.time()
    try:
        while True:
            try:
                if dev.query("*OPC?").strip().startswith("1"):
                    return
            except pyvisa.errors.VisaIOError as e:
                if e.error_code != constants.StatusCode.error_timeout:
                    raise
            if time.time() - t0 > max_wait_s:
                raise TimeoutError(f"Timeout waiting for *OPC? after {cmd!r}")
            time.sleep(poll_s)
    finally:
        dev.inst.timeout = old_to

# =========================
# 장비별 래퍼
# =========================
class SMW200A:
    def __init__(self, dev: VisaDevice): self.d = dev
    def set_power_dbm(self, p_dbm: float):
        self.d.write(f"SOUR:POW:LEV:IMM:AMPL {p_dbm} dBm")
    def rf_on(self, on: bool = True):
        self.d.write(f"OUTP {'ON' if on else 'OFF'}")

class FSVA3030:
    """
    ⚠️ 이 래퍼는 '읽기 전용'으로 동작.
    - 네가 이미 맞춰둔 ACP/CHP/마커/유닛을 그대로 사용
    - 필요 시 최신 프레임을 원하면 USE_TRIGGER_ON_FETCH=True로 바꿔 ABOR;INIT:IMM 실행
      (설정 자체는 건드리지 않음)
    """
    def __init__(self, dev: VisaDevice): self.d = dev

    def trigger_once_if_enabled(self):
        if USE_TRIGGER_ON_FETCH:
            # 설정 변경 없이, 현재 설정으로 단발 측정만 수행
            self.d.write("ABOR")
            wait_opc_poll(self.d, "INIT:IMM", max_wait_s=30, poll_s=0.2, query_timeout_ms=500)

    def read_channel_power_dbm(self) -> float:
        # 화면에 표시중인 채널 파워(dBm)
        resp = self.d.query("CALC:MARK:FUNC:POW:RES? CPOW")
        return parse_first_float(resp)
      
        
    def read_acp_relative_db(self) -> Tuple[float, float]:
    #상대 ACP(dBc)만 읽어 반환.
    #CALC:MARK:FUNC:POW:RES? ACP  →  "<channel_power_dBm>,<lower_rel_dBc>,<upper_rel_dBc>"
    #- 기본: 위 명령의 '마지막 두 값'을 사용 (lower, upper)
    #- 응답이 비거나 3개 미만일 때: 0.1s 후 1회 재시도
    #- 그래도 부족하면 REL?로 폴백
        # 1) 주 경로: 마커 함수 결과에서 마지막 두 값을 사용
        last_resp = ""
        for attempt in (1, 2):
            last_resp = self.d.query("CALC:MARK:FUNC:POW:RES? ACP")
            nums = parse_all_floats(last_resp)
            if len(nums) >= 3:
                # 순서: [channel_power_dBm, lower_rel_dBc, upper_rel_dBc]
                lower_rel_dbc = nums[-2]
                upper_rel_dbc = nums[-1]
                return lower_rel_dbc, upper_rel_dbc
            time.sleep(0.1)  # 짧은 재시도 대기

        # 2) 폴백: REL? 응답에서 앞의 두 개 사용 (Lower, Upper)
        try:
            resp_rel = self.d.query("CALC:LIM:ACP:ACH:RES:REL?")
            nums_rel = parse_all_floats(resp_rel)
            if len(nums_rel) >= 2:
                return nums_rel[0], nums_rel[1]
        except Exception:
            pass

        # 3) 최종 실패
        raise RuntimeError(f"ACP 상대(dBc) 파싱 실패: RESP={last_resp!r}")    

class NGP800:
    def __init__(self, dev: VisaDevice): self.d = dev
    def read_voltage_current(self, ch: int) -> Tuple[float, float]:
        v_queries = [f"MEAS:VOLT? (@{ch})", f"MEAS:VOLT? CH{ch}",
                     f"MEAS:SCAL:VOLT:DC? (@{ch})", f"MEAS:VOLT:DC? (@{ch})"]
        i_queries = [f"MEAS:CURR? (@{ch})", f"MEAS:CURR? CH{ch}",
                     f"MEAS:SCAL:CURR:DC? (@{ch})", f"MEAS:CURR:DC? (@{ch})"]
        v_val = i_val = None; last_v_err = last_i_err = ""
        for q in v_queries:
            try: v_val = parse_first_float(self.d.query(q)); break
            except Exception as e: last_v_err = f"{q} -> {e}"
        for q in i_queries:
            try: i_val = parse_first_float(self.d.query(q)); break
            except Exception as e: last_i_err = f"{q} -> {e}"
        if v_val is None or i_val is None:
            raise RuntimeError(
                f"NGP800 V/I 읽기 실패 (채널 {ch}).\n"
                f"Voltage 마지막 에러: {last_v_err}\nCurrent 마지막 에러: {last_i_err}"
            )
        return (v_val, i_val)

# =========================
# 메인
# =========================
def main():
    smw_res  = build_resource(SMW_IP,  PORT, LINK_MODE)
    fsva_res = build_resource(FSVA_IP, PORT, LINK_MODE)
    ngp_res  = build_resource(NGP_IP,  PORT, LINK_MODE)

    smw = fsva = ngp = None
    try:
        smw = VisaDevice(smw_res, timeout_ms=10000)
        fsva = VisaDevice(fsva_res, timeout_ms=10000)
        ngp  = VisaDevice(ngp_res,  timeout_ms=5000)

        print("[SMW] *IDN? ->", smw.idn())
        print("[FSVA]*IDN? ->", fsva.idn())
        print("[NGP ]*IDN? ->", ngp.idn())

        smw_dev  = SMW200A(smw)
        fsva_dev = FSVA3030(fsva)
        ngp_dev  = NGP800(ngp)

        # SG RF ON (필요 시 끄고/켜기)
        smw_dev.rf_on(True)

        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            header = [
                "timestamp",
                "sg_power_dbm",
                "channel_power_dbm",   # CPOW (dBm)
                "acp_lower_dbc",       # Lower ACP (dBc, 상대)
                "acp_upper_dbc",       # Upper ACP (dBc, 상대)
                "psu_ch1_V", "psu_ch1_I",
                "psu_ch2_V", "psu_ch2_I",
                "psu_ch3_V", "psu_ch3_I",
            ]
            writer.writerow(header)

            step_idx = 0
            for p_dbm in frange_inclusive(POWER_START_DBM, POWER_STOP_DBM, POWER_STEP_DBM):
                step_idx += 1
                print(f"\n[STEP {step_idx}] Set SG power = {p_dbm} dBm")

                # 1) SG 설정 + 안정화
                smw_dev.set_power_dbm(p_dbm)
                time.sleep(SETTLE_TIME_S)

                # 2) (옵션) 최신 프레임 확보 — 설정은 바꾸지 않고 단발 측정만
                fsva_dev.trigger_once_if_enabled()

                # 3) 화면에 표시된 ACP/CHP 값 읽기
                ch_pow_dbm = fsva_dev.read_channel_power_dbm()
                acp_lower_dbc, acp_upper_dbc = fsva_dev.read_acp_relative_db()

                # 4) PSU 1~3채널 V/I
                vi: List[float] = []
                for ch in PSU_CHANNELS:
                    v, i = ngp_dev.read_voltage_current(ch)
                    vi.extend([v, i*1000])

                # 5) CSV 기록
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([ts, p_dbm, ch_pow_dbm, acp_lower_dbc, acp_upper_dbc] + vi)
                f.flush()

                # 6) 콘솔 출력
                print(f"  Channel Power (dBm) = {ch_pow_dbm}")
                print(f"  ACP Lower/Upper (dBc) = {acp_lower_dbc} / {acp_upper_dbc}")
                print(f"  PSU Ch1(V,I)={vi[0:2]}  Ch2={vi[2:4]}  Ch3={vi[4:6]}")

        print(f"\n완료! CSV 저장: {CSV_PATH}")

    except KeyboardInterrupt:
        print("\n사용자 중단")
    except Exception as e:
        print("\n에러 발생:", e)
    finally:
        try:
            if smw: smw.close()
        except Exception: pass
        try:
            if fsva: fsva.close()
        except Exception: pass
        try:
            if ngp: ngp.close()
        except Exception: pass

if __name__ == "__main__":
    main()
