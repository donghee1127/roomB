# -*- coding: utf-8 -*-
"""
R&S 자동화 (스파이크 방지 + 일관성 검증/재측정 + Auto EVM 1회 기본)
- SG 파워 스윕
- SA Auto EVM (기본: 시작 전 1회), 동기 단발 측정 → EVM(dB)/총전력(dBm) Fetch
- PSU 3채널 V/I 로깅
"""

import time
import csv
import re
import math
from typing import Tuple, Optional, List

# ============== 사용자 설정 ==============
SMW_IP   = "192.168.10.2"
FSVA_IP  = "192.168.10.3"
NGP_IP   = "192.168.10.4"
PORT     = 5025
LINK_MODE = "SOCKET"

# 스윕
POWER_START_DBM = -70
POWER_STOP_DBM  = -20
POWER_STEP_DBM  = 1
SETTLE_TIME_S   = 0.20          # SG 레벨 안정화 대기(조금 늘림)
CSV_PATH        = "evm_sweep_log.csv"

# 주파수/스팬
SG_RF_FREQUENCY_HZ = 28e9
SA_CENTER_HZ       = 28e9
SA_SPAN_HZ         = 10e6
SA_INIT_WAIT_S     = 0.03       # 단발 측정 후 아주 짧은 안정화

# Auto EVM 대기/폴링
AUTO_EVM_MAX_WAIT_S   = 240
AUTO_EVM_POLL_S       = 0.5
AUTO_EVM_QUERY_TO_MS  = 1000
AUTO_EVM_POST_WAIT_S  = 0.10     # Auto EVM 직후 약간 쉬어주기(후처리/리락용)

# 단발 측정 대기/폴링
MEASURE_MAX_WAIT_S    = 30
MEASURE_POLL_S        = 0.2
MEASURE_QUERY_TO_MS   = 500

# EVM SCPI
PREFERRED_EVM_QUERY: Optional[str] = None
EVM_QUERY_CANDIDATES = [
    "FETC:CC1:ISRC:FRAM:SUMM:EVM:DSSF:AVER?"
]

# PSU 채널
PSU_CHANNELS = [1, 2, 3]

# ====== 스파이크 방지 파라미터(현장 튜닝 포인트) ======
# Auto EVM 수행 모드: "once" (시작 전 1회) 또는 "each_step" (매 스텝)
AUTO_EVM_MODE = "once"

# EVM 정상 범위(dB) — 환경에 맞게 좁혀도 됨(예: -60~-10)
EVM_DB_MIN, EVM_DB_MAX = -100.0, -1.0

# 이전 스텝 대비 EVM 허용 점프(dB) — 넘어가면 재측정
EVM_JUMP_MAX_DB = 6.0

# 이전 스텝 대비 SA Total Power 허용 변화량(dB)
# 1 dB 스텝이므로 보수적으로 -0.7 ~ +3.0 정도 허용
PWR_DELTA_MIN_DB = -0.7
PWR_DELTA_MAX_DB = +3.0

# 동일 스텝에서 재측정 최대 횟수
MAX_REMEASURE = 2

# 디버깅
DEBUG = False

# ============== 유틸 ==============
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

# ============== VISA 래퍼 ==============
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
    def opc(self): self.query("*OPC?")
    def clear_status(self):
        try: self.write("*CLS")
        except Exception: pass
    def last_error(self) -> str:
        try: return self.query("SYST:ERR?")
        except Exception: return "SYST:ERR? not supported"

def wait_opc_poll(dev: VisaDevice, cmd: str,
                  max_wait_s: float, poll_s: float, query_timeout_ms: int):
    """긴 작업을 dev.write(cmd)로 시작 → *OPC?를 짧은 타임아웃으로 폴링하며 완료 대기"""
    dev.write(cmd)
    old_to = dev.inst.timeout
    dev.inst.timeout = query_timeout_ms
    t0 = time.time()
    try:
        while True:
            try:
                resp = dev.query("*OPC?")
                if resp.strip().startswith("1"):
                    return
            except pyvisa.errors.VisaIOError as e:
                if e.error_code != constants.StatusCode.error_timeout:
                    raise
            if time.time() - t0 > max_wait_s:
                try: err = dev.query("SYST:ERR?")
                except Exception: err = "SYST:ERR? not available"
                raise TimeoutError(
                    f"OPC polling timed out after {max_wait_s}s for cmd: {cmd!r}\n"
                    f"Instrument last error: {err}"
                )
            time.sleep(poll_s)
    finally:
        dev.inst.timeout = old_to

# ============== 장비별 래퍼 ==============
class SMW200A:
    def __init__(self, dev: VisaDevice): self.d = dev
    def basic_setup(self, freq_hz: float):
        self.d.clear_status()
        self.d.write(f"SOUR:FREQ {freq_hz}")
        self.d.opc()
    def set_power_dbm(self, p_dbm: float):
        self.d.write(f"SOUR:POW:LEV:IMM:AMPL {p_dbm} dBm")
    def rf_on(self, on: bool = True):
        self.d.write(f"OUTP {'ON' if on else 'OFF'}")

class FSVA3030:
    def __init__(self, dev: VisaDevice): self.d = dev
    def basic_setup(self, center_hz: float, span_hz: float):
        self.d.clear_status()
        self.d.write(f"FREQ:CENT {center_hz}")
        self.d.write(f"FREQ:SPAN {span_hz}")
        self.d.write("UNIT:POW DBM")     # 파워 결과 dBm
        self.d.write("INIT:CONT OFF")     # 단발 측정
        self.d.write("TRIG:SOUR IMM")     # 즉시 트리거
        self.d.opc()
    def auto_evm_adjust(self):
        wait_opc_poll(self.d, "SENS:ADJ:EVM",
                      max_wait_s=AUTO_EVM_MAX_WAIT_S,
                      poll_s=AUTO_EVM_POLL_S,
                      query_timeout_ms=AUTO_EVM_QUERY_TO_MS)
        if AUTO_EVM_POST_WAIT_S > 0:
            time.sleep(AUTO_EVM_POST_WAIT_S)
    def auto_level_adjust(self):
        wait_opc_poll(self.d, "SENS:ADJ:LEV",
                      max_wait_s=AUTO_EVM_MAX_WAIT_S,
                      poll_s=AUTO_EVM_POLL_S,
                      query_timeout_ms=AUTO_EVM_QUERY_TO_MS)
        if AUTO_EVM_POST_WAIT_S > 0:
            time.sleep(AUTO_EVM_POST_WAIT_S)        
    def measure_once_sync(self):
        self.d.write("ABOR")
        wait_opc_poll(self.d, "INIT:IMM",
                      max_wait_s=MEASURE_MAX_WAIT_S,
                      poll_s=MEASURE_POLL_S,
                      query_timeout_ms=MEASURE_QUERY_TO_MS)
        time.sleep(SA_INIT_WAIT_S)
    def _evm_from_response(self, resp: str) -> Optional[float]:
        nums = parse_all_floats(resp)
        if DEBUG:
            print("[DEBUG] EVM raw:", resp)
            print("[DEBUG] EVM nums:", nums)
        db_candidates = [v for v in nums if EVM_DB_MIN <= v <= EVM_DB_MAX]
        if db_candidates:
            return db_candidates[0]
        pct_candidates = [v for v in nums if 0.0 < v < 100.0]
        if pct_candidates:
            return 20.0 * math.log10(pct_candidates[0] / 100.0)
        if nums:
            return nums[-1]
        return None
    def read_evm_value(self, retry_once=True) -> float:
        queries: List[str] = []
        if PREFERRED_EVM_QUERY:
            queries.append(PREFERRED_EVM_QUERY)
        queries.extend(EVM_QUERY_CANDIDATES)
        last_detail = ""
        for q in queries:
            try:
                resp = self.d.query(q)
                evm_db = self._evm_from_response(resp)
                if evm_db is not None:
                    return evm_db
                last_detail = f"{q} -> no usable EVM in resp: {resp!r}"
            except Exception as e:
                last_detail = f"{q} -> {e}"
        if retry_once:
            self.measure_once_sync()
            return self.read_evm_value(retry_once=False)
        raise RuntimeError("EVM 파싱 실패: " + last_detail)

class NGP800:
    def __init__(self, dev: VisaDevice): self.d = dev
    def read_voltage_current(self, ch: int) -> Tuple[float, float]:
        v_queries = [
            f"MEAS:VOLT? (@{ch})",
            f"MEAS:VOLT? CH{ch}",
            f"MEAS:SCAL:VOLT:DC? (@{ch})",
            f"MEAS:VOLT:DC? (@{ch})",
        ]
        i_queries = [
            f"MEAS:CURR? (@{ch})",
            f"MEAS:CURR? CH{ch}",
            f"MEAS:SCAL:CURR:DC? (@{ch})",
            f"MEAS:CURR:DC? (@{ch})",
        ]
        v_val = i_val = None
        last_v_err = last_i_err = ""
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

# ============== 일관성 체크/재측정 로직 ==============
def is_suspicious_read(evm_db: float, sa_pw_dbm: float,
                       prev_evm_db: Optional[float], prev_sa_pw_dbm: Optional[float]) -> bool:
    """
    - EVM이 정상 범위 밖이면 의심
    - 이전 스텝 대비 EVM 점프가 너무 크면 의심
    - 이전 스텝 대비 SA 파워 변화량이 허용 범위를 벗어나면 의심
    """
    bad_range = not (EVM_DB_MIN < evm_db < EVM_DB_MAX)
    big_jump = (prev_evm_db is not None and abs(evm_db - prev_evm_db) > EVM_JUMP_MAX_DB)
    bad_power_delta = False
    if prev_sa_pw_dbm is not None:
        delta = sa_pw_dbm - prev_sa_pw_dbm
        bad_power_delta = not (PWR_DELTA_MIN_DB <= delta <= PWR_DELTA_MAX_DB)
        if DEBUG:
            print(f"[DEBUG] SA power delta = {delta:.3f} dB (ok {PWR_DELTA_MIN_DB}~{PWR_DELTA_MAX_DB})")
    if DEBUG and (bad_range or big_jump or bad_power_delta):
        print(f"[DEBUG] suspicious: bad_range={bad_range}, big_jump={big_jump}, bad_power_delta={bad_power_delta}")
    return bad_range or big_jump or bad_power_delta

# ============== 메인 ==============
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

        smw_dev.basic_setup(SG_RF_FREQUENCY_HZ)
        fsva_dev.basic_setup(SA_CENTER_HZ, SA_SPAN_HZ)
        smw_dev.rf_on(True)

        # Auto EVM: 기본은 '시작 전 1회'만 수행 → 스텝별 레벨/감쇠 재구성이 없어 안정적
        # 1) SG 세팅 후 안정화
        smw_dev.set_power_dbm(POWER_START_DBM)
        time.sleep(SETTLE_TIME_S)
        if AUTO_EVM_MODE.lower() == "once":
            print("[FSVA] Auto EVM (one-time) ...")
            fsva_dev.auto_evm_adjust()

        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            header = [
                "timestamp",
                "sg_power_dbm",
                "sa_total_pwr_dbm",
                "evm_db",
                "psu_ch1_V", "psu_ch1_I",
                "psu_ch2_V", "psu_ch2_I",
                "psu_ch3_V", "psu_ch3_I",
            ]
            writer.writerow(header)

            prev_evm = None
            prev_pw  = None

            step_idx = 0
            for p_dbm in frange_inclusive(POWER_START_DBM, POWER_STOP_DBM, POWER_STEP_DBM):
                step_idx += 1
                print(f"\n[STEP {step_idx}] Set SG power = {p_dbm} dBm")

                # 1) SG 세팅 후 안정화
                smw_dev.set_power_dbm(p_dbm)
                time.sleep(SETTLE_TIME_S)

                # (옵션) 매 스텝 Auto EVM — 정말 필요할 때만 켜세요(불안정 원인이 될 수 있음)
                if AUTO_EVM_MODE.lower() == "each_step":
                    fsva_dev.auto_evm_adjust()
                
                fsva_dev.auto_level_adjust()
                print("[FSVA] Auto Level ...")

                # 2) 동기 단발 측정 + Fetch
                def measure_fetch_once():
                    fsva_dev.measure_once_sync()
                    evm_db  = fsva_dev.read_evm_value()
                    sa_pw   = parse_first_float(fsva.query("FETC:CC1:ISRC:FRAM:SUMM:POW:AVER?"))
                    return evm_db, sa_pw

                evm_db, sa_pw = measure_fetch_once()

                # 3) 일관성 검사 후 필요 시 재측정(최대 MAX_REMEASURE)
                retries = 0
                while retries < MAX_REMEASURE and is_suspicious_read(evm_db, sa_pw, prev_evm, prev_pw):
                    if DEBUG:
                        print(f"[DEBUG] retry #{retries+1} due to suspicious read")
                    evm_db2, sa_pw2 = measure_fetch_once()
                    # 더 그럴듯한(정상 범위/변화량)에 가까운 값을 선택
                    choose_second = not is_suspicious_read(evm_db2, sa_pw2, prev_evm, prev_pw)
                    if choose_second:
                        evm_db, sa_pw = evm_db2, sa_pw2
                        break
                    else:
                        # 둘 다 애매하면 더 나은 쪽(이상치 정도가 작은 쪽) 선택
                        # 간단히: 이전값 대비 변화가 더 작은 쪽 채택
                        def score(e, p):
                            score_e = abs(e - prev_evm) if prev_evm is not None else 0.0
                            score_p = abs((p - prev_pw)) if prev_pw is not None else 0.0
                            return score_e + score_p
                        if score(evm_db2, sa_pw2) < score(evm_db, sa_pw):
                            evm_db, sa_pw = evm_db2, sa_pw2
                    retries += 1

                # 4) PSU 읽기
                vi: List[float] = []
                for ch in PSU_CHANNELS:
                    v, i = ngp_dev.read_voltage_current(ch)
                    vi.extend([v, i*1000])

                # 5) CSV 기록
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([ts, p_dbm, sa_pw, evm_db] + vi)
                f.flush()

                # 6) 콘솔
                print(f"  SA Total Power (dBm) = {sa_pw}")
                print(f"  EVM (dB) = {evm_db}")
                print(f"  PSU Ch1(V,I)={vi[0:2]}  Ch2={vi[2:4]}  Ch3={vi[4:6]}")

                # 7) 다음 스텝을 위한 기준 업데이트
                prev_evm, prev_pw = evm_db, sa_pw

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
