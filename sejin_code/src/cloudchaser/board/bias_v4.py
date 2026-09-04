"""Sivers Cloudchaser ES1 optimized bias codes (BiasMapping Tuning Bits v4).

출처: Cloudchaser_ES1_BiasMapping_Tuning_Bits_v4.xlsx (2026-08-20 수령)
  - TX: 'Stampede TX Digital Settings' 시트, 'H0-B0 (Casper)' 열
  - RX: 'Blueway RX Digital Settings' 시트, 'NF_OPTIM' 열
보관: C:\\claude_code\\_reference\\01_Cloudchaser_BFIC\\01_datasheet\\

적용 규칙(MATLAB/Sivers 덤프와 동일):
  - 활성 채널/편파 원소에만 기입한다. 비활성 행은 0.
  - CTAT/CBIAS 는 시트에 최적화값이 없으므로 die eFuse 리드백 값을 유지한다.
"""

from __future__ import annotations

from .firehawk import fe_row, parse_ch

# TX Casper -- PA St1 을 내리고(32->15) 구동단/합성단에 전류를 몰아준다.
CASPER_FE = {"ptat_st1": 15, "ptat_st2": 45, "ptat_st3": 55}
CASPER_DIST_B0 = {"st1_ptat": 50, "st2_0_ptat": 13, "cbias1": 6}

# RX NF_OPTIM -- St2 LNA 전류를 낮추고(30->24) 후단 splitter/combiner 를 올린다.
NF_OPTIM_FE = {"ptat_st1": 34, "ptat_st2": 24, "ptat_st3": 48}
NF_OPTIM_DIST_B0 = {"st1_ptat": 44}
NF_OPTIM_CAPTUNE = 0x8888        # 바이트당 136 (기본 119=0x77 -> 136=0x88)


def apply_fe_bias(efuse_bias, active_channels, kind):
    """eFuse FE bias(8x5)에 최적화 PTAT 를 얹어 8x5 를 반환한다.

    efuse_bias      : FH.get_fe_bias() 결과 (8x5)
    active_channels : ["v1"] 처럼 켤 채널 목록
    kind            : "tx" -> Casper / "rx" -> NF_OPTIM
    """
    opt = CASPER_FE if kind == "tx" else NF_OPTIM_FE
    out = [[0, 0, 0, 0, 0] for _ in range(8)]
    for ch in active_channels:
        pol, ci = parse_ch(ch)
        r = fe_row(ci, pol)
        row = list(efuse_bias[r])
        row[0] = opt["ptat_st1"]
        row[1] = opt["ptat_st2"]
        row[2] = opt["ptat_st3"]
        # row[3](CTAT), row[4](CBIAS) 는 eFuse 값 유지
        out[r] = row
    return out


def apply_dist_bias(efuse_dist, beam_idx, kind, st2_1_ptat):
    """eFuse DIST bias(3x6)에 최적화 값을 얹어 3x6 을 반환한다.

    열 = [PTAT1 PTAT2_0 PTAT2_1 cbias1 cbias2_0 cbias2_1]
    st2_1_ptat : 0x104D[5:0]. 시트 v4=13 / MATLAB=28 (bench.toml 로 선택)
    """
    out = [[0, 0, 0, 0, 0, 0] for _ in range(3)]
    row = list(efuse_dist[beam_idx])
    if kind == "tx":
        row[0] = CASPER_DIST_B0["st1_ptat"]
        row[1] = CASPER_DIST_B0["st2_0_ptat"]
        row[2] = int(st2_1_ptat)
        row[3] = CASPER_DIST_B0["cbias1"]
    else:
        row[0] = NF_OPTIM_DIST_B0["st1_ptat"]
    out[beam_idx] = row
    if kind == "tx":
        out[2][0:3] = [6, 6, 6]      # MATLAB: B2 PTAT 하드코딩
    return out
