# -*- coding: utf-8 -*-
"""
R&S 자동화 (Marker 읽기 전용):
- SG(SMW200A) 파워 스윕
- FSVA3030: 설정은 전혀 건드리지 않고, 화면의 마커 값만 읽음 (CALC1:MARK1:Y?)
- PSU(NGP800) 3채널 V/I 로깅
- CSV 저장: [timestamp, sg_power_dbm, marker_y, psu_ch*_V/I...]

세팅 포인트:
- USE_TRIGGER_ON_FETCH=False 면 '진짜 화면값'만 읽음(설정 무변경).
- 최신 프레임을 원하면 True로 바꾸면 ABOR;INIT:IMM 1회만 수행(*OPC? 폴링) — 설정은 그대로.
- SG 파워 변경 후 EXTRA_WAIT_AFTER_SG_S=2.0초 대기(값 안정화).
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
LINK_MODE = "SOCKET"   # "SOCKET" 또는 "INSTR"

# 스윕 파라미터
POWER_START_DBM = -70
POWER_STOP_DBM  = -20
POWER_STEP_DBM  = 1
SETTLE_TIME_S   = 0.20          # RF 체인 짧은 안정화
EXTRA_WAIT_AFTER_SG_S = 3     # ✅ SG 파워 변경 후 추가 대기(화면/계산 안정화)
CSV_PATH        = "marker_sweep_log.csv"

# FSVA 읽기 옵션
USE_TRIGGER_ON_FETCH = False     # True면 ABOR; INIT:IMM으로 최신 프레임 트리거(설정은 유지)
TRIGGER_MAX_WAIT_S   = 30
TRIGGER_POLL_S       = 0.2
TRIGGER_QUERY_TO_MS  = 500

# 읽을 마커 SCPI (세진님 환경 기준)
MARKER_QUERY = "CALC1:MARK1:Y?"

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

def wait_opc_poll(dev: VisaDevice, cmd: str,
                  max_wait_s: float, poll_s: float, query_timeout_ms: int):
    """설정 변경 없이 단발 측정만 수행할 때 사용(ABOR; INIT:IMM 등)"""
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
                raise TimeoutError(f"*OPC? polling timeout after {max_wait_s}s for {cmd!r}")
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
    ⚠️ 읽기 전용 래퍼:
    - FSVA 설정(ACP/CHP/마커/유닛/대역폭 등)은 사용자가 이미 맞춰둔 상태 그대로
    - 필요 시 최신 프레임만 트리거 (USE_TRIGGER_ON_FETCH=True)
    """
    def __init__(self, dev: VisaDevice): self.d = dev
    def trigger_once_if_enabled(self):
        if USE_TRIGGER_ON_FETCH:
            self.d.write("ABOR")
            wait_opc_poll(self.d, "INIT:IMM",
                          max_wait_s=TRIGGER_MAX_WAIT_S,
                          poll_s=TRIGGER_POLL_S,
                          query_timeout_ms=TRIGGER_QUERY_TO_MS)
    def read_marker_y(self) -> float:
        resp = self.d.query(MARKER_QUERY)  # 예: "CALC1:MARK1:Y?"
        return parse_first_float(resp)
    def auto_level_adjust(self):
        wait_opc_poll(self.d, "SENS:ADJ:LEV",
                      max_wait_s=TRIGGER_MAX_WAIT_S,
                      poll_s=TRIGGER_POLL_S,
                      query_timeout_ms=TRIGGER_QUERY_TO_MS)

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

        smw_dev.rf_on(True)

        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            header = [
                "timestamp",
                "sg_power_dbm",
                "marker_y",           # 화면의 마커 Y 값 (단위/스케일은 FSVA 설정에 따름)
                "psu_ch1_V", "psu_ch1_I",
                "psu_ch2_V", "psu_ch2_I",
                "psu_ch3_V", "psu_ch3_I",
            ]
            writer.writerow(header)
            
            smw_dev.set_power_dbm(POWER_START_DBM)
            
            step_idx = 0
            for p_dbm in frange_inclusive(POWER_START_DBM, POWER_STOP_DBM, POWER_STEP_DBM):
                step_idx += 1
                print(f"\n[STEP {step_idx}] Set SG power = {p_dbm} dBm")

                # 1) SG 파워 설정 + 안정화 + 추가 대기(화면 업데이트/계산 완료 대기)
                smw_dev.set_power_dbm(p_dbm)
                time.sleep(SETTLE_TIME_S)
                time.sleep(EXTRA_WAIT_AFTER_SG_S)  # ✅ 핵심: 충분히 기다렸다가 읽음
                                
                # 2) (옵션) 최신 프레임 확보 — 설정은 변경하지 않음
                fsva_dev.trigger_once_if_enabled()

                # 3) 마커 값 읽기
                marker_y = fsva_dev.read_marker_y()

                # 4) PSU 1~3 채널 V/I
                vi: List[float] = []
                for ch in PSU_CHANNELS:
                    v, i = ngp_dev.read_voltage_current(ch)
                    vi.extend([v, i*1000])
                
                #fsva_dev.auto_level_adjust()
                #print("[FSVA] Auto Level ...")
                
                # 5) CSV 기록
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([ts, p_dbm, marker_y] + vi)
                f.flush()

                # 6) 콘솔 출력
                print(f"  Marker Y = {marker_y}")
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
