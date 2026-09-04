"""조건 폴더 이름 -> bias 코드 파싱.

폴더 이름 규칙이 늘어났다: 앞에 측정일(YYMMDD)이 붙고 뒤에 채널/빔(H0B0)이 붙는
이름을 쓴다. 숫자 그룹을 그냥 다 긁으면 날짜와 채널 번호가 bias 코드로 섞여 들어가
워크북 요약에 `St1=260904` 같은 값이 찍힌다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_bare_ptat_triplet():
    from postprocess_bias_vdd import bias_codes
    assert bias_codes("15_45_55") == [15, 45, 55]
    assert bias_codes("63_63_63") == [63, 63, 63]


def test_six_codes_with_a_word_prefix():
    from postprocess_bias_vdd import bias_codes
    assert bias_codes("new bias_17_55_61_63_16_0") == [17, 55, 61, 63, 16, 0]


def test_leading_date_is_not_a_bias_code():
    from postprocess_bias_vdd import bias_codes
    assert bias_codes("260904_new bias_17_55_61_63_16_63") == \
        [17, 55, 61, 63, 16, 63]


def test_trailing_channel_and_beam_are_not_bias_codes():
    from postprocess_bias_vdd import bias_codes
    assert bias_codes("new bias_17_55_61_63_16_63_H0B0") == \
        [17, 55, 61, 63, 16, 63]
    assert bias_codes("new bias_17_55_61_63_16_63_v2") == \
        [17, 55, 61, 63, 16, 63]


def test_date_and_channel_together():
    from postprocess_bias_vdd import bias_codes
    assert bias_codes("260904_new bias_17_55_61_63_16_63_H0B0") == \
        [17, 55, 61, 63, 16, 63]


def test_name_without_codes_yields_nothing():
    from postprocess_bias_vdd import bias_codes
    assert bias_codes("reference") == []
