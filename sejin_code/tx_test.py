# =====================================================================================
#  Cloudchaser Stampede2731 (TX) — Test Script
#  통신이 된다고 가정한 TX 구동 템플릿
#
#  흐름 :  IC bring-up → 채널 활성화 → 주파수(cal band) → 게인 → 감쇠 → 위상 → 검증
#
#  - 필드 이름은 전부 Cloudchaser_Stampede_register_map.xlsx 기준 실제 이름입니다.
#  - 값(코드)은 예시이며, 각 코드의 실제 dB/deg 환산은 데이터시트 표를 따르세요.
#  - 실행:  python tx_test.py     (또는 IPython에서  %run tx_test.py)
# =====================================================================================

from sivers_api import Stampede

# -------------------------------------------------------------------------------------
# 0. CONFIG  — 여기 값만 바꿔서 쓰면 됩니다
# -------------------------------------------------------------------------------------
CHIP_ID     = 0                          # 보드 chip_id (스트랩 0이면 0)
BEAM        = "b0"                        # 사용할 빔 포트:  "b0" 또는 "b1"
ACTIVE_CH   = ["h0", "h1", "h2", "h3"]   # 활성화할 채널 목록 (h0~h3 / v0~v3 혼용 가능)

FREQ_CODE   = 0x0                         # cal_freq_sel 코드 (보정 대역 선택) — 데이터시트 표 참고
COMMON_GAIN = 0x20                        # 빔 공통 게인 b{n}_common_gain (6-bit, 0~63)

# 채널별 설정 (코드값). 키는 ACTIVE_CH 와 일치시킬 것.
CH_GAIN  = {"h0": 0x8,  "h1": 0x8,  "h2": 0x8,  "h3": 0x8}    # gain_control_*  (채널 게인)
CH_ATTEN = {"h0": 0x00, "h1": 0x00, "h2": 0x00, "h3": 0x00}   # attn_cal  (6-bit, 0=최소 감쇠)
CH_PHASE = {"h0": 0,    "h1": 32,   "h2": 64,   "h3": 96}     # phase_shifter (7-bit, 0~127 ≈ 0~360°)

SET_PHASE_VIA_BEAM_TABLE = False         # 위상까지 설정할지 (아래 ⚠ 주의 참고). 기본 False.

# -------------------------------------------------------------------------------------
# 보조 함수 : "h0" → (pol='h', idx=0)
# -------------------------------------------------------------------------------------
def parse_ch(ch):
    return ch[0].lower(), int(ch[1])     # 'h', 0

BN = BEAM[-1]                            # "b0" → "0",  필드 이름 suffix 로 사용


# -------------------------------------------------------------------------------------
# 1. IC BRING-UP  (chip 생성 + 초기화 + 통신 확인)
# -------------------------------------------------------------------------------------
chip = Stampede(chip_id=CHIP_ID)
chip.init()                              # reset → 전체 레지스터 read → eFuse 시퀀스 적용

ver = chip.fields.rd("version_id")       # 하드와이어 버전 ID. 정상 칩이면 0xDC
print(f"[bring-up] version_id = {hex(ver)}  ->", "OK" if ver == 0xDC else "NG (통신 확인 필요)")

# 대량 설정이므로 auto-commit 끄고 마지막에 한 번에 flush (SPI 트래픽 최소화)
chip.cfg.set_auto_commit(False)


# -------------------------------------------------------------------------------------
# 2. 채널 활성화 (경로 설정)
#    path.enable() 한 번이 routing + center(common) + bias 까지 자동 enable 합니다.
#    → 선택한 채널들이 BEAM 포트로 연결됨.  TX: 신호 BEAM → 안테나 채널로 분배
# -------------------------------------------------------------------------------------
chip.path.enable(ACTIVE_CH, BEAM)
print(f"[enable ] {ACTIVE_CH} -> {BEAM}")


# -------------------------------------------------------------------------------------
# 3. 주파수 (보정 대역 선택)
#    Cloudchaser는 LO 주파수를 칩에서 직접 설정하지 않고, 채널/빔별로
#    'cal frequency band'를 선택합니다 (ch{n}_cal_freq_sel_beam{n}).
#    실제 RF 주파수는 외부 신호원(SMW 등)에서 인가하고, 여기서는 보정 대역만 맞춥니다.
# -------------------------------------------------------------------------------------
for ch in ACTIVE_CH:
    pol, idx = parse_ch(ch)
    chip.fields.wr(f"ch{idx}_cal_freq_sel_beam{BN}", FREQ_CODE)
print(f"[freq   ] cal_freq_sel = {hex(FREQ_CODE)} (beam{BN}, all active ch)")


# -------------------------------------------------------------------------------------
# 4. 게인
#    (a) 빔 공통 게인  : 결합 후 빔 전체에 적용  (b{n}_common_gain)
#    (b) 채널별 게인   : 채널 단위 게인 단     (gain_control_{pol}{idx})
# -------------------------------------------------------------------------------------
chip.fields.wr(f"b{BN}_common_gain", COMMON_GAIN)          # (a)
for ch in ACTIVE_CH:                                        # (b)
    pol, idx = parse_ch(ch)
    chip.fields.wr(f"gain_control_{pol}{idx}", CH_GAIN[ch])
print(f"[gain   ] common={hex(COMMON_GAIN)},  per-ch={CH_GAIN}")


# -------------------------------------------------------------------------------------
# 5. 감쇠 (attenuator)
#    채널-빔별 디지털 감쇠기 (ch{n}_{pol}_b{n}_attn_cal). 6-bit.
#    빔 진폭 테이퍼/보정에 사용. 코드↔dB 환산은 데이터시트 참고.
# -------------------------------------------------------------------------------------
for ch in ACTIVE_CH:
    pol, idx = parse_ch(ch)
    chip.fields.wr(f"ch{idx}_{pol}_b{BN}_attn_cal", CH_ATTEN[ch])
print(f"[atten  ] attn_cal = {CH_ATTEN}")


# -------------------------------------------------------------------------------------
# 6. 모든 설정 하드웨어로 flush (auto-commit 껐으므로 여기서 한 번에 전송)
# -------------------------------------------------------------------------------------
chip.commit()
chip.cfg.set_auto_commit(True)
print("[commit ] 위 모든 레지스터 설정 전송 완료")


# -------------------------------------------------------------------------------------
# 7. 위상 (phase)  ⚠ 주의
#    이 칩의 빔포밍 위상은 'beam table'(빔 계수 세트)에 들어갑니다:
#       beam word :  attenuator_setting[0:5], phase_shifter_setting[7:13]
#    현재 공식 API의 beam_table 인터페이스는 "미검증(use with caution)" 상태입니다.
#    또한 beam table은 (beam_index, quad) 단위라 quad 내 H/V 분리 매핑은 데이터시트로
#    반드시 확인하세요. 아래는 구조 예시 템플릿입니다 (기본 비활성).
# -------------------------------------------------------------------------------------
if SET_PHASE_VIA_BEAM_TABLE:
    bt = chip.beam_table
    bt.zero_table(commit=False)
    BEAM_INDEX = 0                                  # 사용할 빔 계수 세트 인덱스
    for ch in ACTIVE_CH:
        pol, idx = parse_ch(ch)
        quad = idx                                  # h0/v0 → quad0 ...  (H/V 매핑 확인 필요)
        atn = CH_ATTEN[ch] & 0x3F                   # 6-bit
        ph  = CH_PHASE[ch] & 0x7F                   # 7-bit
        bt.tmp_table[BEAM_INDEX, quad] = atn | (ph << 7)
    bt.update_table(BEAM_INDEX, BEAM_INDEX)         # tmp → table 반영
    bt.commit_table(BEAM_INDEX, BEAM_INDEX)         # 디바이스로 기록
    # 빔 계수는 BEAM_UPDATE 펄스가 와야 출력에 반영됩니다 (latch).
    chip.spi.beam_up()
    print(f"[phase  ] beam table idx {BEAM_INDEX} 기록 + beam_update (⚠ 미검증 인터페이스)")
else:
    print("[phase  ] SKIP (SET_PHASE_VIA_BEAM_TABLE=False)")


# -------------------------------------------------------------------------------------
# 8. 검증 — 쓴 값이 실제로 반영됐는지 되읽기
# -------------------------------------------------------------------------------------
print("\n[verify] readback:")
print(f"  common_gain        = {hex(chip.fields.rd(f'b{BN}_common_gain'))}")
for ch in ACTIVE_CH:
    pol, idx = parse_ch(ch)
    g = chip.fields.rd(f"gain_control_{pol}{idx}")
    a = chip.fields.rd(f"ch{idx}_{pol}_b{BN}_attn_cal")
    print(f"  {ch}: gain={hex(g)}  atten={hex(a)}")
print("  active paths:", chip.path.active)

# 전체 필드 상태를 CSV로 저장하고 싶으면:
# chip.fields.dump(update=True, save_to_file=True, filename="tx_state.csv")

print("\nDone. 외부 신호원에서 RF 인가 후 측정하세요.")
