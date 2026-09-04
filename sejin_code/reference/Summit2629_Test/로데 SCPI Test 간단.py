# pip install pyvisa
import re
import pyvisa

VISA_ADDR = "TCPIP0::192.168.10.3::inst0::INSTR"  # 장비 주소로 바꿔줘
rm = pyvisa.ResourceManager()
d = rm.open_resource(VISA_ADDR)
d.timeout = 5000
d.write_termination = "\n"
d.read_termination = "\n"

cmd = "SENS:ADJ:LEV" #원하는 명령어 입력
raw = d.query(cmd)
print(f"SCPI  -> {cmd}")
print(f"RAW   -> {raw!r}")

floats = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", raw)]
print("floats:", floats)

# 옵션: 에러 확인
print("SYST:ERR? ->", d.query("SYST:ERR?").strip())

d.close()

