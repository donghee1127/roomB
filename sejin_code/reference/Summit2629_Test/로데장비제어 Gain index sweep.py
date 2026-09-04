# -*- coding: utf-8 -*-
"""
R&S 자동화 (Marker 읽기 전용, 사용자 제어형 반복):
- SG(SMW200A) 파워 '한 번만' 설정 → 고정 운용
- FSVA3030: 설정은 전혀 건드리지 않고, 화면의 마커 값만 읽음 (CALC1:MARK1:Y?)
- PSU(NGP800) 3채널 V/I 로깅
- 사용자 팝업:
    - '계속 측정'을 누르면 1회 측정 & CSV 기록
    - '측정 종료'를 누르면 종료

CSV 저장: [timestamp, sg_power_dbm_fixed, marker_y, psu_ch1_V, psu_ch1_I_mA, psu_ch2_V, psu_ch2_I_mA, psu_ch3_V, psu_ch3_I_mA]
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

# SG 고정 파워 설정 및 안정화
SG_FIXED_POWER_DBM     = -30.0      # ✅ 시작 시 한 번만 설정하여 이후 고정 사용 (원하면 바꾸세요)
SETTLE_TIME_S          = 0.20       # RF 체인 짧은 안정화
EXTRA_WAIT_AFTER_SG_S  = 3.0        # SG 파워 설정 직후 추가 대기(초) — 시작 시 1회

# CSV 경로
CSV_PATH = "gain_index_sweep_log.csv"

# FSVA 읽기 옵션
USE_TRIGGER_ON_FETCH = False        # True면 ABOR; INIT:IMM으로 최신 프레임 트리거(설정은 유지)
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
# 사용자 팝업/프롬프트
# =========================
def user_wants_continue() -> bool:
    """
    True  → '계속 측정' (다음 1회 측정 진행)
    False → '측정 종료' (루프 탈출)
    - 우선 GUI(Tk) 팝업을 시도, 실패 시 콘솔 프롬프트로 폴백
    """
    # 1) Tkinter 팝업 시도
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()  # 메인 창 숨김
        msg = (
            "Atten/Gain index를 원하는 값으로 변경한 뒤,\n"
            "'예(계속 측정)'을 누르면 다음 측정을 시작합니다.\n\n"
            "계속 측정: 예     /     측정 종료: 아니오"
        )
        res = messagebox.askyesno("측정 진행", msg)
        root.destroy()
        return bool(res)
    except Exception:
        # 2) 콘솔 입력 폴백
        try:
            ans = input("\n계속 측정하려면 [Y] 입력, 종료하려면 [N] 입력 후 엔터: ").strip().lower()
            return ans in ("y", "yes", "")
        except EOFError:
            # 파이프 실행 등으로 입력이 불가하면, 안전하게 종료하지 않고 계속하도록 설정
            return True

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

        # --- SG 파워 '한 번만' 설정 & 안정화 ---
        print(f"\n[SG] Fixed power set to {SG_FIXED_POWER_DBM} dBm")
        smw_dev.rf_on(True)
        smw_dev.set_power_dbm(SG_FIXED_POWER_DBM)
        time.sleep(SETTLE_TIME_S)
        time.sleep(EXTRA_WAIT_AFTER_SG_S)

        # --- CSV 준비 ---
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            header = [
                "timestamp",
                "sg_power_dbm_fixed",
                "marker_y",            # 화면의 마커 Y 값 (단위/스케일은 FSVA 설정에 따름)
                "psu_ch1_V", "psu_ch1_I_mA",
                "psu_ch2_V", "psu_ch2_I_mA",
                "psu_ch3_V", "psu_ch3_I_mA",
            ]
            writer.writerow(header)

            step_idx = 0
            print("\n이제부터 각 스텝은 사용자가 제어합니다.")
            print("팝업(또는 콘솔 안내)에서 '계속 측정'을 선택하면 1회 측정을 수행합니다.")

            # -------- 사용자 제어 루프 --------
            while True:
                # 0) 사용자에게 '계속 측정 / 종료' 선택 받기 (Atten/Gain 변경 시간 제공)
                if not user_wants_continue():
                    print("\n사용자 요청으로 측정을 종료합니다.")
                    break

                step_idx += 1
                print(f"\n[STEP {step_idx}] Measuring at FIXED SG power = {SG_FIXED_POWER_DBM} dBm")

                # 1) (옵션) 최신 프레임 확보 — 설정은 변경하지 않음
                fsva_dev.trigger_once_if_enabled()

                # 2) 마커 값 읽기
                marker_y = fsva_dev.read_marker_y()

                # 3) PSU 1~3 채널 V/I (I를 mA로 저장)
                vi: List[float] = []
                for ch in PSU_CHANNELS:
                    v, i = ngp_dev.read_voltage_current(ch)
                    vi.extend([v, i * 1000.0])  # mA 변환

                # 4) CSV 기록
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([ts, SG_FIXED_POWER_DBM, marker_y] + vi)
                f.flush()

                # 5) 콘솔 출력
                print(f"  Marker Y = {marker_y}")
                print(f"  PSU Ch1(V, I[mA])={vi[0:2]}  Ch2={vi[2:4]}  Ch3={vi[4:6]}")

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
