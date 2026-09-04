r"""cloudchaser bring-up 의 레지스터 결과가 evb_full.py 골든과 일치하는지 검증.

골든 픽스처: tests/data/golden_regs_tx_v1_split.csv
  = TX / channels=["v1"] / beam="b0" / split_mode=True 로 bring-up 한 뒤의
    0x1000~0x106F 덤프(112워드). 생성 원본은 다른 repo 의 검증된 스크립트
    C:\claude_code\Sivers_EVB\evb_full.py 다 (읽기 전용 -- 절대 수정하지 말 것).

--- 골든 재생성 절차 (그대로 실행 가능) ---------------------------------------

설계 스펙 12장이 요구하는 대로 0x104D 의 13-vs-28 을 실하드웨어로 확정하면
골든을 다시 떠야 한다. evb_full.py 파일은 건드리지 말고 모듈 전역만 런타임에
대입한다. 아래를 gen_golden.py 로 저장하고 실행한다:

    # gen_golden.py
    import sys
    sys.path.insert(0, r'C:\claude_code\Sivers_EVB')
    import evb_full as E
    # 골든은 결정적이어야 한다: eFuse 리드백 대신 명시 행렬을 쓴다.
    # 행 3 = v1 (fe_row(1,'v') = 3). PTAT=Casper(15/45/55), CTAT/CBIAS=MockSPI 시드(32/5).
    fe = [[0, 0, 0, 0, 0] for _ in range(8)]
    fe[3] = [15, 45, 55, 32, 5]
    E.FE_BIAS_MATRIX = fe
    E.DIST_BIAS_MATRIX = [[50, 13, 13, 6, 1, 1], [0] * 6, [6, 6, 6, 0, 0, 0]]
    # 스펙 5장 "열린 항목": 0x104D[5:0] 는 시트 v4 Casper=13 을 기본으로 한다.
    # evb_full 의 하드코딩 3100 은 MATLAB 값(28)이라 우리 사양과 다르다. [11:9]=6 은 동일.
    E.DIRECT_REGS_TX = dict(E.DIRECT_REGS_TX)
    E.DIRECT_REGS_TX[0x104D] = (13 & 0x3F) | (6 << 9)      # = 3085
    E.bringup(kind='tx', fake=True)
    E.dump(a=0x1000, b=0x1070,
           save=r'C:\claude_code\cloudchaser\tests\data\golden_regs_tx_v1_split.csv',
           quiet=True)

실행 (PowerShell, cloudchaser repo 루트에서):

    New-Item -ItemType Directory -Force tests\data
    .\.venv\Scripts\python.exe gen_golden.py

기대 출력: "dumped 112 regs 0x1000..0x106F -> ...".
CSV 는 헤더 'addr,value' 포함 113줄이어야 한다.
BoardConfig.dist_st2_1_ptat 기본값을 바꾸면 위 3085 도 같이 바꿔 재생성할 것.

--- RX 골든 재생성 절차 (그대로 실행 가능) ------------------------------------

RX 골든(tests/data/golden_regs_rx_h0.csv)은 channels=["h0"] / beam="b0" /
optimized_bias=True 로 bring-up 한 뒤의 0x1000~0x106F 덤프다. evb_full.py 에는
NF_OPTIM 코드가 없으므로(cloudchaser 만의 v4 확장), FE_BIAS_MATRIX/DIST_BIAS_MATRIX
를 "eFuse 리드백 위에 NF_OPTIM 을 얹은 결과"로 직접 채워 넣는다 -- 즉
apply_fe_bias/apply_dist_bias(kind="rx") 가 만들 값을 미리 계산해 대입한다.
아래를 gen_golden_rx.py 로 저장하고 실행한다:

    # gen_golden_rx.py
    import sys
    sys.path.insert(0, r'C:\claude_code\Sivers_EVB')
    import evb_full as E
    fe = [[0, 0, 0, 0, 0] for _ in range(8)]
    fe[0] = [34, 24, 48, 32, 5]      # row 0 = h0 (fe_row(0,'h')=0)
    #   PTAT=NF_OPTIM(34/24/48), CTAT/CBIAS=MockSPI eFuse 시드(32/5)
    E.FE_BIAS_MATRIX = fe
    E.DIST_BIAS_MATRIX = [[44, 13, 14, 1, 1, 1], [0] * 6, [0] * 6]
    #   beam0: PTAT1=NF_OPTIM(44), 나머지(13/14/1/1/1)=MockSPI eFuse 시드
    E.bringup(kind='rx', channels=['h0'], fake=True)
    E.dump(a=0x1000, b=0x1070,
           save=r'C:\claude_code\cloudchaser\tests\data\golden_regs_rx_h0.csv',
           quiet=True)

실행 (PowerShell, cloudchaser repo 루트에서):

    .\.venv\Scripts\python.exe gen_golden_rx.py

기대 출력: "dumped 112 regs 0x1000..0x106F -> ...".

--- 이 파일의 fake 선택 ------------------------------------------------------

골든/`chip._fh` 테스트만 벤더 sivers_api Fake_SPI(`make_chip(..., fake=True)`)를 쓴다.
그 둘은 "raw 시퀀스가 실제 벤더 chip 객체 위에서 동작하는가"까지 증명해야 하기
때문이다(FH 의 SPI 어댑터 분기, Stampede 인스턴스에 속성 대입 가능 여부).
나머지는 conftest 의 조용한 MemSPI(`fh` fixture 의 `fh.C`)를 쓴다 -- Fake_SPI 는
SPI 트랜잭션마다 print 해서 stdout 이 수십 KB 로 불어난다.
"""
from pathlib import Path

from cloudchaser.board.bringup import (
    BoardConfig,
    _cal_matrix,
    _efuse_only_dist,
    _extra_code,
    bring_up_rx,
    bring_up_tx,
    make_chip,
    make_chip_rx,
)
from cloudchaser.board.firehawk import FH

GOLDEN_TX = Path(__file__).parent / "data" / "golden_regs_tx_v1_split.csv"
GOLDEN_RX = Path(__file__).parent / "data" / "golden_regs_rx_h0.csv"


def QUIET(*_a, **_k):
    """로그 억제용 sink."""


def load_dump(path):
    """addr,value CSV -> {addr: value}."""
    out = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("addr"):
            continue
        a, v = s.split(",")
        out[int(a, 0)] = int(v, 0) & 0xFFFF
    return out


def tx_config():
    """골든을 뜬 evb_full 설정과 동일하게 맞춘다(Doosan 260729)."""
    return BoardConfig(
        chip_id=0,
        beam="b0",
        active_channels=["v1"],
        common_gain=0x00,
        split_mode=True,
        optimized_bias=True,
        dist_st2_1_ptat=13,
        run_efuse_init=False,
    )


def seed_efuse(chip):
    """골든과 같은 eFuse 시드를 심는다(evb_full MockSPI._seed_efuse 와 동일).

    CTAT=32, CBIAS=5 만 결과에 남는다(PTAT 는 Casper 로 덮이므로).
    0x1000 identity 워드도 심는다 -- sivers_api Fake_SPI 는 전 레지스터 0 으로
    시작하는데 bring-up 은 0x1000 을 읽기만 하므로, 안 심으면 골든(0xDC11)과
    가짜 차이가 난다.
    """
    f = FH(chip, 0)
    f.wr(0x1000, (0xDC << 8) | 0x11)     # TX identity, matches evb_full MockSPI seed
    fe = [[10, 20, 30, 32, 5] for _ in range(8)]
    f.set_fe_bias(fe)
    f.set_dist_bias([[12, 13, 14, 1, 1, 1] for _ in range(3)], 8)


def rx_config():
    """골든을 뜬 evb_full 설정과 동일하게 맞춘다(channels=["h0"], beam="b0")."""
    return BoardConfig(
        chip_id=0,
        beam="b0",
        active_channels=["h0"],
        common_gain=0x00,
        split_mode=False,
        optimized_bias=True,
        dist_st2_1_ptat=13,
        run_efuse_init=False,
    )


def seed_efuse_rx(chip):
    """RX 골든과 같은 eFuse 시드를 심는다(evb_full MockSPI._seed_efuse 와 동일).

    seed_efuse(TX 용)와 값은 같지만 identity 워드가 다르다(Ruling 7) -- RX 는
    0xD411 이어야 한다. TX 용 seed_efuse 를 그대로 재사용하면 0x1000 에서
    골든과 어긋나므로 별도 헬퍼로 둔다.
    """
    f = FH(chip, 0)
    f.wr(0x1000, (0xD4 << 8) | 0x11)     # RX identity, matches evb_full MockSPI seed
    fe = [[10, 20, 30, 32, 5] for _ in range(8)]
    f.set_fe_bias(fe)
    f.set_dist_bias([[12, 13, 14, 1, 1, 1] for _ in range(3)], 8)


# ---------------------------------------------------------------- 골든 일치
def test_bring_up_tx_matches_golden():
    chip = make_chip(tx_config(), fake=True)
    seed_efuse(chip)
    bring_up_tx(chip, tx_config(), require_version=False)

    f = FH(chip, 0)
    ours = {a: f.rd(a) for a in range(0x1000, 0x1070)}
    theirs = load_dump(GOLDEN_TX)

    diffs = [a for a in sorted(theirs) if theirs[a] != ours.get(a)]
    detail = "\n".join(
        f"  0x{a:04X}: golden=0x{theirs[a]:04X} ours=0x{ours.get(a, 0):04X}"
        for a in diffs
    )
    assert not diffs, f"{len(diffs)} differing registers:\n{detail}"


def test_bring_up_tx_exposes_fh_on_chip():
    """Task 6/9/10 이 재사용하는 chip._fh 를 남긴다(실제 벤더 chip 객체 위에서)."""
    chip = make_chip(tx_config(), fake=True)
    bring_up_tx(chip, tx_config(), require_version=False, log=QUIET)
    assert isinstance(getattr(chip, "_fh", None), FH)


# ------------------------------------------------- eFuse 트림 보존(재-bring-up)
def _seed_distinct_efuse(f, ident=0xDC):
    """행마다 서로 다른 CTAT/CBIAS 를 심는다 -- 재사용 여부가 값으로 구분되게."""
    f.wr(0x1000, (ident << 8) | 0x11)
    f.set_fe_bias([[10, 20, 30, 30 + r, 5 + r] for r in range(8)])
    f.set_dist_bias([[12, 13, 14, 1, 1, 1] for _ in range(3)], 8)


def _cfg(channels, beam="b0"):
    c = tx_config()
    c.active_channels = list(channels)
    c.beam = beam
    return c


def test_second_bring_up_keeps_the_first_efuse_readback(fh):
    """Ruling 42: bring-up 을 채널 바꿔 다시 돌려도 die eFuse 트림이 살아 있어야 한다.

    bring-up 은 비활성 채널 행을 0 으로 기입한다. `fh.reset()` 은 SPI 엔진 리셋이지
    칩 POR 이 아니라서, 캐시가 없으면 두 번째 `get_fe_bias()` 가 그 0 을 "eFuse
    리드백"으로 읽고 CTAT/CBIAS 가 영영 0 이 된다(리뷰 실측:
    h0 -> h1 -> h0 을 돌리면 h0 행이 [15,45,55,0,0] 으로 남았다).
    """
    from cloudchaser.board.firehawk import fe_row

    f, chip = fh, fh.C
    _seed_distinct_efuse(f)
    ctat_h1, cbias_h1 = 30 + fe_row(1, "h"), 5 + fe_row(1, "h")
    ctat_h0, cbias_h0 = 30 + fe_row(0, "h"), 5 + fe_row(0, "h")

    bring_up_tx(chip, _cfg(["h0"]), require_version=False, log=QUIET)
    assert f.get_fe_bias()[fe_row(1, "h")] == [0, 0, 0, 0, 0], \
        "sanity: bring-up must zero the inactive channel's row on the chip"

    bring_up_tx(chip, _cfg(["h1"]), require_version=False, log=QUIET)
    row = f.get_fe_bias()[fe_row(1, "h")]
    assert row[0:3] == [15, 45, 55], "Casper PTAT not applied on re-bring-up"
    assert row[3:5] == [ctat_h1, cbias_h1], \
        f"h1 CTAT/CBIAS lost -- read back {row[3:5]}, expected the die eFuse values"

    bring_up_tx(chip, _cfg(["h0"]), require_version=False, log=QUIET)
    row0 = f.get_fe_bias()[fe_row(0, "h")]
    assert row0[3:5] == [ctat_h0, cbias_h0], \
        f"h0 CTAT/CBIAS lost on the third bring-up -- read back {row0[3:5]}"


def test_second_bring_up_keeps_the_first_dist_efuse_readback(fh):
    """DIST bias 도 같은 이유로 캐시된 첫 리드백을 써야 한다(빔을 바꿔 재실행).

    B0(0x104C/0x104D)는 step 18 의 DIRECT_REGS_TX 가 무조건 덮어쓰므로(Ruling 37)
    B1(0x104E/0x104F)로 확인한다 -- 거기가 eFuse 유래 필드가 살아남는 행이다.
    """
    f, chip = fh, fh.C
    _seed_distinct_efuse(f)
    bring_up_tx(chip, _cfg(["h0"], beam="b0"), require_version=False, log=QUIET)
    bring_up_tx(chip, _cfg(["h0"], beam="b1"), require_version=False, log=QUIET)
    edb, _ = f.get_dist_bias()
    # B1 행: PTAT/cbias1 은 Casper 로 덮이고 cbias2_0/cbias2_1 은 eFuse(1/1) 유지.
    assert edb[1][4:6] == [1, 1], f"B1 DIST cbias lost on re-bring-up: {edb[1]}"


def test_first_bring_up_reads_the_chip_not_a_stale_cache(fh):
    """캐시는 chip 객체 단위다 -- 새 chip 은 반드시 새로 읽는다(골든 불변의 근거)."""
    from cloudchaser.board.firehawk import fe_row

    f, chip = fh, fh.C
    _seed_distinct_efuse(f)
    bring_up_tx(chip, _cfg(["h0"]), require_version=False, log=QUIET)
    assert getattr(chip, "_efuse_fe", None) is not None

    chip2 = make_chip(tx_config(), fake=True)
    seed_efuse(chip2)
    bring_up_tx(chip2, _cfg(["h0"]), require_version=False, log=QUIET)
    # seed_efuse 는 전 행 CTAT=32/CBIAS=5 -- 위 chip 의 행별 값이 새어 들어오면 다르다.
    assert FH(chip2, 0).get_fe_bias()[fe_row(0, "h")][3:5] == [32, 5]


# ------------------------------------------------------------- 반환/설정 계약
def test_bring_up_tx_returns_legacy_summary_keys(fh):
    """호출부 6곳이 의존하는 반환 dict 키가 유지돼야 한다."""
    s = bring_up_tx(fh.C, tx_config(), require_version=False, log=QUIET)
    assert set(s) >= {"version_id", "common_gain", "channels", "active_paths"}
    assert "v1" in s["channels"]
    assert set(s["channels"]["v1"]) >= {"gain", "atten"}


def test_summary_atten_reads_the_channel_beam_cal_byte(fh):
    """v1/b0 의 cal atten 은 0x1060+ch 의 상위 바이트다(FH.set_cal 평탄화 순서)."""
    cfg = tx_config()
    cfg.ch_atten = {"v1": 0x0A}
    s = bring_up_tx(fh.C, cfg, require_version=False, log=QUIET)
    assert fh.rd(0x1060 + 1) >> 8 == 0x0A        # 기입 위치 확인
    assert s["channels"]["v1"]["atten"] == 0x0A  # 리드백이 그 바이트를 짚는지


def test_summary_gain_masks_pulse_en_bit(fh):
    """FE gain 은 4-bit -- bit12(pulse_en)가 요약 값에 새면 안 된다.

    bring_up_tx 는 FE gain 레지스터를 기입하지 않으므로(스펙 4장 표에 단계 없음)
    미리 넣어둔 값이 그대로 남는다 -- 그걸 리드백 경로가 어떻게 읽는지 본다.
    """
    fh.set_fe_gains([[0, 0, 0], [0xF, 0xF, 1], [0, 0, 0], [0, 0, 0]])
    assert (fh.rd(0x1018 + 1) >> 8) & 0xFF == 0x1F   # 워드엔 pulse_en(bit12)이 켜져 있다
    s = bring_up_tx(fh.C, tx_config(), require_version=False, log=QUIET)
    assert s["channels"]["v1"]["gain"] == 0xF        # 요약은 4-bit 만 돌려준다


def test_summary_common_gain_is_masked_to_six_bits(fh):
    cfg = tx_config()
    cfg.common_gain = 0xFF
    s = bring_up_tx(fh.C, cfg, require_version=False, log=QUIET)
    assert s["common_gain"] == 0x3F


def test_ignored_knobs_are_reported(fh):
    """적용되지 않는 ch_gain / cal_freq_code 는 로그로 알린다(Ruling 10)."""
    cfg = tx_config()
    cfg.ch_gain = {"v1": 0x8}
    cfg.cal_freq_code = 0x3
    lines = []
    bring_up_tx(fh.C, cfg, require_version=False, log=lines.append)
    text = "\n".join(lines)
    assert "no longer applied" in text
    assert "ch_gain" in text and "cal_freq_code" in text


def test_default_config_stays_quiet_about_ignored_knobs(fh):
    """기본값이면 아무 말도 하지 않는다."""
    lines = []
    bring_up_tx(fh.C, tx_config(), require_version=False, log=lines.append)
    assert not any("no longer applied" in ln for ln in lines)


def test_split_mode_off_skips_split_regs(fh):
    cfg = tx_config()
    cfg.split_mode = False
    bring_up_tx(fh.C, cfg, require_version=False, log=QUIET)
    assert fh.rd(0x1009) != 783


def test_optimized_bias_off_keeps_efuse_ptat(fh):
    """optimized_bias=False 면 eFuse PTAT(10/20/30)가 그대로 남는다."""
    cfg = tx_config()
    cfg.optimized_bias = False
    seed_efuse(fh.C)
    bring_up_tx(fh.C, cfg, require_version=False, log=QUIET)
    assert fh.get_fe_bias()[3][0] == 10


# ----------------------------------------------- 순서 (골든이 못 잡는 부분)
def test_staged_power_up_writes_three_stages_in_order(fh):
    """스펙 4장 15단계. 골든은 끝상태(0x1011=0x00C7)만 고정하므로 순서는 여기서 잡는다.

    실하드웨어에서 PA 보호가 이 순서에 달려 있다: bias only -> +PA/DRV -> +combiner.
    """
    bring_up_tx(fh.C, tx_config(), require_version=False, log=QUIET)
    seq = [v for a, v in fh.C.spi.writes if a == 0x1011]
    assert seq == [0x00C0, 0x00C3, 0x00C7], \
        f"quad_pwrdn(ch1) sequence = {[hex(v) for v in seq]}"


def test_beam_enables_staged_then_overwritten_by_split(fh):
    """16~17단계(splitter bias only -> +amp) 뒤에 19단계 split 이 덮는지 순서로 확인."""
    bring_up_tx(fh.C, tx_config(), require_version=False, log=QUIET)
    seq = [v for a, v in fh.C.spi.writes if a == 0x1009]
    assert seq == [256, 770, 783], f"beam_enables(b0) sequence = {seq}"


def test_beam_enables_stops_at_770_without_split(fh):
    cfg = tx_config()
    cfg.split_mode = False
    bring_up_tx(fh.C, cfg, require_version=False, log=QUIET)
    seq = [v for a, v in fh.C.spi.writes if a == 0x1009]
    assert seq == [256, 770]


# --------------------------------------------------- 보조 함수 직접 커버리지
def test_extra_code_matches_matlab_func():
    """활성 beam=8, 비활성=1, B2=14 하드코딩, misc=0."""
    assert _extra_code(0) == [8, 1, 14, 0]
    assert _extra_code(1) == [1, 8, 14, 0]
    assert _extra_code(2) == [1, 1, 14, 0]      # B2 는 활성이어도 14 로 고정


def test_cal_matrix_default_is_all_zero():
    assert _cal_matrix(tx_config()) == [[[0, 0, 0], [0, 0, 0]] for _ in range(4)]


def test_cal_matrix_maps_pol_to_hv_and_fans_out_over_beams():
    cfg = tx_config()
    cfg.ch_atten = {"v1": 5, "h3": 9}
    cal = _cal_matrix(cfg)
    assert cal[1][1] == [5, 5, 5]      # v -> hv=1, 전 빔
    assert cal[1][0] == [0, 0, 0]      # 같은 채널의 H 는 손대지 않는다
    assert cal[3][0] == [9, 9, 9]      # h -> hv=0
    assert cal[3][1] == [0, 0, 0]
    assert cal[0] == [[0, 0, 0], [0, 0, 0]]


def test_efuse_only_dist_keeps_active_beam_and_hardcodes_b2_for_tx():
    edb = [[12, 13, 14, 1, 1, 1], [21, 22, 23, 2, 2, 2], [31, 32, 33, 3, 3, 3]]
    out = _efuse_only_dist(edb, 0, "tx")
    assert out[0] == [12, 13, 14, 1, 1, 1]     # 활성 빔만 eFuse 값
    assert out[1] == [0, 0, 0, 0, 0, 0]
    assert out[2] == [6, 6, 6, 0, 0, 0]        # TX 는 B2 PTAT 하드코딩
    assert edb[0] == [12, 13, 14, 1, 1, 1]     # 입력을 파괴하지 않는다


def test_efuse_only_dist_beam1_and_rx_leaves_b2_zero():
    edb = [[12, 13, 14, 1, 1, 1], [21, 22, 23, 2, 2, 2], [31, 32, 33, 3, 3, 3]]
    out = _efuse_only_dist(edb, 1, "tx")
    assert out[1] == [21, 22, 23, 2, 2, 2] and out[0] == [0] * 6
    assert out[2] == [6, 6, 6, 0, 0, 0]
    rx = _efuse_only_dist(edb, 1, "rx")
    assert rx[2] == [0, 0, 0, 0, 0, 0]


# ---------------------------------------------------------------- RX 골든 일치
def test_bring_up_rx_matches_golden():
    chip = make_chip_rx(rx_config(), fake=True)
    seed_efuse_rx(chip)
    bring_up_rx(chip, rx_config(), require_version=False)

    fh = FH(chip, 0)
    ours = {a: fh.rd(a) for a in range(0x1000, 0x1070)}
    theirs = load_dump(GOLDEN_RX)

    diffs = [a for a in sorted(theirs) if theirs[a] != ours.get(a)]
    detail = "\n".join(
        f"  0x{a:04X}: golden=0x{theirs[a]:04X} ours=0x{ours.get(a, 0):04X}"
        for a in diffs
    )
    assert not diffs, f"{len(diffs)} differing registers:\n{detail}"


def test_bring_up_rx_exposes_fh_on_chip():
    """Task 6/9/10 이 재사용하는 chip._fh 를 남긴다(실제 벤더 chip 객체 위에서)."""
    chip = make_chip_rx(rx_config(), fake=True)
    bring_up_rx(chip, rx_config(), require_version=False, log=QUIET)
    assert isinstance(getattr(chip, "_fh", None), FH)


# ------------------------------------------------ RX H/V 편파 pwrdn 회귀 방지
def test_rx_h_polarity_pwrdn_is_199(fh):
    """RX H 편파 full = 199 (0b000111). TX 와 비트순서가 반대라는 점의 회귀 방지."""
    bring_up_rx(fh.C, rx_config(), require_version=False, log=QUIET)
    assert fh.rd(0x1010) == 199


def test_rx_v_polarity_pwrdn_is_248(fh):
    """RX V 편파 full = 248 (0b111000)."""
    cfg = rx_config()
    cfg.active_channels = ["v0"]
    bring_up_rx(fh.C, cfg, require_version=False, log=QUIET)
    assert fh.rd(0x1010) == 248


# ------------------------------------------------------------- 반환/설정 계약
def test_bring_up_rx_returns_legacy_summary_keys(fh):
    """호출부가 의존하는 반환 dict 키가 유지돼야 한다. RX 는 gain/atten 이 아니라
    fe_attn/atten 키를 쓴다(TX 와 다름 -- 시그니처/키 계약은 바꾸지 않는다)."""
    s = bring_up_rx(fh.C, rx_config(), require_version=False, log=QUIET)
    assert set(s) >= {"version_id", "common_gain", "channels", "active_paths"}
    assert "h0" in s["channels"]
    assert set(s["channels"]["h0"]) >= {"fe_attn", "atten"}


def test_rx_summary_atten_reads_the_channel_beam_cal_byte(fh):
    """h0/b0 의 cal atten 은 0x105C 의 하위 바이트다(FH.set_cal 평탄화 순서, TX 와 동일 인덱싱).

    RX bring-up 은 BEAM_CAL_ADDR 를 스스로 기입하지 않으므로(스펙 4장 RX 표에 단계
    없음), 여기선 미리 심어둔 값을 올바른 위치에서 읽어오는지만 검증한다.
    """
    # flat = hv*3 + beam_i = 0*3 + 0 = 0 -> word = BEAM_CAL_ADDR + 0, byte 0 (하위)
    fh.wr(0x105C, 0x340A)          # 상위 바이트=0x34(다른 채널/빔), 하위=0x0A
    s = bring_up_rx(fh.C, rx_config(), require_version=False, log=QUIET)
    assert s["channels"]["h0"]["atten"] == 0x0A


def test_summary_atten_masks_to_four_bits(fh):
    """attn_cal 은 4-bit 다 (ch{i}_{pol}_b{n}_attn_cal = 0x105C[3:0] / [11:8]).

    Ruling 45: 리드백이 `& 0xFF` 였다 -- 같은 바이트의 bits[7:4] 를 감쇠 코드인 척
    같이 끌고 와서 요약이 방금 기입한 값과 다른 숫자를 보여줬다(FE gain 쪽에서 이미
    고친 것과 같은 결함 종류).
    """
    fh.wr(0x105C, 0x345A)          # 하위 바이트 = 0x5A -> attn_cal 은 하위 니블 0xA 뿐
    s = bring_up_rx(fh.C, rx_config(), require_version=False, log=QUIET)
    assert s["channels"]["h0"]["atten"] == 0xA


def test_tx_summary_atten_masks_to_four_bits(fh):
    """TX 쪽 리드백도 같은 4-bit 계약이다.

    0x5A 는 4-bit 범위를 일부러 넘는 값이다(bench.toml 의 ch_atten 은 검증되지
    않는다) -- 기입은 바이트 통째로 나가지만 요약은 필드 폭인 하위 니블만 봐야 한다.
    """
    cfg = tx_config()
    cfg.ch_atten = {"v1": 0x5A}
    s = bring_up_tx(fh.C, cfg, require_version=False, log=QUIET)
    assert fh.rd(0x1060 + 1) >> 8 == 0x5A          # 기입은 바이트 단위
    assert s["channels"]["v1"]["atten"] == 0xA     # 리드백은 4-bit 필드


def test_rx_summary_fe_attn_masks_pulse_en_bit(fh):
    """FE gain 은 4-bit -- bit12(pulse_en)가 fe_attn 요약값에 새면 안 된다."""
    fh.set_fe_gains([[0xF, 0xF, 1], [0, 0, 0], [0, 0, 0], [0, 0, 0]])
    assert fh.rd(0x1018) & 0xFF == 0x0F        # 워드엔 pulse_en(bit12)이 켜져 있다
    s = bring_up_rx(fh.C, rx_config(), require_version=False, log=QUIET)
    assert s["channels"]["h0"]["fe_attn"] == 0xF


def test_rx_summary_common_gain_is_masked_to_six_bits(fh):
    """common_gain 요약은 COMMON_GAIN 레지스터를 6-bit 로 마스킹해 읽는다.

    주의: 스펙 4장 RX 10단계 표에는 set_common_gains 단계가 없다(evb_full.py 의
    bring_up_rx 도 안 쓴다) -- cfg.common_gain 은 TX 와 달리 레지스터에 기입되지
    않는다. 그래서 cfg.common_gain 이 아니라 레지스터에 미리 심어둔 값으로
    마스킹만 검증한다.
    """
    fh.wr(0x1005, 0xFF)   # COMMON_GAIN + beam_i(0)
    s = bring_up_rx(fh.C, rx_config(), require_version=False, log=QUIET)
    assert s["common_gain"] == 0x3F


def test_rx_ignored_knobs_are_reported(fh):
    """적용되지 않는 ch_fe_attn / cal_freq_code / common_gain / ch_atten 은 로그로
    알린다(Ruling 10 -> Ruling 13: RX 도 같은 결함 종류라 common_gain/ch_atten 추가).

    "=" 까지 확인하는 이유: 로그 머리글은 네 이름을 항상 나열하므로(어느 게
    실제로 무시됐는지와 무관), "이름=값" 형태로 실려야 실제로 그 knob 이 설정돼
    무시 목록에 들어갔다는 증거가 된다.
    """
    cfg = rx_config()
    cfg.ch_fe_attn = {"h0": 0x8}
    cfg.cal_freq_code = 0x3
    cfg.common_gain = 0x20        # bench_rx.toml 의 stock 값과 동일
    cfg.ch_atten = {"h0": 0x0A}
    lines = []
    bring_up_rx(fh.C, cfg, require_version=False, log=lines.append)
    text = "\n".join(lines)
    assert "no longer applied" in text
    assert "ch_fe_attn=" in text and "cal_freq_code=" in text
    assert "common_gain=" in text and "ch_atten=" in text


def test_rx_ignored_knobs_names_only_the_ones_set(fh):
    """네 knob 중 실제로 설정된 것만 무시 목록에 이름을 남긴다(Ruling 13 요건 1).

    bench_rx.toml 의 stock 설정(common_gain=0x20, 나머지 3개는 비어있음/0)을
    그대로 재현한다 -- 매 실행마다 이 로그가 찍히는 게 의도된 동작이다.
    """
    cfg = rx_config()
    cfg.common_gain = 0x20
    lines = []
    bring_up_rx(fh.C, cfg, require_version=False, log=lines.append)
    text = "\n".join(lines)
    assert "no longer applied" in text
    assert "common_gain=" in text
    assert "ch_fe_attn=" not in text
    assert "cal_freq_code=" not in text
    assert "ch_atten=" not in text


def test_rx_default_config_stays_quiet_about_ignored_knobs(fh):
    """네 knob 이 전부 '무시 없음' 값이면 아무 말도 하지 않는다.

    주의(Ruling 13 요건 2): BoardConfig() 의 순수 dataclass 기본값만 쓰면 이
    상태에 도달할 수 없다 -- common_gain 기본값 자체가 0x20(비어있지 않음)이라
    bring_up_tx 의 ch_gain/cal_freq_code 조용함 테스트와 달리 RX 는 "아무 설정도
    안 건드린 기본 상태"가 자동으로 조용하지 않다. 여기 쓰는 rx_config() 는
    골든 재현을 위해 common_gain=0x00 을 이미 명시하고 있어(다른 이유로,
    골든이 그 값으로 떴으므로) 도달 가능한 조용한 조합이 된다 -- 억지로 만든
    설정이 아니라 이미 존재하던 골든-일치 설정이 우연히 이 요건도 만족한다.
    """
    lines = []
    bring_up_rx(fh.C, rx_config(), require_version=False, log=lines.append)
    assert not any("no longer applied" in ln for ln in lines)


# ------------------------------------------- 순서 (골든이 못 잡는 부분, mutation check)
def test_rx_bias_written_before_enables(fh):
    """스펙 4장 RX 3단계: bias 를 enable(0x1004/0x1008/0x1009) 보다 먼저 기입한다.

    실하드웨어에서는 이 순서가 중요하지만(bias 없이 enable 하면 과도전류/오동작
    위험), 최종 레지스터 값만 비교하는 골든 테스트는 이 순서를 잡지 못한다(bias
    주소와 enable 주소가 겹치지 않기 때문). 순서는 여기서 쓰기 시퀀스로 직접 잡는다.
    """
    bring_up_rx(fh.C, rx_config(), require_version=False, log=QUIET)
    addrs = [a for a, _ in fh.C.spi.writes]
    first_enable_idx = min(i for i, a in enumerate(addrs) if a in (0x1004, 0x1008, 0x1009))
    last_bias_idx = max(i for i, a in enumerate(addrs) if 0x1038 <= a < 0x1053)
    assert last_bias_idx < first_enable_idx, \
        f"bias write (idx {last_bias_idx}) must precede first enable write (idx {first_enable_idx})"


def test_bring_up_writes_common_gain_to_all_three_beams():
    """common_gain 은 B0/B1/B2(0x1005~0x1007) 세 워드 모두에 기입된다."""
    cfg = tx_config()
    cfg.common_gain = 0x00
    chip = make_chip(cfg, fake=True)
    bring_up_tx(chip, cfg, require_version=False)
    fh = FH(chip, 0)
    assert [fh.rd(a) for a in (0x1005, 0x1006, 0x1007)] == [0, 0, 0]
