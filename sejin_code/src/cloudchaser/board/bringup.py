"""Stampede(TX)/Blueway(RX) 보드 bring-up(초기화·구성) 로직.

TX(`bring_up_tx`)/RX(`bring_up_rx`) 모두 벤더 고수준 API 대신 `FH` raw 레지스터
엔진으로 MATLAB firehawk 시퀀스를 그대로 기입한다(TX 20단계 / RX 10단계). 근거·
시퀀스 정본:
  docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md 4장
레지스터 결과는 `tests/data/golden_regs_tx_v1_split.csv` / `golden_regs_rx_h0.csv`
골든으로 고정돼 있다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bias_measured import apply_measured_bias_bringup
from .bias_v4 import NF_OPTIM_CAPTUNE, apply_dist_bias, apply_fe_bias
from .firehawk import (
    FH,
    ADC_SET_ADDR,
    BEAM_CAL_ADDR,
    COMMON_GAIN,
    FE_GAIN_ADDR,
    SHORT_ID_ADDR,
    VERSION_ID_RX,
    VERSION_ID_TX,
    fe_row,
    parse_ch,
)

# 정상 칩이면 version_id 가 고정값으로 읽힌다. SPI 통신이 살아있는지 점검하는 값.
#   TX(Stampede) = 0xDC.
#   RX(Blueway)  = 0xD4 -- 실측 확정(20회 고정 + unique_id=0x00250b7b 정상 -> SPI OK).
# firehawk 모듈이 정본이고, 아래 두 이름은 하위호환 별칭이다(session.py 등이 import).
VERSION_ID_OK = VERSION_ID_TX       # TX (Stampede)
VERSION_ID_OK_RX = VERSION_ID_RX    # RX (Blueway)

# bring-up 마지막에 그대로 기입하는 하드코딩 레지스터 (MATLAB Func/Meas 검증값).
# 0x104D 는 cfg.dist_st2_1_ptat 로 계산하므로 여기 없다(스펙 5장 "열린 항목").
DIRECT_REGS_TX = {0x104C: 3378, 0x1050: 1542, 0x1051: 6,
                  0x1052: 8, 0x1058: 8, 0x1059: 11}
# split_mode=True 일 때 direct regs 다음에 추가 기입 (MATLAB Split func).
# 필드 해석 근거: docs/sivers_unified_api_v0.1.0/register_maps/Cloudchaser_Stampede_register_map.xlsx
#   0x1009=783(0x30F) = center_dist_b0. split 을 가르는 것은 이 워드다:
#     [3:0]  dist_b0_st1_en   = 0xF  -> beam0 분배망을 CH0..CH3 전부 enable(= 다채널 결합).
#                                      thru(단일 채널)면 활성 채널 비트만 선다.
#     [8]    center_bias_beam0_en = 1
#     [13:9] beam0_pwrdn      = 0x1  (TX 값)
#     ★ 앞서 쓴 beam_enables 를 덮는다. 그리고 이 주소는 b0 전용이다
#       (center_dist_b{n} = 0x1009+n) -- cfg.beam 이 b1/b2 여도 b0 워드를 쓴다.
#       Doosan 260729 레퍼런스 설정이 b0 라 드러나지 않은 부분. 실칩 확인 전까지는
#       split 은 b0 에서만 쓴다.
#   0x1068=0x8888    = ch0_captune (CH0 H/V combiner in/out captune). 레지스터 맵 기준
#     0x1068~0x106B 가 CH0~CH3 captune 이고, firehawk.set_captune() 이 쓰는 블록의
#     첫 워드다. 즉 이 write 는 앞서 set_captune([0,0,0,0]) 으로 0 을 채운 CH0 만
#     되돌린다(CH1~3 은 0 유지). 값 분해: h_comb_out=1, v_comb_out=1, in 쪽은 0
#     (bit 7/15 는 맵에 정의된 필드 밖).
#     ⚠️ 예전 주석은 이 워드를 "DIST St1<->St2 단간 captune" 이라고 적었는데 틀렸다.
#        MATLAB 원본에서 DIST St1<->St2 captune 은 extra_misc 필드(<6:0>, beam 별 2-bit)다.
SPLIT_REGS_TX = {0x1009: 783, 0x1068: 0x8888}

def apply_split_mode(fh, cfg, *, kind: str = "tx", log=print) -> bool:
    """cfg.split_mode 가 켜져 있으면 SPLIT_REGS_TX 를 (다시) 기입한다. 적용 여부 반환.

    bring-up 끝에서 한 번 부르고, **채널 라우팅을 바꾼 뒤에도 다시** 불러야 한다.
    route_channels() 가 0x1009(center_dist_b0)를 그 채널 분기만 남기도록 다시 쓰기
    때문이다 -- 그러면 bring-up 이 걸어둔 split(dist_b0_st1_en=0xF)이 조용히 풀린다.
    실측에서 이 차이가 게인 8 dB 로 나타났다(1:4 분배 -> 10*log10(4) + 분배망 손실).

    kind 는 호출부가 넘긴다(TX 전용 설정이라 RX 면 아무것도 안 한다). 여기서
    chip_kind(fh) 를 직접 읽지 않는 이유: bring_up_tx 는 이미 자기가 TX 인 걸 알고,
    identity 를 아직 안 읽은 상태(require_version=False 경로)에서 부르면 판별이
    실패한다. 라우팅 헬퍼들은 route_channels 에 넘기려고 어차피 kind 를 들고 있다.
    """
    if not getattr(cfg, "split_mode", False) or kind != "tx":
        return False
    for addr in sorted(SPLIT_REGS_TX):
        fh.wr_verify(addr, SPLIT_REGS_TX[addr])
    log("[split  ] DIST split mode ON (0x1009=783, 0x1068=0x8888)")
    return True


# RX bring-up 마지막에 그대로 기입하는 하드코딩 레지스터 (MATLAB Meas_260724_BLWY01).
DIRECT_REGS_RX = {0x1004: 31, 0x1058: 0x8888, 0x1068: 0x8888, 0x1059: 4}


@dataclass
class BoardConfig:
    """보드 bring-up 에 필요한 설정 묶음(bench.toml 의 [board] 섹션에서 채워진다).

    chip_id         : 보드 strap 으로 정해지는 칩 ID(보통 0)
    beam            : 사용할 빔 포트("b0" 또는 "b1")
    active_channels : 활성화할 안테나 채널 목록(예: ["h0","h1","h2","h3"])
    cal_freq_code   : 보정 주파수 대역 선택 코드(데이터시트 표 기준)
    common_gain     : 빔 공통 게인 코드(6-bit 감쇠, 0=최대 게인). 기본 0 --
                      bring-up 은 이 값을 B0/B1/B2 세 워드(0x1005~0x1007)에
                      모두 기입한다.
    ch_gain         : (TX) 채널별 게인 코드 {"h0": 0x8, ...} — Stampede gain_control_*
    ch_atten        : 채널별 감쇠 코드 {"h0": 0x00, ...} — *_attn_cal (TX/RX 공통)
    ch_fe_attn      : (RX) 채널별 FE 감쇠 코드 {"h1": 0x0, ...} — Blueway ch{i}_{pol}_fe_attn
                      (4-bit, 8 dB/bit, 0=무감쇠=최대 게인). Blueway 엔 gain_control 이
                      없어 채널 레벨을 이 FE 감쇠기로 잡는다.
    split_mode      : (TX) DIST 스플리터 split 모드 -> 0x1009=783, 0x1068=0x8888
    optimized_bias  : v4 시트 Casper/NF_OPTIM 적용 (False = eFuse 기본값)
    dist_st2_1_ptat : 0x104D[5:0]. 13=시트 v4 / 28=기존 MATLAB
    run_efuse_init  : True 면 벤더 init 호출(chip.init, load_efuse 실행)
    measured_bias   : bench.toml [board.bias.<ch>] -- bias_match 로 이 보드에서
                      직접 찾은 채널별 코드 {"h0": {"ptat": [...], "dist": [...]}}.
                      bring-up 의 마지막 쓰기 단계에서 v4 Casper 위에 덮는다.
    """

    chip_id: int = 0
    beam: str = "b0"
    active_channels: list[str] = field(default_factory=lambda: ["h0", "h1", "h2", "h3"])
    cal_freq_code: int = 0x0
    common_gain: int = 0x00
    ch_gain: dict[str, int] = field(default_factory=dict)
    ch_atten: dict[str, int] = field(default_factory=dict)
    ch_fe_attn: dict[str, int] = field(default_factory=dict)
    split_mode: bool = True          # (TX) DIST 스플리터 split 모드 -> 0x1009=783, 0x1068=0x8888
    optimized_bias: bool = True      # v4 시트 Casper/NF_OPTIM 적용 (False = eFuse 기본값)
    dist_st2_1_ptat: int = 13        # 0x104D[5:0]. 13=시트 v4 / 28=기존 MATLAB
    run_efuse_init: bool = False
    measured_bias: dict = field(default_factory=dict)     # True 면 벤더 init 호출(chip.init, load_efuse 실행)


def _cal_matrix(cfg):
    """cal atten 4x2x3. 기본 0, cfg.ch_atten 에 값이 있으면 해당 채널·편파 전 빔에 기입."""
    cal = [[[0, 0, 0], [0, 0, 0]] for _ in range(4)]
    for ch, code in (cfg.ch_atten or {}).items():
        pol, ci = parse_ch(ch)
        hv = 1 if pol == "v" else 0
        cal[ci][hv] = [int(code)] * 3
    return cal


def _extra_code(beam_i):
    """extra_bias_code 1x4. 활성 beam=8, 비활성=1, B2=14, misc=0 (MATLAB Func)."""
    code = []
    for b in range(3):
        if b == 2:
            code.append(14)
        elif b == beam_i:
            code.append(8)
        else:
            code.append(1)
    code.append(0)
    return code


def _efuse_only_fe(efuse_bias, active_channels):
    """optimized_bias=False: 활성 채널 행만 eFuse 값 그대로, 나머지 0."""
    out = [[0, 0, 0, 0, 0] for _ in range(8)]
    for ch in active_channels:
        pol, ci = parse_ch(ch)
        r = fe_row(ci, pol)
        out[r] = list(efuse_bias[r])
    return out


def _efuse_only_dist(efuse_dist, beam_idx, kind):
    """optimized_bias=False: 활성 빔 행만 eFuse 값, TX 는 B2 PTAT=[6,6,6]."""
    out = [[0, 0, 0, 0, 0, 0] for _ in range(3)]
    out[beam_idx] = list(efuse_dist[beam_idx])
    if kind == "tx":
        out[2][0:3] = [6, 6, 6]
    return out


def _efuse_readback(chip, fh):
    """die eFuse 트림(FE 8x5, DIST 3x6, CTAT)을 읽되 칩 객체에 한 번만 캐시한다.

    bring-up 은 비활성 채널/빔 행을 0 으로 기입한다. `fh.reset()` 은 SPI 엔진 리셋이지
    칩 리셋(POR)이 아니라서, 같은 칩 객체로 채널을 바꿔 bring-up 을 다시 돌리면 두 번째
    `get_fe_bias()` 가 앞서 쓴 0 을 "eFuse 리드백"으로 읽는다 -- 그러면 스펙의
    "CTAT/CBIAS 는 die eFuse 값 유지" 규칙이 두 번째 실행부터 깨지고, 방금 끈 채널의
    트림이 영구히 사라진다. 그래서 첫 리드백을 스냅샷으로 잡아두고 이후 bring-up 이
    그걸 재사용한다.

    캐시는 chip 객체 단위다(모듈 전역이 아니다) -- 새 chip 객체는 새 칩일 수 있고,
    fake SPI 는 전 칩이 같은 unique_id(0)를 주므로 전역 캐시는 서로 다른 fake 칩의
    값을 섞어버린다. 즉 `session.restart()` 처럼 chip 을 새로 만드는 경로는 여전히
    새로 읽는다 -- 채널을 바꿔 다시 bring-up 하려면 전원 사이클이 필요하다
    (docs/SESSION.md 참고). 첫 실행 동작은 그대로라 골든 레지스터는 안 바뀐다.

    반환: (fe 8x5, dist 3x6, ctat) -- 호출부가 마음대로 수정해도 캐시가 상하지 않게
    매번 복사본을 준다.
    """
    if getattr(chip, "_efuse_fe", None) is None:
        chip._efuse_fe = fh.get_fe_bias()
        chip._efuse_dist, chip._efuse_dist_ctat = fh.get_dist_bias()
    return ([list(r) for r in chip._efuse_fe],
            [list(r) for r in chip._efuse_dist],
            chip._efuse_dist_ctat)


def bring_up_tx(chip, cfg: BoardConfig, *, require_version: bool = True, log=print) -> dict:
    """Configure a Stampede(TX) board to the measurement-ready state.

    Writes raw registers through chip.spi (MATLAB firehawk sequence); the
    vendor high-level API is not used on the write path. See the design spec
    for why: docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md

    chip            : sivers_api.Stampede instance (caller decides fake_spi)
    require_version : True -> raise when version_id != 0xDC (real hardware)
    returns         : readback summary dict
    """
    fh = FH(chip, cfg.chip_id)
    chip._fh = fh                      # 세션/테스트 항목이 재사용한다
    beam_i = int(cfg.beam[-1])
    active = [c.strip().lower() for c in cfg.active_channels]

    # 0. 벤더 API 시절 적용하던 두 knob 은 raw 시퀀스의 기입 대상이 아니다
    #    (스펙 4장 TX 표에 FE gain / cal_freq 단계가 없고 evb_full 도 안 쓴다).
    #    ch_gain 기본 0x8 -> 0 은 실제 RF 동작이 바뀌는 변화라 조용히 버리면 안 된다.
    #    기본값이면 아무것도 찍지 않아 평소 실행은 그대로 조용하다.
    ignored = []
    if cfg.ch_gain:
        ignored.append("ch_gain=" + repr(dict(cfg.ch_gain)))
    if cfg.cal_freq_code:
        ignored.append(f"cal_freq_code={hex(cfg.cal_freq_code)}")
    if ignored:
        log("[bring-up] note: ch_gain / cal_freq_code from bench.toml are no longer applied")
        log("           (raw sequence matches evb_full, which sets neither) -- "
            "values ignored: " + ", ".join(ignored))

    # 1. reset. 벤더 chip.init() 은 load_efuse() 로 레지스터를 건드리므로 기본으로 안 쓴다.
    if cfg.run_efuse_init:
        chip.init()
    else:
        fh.reset()

    # 2. 통신 확인
    _, ver = fh.get_short_id()
    ok = ver == VERSION_ID_TX
    log(f"[bring-up] version_id = {hex(ver)} -> {'OK' if ok else 'NG'}")
    if not ok and require_version:
        raise RuntimeError(
            f"version_id {hex(ver)} != {hex(VERSION_ID_TX)} -> check SPI link / board"
        )

    # 3~8. 공통 설정
    fh.zero_phase_cal()                       # ★ RTPS fine-phase 전제
    fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    fh.set_common_gains([cfg.common_gain] * 3)
    fh.set_cal(_cal_matrix(cfg))
    fh.load_beam_table(0, [[0, 0, 0, 0, 0, 0, 0, 0]])
    fh.beam_up()
    fh.set_captune([0, 0, 0, 0])

    # 9~10. bias (eFuse 리드백 위에 v4 최적화값을 얹는다)
    efb, edb, ectat = _efuse_readback(chip, fh)
    if cfg.optimized_bias:
        fh.set_fe_bias(apply_fe_bias(efb, active, "tx"))
        fh.set_dist_bias(apply_dist_bias(edb, beam_i, "tx", cfg.dist_st2_1_ptat), ectat)
    else:
        fh.set_fe_bias(_efuse_only_fe(efb, active))
        fh.set_dist_bias(_efuse_only_dist(edb, beam_i, "tx"), ectat)

    # 11~13
    fh.set_extra(_extra_code(beam_i))
    fh.set_temp_sensor([8, 8], [1, 1])
    fh.wr_verify(0x1004, 0x000F)              # daisy amp ctrl
    fh.wr_verify(ADC_SET_ADDR, 0x0021)        # ADC clk
    fh.wr_verify(ADC_SET_ADDR + 1, 0x4100)    # ADC enable(temp) + rst

    # 14. quad enables
    enbit = 1 << beam_i
    qen = [[0, 0, 0] for _ in range(4)]
    for ch in active:
        _, ci = parse_ch(ch)
        qen[ci] = [enbit, enbit, 0]
    fh.set_quad_enables(qen)

    # 15. staged power-up (bias only -> +PA/DRV -> +combiner)
    def _pwrdn(stage_bits_fn):
        rows = [[0, 0, 0, 0, 0] for _ in range(4)]
        for ch in active:
            pol, ci = parse_ch(ch)
            # TX(Stampede)는 quad_pwrdn 의 H/V 비트 위치가 RX와 반대다
            # (REGISTERS.md: TX h=[5:3]/v=[2:0]). 그래서 V=bits0-2, H=bits3-5.
            base = 0 if pol == "v" else 3
            rows[ci] = [stage_bits_fn(base), 1, 1, 0, 0]
        return rows

    fh.set_quad_pwrdn(_pwrdn(lambda b: 0))
    fh.set_quad_pwrdn(_pwrdn(lambda b: 0b011 << b))
    fh.set_quad_pwrdn(_pwrdn(lambda b: 0b111 << b))

    # 16~17. beam enables (splitter bias only -> +amp)
    be1 = [[0, 0, 0, 0] for _ in range(3)]
    be1[beam_i] = [0, 1, 0, 0]
    fh.set_beam_enables(be1)
    chan_mask = 0
    for ch in active:
        _, ci = parse_ch(ch)
        chan_mask |= 1 << ci
    be2 = [[0, 0, 0, 0] for _ in range(3)]
    be2[beam_i] = [chan_mask, 1, 1, 0]
    fh.set_beam_enables(be2)

    # 18~19. 하드코딩 레지스터 + split
    direct = dict(DIRECT_REGS_TX)
    direct[0x104D] = (int(cfg.dist_st2_1_ptat) & 0x3F) | (6 << 9)   # [5:0] ptat, [11:9] cbias
    for addr in sorted(direct):
        fh.wr_verify(addr, direct[addr])
    apply_split_mode(fh, cfg, log=log)

    # 19-b. 실측 bias 덮어쓰기 -- 반드시 DIRECT_REGS/split 다음이다. DIRECT_REGS_TX 가
    #       0x104C 에 v4 Casper DIST 를 하드코딩으로 넣으므로, 그 앞에서 쓰면 지워진다.
    apply_measured_bias_bringup(fh, cfg, active, beam_idx=beam_i, log=log)

    # 20. readback 요약 (기존 반환 계약 유지)
    summary: dict = {"version_id": ver, "channels": {}}
    summary["common_gain"] = fh.rd(COMMON_GAIN + beam_i) & 0x3F     # 6-bit field
    for ch in active:
        pol, ci = parse_ch(ch)
        # FE gain 은 4-bit (H=[3:0], V=[11:8]). bit12 는 pulse_en 이라 마스크로 거른다.
        w = fh.rd(FE_GAIN_ADDR + ci)
        g = (w >> 8) & 0xF if pol == "v" else w & 0xF
        # cal atten 은 (hv, beam) 을 평탄화해 2개씩 한 워드에 담는다(FH.set_cal 참조):
        #   flat = hv*3 + beam -> 워드 BEAM_CAL_ADDR + (flat//2)*4 + ch, 바이트 flat%2
        flat = (3 if pol == "v" else 0) + beam_i
        # attn_cal 은 4-bit 다 (ch{i}_{pol}_b{n}_attn_cal = 0x105C[3:0] / [11:8]).
        a = (fh.rd(BEAM_CAL_ADDR + (flat // 2) * 4 + ci) >> (8 * (flat % 2))) & 0xF
        summary["channels"][ch] = {"gain": g, "atten": a}
        log(f"  {ch}: gain={hex(g)} atten={hex(a)}")
    summary["active_paths"] = list(active)
    log(f"[verify ] active paths: {summary['active_paths']}")
    return summary

def make_chip(cfg: BoardConfig, *, fake: bool):
    """sivers_api.Stampede 객체를 생성한다.

    fake=True 면 fake_spi 모드로 만들어 하드웨어(FTDI 동글) 없이도 동작한다.
    import 를 함수 안에서 하는 이유: sivers_api 가 없는 환경(테스트 등)에서도
    이 모듈 자체는 import 되게 하기 위함.

    fake 모드에서는 0x1000(identity) 도 심는다. 실칩은 이 필드가 읽기 전용이라
    항상 올바른 값을 주지만 Fake_SPI 는 전 레지스터 0 으로 시작한다 --
    gain_map.chip_kind() 의 런타임 TX/RX 판별(Ruling 21, manual.chan() 등이 의존)이
    fake 모드에서도 동작하려면 필요하다. bring_up_tx 자신은 이 주소를 읽기만
    하므로(쓰지 않으므로) 골든 레지스터 비교에는 영향 없다.
    """
    from sivers_api import Stampede

    chip = Stampede(chip_id=cfg.chip_id, fake_spi=fake)
    if fake:
        FH(chip, cfg.chip_id).wr(SHORT_ID_ADDR, (VERSION_ID_TX << 8) | 0x11)
    return chip


def bring_up_rx(chip, cfg: BoardConfig, *, require_version: bool = True, log=print) -> dict:
    """Configure a Blueway(RX) board to the measurement-ready state.

    Writes raw registers through chip.spi (MATLAB firehawk sequence); the
    vendor high-level API is not used on the write path. See the design spec
    for why: docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md

    Single-channel oriented (uses cfg.active_channels[0]); generalized from the
    MATLAB Meas_260724_BLWY01 H0B0 sequence.

    chip            : sivers_api.Blueway instance (caller decides fake_spi)
    require_version : True -> raise when version_id != 0xD4 (real hardware)
    returns         : readback summary dict
    """
    fh = FH(chip, cfg.chip_id)
    chip._fh = fh                      # 세션/테스트 항목이 재사용한다
    beam_i = int(cfg.beam[-1])
    active = [c.strip().lower() for c in cfg.active_channels]
    ch = active[0]
    pol, ci = parse_ch(ch)

    # 0. 벤더 API 시절 적용하던 네 knob 은 raw 시퀀스의 기입 대상이 아니다
    #    (스펙 4장 RX 표에 fe_attn / cal_freq / common_gain / cal_atten 단계가 없고
    #    evb_full 의 bring_up_rx 도 그중 어느 것도 쓰지 않는다). Ruling 13: TX 의
    #    Ruling 10 과 같은 결함 종류(bench.toml 에 살아있는 knob 처럼 보이지만
    #    아무 효과가 없는 것)이므로 common_gain / ch_atten 도 같이 로그한다.
    #    bench_rx.toml 이 common_gain 을 0 이 아닌 값으로 두면 stock 설정에서도
    #    이 로그는 매번 찍힌다 -- 의도된 동작이다(조용히 숨기지 않는다).
    ignored = []
    if cfg.ch_fe_attn:
        ignored.append("ch_fe_attn=" + repr(dict(cfg.ch_fe_attn)))
    if cfg.cal_freq_code:
        ignored.append(f"cal_freq_code={hex(cfg.cal_freq_code)}")
    if cfg.common_gain:
        ignored.append(f"common_gain={hex(cfg.common_gain)}")
    if cfg.ch_atten:
        ignored.append("ch_atten=" + repr(dict(cfg.ch_atten)))
    if ignored:
        log("[bring-up] note: ch_fe_attn / cal_freq_code / common_gain / ch_atten "
            "from bench.toml are no longer applied")
        log("           (raw sequence matches evb_full, which sets none of them) -- "
            "values ignored: " + ", ".join(ignored))

    # 1. reset. 벤더 chip.init() 은 load_efuse() 로 레지스터를 건드리므로 기본으로 안 쓴다.
    if cfg.run_efuse_init:
        chip.init()
    else:
        fh.reset()

    # 2. 통신 확인
    _, ver = fh.get_short_id()
    ok = ver == VERSION_ID_RX
    log(f"[bringup] version_id = {hex(ver)} -> {'OK' if ok else 'NG'}")
    if not ok and require_version:
        raise RuntimeError(
            f"version_id {hex(ver)} != {hex(VERSION_ID_RX)} -> check SPI link / board"
        )

    # 3. bias 를 enable 보다 먼저 기입한다(MATLAB 순서, eFuse 리드백 위에 v4 최적화값을 얹는다).
    efb, edb, ectat = _efuse_readback(chip, fh)
    if cfg.optimized_bias:
        fh.set_fe_bias(apply_fe_bias(efb, active, "rx"))
        fh.set_dist_bias(apply_dist_bias(edb, beam_i, "rx", cfg.dist_st2_1_ptat), ectat)
    else:
        fh.set_fe_bias(_efuse_only_fe(efb, active))
        fh.set_dist_bias(_efuse_only_dist(edb, beam_i, "rx"), ectat)

    # 4~9. 하드코딩 enable (MATLAB 검증값 일반화)
    fh.wr_verify(0x1004, 31)
    fh.set_center_enables([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])      # 0x1008 = 7
    be = [[0, 0, 0, 0] for _ in range(3)]
    be[beam_i] = [1 << ci, 1, 4, 0]
    fh.set_beam_enables(be)
    qen = [[0, 0, 0] for _ in range(4)]
    qen[ci] = [1 << beam_i, 1 << beam_i, 0]
    fh.set_quad_enables(qen)
    # RX 는 TX 와 반대: H=[2:0], V=[5:3].
    pwr = 0b000111 if pol == "h" else 0b111000
    qpd = [[0, 1, 0, 0, 0] for _ in range(4)]                  # 그 외 quad 는 override 만(64)
    qpd[ci] = [pwr, 1, 1, 0, 0]
    fh.set_quad_pwrdn(qpd)
    fh.set_captune([NF_OPTIM_CAPTUNE, 0, 0, 0])

    # 10. 하드코딩 레지스터
    for addr in sorted(DIRECT_REGS_RX):
        fh.wr_verify(addr, DIRECT_REGS_RX[addr])

    # readback 요약 (기존 반환 계약 유지)
    summary: dict = {"version_id": ver, "channels": {}}
    summary["common_gain"] = fh.rd(COMMON_GAIN + beam_i) & 0x3F     # 6-bit field
    # FE gain 은 4-bit (H=[3:0], V=[11:8]). bit12 는 pulse_en 이라 마스크로 거른다.
    w = fh.rd(FE_GAIN_ADDR + ci)
    g = (w >> 8) & 0xF if pol == "v" else w & 0xF
    # cal atten 은 (hv, beam) 을 평탄화해 2개씩 한 워드에 담는다(FH.set_cal 참조, TX 와 동일 인덱싱):
    #   flat = hv*3 + beam -> 워드 BEAM_CAL_ADDR + (flat//2)*4 + ch, 바이트 flat%2
    # RX bring-up 시퀀스는 BEAM_CAL_ADDR 를 기입하지 않으므로(스펙 4장 RX 표에 단계 없음)
    # 이건 그 위치의 리드백일 뿐이다(보통 0).
    flat = (3 if pol == "v" else 0) + beam_i
    # attn_cal 은 4-bit 다 (ch{i}_{pol}_b{n}_attn_cal = 0x105C[3:0] / [11:8]).
    a = (fh.rd(BEAM_CAL_ADDR + (flat // 2) * 4 + ci) >> (8 * (flat % 2))) & 0xF
    summary["channels"][ch] = {"fe_attn": g, "atten": a}
    log(f"  {ch}: fe_attn={hex(g)} atten={hex(a)}")
    summary["active_paths"] = list(active)
    log(f"[verify ] active paths: {summary['active_paths']}")
    return summary


def make_chip_rx(cfg: BoardConfig, *, fake: bool):
    """sivers_api.Blueway 객체를 생성한다.

    fake=True 면 fake_spi 모드로 만들어 하드웨어 없이도 동작한다.
    import 를 함수 안에서 하는 이유: sivers_api 가 없는 환경(테스트 등)에서도
    이 모듈 자체는 import 되게 하기 위함.

    fake 모드에서는 0x1000(identity, RX=0xD4) 도 심는다 -- make_chip() 의 TX
    쪽과 동일한 이유(Ruling 21의 chip_kind() 런타임 판별용).
    """
    from sivers_api import Blueway

    chip = Blueway(chip_id=cfg.chip_id, fake_spi=fake)
    if fake:
        FH(chip, cfg.chip_id).wr(SHORT_ID_ADDR, (VERSION_ID_RX << 8) | 0x11)
    return chip
