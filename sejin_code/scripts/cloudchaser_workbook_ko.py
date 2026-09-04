"""CloudChaser 수동 조작 워크북 -- IPython 복붙(copy-paste) 레퍼런스.

사용법:
  1. 이 파일을 IPython 터미널 옆에 열어 둔다.
  2. [PARAMETERS] 섹션을 오늘 세션에 맞게 수정한다.
  3. 각 [STEP] 블록을 IPython에 하나씩 붙여넣는다.
     - 각 블록은 독립적이므로 다시 붙여넣으면 재실행된다.
     - 중간 조작 블록(3b/3c/3d/3e)은 세션 도중 언제든 붙여넣을 수 있다.
  4. [STEP 7] SHUTDOWN으로 세션을 마무리한다.

STEP 3 이후 사용 가능한 객체: bench, chip, sg, sa, fh (raw 레지스터 엔진)
STEP 3 이후 사용 가능한 헬퍼: rd, gain, chgain, atten, phase,
                               chan, enable, disable, paths, biasscan,
                               load_golden, rf, rfoff, level,
                               saconf, peak, vi, shutdown

NOTE: bring-up 은 raw 레지스터를 직접 쓴다(fh.wr_verify) -- pulse 비트가 같은
      워드에 함께 기입되므로 별도의 latch()/commit() 단계가 없다(그 벤더
      shadow-cache 헬퍼들은 더 이상 존재하지 않음). 단발성 raw 쓰기는
      fh.wr_verify(addr, val), 필드 이름으로 읽는 rd(field) 는 그대로 유효
      (읽기 전용, 안전).

NOTE: 새 TX EVB 로 교체됨 -- 구 EVB 의 H0/V0/H2 driver단 불량은 해당 없음.
      전 채널 사용 가능(재검증 진행 중).
"""

# =============================================================================
# [PARAMETERS] -- 일반적으로 이 섹션만 수정하면 된다
# =============================================================================

# --- 계측기 IP 주소 ----------------------------------------------------------
#  실제 벤치 네트워크에 맞게 IP를 변경한다.
PSU1_IP   = "192.168.5.18"   # Keysight E36313A #1  (FE1_4V0 / CORE_1V0 / IO_ANA_1V8)
PSU2_IP   = "192.168.5.19"   # Keysight E36313A #2  (DIST_1V8 / FE2_1V8 / FE3_1V8)
SG_IP     = "192.168.5.14"   # R&S SMW200A 신호발생기
SA_IP     = "192.168.5.12"   # R&S FSVA3030 스펙트럼 분석기
SCPI_PORT = 5025              # SCPI-over-LAN 포트 (포트 포워딩을 하지 않는 한 변경 불필요)

# --- 칩 / 보드 종류 ----------------------------------------------------------
CHIP = "rx"
#   "tx"  = Stampede2731 TX EVB  (config/bench.toml 사용)
#   "rx"  = Blueway RX EVB       (config/bench_rx.toml 사용)

CHANNELS = ["h0"]
#   활성화할 안테나 채널 목록 (모두 같은 빔 포트로 라우팅됨).
#   TX/RX: "h0"~"h3", "v0"~"v3"  (새 TX EVB: 전 채널 사용 가능)
#   다중 채널 예시: ["h1", "h3"]

BEAM = "b0"
#   채널을 라우팅할 빔 포트.
#   "b0" 또는 "b1"

CAL_FREQ = 0x0
#   ch{i}_cal_freq_sel_beam{n} 필드 코드 (bring-up이 활성 채널마다 write).
#   [확인된 사실] 3비트 필드 -> 값 범위 0x0~0x7, Reset=0.
#     레지스터 맵 Cloudchaser_Stampede_register_map.xlsx, CAL 시트(0x1014~0x1017),
#       Bit Length=3, Description "Frequency selection for calibration optimization  Beam{n}"
#     SPI Interface Spec Cloudchaser SPI Interface Specification_V1_0.pdf (CHx CAL FREQ SEL):
#       "These bits selects the frequency range for which the calibration is optimized. Reset Value = 0"
#   [예상/미확인] 0x0=기본/광대역, 다른 코드=특정 대역 보정 -- 코드별 실제 주파수 매핑
#     표는 제공 문서 어디에도 없음(데이터시트 포함). Sivers 확인 필요.
#   NOTE: bring-up 은 이 값을 raw 시퀀스에 기입하지 않는다(board/bringup.py 의
#   "ignored" 로그 참고). 참고용으로만 남겨둔다.

COMMON_GAIN = 0x00
#   b{n}_common_gain: 빔 공통 게인 (combining 이후 모든 채널에 동일 적용).
#   [확인된 사실] 6비트 필드 -> 0x00~0x3F.
#     레지스터 맵 SYS 시트(0x1005): "Common gain setting for beam0 applied after combining"
#     데이터시트 Features: "16-dB common-beam gain control with 0.25-dB step" (6비트)
#   [예상] 방향(0x00=최대 게인=감쇠 0dB)은 맵에 명시 없음 -- 통상적 해석.
#   아래 dB는 0.25 dB/step 가정한 근사치(예상치):
#     0x00 = 0 dB       0x08 ~= 2 dB      0x10 ~= 4 dB
#     0x20 ~= 8 dB      0x3F ~= 15.75 dB  (= 63 * 0.25, 데이터시트 16dB 범위와 일치)
#   NOTE: TX(bring_up_tx)는 이 값을 raw 시퀀스에 기입한다(적용됨). RX(bring_up_rx,
#   이 파일 기본 CHIP="rx")는 이 값을 기입하지 않는다(board/bringup.py 의
#   "ignored" 로그 참고) -- RX 에서 게인을 바꾸려면 bring-up 후 gain() 을 쓸 것.

CH_GAIN = {"h0": 0x00}
#   채널별 gain_control_{pol}{idx} 코드 (TX 전용).
#   [확인된 사실] 4비트 필드 -> 0x0~0xF.
#     레지스터 맵 Stampede CTRL 시트(0x1018~0x101B): "4 bit gain control for CHx H/V".
#     이 필드는 Stampede(TX) 맵에만 존재. Blueway(RX) 맵엔 없고 같은 주소가
#     ch{i}_{pol}_fe_attn(FE 감쇠기)로 정의됨. bring_up_rx는 ch_gain 미사용(ch_fe_attn 사용)
#     -> RX에선 이 값 무시되고, chgain() 헬퍼는 RX에서 KeyError.
#   [미확인] 어느 증폭단/ dB-step / 방향(0=최대?)은 맵에 없음. 데이터시트의
#     "Gain Control 6-bit 0.5-dB/step per path"는 이 4비트 필드와 폭이 안 맞아 동일 확정 불가.
#   CHANNELS에 포함된 채널만 작성. 예: {"h1": 0x08, "h3": 0x08}
#   빠진 채널은 bench.toml [board.ch_gain] 기본값을 사용한다.
#   NOTE: bring_up_tx 는 이 값을 더 이상 raw 시퀀스에 기입하지 않는다
#   (board/bringup.py 의 "ignored" 로그 참고). 여기서 값을 바꿔도 bring-up
#   로그에 찍히는 "ignored" 문구만 바뀔 뿐 실동작은 없다 -- 대신 bring-up
#   이후 chgain()/atten() 을 쓸 것.

CH_ATTEN = {"h0": 0x00}
#   채널별 ch{idx}_{pol}_b{beam}_attn_cal 코드 (채널 x 편파 x 빔 단위).
#   [확인된 사실] 4비트 필드 -> 0x0~0xF. RTPS(Reflective-Type Phase Shifter, 위상기)
#     진폭 보정용 감쇠기. 범위 4 dB, 스텝 0.25 dB. TX/RX 양쪽 맵에 동일하게 존재.
#     레지스터 맵 CAL 시트(0x105C~0x1067): "RTPS amplitude cal attenuation ...; 4-dB range, 0.25-dB/step"
#   [예상] 0x00 = 감쇠 없음(0 dB) -- "attenuation" 정의상 자연스러운 해석(맵에 명시 없음).
#   CHANNELS에 포함된 채널만 작성. 예: {"h1": 0x00, "h3": 0x00}
#   NOTE: TX(bring_up_tx)는 이 값을 cal atten 행렬에 기입한다(적용됨).
#   RX(bring_up_rx, 이 파일 기본 CHIP="rx")는 이 값을 기입하지 않는다(ignored).

# --- 신호발생기(SG) -----------------------------------------------------------
FREQ_HZ   = 28.0e9  #tx
FREQ_HZ   = 19.5e9  #rx
#   측정 주파수 [Hz].
#   예시: 25.0e9, 27.0e9, 28.0e9, 28.5e9, 39.0e9

LEVEL_DBM = -30.0
#   SG 출력 레벨 [dBm] = 경로 손실 적용 후의 칩 입력 레벨.
#   Loss_data CSV 오프셋이 자동으로 적용되므로 이 값은 SG 실제 출력이 아니라
#   DUT(칩)에 실제로 들어가는 레벨을 뜻한다.
#   일반 범위: -40.0 ~ +5.0 dBm (칩 입력 기준)

RF_ON = False
#   True  = STEP 4의 rf() 호출 시 즉시 RF 출력 ON
#   False = rf() 구성만 하고 RF는 OFF 유지 -- 필요할 때 rf(True, ...)로 켠다

# --- 스펙트럼 분석기(SA) ------------------------------------------------------
SA_SPAN  = 100e6
#   SA 표시 스팬 [Hz].  예시: 10e6, 100e6, 500e6, 1e9

SA_REF   = 20.0
#   SA 기준 레벨 [dBm] -- 예상 피크보다 약 10 dB 높게 설정.
#   경로 손실 오프셋 적용 후: 칩 출력 기준 기준 레벨.

SA_RBW   = 1e6
#   SA 해상도 대역폭(RBW) [Hz].  좁을수록 정확하지만 스윕이 느려진다.
#   예시: 100e3, 1e6, 3e6

SA_ATTEN = 10.0
#   SA 입력 감쇠기 [dB].  높을수록 SA 믹서를 보호하지만 감도는 낮아진다.
#   0 = 최고 감도.  10 = 일반.  30 = 고출력 신호용.

# --- 기타 --------------------------------------------------------------------
FAKE = False
#   True  = dry-run 모드: TCP 연결 없음, SPI 쓰기 없음 (코드 테스트용)
#   False = 실제 하드웨어  <- 실측 시 사용

# =============================================================================
# [STEP 1] 계측기 연결
# =============================================================================
# IPython 세션 시작 시 이 블록을 한 번 붙여넣는다.
# 수행 내용:
#   1. bench.toml에서 벤치 설정 로드 (안정적인 레일 전압/전류 한계는 TOML에 유지)
#   2. [PARAMETERS]에서 IP와 보드 설정을 덮어씀
#   3. 계측기 4대에 TCP 소켓을 열고 오래된 에러 큐를 비움
#
# 세션 중 연결이 끊기면 이 블록만 다시 붙여넣으면 된다.
# 내보내는 변수: bench, sg, sa
# =============================================================================
from pathlib import Path
from cloudchaser.bench import Bench
from cloudchaser.board.bringup import (
    make_chip, make_chip_rx, bring_up_tx, bring_up_rx,
)
from cloudchaser.manual import build_namespace

# CHIP 종류에 따라 TOML 파일 선택 (레일 전압/전류 한계는 TOML에 있음)
_workbook_toml = (
    Path("config/bench_rx.toml") if CHIP == "rx"
    else Path("config/bench.toml")
)
bench = Bench.from_toml(_workbook_toml, fake=FAKE)

# [PARAMETERS]의 IP로 계측기 호스트를 덮어씀 (bench.toml IP는 무시됨)
# ScpiSocket은 connect() 호출 시 self.host를 읽으므로, connect_all() 전에 덮어쓰면 된다.
bench.psu1.host = PSU1_IP;  bench.psu1.port = SCPI_PORT
bench.psu2.host = PSU2_IP;  bench.psu2.port = SCPI_PORT
bench.sg.host   = SG_IP;    bench.sg.port   = SCPI_PORT
bench.sa.host   = SA_IP;    bench.sa.port   = SCPI_PORT

# [PARAMETERS]에서 보드 설정 덮어씀
bench.board.active_channels = list(CHANNELS)
bench.board.beam            = BEAM
bench.board.cal_freq_code   = CAL_FREQ
bench.board.common_gain     = COMMON_GAIN
bench.board.ch_gain         = {k: int(v) for k, v in CH_GAIN.items()}
bench.board.ch_atten        = {k: int(v) for k, v in CH_ATTEN.items()}
bench.chip_kind             = CHIP

bench.connect_all()     # 소켓 열기 + 오래된 에러 큐 비우기 (연결마다 출력)
sg = bench.sg           # 이 세션에서 SG 단축 이름
sa = bench.sa           # 이 세션에서 SA 단축 이름

print(f"[OK] Connected: PSU1={PSU1_IP}  PSU2={PSU2_IP}  SG={SG_IP}  SA={SA_IP}")
print(f"     chip={CHIP}  channels={CHANNELS}  beam={BEAM}  fake={FAKE}")

# =============================================================================
# [STEP 2] 전원 레일 램프업
# =============================================================================
# bench.toml [ramp] power_up_order에 정의된 순서대로 PSU 레일을 올린다:
#   CORE_1V0 -> DIST_1V8 -> IO_ANA_1V8 -> FE2_1V8 -> FE3_1V8 -> FE1_4V0
# 각 레일은 0V에서 목표값까지 0.2V씩 스텝, 스텝마다 0.1초 안정화 대기한다.
# 전체 도달 후 모든 레일의 전압[V]과 전류[mA]를 출력한다.
#
# 이전 세션에서 레일이 이미 켜져 있으면 이 블록은 건너뛴다.
# (소켓만 재연결하려면 STEP 1만 다시 붙여넣는다.)
#
# SPI 레일만 먼저 올려 칩 자동 감지 후 FE를 올리려면:
#   bench.power_up(rails=bench.detect_rail_names)
# =============================================================================
bench.power_up()
# bring-up 후 예상 전류: FE1_4V0 약 50~200 mA (활성화된 채널 수에 따라 다름)
# bring-up 후 FE 전류가 0 mA이면 케이블 또는 보드 전원 커넥터를 확인한다.

# =============================================================================
# [STEP 2b] 레일 전압/전류 읽기 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# for name, m in bench.read_all_vi().items():
#     print(f"  {name:12}: {m['v']:.3f} V   {m['i']*1000:.1f} mA")

# =============================================================================
# [STEP 3] 칩 초기화 + bring-up + 헬퍼 함수 할당
# =============================================================================
# 수행 내용:
#   1. sivers_api 칩 객체 생성 (Stampede 또는 Blueway)
#   2. chip.init() + eFuse 로드 + version_id 확인 (SPI 동작 확인)
#   3. centerbias_en + centermirror_en 수동 ON (path.enable이 하지 않으므로 필수)
#   4. CHANNELS → BEAM 라우팅, cal_freq / common_gain / ch_gain / ch_atten 설정
#   5. 모든 레지스터 쓰기를 한 번에 하드웨어에 커밋
#   6. 헬퍼 함수 세트를 빌드하고 로컬 이름에 할당
#
# 이 블록 이후: 칩 준비 완료, 헬퍼 함수 사용 가능.
# 레지스터가 오염된 경우 등 칩을 완전히 재초기화하려면 이 블록을 다시 붙여넣는다.
# 내보내는 이름: chip, fh, rd, gain, chgain, atten, phase, chan, enable, disable,
#               paths, biasscan, load_golden, rf, rfoff, level, saconf, peak, vi,
#               shutdown
# =============================================================================
_make_fn    = make_chip_rx if CHIP == "rx" else make_chip
_bringup_fn = bring_up_rx  if CHIP == "rx" else bring_up_tx

chip = _make_fn(bench.board, fake=FAKE)
_bringup_fn(chip, bench.board, require_version=not FAKE)

print(f"[OK] Bring-up done: chip={CHIP}  channels={bench.board.active_channels}"
      f"  beam={bench.board.beam}")

# 헬퍼 네임스페이스를 빌드하고 로컬 이름에 풀어 할당한다.
# 모든 헬퍼는 현재 bench + chip 상태를 사용한다.
_ns = build_namespace(bench, chip, bench.board.beam)
fh        = _ns["fh"]          # raw 레지스터 엔진: fh.rd(addr) / fh.wr_verify(addr, val)
rd        = _ns["rd"]          # rd("field")          레지스터 필드 읽기 + 값 출력
enable    = _ns["enable"]      # enable("h1")          채널을 빔에 라우팅
disable   = _ns["disable"]     # disable() / disable("h1")  경로 끄기
paths     = _ns["paths"]       # paths()               현재 빔->채널 라우팅 출력
gain      = _ns["gain"]        # gain(code)            공통 빔 게인 설정 (6비트 감쇠, 0=최대)
chgain    = _ns["chgain"]      # chgain("h1", code)    채널별 FE 게인 설정 (이 칩에서 DEAD)
atten     = _ns["atten"]       # atten("h1", code)     채널별 RTPS 감쇠기(beam-table) 설정
phase     = _ns["phase"]       # phase("h1", code)     채널별 RTPS 위상 설정 (9-bit)
load_golden = _ns["load_golden"] # load_golden()       알려진 정상 레지스터 상태 복원
chan      = _ns["chan"]         # chan("h1")            채널 하나를 측정 준비 상태로
biasscan  = _ns["biasscan"]    # biasscan("h1")        PTAT 바이어스 스윕, 죽은 스테이지 진단
rf        = _ns["rf"]          # rf(True, freq=28e9, level=-20)  SG 제어 + 경로 손실 적용
rfoff     = _ns["rfoff"]       # rfoff()               SG RF 출력 OFF (간편 단축키)
level     = _ns["level"]       # level(-15)            SG 레벨만 변경 [dBm]
saconf    = _ns["saconf"]      # saconf(center=28e9, span=100e6, ref=20)  SA 설정
peak      = _ns["peak"]        # peak()                단회 스윕 후 SA 피크 반환 [dBm]
vi        = _ns["vi"]          # vi()                  전체 레일 V/I 읽기 + 출력
shutdown  = _ns["shutdown"]    # shutdown()            RF OFF + 모든 레일 0V로 내리기

# NOTE: gain()/chgain()/atten()/enable()/chan() 은 모두 raw 레지스터를 fh 를 통해
# 즉시 쓴다(pulse 비트가 같은 워드에 함께 기입됨) -- 더 이상 별도의
# latch()/commit() 단계가 없다.

print()
print("  Helpers ready: rd gain chgain atten phase chan enable disable paths")
print("                 biasscan load_golden rf rfoff level saconf peak vi shutdown fh")

############여기까지 bring-up, 여기까지 복붙하면 바로 bring up 됨.##############################

# =============================================================================
# [STEP 3b] 채널 변경 -- 세션 중 언제든 붙여넣을 수 있다 (재시작 불필요)
# =============================================================================
# STEP 3을 다시 실행하지 않고 단일 측정 채널로 전환한다.
# 아래는 chan()이 '자동으로' 수행하는 내용(수동 체크리스트가 아님; manual.py chan()):
#   모든 경로 disable -> centerbias/centermirror ON -> 그 채널만 빔에 라우팅(배타적)
#   -> RTPS 빔 테이블 초기화(0) + beam_up -> 공통 게인 최대(코드 0)
# 참고: chan()은 칩 init/reset이 아님. 채널별 gain_control/attn_cal/cal_freq는 다시
#       적용하지 않음(bring-up 값 유지). enable()과 달리 다른 채널은 모두 끈다.
#
# 예시:   chan("h1")   chan("h3")   chan("v1")   chan("v2")   chan("v3")
# 실행 후: SA 케이블을 새 채널의 RF 포트로 옮긴 뒤 STEP 4를 다시 붙여넣는다.
#
# SA 케이블 위치 (RF 포트):
#   chan("h1") -> RF_CH1_HPOL     chan("h3") -> RF_CH3_HPOL
#   chan("v1") -> RF_CH1_VPOL     chan("v2") -> RF_CH2_VPOL     chan("v3") -> RF_CH3_VPOL
# =============================================================================
chan("h1")


# =============================================================================
# [STEP 3c] 공통 게인 변경 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# b{n}_common_gain: 빔 공통 게인(6비트, combining 이후 적용, 0x1005 + beam index).
# gain()은 raw 쓰기(fh.wr_verify)로 즉시 아날로그에 반영된다 -- 별도의 latch() 단계 없음
# (pulse 비트가 같은 워드에 함께 기입되기 때문. 벤더 shadow-cache 방식이 아니다).
# 값은 정수면 됨(헥사/10진수 무관). 단 gain(10)은 10진수 10(=0x0A)이라 0x10(=16)과 다름.
#
# 코드 참조 (dB는 0.25 dB/step 가정한 근사치 -- 예상치):
#   gain(0x00)   # 0 dB (최대 게인)  <- 기본 시작값
#   gain(0x08)   # ~2 dB
#   gain(0x10)   # ~4 dB
#   gain(0x20)   # ~8 dB
#   gain(0x3F)   # ~15.75 dB (최대 감쇠)
# =============================================================================
gain(0x00)


# =============================================================================
# [STEP 3d] 채널별 게인 변경 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# 채널별 FE 게인(0x1018 + 채널 인덱스, 4비트)을 설정한다. **이 칩에서 DEAD** --
# 실동작하는 per-path 손잡이는 atten()(STEP 3e, beam-table RTPS 감쇠기)이다.
# raw 쓰기로 즉시 반영된다 -- 별도의 latch() 단계 없음.
# TX/RX 모두 같은 raw 주소를 쓰므로 필드 이름 불일치로 인한 KeyError는 없다
# (구 버전의 필드-이름 방식에서만 있던 문제).
#
# 예시:
#   chgain("h1", 0x08)   # H1: 4비트 게인 코드 (실칩에서 측정 가능한 효과 없음)
#   chgain("h3", 0x0F)   # H3
# =============================================================================
chgain("h0", 0x00)


# =============================================================================
# [STEP 3e] 채널별 감쇠(RTPS) 변경 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# 채널 RTPS 감쇠기(beam-table 워드, 7비트, 0=최대 게인)를 설정한다. 이 칩에서
# 실동작하는 per-path 게인 손잡이다(chgain()/FE 게인은 DEAD). raw 쓰기 +
# beam_up() 으로 즉시 반영된다 -- 별도의 latch() 단계 없음.
#
# 예시:
#   atten("h1", 0x00)   # 최대 게인(최소 감쇠)
#   atten("h3", 0x10)   # H3에 더 많은 감쇠
# =============================================================================
atten("h1", 0x00)


# =============================================================================
# [STEP 4] SG / SA 설정 + 신호 확인
# =============================================================================
# 신호발생기 + 스펙트럼 분석기를 설정하고 피크를 읽는다.
# Loss_data CSV의 경로 손실이 SG와 SA 오프셋에 자동으로 적용된다:
#   - SG 레벨 오프셋: LEVEL_DBM = 칩 입력 레벨이 되도록 보정
#   - SA 기준 레벨 오프셋: peak()가 칩 출력 레벨을 반환하도록 보정
# rf() + saconf() 이후에는 peak()만 반복 호출하면 신호를 읽을 수 있다.
# RF 출력 상태는 [PARAMETERS]의 RF_ON으로 결정된다.
# RF_ON=False이면 rf()가 SG를 구성만 하고 RF는 OFF -- rf(True)로 수동으로 켠다.
#
# rf(on, freq=Hz, level=dBm)
#   on    : True = RF 출력 ON  |  False = RF OFF
#   freq  : [Hz]  예: 25e9, 27e9, 28.0e9, 39e9
#   level : [dBm] 칩 입력 레벨 (경로 손실 자동 보정)
#
# saconf(center=Hz, span=Hz, ref=dBm, rbw=Hz, atten_db=dB)
#   center   : [Hz]  생략하면 현재 SG 주파수 사용
#   span     : [Hz]  표시 스팬.  기본값 100 MHz
#   ref      : [dBm] 기준 레벨 (예상 칩 출력보다 약 10 dB 높게)
#   rbw      : [Hz]  해상도 대역폭.  기본값 1 MHz
#   atten_db : [dB]  입력 감쇠기.  기본값 10 dB
#
# peak() -> float [dBm]
#   단회 스윕 + 마커를 피크에 이동. 칩 출력 전력 [dBm] 반환 (손실 보정됨).
# =============================================================================
RF_ON=True
rf(RF_ON, freq=FREQ_HZ, level=LEVEL_DBM)
saconf(center=FREQ_HZ, span=SA_SPAN, ref=SA_REF, rbw=SA_RBW, atten_db=SA_ATTEN)
p = peak()
print(f"  chip output ~= {p:.1f} dBm")

# 세션 중 즉석 조정용 한 줄 명령 (필요한 것만 개별적으로 붙여넣는다):
# 이 블록 붙여넣기 후 RF 상태: PARAMETERS에서 RF_ON=True이면 ON, False이면 OFF
# level(-15)                                    # SG 레벨만 변경
# rf(False)    # RF 끄기 (대안: 아래의 rfoff())
# rfoff()      # RF 끄기 단축키
# peak()                                        # SA 피크 다시 읽기
# rf(True, freq=28.5e9, level=-20)              # 주파수 변경 + 손실 재적용
# saconf(center=28.5e9, ref=20)                 # SA를 새 중심 주파수로 재설정
# vi()                                          # 전체 레일 V/I 확인


# =============================================================================
# [STEP 5a] 레지스터 읽기/쓰기 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# rd("field")               : 벤더 필드 이름으로 읽기, 16진수+10진수로 출력, int 반환
#                              (읽기 전용 헬퍼 -- 안전, HW를 직접 읽는다)
# fh.rd(addr)                : raw 레지스터 주소 읽기 (int, 예: 0x1005)
# fh.wr_verify(addr, val)    : raw 레지스터 주소 쓰기, 즉시 반영 + readback 검증
#                              (latch()/commit() 불필요 -- pulse 비트가 같은 워드에
#                              함께 기입되기 때문)
#
# 자주 쓰는 읽기 필드(rd) / raw 주소(fh.wr_verify):
#   "b0_common_gain"  / 0x1005     6비트 빔0 게인 (0=최대, 0x3F=최대 감쇠)
#   "b1_common_gain"  / 0x1006     6비트 빔1 게인
#   "version_id"      / 0x1000     읽기 전용 칩 ID (0xDC=TX Stampede, 0xD4=RX Blueway)
#
# 채널/빔 게인·감쇠는 raw 주소보다 gain()/chgain()/atten()(STEP 3c/3d/3e)을 쓸 것
# -- 빔/채널 오프셋을 알아서 계산해준다.
# =============================================================================
rd("b0_common_gain")
# fh.wr_verify(0x1005, 0x10)


# =============================================================================
# [STEP 5b] 채널 활성화/비활성화 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# enable("h1")                 H1을 현재 빔에 라우팅 (누적: 기존 채널 안 끔)
# enable("h1", "h3")           H1과 H3을 함께 라우팅
# disable()                    활성 경로 전체 비활성화 (모든 채널 끄기)
# disable("h1")                H1 경로만 비활성화
# paths()                      현재 빔 -> 채널 라우팅 상태 출력
# 참고: enable()은 additive (기존 active 유지; vendor path.single 근거). 채널을 '교체'하려면
#       disable(old)+enable(new), 또는 클린 측정상태가 필요하면 chan(new)을 쓴다.
# =============================================================================
paths()


# =============================================================================
# [STEP 5c] centerbias 수동 강제 설정 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# centerbias_en = center 바이어스 생성기 ON (레지스터 맵: "Enable for the center bias generator").
# vendor path.enable()/center.enable()은 빔 분배 증폭기(beam_pwrdn/dist_st1_en)만 켜고
# 이 '마스터 바이어스' 두 비트는 건드리지 않는다(center.py 확인). 안 켜면 채널이 enable
# 돼 있어도 바이어스가 없어 신호가 죽는다(※ "신호 죽음"은 bring-up 노트 기반 해석).
# bring_up_tx/rx와 chan()은 자동으로 켜주므로 평소엔 불필요. reset()/load_golden()/커스텀
# 레지스터 로드 후엔 vendor API가 여전히 안 켜주므로 아래로 수동 재설정한다.
# centerbias_en(bit0) + centermirror_en(bit1)은 0x1008의 하위 2비트다.
# =============================================================================
# fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])   # 0x1008 = 3 (bandgap + mirror)


# =============================================================================
# [STEP 5d] 바이어스 스테이지 진단 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# 각 증폭 스테이지의 PTAT 바이어스를 0->63으로 스윕하며 FE 레일 전류 변화를 관찰한다.
# 특정 스테이지에서 "NO RESPONSE"가 뜨면 그 스테이지가 전력을 소비하지 않는 것(고장 의심).
# biasscan 실행 전에 chan("hN")으로 하나의 채널을 먼저 격리한다.
#
# biasscan("h1")   # H1 진단
# biasscan("h3")   # H3 진단
# =============================================================================
# chan("h1"); biasscan("h1")


# =============================================================================
# [STEP 5e] 골든 레지스터 상태 로드 -- 세션 중 언제든 붙여넣을 수 있다
# =============================================================================
# 알려진 정상 측정에서 캡처한 전체 레지스터 상태를 복원한다.
# 소스 파일: docs/golden_h0b0_25g.json (25 GHz, H0->B0 기준 MATLAB mem_dump)
# 빈 상태에서 신호 경로 무결성을 검증할 때 사용한다.
#
# load_golden()                             # 기본 골든 파일 로드
# load_golden("path/to/custom.json")        # 다른 캡처 파일 로드
# =============================================================================
# load_golden()


# =============================================================================
# [STEP 6] 테스트 항목 실행
# =============================================================================
# 테스트 항목 함수(op1db, evm 등)가 현재 bench + chip 상태를 사용하도록
# 세션 전역 변수를 연결한다 (재연결 또는 재시작 불필요).
# 아래 연결 블록을 한 번 붙여넣은 뒤 원하는 테스트 호출 주석을 해제한다.
#
# 모든 테스트 함수:
#   - Loss_data CSV의 경로 손실을 SG/SA 오프셋에 자동 적용
#   - 결과를 out/ 디렉토리에 CSV로 저장
#   - 완료 시 요약 한 줄 출력
# =============================================================================

# --- 세션 연결 (이 서브블록을 먼저 붙여넣는다) ----------------------------------
import cloudchaser.session as _sess
_sess.B          = bench
_sess.C          = chip
_sess._fake      = FAKE
_sess._ns        = _ns
_sess._chip_kind = CHIP
from cloudchaser.session import (
    op1db, gain_index_accuracy, channel_gain_alignment, evm, acp, ip1db, params
)
print("[OK] Session wired: op1db / gain_index_accuracy / channel_gain_alignment / evm / acp / ip1db ready")
# 연결 후 params("op1db") 등으로 각 테스트의 전체 파라미터 설명을 볼 수 있다

# --- OP1dB (TX 출력 1 dB 압축점) -----------------------------------------------
# SG 입력 전력을 pin_start에서 pin_stop까지 스윕하며 출력을 측정, 1 dB 압축점 추출.
#
op1db(freq_hz=FREQ_HZ, gain_code=COMMON_GAIN)
op1db(freq_hz=28e9, gain_code=0, pin_start_dbm=-30, pin_stop_dbm=5)
params("op1db")    # 모든 파라미터와 기본값 출력

# --- Gain Index Accuracy (게인 인덱스 정확도) -----------------------------------
# SG 입력을 '고정'하고 게인 코드를 sweep -> 코드별 Pout 측정(Gain_dB=Pout-Pin).
# 게인 손잡이 2축: (A) 빔 공통게인 common_codes, (B) 채널 per-path RTPS channel_codes.
#   한 축을 단일값([0])으로 주면 다른 축만 1D sweep.
# 채널 손잡이: channel_target="beamtable"(RTPS, 동작함) 유지. "fe"(구 gain_control)는 이 칩에서 DEAD.
# 모든 파라미터 설명: params("gain_index_accuracy")
#
# [!] channel_quad: routed 채널의 quad 와 반드시 일치해야 함(beam table = beam0/quad).
#     기본값 None = active 채널에서 자동 유도(h0->0, h1->1, h2->2, h3->3). 보통 그냥 두면 됨.
#     수동으로 안 맞는 quad(예: h0인데 channel_quad=1)를 주면 측정 경로가 아닌 quad 를
#     sweep 하게 되어 출력이 반응하지 않는다(과거 default=1 고정이 이 문제를 일으켰음).
#
# [!] RX(Blueway) 직접 호출 함정: 함수로 부르면 rx_default(19.5GHz/-50dBm/ref10)가
#     적용되지 않고 TX 기본값(28GHz/0dBm/ref20)이 쓰인다(rx_default는 대화형 wizard 전용).
#     -> RX에서는 freq_hz / sg_level_dbm / sa_ref_level_dbm 를 반드시 명시할 것.
#     (안 그러면 28GHz에서 0dBm을 민감한 RX LNA에 인가하게 됨)
#
# [기본 sweep] channel_codes 기본값 [0] = 채널 고정, common 64점만 1D sweep(빠름, 매 점 출력).
#     per-path(RTPS)까지 보려면 channel_codes=list(range(0,64,4)) 처럼 채널축을 명시(2D).
# [PSU timeout 대처] log_psu=False 면 PSU V/I 읽기를 생략 -> 빠르고 timeout 회피.
#
# RX 레시피 ----------------------------------------------------------------------
# (A) 공통게인 정확도만 (채널 고정):
gain_index_accuracy(freq_hz=19.5e9, sg_level_dbm=-50, sa_ref_level_dbm=10,
                    common_codes=[0,8,16,24,32,40,48,56,63], channel_codes=[0])
# (B) per-path RTPS 정확도만 (공통 고정, 측정 채널 quad에 맞춤):
gain_index_accuracy(freq_hz=19.5e9, sg_level_dbm=-50, sa_ref_level_dbm=10,
                    common_codes=[0], channel_quad=0, channel_codes=list(range(0,64,4)))
# (C) PSU 로깅 끄고 빠르게:
gain_index_accuracy(freq_hz=19.5e9, sg_level_dbm=-50, sa_ref_level_dbm=10,
                    common_codes=[0,16,32,48,63], channel_codes=[0], log_psu=False)
# TX 예시:
gain_index_accuracy(sg_level_dbm=0, channel_target="beamtable", channel_quad=1)
params("gain_index_accuracy")

# --- Channel Gain Alignment (채널 간 게인 정렬) ---------------------------------
# 대화형 또는 자동: 채널별 출력 레벨을 측정하고 편차[dB]를 보고한다.
#   channel_mode="single"  : 칩이 채널을 자동 전환하며 측정 (SA 자동)
#   channel_mode="all"     : 모든 채널 동시 ON, SA 케이블을 수동으로 이동
#   channels_script="h1,h3": 비대화형 스크립트 모드 (input() 프롬프트 없음)
#
channel_gain_alignment(channel_mode="single")
channel_gain_alignment(channels_script="h1,h3")
params("channel_gain_alignment")

# --- EVM (5G NR 변조 품질 vs 출력 전력) -----------------------------------------
#   modulation="setup"  : SG가 내부에서 파형 생성 (기본값)
#   modulation="load"   : 파일에서 파형 로드 (waveform_path 필요)
#   modulation="manual" : SG에 이미 파형이 로드됨, 설정 단계 건너뜀
#
# evm(freq_hz=FREQ_HZ)
evm(freq_hz=28e9, modulation="load", waveform_path="waveforms/nr_fr2.wv")
evm(freq_hz=19.5e9, modulation="setup", pin_start_dbm=-40, pin_stop_dbm=-20, pin_step_db=1)
params("evm")

# --- ACP (인접 채널 전력비 vs 출력 전력) -----------------------------------------
acp(freq_hz=FREQ_HZ)
params("acp")

# --- IP1dB (RX 입력 1 dB 압축점 -- Blueway EVB 전용) ----------------------------
# RX 신호 흐름: SG -> 채널 포트(안테나 입력) -> IC -> 빔 포트 -> SA
#
ip1db(freq_hz=19.5e9, gain_code=0, pin_start_dbm=-50, pin_stop_dbm=-20, pin_step_db=1, settle_s=0.1)
params("ip1db")


# =============================================================================
# [STEP 7] 종료
# =============================================================================
# 세션을 안전하게 종료한다:
#   1. RF 출력 OFF (SG: RF off)
#   2. 파워업 순서의 역순으로 모든 PSU 레일을 0V로 내린다:
#      FE1_4V0 -> FE3_1V8 -> FE2_1V8 -> IO_ANA_1V8 -> DIST_1V8 -> CORE_1V0
#   3. 모든 TCP 소켓 닫기
#
# EVB 사용이 끝나면 shutdown()을 호출한다.
# 이후 전원은 OFF 상태가 된다; 새 세션을 시작하려면 STEP 1+2를 다시 붙여넣는다.
# =============================================================================
rfoff()          # 선택사항: 종료 전 RF 먼저 끄기 (shutdown()도 이 작업을 수행함)
shutdown()       # 레일을 0V로 내림
bench.close_all()  # 선택사항: 종료 후 소켓 닫기
